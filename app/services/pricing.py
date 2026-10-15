"""Денежная арифметика: чистые функции без FastAPI и БД. Все суммы — int в копейках."""

from app.errors import UnknownPromoCode

# Код промокода (в верхнем регистре) → процент скидки.
PROMO_CODES: dict[str, int] = {"KVITTO10": 10}


def resolve_promo(code: str | None) -> int:
    """Возвращает процент скидки по промокоду; регистр и пробелы по краям не важны.

    `None` и пустая строка (в том числе из одних пробелов) — промокода нет, скидка 0 %.
    Неизвестный код — `UnknownPromoCode`.
    """
    if code is None or not code.strip():
        return 0
    percent = PROMO_CODES.get(code.strip().upper())
    if percent is None:
        raise UnknownPromoCode(code)
    return percent


def calc_discount(price: int, percent: int) -> int:
    """Скидка в копейках; дробная копейка отбрасывается (округление вниз)."""
    return price * percent // 100
