from typing import Annotated

from fastapi import APIRouter, Path, status

from app.db import SessionDep
from app.models import Payment
from app.schemas import MAX_ID, ErrorOut, PaymentCreate, PaymentOut, UnprocessableOut
from app.services.payments import create_payment, get_payment

router = APIRouter(tags=["payments"])


@router.post(
    "/payments",
    response_model=PaymentOut,
    status_code=status.HTTP_201_CREATED,
    responses={
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": UnprocessableOut,
            "description": "Validation error, unknown tariff or unknown promo code",
        }
    },
)
def post_payment(data: PaymentCreate, session: SessionDep) -> Payment:
    return create_payment(session, data)


@router.get(
    "/payments/{payment_id}",
    response_model=PaymentOut,
    responses={status.HTTP_404_NOT_FOUND: {"model": ErrorOut, "description": "Payment not found"}},
)
def read_payment(payment_id: Annotated[int, Path(gt=0, le=MAX_ID)], session: SessionDep) -> Payment:
    return get_payment(session, payment_id)
