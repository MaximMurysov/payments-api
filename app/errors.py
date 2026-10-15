class DomainError(Exception):
    """Базовое доменное исключение. HTTP-коды ему назначают обработчики в `main.py`."""


class UnknownPromoCode(DomainError):
    def __init__(self, code: str) -> None:
        super().__init__(f"unknown promo code: {code!r}")
        self.code = code
