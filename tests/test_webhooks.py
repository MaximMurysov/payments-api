import hashlib
import hmac
import json
from collections.abc import Iterator
from itertools import product
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.config import Settings
from app.errors import InvalidTransition, PaymentNotFound
from app.main import create_app
from app.models import Payment, PaymentStatus
from app.services import payments as payments_service
from app.services.payments import can_transition, change_status

ALLOWED_PAIRS = {
    (PaymentStatus.PENDING, PaymentStatus.SUCCEEDED),
    (PaymentStatus.PENDING, PaymentStatus.FAILED),
    (PaymentStatus.SUCCEEDED, PaymentStatus.REFUNDED),
}
# Цепочка разрешённых вебхуков, которая приводит свежий платёж (pending) в нужный статус.
PATH_TO: dict[PaymentStatus, list[PaymentStatus]] = {
    PaymentStatus.PENDING: [],
    PaymentStatus.SUCCEEDED: [PaymentStatus.SUCCEEDED],
    PaymentStatus.FAILED: [PaymentStatus.FAILED],
    PaymentStatus.REFUNDED: [PaymentStatus.SUCCEEDED, PaymentStatus.REFUNDED],
}
FORBIDDEN_PAIRS = [
    pair for pair in product(PaymentStatus, PaymentStatus) if pair not in ALLOWED_PAIRS
]


@pytest.mark.parametrize(
    ("old", "new"),
    list(product(PaymentStatus, PaymentStatus)),
    ids=lambda status: status.value,
)
def test_can_transition_matches_allowed_table(old: PaymentStatus, new: PaymentStatus) -> None:
    assert can_transition(old, new) is ((old, new) in ALLOWED_PAIRS)


def test_exactly_three_transitions_are_allowed() -> None:
    pairs = list(product(PaymentStatus, PaymentStatus))

    assert len(pairs) == 16
    assert sum(can_transition(old, new) for old, new in pairs) == 3


def _create_payment(client: TestClient) -> int:
    tariff_id = client.get("/tariffs").json()[0]["id"]
    response = client.post(
        "/payments", json={"tariff_id": tariff_id, "email": "student@example.com", "method": "card"}
    )
    assert response.status_code == 201
    return response.json()["id"]


def _webhook(client: TestClient, payment_id: int, status: str) -> Any:
    return client.post("/webhooks/bank", json={"payment_id": payment_id, "status": status})


def _payment_in_status(client: TestClient, status: PaymentStatus) -> int:
    payment_id = _create_payment(client)
    for step in PATH_TO[status]:
        assert _webhook(client, payment_id, step).status_code == 200
    assert client.get(f"/payments/{payment_id}").json()["status"] == status
    return payment_id


def _status(client: TestClient, payment_id: int) -> str:
    return client.get(f"/payments/{payment_id}").json()["status"]


@pytest.mark.parametrize(("old", "new"), sorted(ALLOWED_PAIRS), ids=lambda status: status.value)
def test_allowed_transition_updates_status(
    client: TestClient, old: PaymentStatus, new: PaymentStatus
) -> None:
    payment_id = _payment_in_status(client, old)

    response = _webhook(client, payment_id, new)

    assert response.status_code == 200
    assert response.json() == {"result": "ok"}
    assert _status(client, payment_id) == new


@pytest.mark.parametrize(("old", "new"), FORBIDDEN_PAIRS, ids=lambda status: status.value)
def test_forbidden_transition_returns_409_and_keeps_status(
    client: TestClient, old: PaymentStatus, new: PaymentStatus
) -> None:
    payment_id = _payment_in_status(client, old)

    response = _webhook(client, payment_id, new)

    assert response.status_code == 409
    assert response.json() == {"error": "invalid_transition"}
    assert _status(client, payment_id) == old


def test_unknown_payment_returns_404(client: TestClient) -> None:
    response = _webhook(client, 999999, "succeeded")

    assert response.status_code == 404


def test_unknown_status_returns_422_and_keeps_status(client: TestClient) -> None:
    payment_id = _create_payment(client)

    response = _webhook(client, payment_id, "paid")

    assert response.status_code == 422
    assert _status(client, payment_id) == "pending"


