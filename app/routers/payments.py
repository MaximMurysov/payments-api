from typing import Annotated

from fastapi import APIRouter, Header, Path, Response, status

from app.db import SessionDep
from app.models import Payment
from app.schemas import MAX_ID, ErrorOut, PaymentCreate, PaymentOut, UnprocessableOut
from app.services.payments import create_payment, get_payment

# Длина колонки `payments.idempotency_key`: больший ключ Postgres отвергнет с 500, а не 422.
MAX_IDEMPOTENCY_KEY = 255

router = APIRouter(tags=["payments"])


@router.post(
    "/payments",
    response_model=PaymentOut,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_200_OK: {
            "model": PaymentOut,
            "description": "Repeat request with the same Idempotency-Key: the existing payment",
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": UnprocessableOut,
            "description": "Validation error, unknown tariff or unknown promo code",
        },
    },
)
def post_payment(
    data: PaymentCreate,
    session: SessionDep,
    response: Response,
    idempotency_key: Annotated[
        str | None, Header(alias="Idempotency-Key", min_length=1, max_length=MAX_IDEMPOTENCY_KEY)
    ] = None,
) -> Payment:
    payment, created = create_payment(session, data, idempotency_key)
    if not created:
        response.status_code = status.HTTP_200_OK
    return payment


@router.get(
    "/payments/{payment_id}",
    response_model=PaymentOut,
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorOut, "description": "Payment not found"}},
)
def read_payment(payment_id: Annotated[int, Path(gt=0, le=MAX_ID)], session: SessionDep) -> Payment:
    return get_payment(session, payment_id)
