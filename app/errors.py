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
