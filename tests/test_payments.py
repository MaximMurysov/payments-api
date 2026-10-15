from datetime import datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Payment, PaymentMethod, PaymentStatus, Tariff
from app.schemas import PaymentCreate, UnprocessableOut
from app.services import payments as payments_service
from app.services.payments import create_payment
from app.services.pricing import build_schedule

EMAIL = "student@example.com"
# Цены тарифов в копейках и суммы к оплате с промокодом KVITTO10 (−10 %).
PRICES = {"basic": 990000, "standard": 1990000, "premium": 2990000}
PRICES_WITH_PROMO = {"basic": 891000, "standard": 1791000, "premium": 2691000}


def _tariff_id(session: Session, code: str = "standard") -> int:
    tariff_id = session.scalar(select(Tariff.id).where(Tariff.code == code))
    assert tariff_id is not None
    return tariff_id


def _body(session: Session, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"tariff_id": _tariff_id(session), "email": EMAIL, "method": "card"}
    body.update(overrides)
    return body


def _payments_count(session: Session) -> int:
    return session.scalar(select(func.count()).select_from(Payment)) or 0


def _stored(session: Session, payment_id: int) -> Payment:
    # Сбрасываем кэш сессии: проверяем то, что реально лежит в БД.
    session.expire_all()
    payment = session.get(Payment, payment_id)
    assert payment is not None
    return payment


def test_create_card_payment_without_promo(client: TestClient, session: Session) -> None:
    tariff_id = _tariff_id(session, "standard")

    response = client.post("/payments", json=_body(session, tariff_id=tariff_id))

    assert response.status_code == 201
    body = response.json()
    assert body["amount"] == PRICES["standard"]
    assert body["discount"] == 0
    assert body["status"] == "pending"
    assert body["schedule"] is None
    assert body["installment_months"] is None
    assert body["method"] == "card"
    assert body["tariff_id"] == tariff_id
    assert body["email"] == EMAIL
    assert set(body) == {
        "id",
        "status",
        "tariff_id",
        "amount",
        "discount",
        "method",
        "installment_months",
        "schedule",
        "email",
        "created_at",
    }

    assert _payments_count(session) == 1
    stored = _stored(session, body["id"])
    assert stored.amount == PRICES["standard"]
    assert stored.discount == 0
    assert stored.status is PaymentStatus.PENDING
    assert stored.promo_code is None
    assert stored.schedule is None


def test_create_payment_money_fields_are_int(client: TestClient, session: Session) -> None:
    body = client.post("/payments", json=_body(session, promo_code="KVITTO10")).json()

    # 1791000 == 1791000.0 в Python, поэтому проверяем именно тип.
    assert type(body["amount"]) is int
    assert type(body["discount"]) is int


def test_create_payment_created_at_is_utc_iso(client: TestClient, session: Session) -> None:
    created_at = client.post("/payments", json=_body(session)).json()["created_at"]

    parsed = datetime.fromisoformat(created_at)
    assert parsed.utcoffset() == timedelta(0)


@pytest.mark.parametrize("tariff_code", ["basic", "standard", "premium"])
def test_create_payment_amount_without_promo(
    client: TestClient, session: Session, tariff_code: str
) -> None:
    body = client.post("/payments", json=_body(session, tariff_id=_tariff_id(session, tariff_code)))

    assert body.status_code == 201
    assert body.json()["amount"] == PRICES[tariff_code]
    assert body.json()["discount"] == 0


