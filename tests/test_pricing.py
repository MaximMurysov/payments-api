import pytest

from app.errors import UnknownPromoCode
from app.services.pricing import PROMO_CODES, calc_discount, resolve_promo


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
    assert all(code == code.strip().upper() for code in PROMO_CODES)


def test_promo_codes_cannot_be_modified_at_runtime() -> None:
    with pytest.raises(TypeError):
        PROMO_CODES["FREE100"] = 100


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
