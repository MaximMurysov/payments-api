from fastapi import APIRouter, status

from app.db import SessionDep
from app.models import Payment
from app.schemas import PaymentCreate, PaymentOut
from app.services.payments import create_payment

router = APIRouter(tags=["payments"])


@router.post("/payments", response_model=PaymentOut, status_code=status.HTTP_201_CREATED)
def post_payment(data: PaymentCreate, session: SessionDep) -> Payment:
    return create_payment(session, data)
