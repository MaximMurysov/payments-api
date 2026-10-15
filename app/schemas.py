from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field

from app.models import PaymentMethod, PaymentStatus


class TariffOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    # Цена в копейках.
    price: int


class PaymentCreate(BaseModel):
    tariff_id: int
    email: EmailStr
    method: PaymentMethod
    installment_months: Literal[3, 6, 12] | None = None
    # Регистр и пробелы по краям не важны; пустая строка — промокода нет (см. services/pricing.py).
    promo_code: str | None = Field(default=None, max_length=32)


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    status: PaymentStatus
    tariff_id: int
    # Суммы в копейках.
    amount: int
    discount: int
    method: PaymentMethod
    installment_months: int | None
    schedule: list[int] | None
    email: str
    created_at: datetime
