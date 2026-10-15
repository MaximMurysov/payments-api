from fastapi import APIRouter, Depends, status

from app.db import SessionDep
from app.schemas import ErrorOut, InvalidTransitionOut, UnprocessableOut, WebhookIn, WebhookOk
from app.security import verify_signature
from app.services.payments import change_status

router = APIRouter(tags=["webhooks"])


@router.post(
    "/webhooks/bank",
    response_model=WebhookOk,
    dependencies=[Depends(verify_signature)],
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "model": ErrorOut,
            "description": "X-Signature is missing or invalid (only when WEBHOOK_SECRET is set)",
        },
        status.HTTP_404_NOT_FOUND: {"model": ErrorOut, "description": "Payment not found"},
        status.HTTP_409_CONFLICT: {
            "model": InvalidTransitionOut,
            "description": "Status transition is not allowed; the payment status is unchanged",
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: {
            "model": UnprocessableOut,
            "description": "Validation error, e.g. unknown status",
        },
    },
)
def bank_webhook(data: WebhookIn, session: SessionDep) -> WebhookOk:
    change_status(session, data.payment_id, data.status)
    return WebhookOk(result="ok")
