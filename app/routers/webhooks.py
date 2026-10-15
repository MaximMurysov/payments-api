from fastapi import APIRouter, status

from app.db import SessionDep
from app.schemas import ErrorOut, InvalidTransitionOut, UnprocessableOut, WebhookIn, WebhookOk
from app.services.payments import change_status

router = APIRouter(tags=["webhooks"])


@router.post(
    "/webhooks/bank",
    response_model=WebhookOk,
    responses={
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