# "PID" и "PID_STR" подставляются id созданного платежа: тогда случаи с ссылкой на платёж проверяют
# именно его статус. Литеральные id (0, 2**31) платёж не адресуют, для них проверяется только 422.
@pytest.mark.parametrize(
    "body",
    [
        {"payment_id": "PID"},
        {"status": "succeeded"},
        {"payment_id": 0, "status": "succeeded"},
        {"payment_id": 2**31, "status": "succeeded"},
        {"payment_id": "PID_STR"},
    ],
    ids=["no-status", "no-payment-id", "zero-id", "id-overflow", "id-as-string"],
)
def test_invalid_body_returns_422_and_keeps_status(
    client: TestClient, body: dict[str, Any]
) -> None:
    payment_id = _create_payment(client)
    filled = {
        key: payment_id if value == "PID" else str(payment_id) if value == "PID_STR" else value
        for key, value in body.items()
    }

    response = client.post("/webhooks/bank", json=filled)

    assert response.status_code == 422
    assert _status(client, payment_id) == "pending"


def test_webhook_openapi_declares_409_and_404(client: TestClient) -> None:
    responses = client.get("/openapi.json").json()["paths"]["/webhooks/bank"]["post"]["responses"]

    assert responses["409"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/InvalidTransitionOut"
    }
    # Presence check: схему 404 проверяет тест формата `GET /payments/{id}`.
    assert "404" in responses


def test_change_status_unknown_payment_raises(session: Session) -> None:
    with pytest.raises(PaymentNotFound):
        change_status(session, 999999, PaymentStatus.SUCCEEDED)


