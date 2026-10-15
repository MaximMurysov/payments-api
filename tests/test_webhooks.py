from itertools import product
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from app.errors import InvalidTransition, PaymentNotFound
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
