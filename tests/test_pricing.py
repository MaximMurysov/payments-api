from typing import cast

import pytest

from app.errors import UnknownPromoCode
from app.services.pricing import PROMO_CODES, build_schedule, calc_discount, resolve_promo


def test_resolve_promo_without_code_gives_no_discount() -> None:
    assert resolve_promo(None) == 0


@pytest.mark.parametrize("code", ["", "   "])
def test_resolve_promo_blank_code_means_no_promo(code: str) -> None:
    assert resolve_promo(code) == 0


@pytest.mark.parametrize("code", ["KVITTO10", "kvitto10", " Kvitto10 ", "kViTtO10"])
def test_resolve_promo_is_case_and_space_insensitive(code: str) -> None:
    assert resolve_promo(code) == 10


def test_promo_codes_keys_are_normalized() -> None:
    # resolve_promo ищет код после strip().upper(): ключ в другом виде никогда бы не сработал.
    assert PROMO_CODES
    assert all(code == code.strip().upper() for code in PROMO_CODES)


def test_promo_codes_cannot_be_modified_at_runtime() -> None:
    with pytest.raises(TypeError):
        # cast: проверяем поведение во время работы, статический тип Mapping запись не допускает.
        cast(dict[str, int], PROMO_CODES)["FREE100"] = 100


@pytest.mark.parametrize("code", ["NOPE", "KVITTO1", "KVITTO100", "KVITTO 10"])
def test_resolve_promo_unknown_code_raises(code: str) -> None:
    with pytest.raises(UnknownPromoCode) as exc_info:
        resolve_promo(code)

    # Код сохраняется как прислан: пригодится для сообщения об ошибке на HTTP-слое.
    assert exc_info.value.code == code


@pytest.mark.parametrize(
    ("price", "percent", "expected"),
    [
        (990000, 10, 99000),
        (1990000, 10, 199000),
        (2990000, 10, 299000),
        (1990000, 0, 0),
        # Дробная копейка отбрасывается: скидка округляется вниз, в пользу школы.
        (999, 10, 99),
        (1, 10, 0),
    ],
)
def test_calc_discount(price: int, percent: int, expected: int) -> None:
    discount = calc_discount(price, percent)

    assert discount == expected
    assert type(discount) is int


TARIFF_PRICES = (990000, 1990000, 2990000)
# Суммы к оплате по всем тарифам, без промокода и с ним. Суммы с промокодом делятся на 3/6/12
# нацело, поэтому добавлены суммы с заведомым остатком: иначе остаток проверялся бы не везде.
SCHEDULE_AMOUNTS = sorted(
    {price - calc_discount(price, percent) for price in TARIFF_PRICES for percent in (0, 10)}
    | {1000, 2989999}
)


@pytest.mark.parametrize("months", [3, 6, 12])
@pytest.mark.parametrize("amount", SCHEDULE_AMOUNTS)
def test_build_schedule_invariants(amount: int, months: int) -> None:
    schedule = build_schedule(amount, months)

    assert sum(schedule) == amount
    assert len(schedule) == months
    assert all(type(payment) is int for payment in schedule)
    assert max(schedule) - min(schedule) <= 1
    # Лишние копейки — в первых платежах: список не возрастает.
    assert schedule == sorted(schedule, reverse=True)


@pytest.mark.parametrize(
    ("amount", "months", "expected"),
    [
        # Пример из ТЗ.
        (1990000, 3, [663334, 663333, 663333]),
        (1000, 3, [334, 333, 333]),
        # Остаток больше 1: несколько лишних копеек, все в начале.
        (1000, 6, [167] * 4 + [166] * 2),
        (2990000, 12, [249167] * 8 + [249166] * 4),
        # Делится нацело: все платежи равны.
        (990000, 12, [82500] * 12),
        # Сумма меньше числа месяцев: последние платежи нулевые, но сумма точная.
        (2, 3, [1, 1, 0]),
    ],
)
def test_build_schedule_exact(amount: int, months: int, expected: list[int]) -> None:
    assert build_schedule(amount, months) == expected


@pytest.mark.parametrize("months", [0, -3])
def test_build_schedule_rejects_non_positive_months(months: int) -> None:
    # Без проверки -3 молча дал бы пустой график, и сумма графика не совпала бы с amount.
    with pytest.raises(ValueError):
        build_schedule(1000, months)