def test_change_status_loses_race_when_status_changed_after_read(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Параллельный вебхук успел сменить статус между чтением платежа и UPDATE.

    Проверка `can_transition` на устаревшем статусе проходит, поэтому инвариант держит только
    условный UPDATE: `rowcount == 0` → `InvalidTransition`, статус победителя не затёрт.
    """
    # Шпион за предпроверкой: тест обязан дойти до UPDATE, а не упасть уже на `can_transition`.
    # Identity map держит объекты слабыми ссылками: не будь живой ссылки `payment`, сессия
    # перечитала бы строку и увидела `succeeded`. Шпион зафиксирует запрет, и тест упадёт,
    # а не вырожденно пройдёт мимо ветки `rowcount == 0`.
    prechecks: list[tuple[PaymentStatus, bool]] = []
    real_can_transition = payments_service.can_transition

    def spy(old: PaymentStatus, new: PaymentStatus) -> bool:
        allowed = real_can_transition(old, new)
        prechecks.append((old, allowed))
        return allowed

    monkeypatch.setattr(payments_service, "can_transition", spy)
    payment_id = _create_payment(client)
    # Платёж в identity map сессии со статусом pending — как у запроса, прочитавшего его до гонки.
    payment = session.get(Payment, payment_id)
    assert payment is not None
    assert payment.status is PaymentStatus.PENDING
    with client.app.state.session_factory() as rival:
        rival.execute(
            update(Payment).where(Payment.id == payment_id).values(status=PaymentStatus.SUCCEEDED)
        )
        rival.commit()

    with pytest.raises(InvalidTransition):
        change_status(session, payment_id, PaymentStatus.FAILED)

    # Предпроверка видела устаревший pending и пропустила; отказал именно условный UPDATE.
    assert prechecks == [(PaymentStatus.PENDING, True)]
    with client.app.state.session_factory() as check:
        stored = check.scalar(select(Payment.status).where(Payment.id == payment_id))
    assert stored is PaymentStatus.SUCCEEDED


# --- Подпись вебхука (X-Signature, HMAC-SHA256 от сырых байтов тела) ---

SECRET = "test-webhook-secret"


@pytest.fixture
def signed_client(tmp_path: Path) -> Iterator[TestClient]:
    """Приложение с заданным `WEBHOOK_SECRET`: вебхук проверяет подпись."""
    settings = Settings(_env_file=None, webhook_secret=SECRET)
    app = create_app(f"sqlite:///{(tmp_path / 'signed.db').as_posix()}", settings)
    with TestClient(app) as test_client:
        yield test_client


def _sign(body: bytes, secret: str = SECRET) -> str:
    return hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _body(payment_id: int, status: str) -> bytes:
    return json.dumps({"payment_id": payment_id, "status": status}).encode()


def _post_raw(client: TestClient, body: bytes, signature: str | bytes | None) -> Any:
    """Шлёт байты тела как есть: TestClient не пересериализует их и не подписывает сам."""
    headers: dict[str, str | bytes] = {"Content-Type": "application/json"}
    if signature is not None:
        headers["X-Signature"] = signature
    return client.post("/webhooks/bank", content=body, headers=headers)


def test_valid_signature_updates_status(signed_client: TestClient) -> None:
    payment_id = _create_payment(signed_client)
    body = _body(payment_id, "succeeded")

    response = _post_raw(signed_client, body, _sign(body))

    assert response.status_code == 200
    assert response.json() == {"result": "ok"}
    assert _status(signed_client, payment_id) == "succeeded"


def test_signature_is_computed_over_raw_body_bytes(signed_client: TestClient) -> None:
    payment_id = _create_payment(signed_client)
    # Пробелы, перенос строки и порядок ключей не совпадают с выводом `json.dumps`: подпись от
    # пересериализованного JSON обязана не подойти, подпись от исходных байтов — подойти.
    body = f'{{ "status" : "succeeded",\n  "payment_id": {payment_id} }}'.encode()
    reserialized = json.dumps(json.loads(body)).encode()
    assert reserialized != body

    rejected = _post_raw(signed_client, body, _sign(reserialized))

    assert rejected.status_code == 401
    assert _status(signed_client, payment_id) == "pending"
    accepted = _post_raw(signed_client, body, _sign(body))
    assert accepted.status_code == 200
    assert _status(signed_client, payment_id) == "succeeded"


BAD_SIGNATURES = {
    "other-secret": lambda body: _sign(body, "other-secret"),
    "signature-of-other-body": lambda body: _sign(body + b" "),
    "garbage": lambda body: "not-a-signature",
    "empty": lambda body: "",
    "uppercase-hex": lambda body: _sign(body).upper(),
    # Не-ASCII в заголовке: `compare_digest` на таких `str` бросает TypeError, ждём 401, не 500.
    "non-ascii": lambda body: "подпись".encode(),
}


@pytest.mark.parametrize("make_signature", BAD_SIGNATURES.values(), ids=BAD_SIGNATURES.keys())
def test_invalid_signature_returns_401_and_keeps_status(
    signed_client: TestClient, make_signature: Any
) -> None:
    payment_id = _create_payment(signed_client)
    body = _body(payment_id, "succeeded")

    response = _post_raw(signed_client, body, make_signature(body))

    assert response.status_code == 401
    assert response.json() == {"detail": "Invalid signature"}
    assert _status(signed_client, payment_id) == "pending"


def test_missing_signature_returns_401_and_keeps_status(signed_client: TestClient) -> None:
    payment_id = _create_payment(signed_client)

    response = _post_raw(signed_client, _body(payment_id, "succeeded"), None)

    assert response.status_code == 401
    assert response.json() == {"detail": "Missing signature"}
    assert _status(signed_client, payment_id) == "pending"


def test_signature_is_not_checked_without_secret(client: TestClient) -> None:
    payment_id = _create_payment(client)
    body = _body(payment_id, "succeeded")

    response = _post_raw(client, body, "whatever")

    assert response.status_code == 200
    assert _status(client, payment_id) == "succeeded"


# Подпись проверяется раньше, чем тело и платёж: иначе 404/409/422 показали бы неавторизованному
# вызывающему, существует ли платёж и в каком он статусе.
@pytest.mark.parametrize(
    ("case", "expected_with_valid_signature"),
    [("unknown-payment", 404), ("unknown-status", 422), ("forbidden-transition", 409)],
)
def test_bad_signature_wins_over_404_422_409(
    signed_client: TestClient, case: str, expected_with_valid_signature: int
) -> None:
    payment_id = _create_payment(signed_client)
    settle = _body(payment_id, "succeeded")
    assert _post_raw(signed_client, settle, _sign(settle)).status_code == 200
    body = {
        "unknown-payment": _body(999999, "succeeded"),
        "unknown-status": _body(payment_id, "paid"),
        "forbidden-transition": _body(payment_id, "succeeded"),
    }[case]
    # Контроль: с верной подписью то же тело даёт 404/422/409, иначе тест не проверял бы порядок.
    assert _post_raw(signed_client, body, _sign(body)).status_code == expected_with_valid_signature

    response = _post_raw(signed_client, body, _sign(body, "other-secret"))

    assert response.status_code == 401
    assert _status(signed_client, payment_id) == "succeeded"


def test_malformed_json_returns_422_before_signature_check(signed_client: TestClient) -> None:
    """FastAPI разбирает JSON раньше зависимостей; про платежи такой ответ ничего не раскрывает."""
    response = _post_raw(signed_client, b'{"payment_id": ', None)

    assert response.status_code == 422


def test_webhook_openapi_declares_401(client: TestClient) -> None:
    responses = client.get("/openapi.json").json()["paths"]["/webhooks/bank"]["post"]["responses"]

    assert responses["401"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/ErrorOut"
    }
