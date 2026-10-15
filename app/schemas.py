from datetime import datetime
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, EmailStr, Field, model_validator

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

    @model_validator(mode="after")
    def check_installment_months(self) -> Self:
        # Срок рассрочки обязателен для рассрочки и запрещён для остальных способов оплаты.
        is_installment = self.method is PaymentMethod.INSTALLMENT
        if is_installment and self.installment_months is None:
            raise ValueError("installment_months is required for installment method")
        if not is_installment and self.installment_months is not None:
            raise ValueError("installment_months is allowed only for installment method")
        return self


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