@pytest.mark.parametrize("promo_code", ["KVITTO10", "kvitto10", " Kvitto10 "])
@pytest.mark.parametrize("tariff_code", ["basic", "standard", "premium"])
def test_create_payment_amount_with_promo_any_case(
    client: TestClient, session: Session, tariff_code: str, promo_code: str
) -> None:
    response = client.post(
        "/payments",
        json=_body(session, tariff_id=_tariff_id(session, tariff_code), promo_code=promo_code),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["amount"] == PRICES_WITH_PROMO[tariff_code]
    assert body["discount"] == PRICES[tariff_code] - PRICES_WITH_PROMO[tariff_code]
    stored = _stored(session, body["id"])
    assert stored.amount == body["amount"]
    assert stored.discount == body["discount"]
    # В платеже хранится нормализованный код, а не то, как его прислали.
    assert stored.promo_code == "KVITTO10"


@pytest.mark.parametrize("promo_code", ["", "   ", None])
def test_create_payment_blank_promo_means_no_promo(
    client: TestClient, session: Session, promo_code: str | None
) -> None:
    response = client.post("/payments", json=_body(session, promo_code=promo_code))

    assert response.status_code == 201
    body = response.json()
    assert body["amount"] == PRICES["standard"]
    assert body["discount"] == 0
    assert _stored(session, body["id"]).promo_code is None


@pytest.mark.parametrize("months", [3, 6, 12])
def test_create_installment_payment_schedule(
    client: TestClient, session: Session, months: int
) -> None:
    response = client.post(
        "/payments", json=_body(session, method="installment", installment_months=months)
    )

    assert response.status_code == 201
    body = response.json()
    assert body["installment_months"] == months
    assert len(body["schedule"]) == months
    assert sum(body["schedule"]) == body["amount"] == PRICES["standard"]
    assert body["schedule"] == build_schedule(PRICES["standard"], months)
    # График из JSON-колонки после чтения из БД — тот же список копеек.
    stored = _stored(session, body["id"])
    assert stored.schedule == body["schedule"]
    assert stored.installment_months == months


def test_create_installment_payment_with_promo(client: TestClient, session: Session) -> None:
    response = client.post(
        "/payments",
        json=_body(session, method="installment", installment_months=12, promo_code="kvitto10"),
    )

    assert response.status_code == 201
    body = response.json()
    assert body["amount"] == PRICES_WITH_PROMO["standard"]
    assert sum(body["schedule"]) == PRICES_WITH_PROMO["standard"]
    assert body["schedule"] == build_schedule(PRICES_WITH_PROMO["standard"], 12)


def test_create_payment_ignores_client_money_and_status(
    client: TestClient, session: Session
) -> None:
    # Сумму, скидку и статус считает сервер: цена — только из таблицы тарифов.
    body = _body(session, amount=1, discount=1989999, status="succeeded", schedule=[1])

    response = client.post("/payments", json=body)

    assert response.status_code == 201
    created = response.json()
    assert (created["amount"], created["discount"]) == (PRICES["standard"], 0)
    assert created["status"] == "pending"
    assert created["schedule"] is None
    stored = _stored(session, created["id"])
    assert (stored.amount, stored.discount) == (PRICES["standard"], 0)
    assert stored.status is PaymentStatus.PENDING
    assert stored.schedule is None


def test_each_request_without_idempotency_key_creates_payment(
    client: TestClient, session: Session
) -> None:
    first = client.post("/payments", json=_body(session)).json()
    second = client.post("/payments", json=_body(session)).json()

    assert first["id"] != second["id"]
    assert _payments_count(session) == 2


@pytest.mark.parametrize("promo_code", ["NOPE", "kvitto1", "KVITTO 10"])
def test_create_payment_unknown_promo_is_422(
    client: TestClient, session: Session, promo_code: str
) -> None:
    response = client.post("/payments", json=_body(session, promo_code=promo_code))

    assert response.status_code == 422
    # Формат как у HTTPException FastAPI; в сообщении — код как его прислали, без repr-кавычек.
    assert response.json() == {"detail": f"Unknown promo code: {promo_code}"}
    # Тело соответствует схеме 422, описанной в OpenAPI.
    UnprocessableOut.model_validate(response.json())
    assert _payments_count(session) == 0


def test_create_payment_unknown_tariff_is_422(client: TestClient, session: Session) -> None:
    response = client.post("/payments", json=_body(session, tariff_id=999999))

    assert response.status_code == 422
    assert response.json() == {"detail": "Tariff 999999 not found"}
    UnprocessableOut.model_validate(response.json())
    assert _payments_count(session) == 0


@pytest.mark.parametrize(
    "overrides",
    [
        pytest.param({"method": "installment"}, id="installment-without-months"),
        pytest.param({"method": "installment", "installment_months": 5}, id="months-5"),
        pytest.param({"method": "card", "installment_months": 3}, id="card-with-months"),
        pytest.param({"method": "sbp", "installment_months": 6}, id="sbp-with-months"),
        pytest.param({"method": "cash"}, id="unknown-method"),
        pytest.param({"email": "not-an-email"}, id="invalid-email"),
        pytest.param({"tariff_id": True}, id="tariff-id-bool"),
        pytest.param({"tariff_id": "1"}, id="tariff-id-string"),
        pytest.param({"promo_code": "X" * 33}, id="promo-too-long"),
    ],
)
def test_create_payment_invalid_body_is_standard_422(
    client: TestClient, session: Session, overrides: dict[str, Any]
) -> None:
    response = client.post("/payments", json=_body(session, **overrides))

    assert response.status_code == 422
    # Стандартный ответ FastAPI на ошибку валидации: список ошибок в `detail`.
    assert isinstance(response.json()["detail"], list)
    UnprocessableOut.model_validate(response.json())
    assert _payments_count(session) == 0


def test_create_payment_documents_both_422_shapes(client: TestClient) -> None:
    openapi = client.get("/openapi.json").json()
    response_422 = openapi["paths"]["/payments"]["post"]["responses"]["422"]
    ref = response_422["content"]["application/json"]["schema"]["$ref"]

    detail = openapi["components"]["schemas"][ref.rsplit("/", 1)[-1]]["properties"]["detail"]

    # Клиент по /docs должен знать оба вида 422: список ошибок валидации FastAPI и строку
    # доменной ошибки (неизвестный промокод или тариф).
    assert {variant.get("type") for variant in detail["anyOf"]} == {"array", "string"}


def test_get_payment_returns_created_payment(client: TestClient, session: Session) -> None:
    created = client.post("/payments", json=_body(session, promo_code="kvitto10")).json()

    response = client.get(f"/payments/{created['id']}")

    assert response.status_code == 200
    # Ответ GET собран из записи в БД, ответ POST — из объекта в памяти: они должны совпасть.
    assert response.json() == created


def test_get_payment_created_at_is_timezone_aware(client: TestClient, session: Session) -> None:
    created = client.post("/payments", json=_body(session)).json()

    created_at = client.get(f"/payments/{created['id']}").json()["created_at"]

    # SQLite не хранит таймзону: без своего типа колонки здесь было бы время без смещения.
    assert created_at.endswith(("Z", "+00:00"))
    assert datetime.fromisoformat(created_at).utcoffset() == timedelta(0)


@pytest.mark.parametrize("months", [3, 6, 12])
def test_get_installment_payment_schedule_from_db(
    client: TestClient, session: Session, months: int
) -> None:
    created = client.post(
        "/payments",
        json=_body(session, method="installment", installment_months=months, promo_code="KVITTO10"),
    ).json()

    body = client.get(f"/payments/{created['id']}").json()

    assert body["schedule"] == build_schedule(body["amount"], months)
    assert sum(body["schedule"]) == body["amount"] == PRICES_WITH_PROMO["standard"]


# 2**31 - 1 — самый большой допустимый id: он проходит валидацию и честно ищется в БД.
@pytest.mark.parametrize("payment_id", [999999, 2**31 - 1])
def test_get_missing_payment_is_404(client: TestClient, session: Session, payment_id: int) -> None:
    client.post("/payments", json=_body(session))

    response = client.get(f"/payments/{payment_id}")

    assert response.status_code == 404
    assert response.json() == {"detail": f"Payment {payment_id} not found"}
    assert _payments_count(session) == 1


def test_get_payment_documents_404(client: TestClient) -> None:
    responses = client.get("/openapi.json").json()["paths"]["/payments/{payment_id}"]["get"][
        "responses"
    ]

    # Клиент, который читает /docs, должен видеть, что платежа может не быть.
    assert "404" in responses


@pytest.mark.parametrize("payment_id", ["abc", "1.5", "0", "-1", str(2**31)])
def test_get_payment_invalid_id_is_422(client: TestClient, payment_id: str) -> None:
    # 2**31 не помещается в INTEGER: без проверки запрос к БД упал бы с 500.
    response = client.get(f"/payments/{payment_id}")

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


def _post_with_key(client: TestClient, key: str, body: dict[str, Any]):
    return client.post("/payments", json=body, headers={"Idempotency-Key": key})


def test_repeat_with_same_idempotency_key_returns_existing_payment(
    client: TestClient, session: Session
) -> None:
    body = _body(session, method="installment", installment_months=6, promo_code="KVITTO10")

    first = _post_with_key(client, "key-1", body)
    second = _post_with_key(client, "key-1", body)

    assert first.status_code == 201
    assert second.status_code == 200
    assert second.json() == first.json()
    assert _payments_count(session) == 1
    stored = _stored(session, first.json()["id"])
    assert stored.idempotency_key == "key-1"


def test_different_idempotency_keys_create_different_payments(
    client: TestClient, session: Session
) -> None:
    first = _post_with_key(client, "key-1", _body(session))
    second = _post_with_key(client, "key-2", _body(session))

    assert (first.status_code, second.status_code) == (201, 201)
    assert first.json()["id"] != second.json()["id"]
    assert _payments_count(session) == 2


def test_repeat_with_same_key_and_different_body_returns_first_payment(
    client: TestClient, session: Session
) -> None:
    first = _post_with_key(client, "key-1", _body(session, method="card"))
    second = _post_with_key(
        client, "key-1", _body(session, method="installment", installment_months=3)
    )

    assert second.status_code == 200
    assert second.json() == first.json()
    assert second.json()["method"] == "card"
    assert _payments_count(session) == 1


def test_repeat_with_same_key_skips_tariff_and_promo_checks(
    client: TestClient, session: Session
) -> None:
    first = _post_with_key(client, "key-1", _body(session))

    second = _post_with_key(client, "key-1", _body(session, promo_code="NOPE"))

    assert second.status_code == 200
    assert second.json() == first.json()
    assert _payments_count(session) == 1


def test_failed_request_with_key_does_not_occupy_the_key(
    client: TestClient, session: Session
) -> None:
    rejected = _post_with_key(client, "key-1", _body(session, promo_code="NOPE"))
    created = _post_with_key(client, "key-1", _body(session))

    assert rejected.status_code == 422
    assert created.status_code == 201
    assert _payments_count(session) == 1


@pytest.mark.parametrize("key", ["", "k" * 256])
def test_invalid_idempotency_key_is_422_and_nothing_is_created(
    client: TestClient, session: Session, key: str
) -> None:
    response = _post_with_key(client, key, _body(session))

    assert response.status_code == 422
    assert _payments_count(session) == 0


def test_max_length_idempotency_key_is_accepted(client: TestClient, session: Session) -> None:
    response = _post_with_key(client, "k" * 255, _body(session))

    assert response.status_code == 201
    assert _stored(session, response.json()["id"]).idempotency_key == "k" * 255


def test_payment_without_idempotency_key_is_stored_with_null_key(
    client: TestClient, session: Session
) -> None:
    response = client.post("/payments", json=_body(session))

    assert response.status_code == 201
    assert _stored(session, response.json()["id"]).idempotency_key is None


def test_concurrent_insert_with_same_key_returns_existing_payment(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _post_with_key(client, "key-1", _body(session))
    real_find = payments_service._find_by_idempotency_key
    calls: list[str] = []

    def find_missing_once(db_session: Session, key: str) -> Payment | None:
        # Первый поиск «не видит» платёж: параллельный запрос вставил его между SELECT и INSERT.
        calls.append(key)
        return None if len(calls) == 1 else real_find(db_session, key)

    monkeypatch.setattr(payments_service, "_find_by_idempotency_key", find_missing_once)

    second = _post_with_key(client, "key-1", _body(session))

    assert second.status_code == 200
    assert second.json() == first.json()
    assert len(calls) == 2
    assert _payments_count(session) == 1


@pytest.mark.parametrize("idempotency_key", [None, "key-1"])
def test_integrity_error_not_caused_by_key_is_not_masked(
    client: TestClient,
    session: Session,
    monkeypatch: pytest.MonkeyPatch,
    idempotency_key: str | None,
) -> None:
    # Ошибка целостности не из-за ключа: платежа с таким ключом нет (или ключа нет вовсе).
    # Такой отказ нельзя выдавать за успешный повтор. Уже лежащий платёж без ключа — приманка:
    # поиск по `None` (`IS NULL`) нашёл бы его и выдал за результат.
    client.post("/payments", json=_body(session))

    def failing_commit() -> None:
        raise IntegrityError("INSERT INTO payments", {}, Exception("boom"))

    monkeypatch.setattr(session, "commit", failing_commit)
    data = PaymentCreate(tariff_id=_tariff_id(session), email=EMAIL, method=PaymentMethod.CARD)

    with pytest.raises(IntegrityError):
        create_payment(session, data, idempotency_key)

    assert _payments_count(session) == 1


# --- GET /payments: фильтры по email и статусу ---


def _create(client: TestClient, session: Session, email: str, **overrides: Any) -> int:
    response = client.post("/payments", json=_body(session, email=email, **overrides))
    assert response.status_code == 201
    return response.json()["id"]


def _set_status(client: TestClient, payment_id: int, status: str) -> None:
    response = client.post("/webhooks/bank", json={"payment_id": payment_id, "status": status})
    assert response.status_code == 200


@pytest.fixture
def listed(client: TestClient, session: Session) -> dict[str, int]:
    """Четыре платежа: ключ — имя, значение — id (в порядке создания)."""
    ids = {
        "a_pending": _create(client, session, "a@example.com"),
        "b_succeeded": _create(client, session, "b@example.com", method="sbp"),
        "a_failed": _create(client, session, "a@example.com"),
        "a_succeeded": _create(
            client, session, "a@example.com", method="installment", installment_months=3
        ),
    }
    _set_status(client, ids["b_succeeded"], "succeeded")
    _set_status(client, ids["a_failed"], "failed")
    _set_status(client, ids["a_succeeded"], "succeeded")
    return ids


def _listed_ids(client: TestClient, **params: str) -> list[int]:
    response = client.get("/payments", params=params)
    assert response.status_code == 200
    return [item["id"] for item in response.json()]


def test_list_payments_without_filters_returns_all_sorted_by_id(
    client: TestClient, session: Session, listed: dict[str, int]
) -> None:
    response = client.get("/payments")

    assert response.status_code == 200
    ids = list(listed.values())
    assert [item["id"] for item in response.json()] == sorted(ids)
    assert len(response.json()) == _payments_count(session)
    # Элементы списка — те же `PaymentOut`, что отдаёт `GET /payments/{id}`.
    assert response.json() == [client.get(f"/payments/{i}").json() for i in sorted(ids)]


def test_list_payments_on_empty_database_returns_empty_list(client: TestClient) -> None:
    response = client.get("/payments")

    assert response.status_code == 200
    assert response.json() == []


def test_list_payments_filters_by_email(client: TestClient, listed: dict[str, int]) -> None:
    ids = _listed_ids(client, email="a@example.com")

    assert ids == [listed["a_pending"], listed["a_failed"], listed["a_succeeded"]]


def test_list_payments_filters_by_status(client: TestClient, listed: dict[str, int]) -> None:
    ids = _listed_ids(client, status="succeeded")

    assert ids == [listed["b_succeeded"], listed["a_succeeded"]]


def test_list_payments_filters_by_email_and_status(
    client: TestClient, listed: dict[str, int]
) -> None:
    ids = _listed_ids(client, email="a@example.com", status="succeeded")

    assert ids == [listed["a_succeeded"]]


@pytest.mark.parametrize(
    "params",
    [
        {"email": "nobody@example.com"},
        {"status": "refunded"},
        {"email": "b@example.com", "status": "failed"},
    ],
    ids=["unknown-email", "no-payment-in-status", "email-and-status-do-not-match"],
)
def test_list_payments_without_matches_returns_empty_list(
    client: TestClient, listed: dict[str, int], params: dict[str, str]
) -> None:
    response = client.get("/payments", params=params)

    assert response.status_code == 200
    assert response.json() == []


def test_list_payments_email_domain_case_is_normalized_like_on_create(
    client: TestClient, session: Session
) -> None:
    # EmailStr приводит домен к нижнему регистру и при создании, и в фильтре.
    payment_id = _create(client, session, "Student@Example.COM")

    assert _listed_ids(client, email="Student@EXAMPLE.com") == [payment_id]


def test_list_payments_email_local_part_case_matters(client: TestClient, session: Session) -> None:
    _create(client, session, "Student@example.com")

    assert _listed_ids(client, email="student@example.com") == []


def test_list_payments_email_with_plus_sign(client: TestClient, session: Session) -> None:
    payment_id = _create(client, session, "a+tag@example.com")
    _create(client, session, "a@example.com")

    # httpx кодирует `+` как %2B; без кодирования сервер увидел бы пробел.
    assert _listed_ids(client, email="a+tag@example.com") == [payment_id]


@pytest.mark.parametrize(
    "params",
    [{"status": "paid"}, {"status": ""}, {"email": "not-an-email"}, {"email": ""}],
    ids=["unknown-status", "empty-status", "invalid-email", "empty-email"],
)
def test_list_payments_invalid_filter_is_standard_422(
    client: TestClient, listed: dict[str, int], params: dict[str, str]
) -> None:
    response = client.get("/payments", params=params)

    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)


def test_list_payments_does_not_change_anything(
    client: TestClient, session: Session, listed: dict[str, int]
) -> None:
    before = client.get("/payments")
    assert before.status_code == 200

    filtered = client.get("/payments", params={"email": "a@example.com", "status": "pending"})
    assert filtered.status_code == 200

    assert client.get("/payments").json() == before.json()
    assert _payments_count(session) == len(listed)


def test_list_payments_openapi_declares_list_and_422(client: TestClient) -> None:
    operation = client.get("/openapi.json").json()["paths"]["/payments"]["get"]

    schema = operation["responses"]["200"]["content"]["application/json"]["schema"]
    assert schema["type"] == "array"
    assert schema["items"] == {"$ref": "#/components/schemas/PaymentOut"}
    assert "422" in operation["responses"]
    assert {p["name"] for p in operation["parameters"]} == {"email", "status"}
    assert all(not p["required"] for p in operation["parameters"])
