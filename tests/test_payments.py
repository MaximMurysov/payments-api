from datetime import datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import Payment, PaymentStatus, Tariff
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
    assert _payments_count(session) == 0


def test_create_payment_unknown_tariff_is_422(client: TestClient, session: Session) -> None:
    response = client.post("/payments", json=_body(session, tariff_id=999999))

    assert response.status_code == 422
    assert response.json() == {"detail": "Tariff 999999 not found"}
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
    assert _payments_count(session) == 0
