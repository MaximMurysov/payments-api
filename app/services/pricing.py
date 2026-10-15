"""Денежная арифметика: чистые функции без FastAPI и БД. Все суммы — int в копейках."""

from collections.abc import Mapping
from types import MappingProxyType
from typing import Final

from app.errors import UnknownPromoCode

# Код промокода (в верхнем регистре, без пробелов) → процент скидки. Только для чтения.
PROMO_CODES: Final[Mapping[str, int]] = MappingProxyType({"KVITTO10": 10})


def normalize_promo_code(code: str | None) -> str | None:
    """Код в каноническом виде (`KVITTO10`): без пробелов по краям, в верхнем регистре.

    `None` и пустая строка (в том числе из одних пробелов) — промокода нет, результат `None`.
    """
    if code is None:
        return None
    return code.strip().upper() or None


def resolve_promo(code: str | None) -> int:
    """Возвращает процент скидки по промокоду; регистр и пробелы по краям не важны.

    `None` и пустая строка (в том числе из одних пробелов) — промокода нет, скидка 0 %.
    Неизвестный код — `UnknownPromoCode`.
    """
    normalized = normalize_promo_code(code)
    if normalized is None:
        return 0
    percent = PROMO_CODES.get(normalized)
    if percent is None:
        raise UnknownPromoCode(code)
    return percent


def calc_discount(price: int, percent: int) -> int:
    """Скидка в копейках; дробная копейка отбрасывается (округление вниз)."""
    return price * percent // 100


def build_schedule(amount: int, months: int) -> list[int]:
    """График рассрочки: `months` платежей в копейках, сумма ровно равна `amount`.

    Платежи отличаются не больше чем на копейку; лишние копейки остатка — в первых платежах.
    Предусловие: `amount >= 0` (сумма к оплате — цена тарифа минус скидка), его держит вызывающий.
    """
    if months <= 0:
        raise ValueError(f"months must be positive, got {months}")
    base, rem = divmod(amount, months)
    return [base + 1] * rem + [base] * (months - rem)
