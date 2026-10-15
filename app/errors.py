from app.models import PaymentStatus


class DomainError(Exception):
    """Базовое доменное исключение. HTTP-коды ему назначают обработчики в `main.py`."""


class UnknownPromoCode(DomainError):
    def __init__(self, code: str) -> None:
        super().__init__(f"unknown promo code: {code!r}")
        self.code = code


class TariffNotFound(DomainError):
    def __init__(self, tariff_id: int) -> None:
        super().__init__(f"tariff not found: {tariff_id}")
        self.tariff_id = tariff_id


class PaymentNotFound(DomainError):
    def __init__(self, payment_id: int) -> None:
        super().__init__(f"payment not found: {payment_id}")
        self.payment_id = payment_id


class InvalidTransition(DomainError):
    def __init__(self, old: PaymentStatus, new: PaymentStatus) -> None:
        super().__init__(f"invalid status transition: {old.value} -> {new.value}")
        self.old = old
        self.new = new
