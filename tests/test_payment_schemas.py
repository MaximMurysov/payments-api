from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from app.models import Payment, PaymentMethod, PaymentStatus
from app.schemas import PaymentCreate, PaymentOut

VALID_CARD = {"tariff_id": 1, "email": "student@example.com", "method": "card"}


def test_payment_create_accepts_card_without_promo() -> None:
    data = PaymentCreate.model_validate(VALID_CARD)

    assert data.method is PaymentMethod.CARD
    assert data.installment_months is None
    assert data.promo_code is None


@pytest.mark.parametrize("method", ["card", "sbp", "installment"])
def test_payment_create_method_is_enum(method: str) -> None:
    months = 3 if method == "installment" else None
    data = PaymentCreate.model_validate(
        {**VALID_CARD, "method": method, "installment_months": months}
    )

    assert data.method is PaymentMethod(method)


@pytest.mark.parametrize("method", ["cash", "CARD", ""])
def test_payment_create_rejects_unknown_method(method: str) -> None:
    with pytest.raises(ValidationError):
        PaymentCreate.model_validate({**VALID_CARD, "method": method})


@pytest.mark.parametrize("email", ["not-an-email", "student@", ""])
def test_payment_create_rejects_invalid_email(email: str) -> None:
    with pytest.raises(ValidationError):
        PaymentCreate.model_validate({**VALID_CARD, "email": email})


@pytest.mark.parametrize("tariff_id", [True, "1", 1.0, 0, -1, 2**31])
def test_payment_create_rejects_invalid_tariff_id(tariff_id: object) -> None:
    # Без строгого режима JSON `true` молча превратился бы в тариф с id 1.
    with pytest.raises(ValidationError):
        PaymentCreate.model_validate({**VALID_CARD, "tariff_id": tariff_id})


@pytest.mark.parametrize("field", ["tariff_id", "email", "method"])
def test_payment_create_requires_field(field: str) -> None:
    body = {key: value for key, value in VALID_CARD.items() if key != field}

    with pytest.raises(ValidationError):
        PaymentCreate.model_validate(body)


@pytest.mark.parametrize("months", [0, 1, 5, 24, -3])
def test_payment_create_rejects_months_outside_3_6_12(months: int) -> None:
    with pytest.raises(ValidationError):
        PaymentCreate.model_validate(
            {**VALID_CARD, "method": "installment", "installment_months": months}
        )


def test_payment_create_limits_promo_code_length() -> None:
    PaymentCreate.model_validate({**VALID_CARD, "promo_code": "X" * 32})

    # Код попадает в тело ответа 422 и в БД: без ограничения туда пришла бы строка любой длины.
    with pytest.raises(ValidationError):
        PaymentCreate.model_validate({**VALID_CARD, "promo_code": "X" * 33})


def test_payment_out_exposes_only_public_fields() -> None:
    payment = Payment(
        id=7,
        tariff_id=2,
        email="student@example.com",
        method=PaymentMethod.INSTALLMENT,
        installment_months=3,
        amount=1990000,
        discount=0,
        promo_code=None,
        schedule=[663334, 663333, 663333],
        status=PaymentStatus.PENDING,
        idempotency_key="secret-key",
        created_at=datetime(2026, 10, 15, 12, 0, tzinfo=UTC),
    )

    body = PaymentOut.model_validate(payment).model_dump(mode="json")

    assert body == {
        "id": 7,
        "status": "pending",
        "tariff_id": 2,
        "amount": 1990000,
        "discount": 0,
        "method": "installment",
        "installment_months": 3,
        "schedule": [663334, 663333, 663333],
        "email": "student@example.com",
        "created_at": "2026-10-15T12:00:00Z",
    }


@pytest.mark.parametrize("months", [3, 6, 12])
def test_payment_create_accepts_installment_with_months(months: int) -> None:
    data = PaymentCreate.model_validate(
        {**VALID_CARD, "method": "installment", "installment_months": months}
    )

    assert data.installment_months == months


def test_payment_create_requires_months_for_installment() -> None:
    with pytest.raises(ValidationError, match="installment_months"):
        PaymentCreate.model_validate({**VALID_CARD, "method": "installment"})


@pytest.mark.parametrize("method", ["card", "sbp"])
def test_payment_create_rejects_months_for_non_installment(method: str) -> None:
    # Невалидная комбинация не должна молча сохраниться с месяцами у оплаты картой.
    with pytest.raises(ValidationError, match="installment_months"):
        PaymentCreate.model_validate({**VALID_CARD, "method": method, "installment_months": 3})
