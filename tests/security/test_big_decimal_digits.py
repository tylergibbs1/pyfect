"""(pyfect) ``big_decimal.from_string`` reads at most ``MAX_DIGITS`` significant digits (#31)."""

from __future__ import annotations

from _guards import guards

from pyfect import big_decimal
from pyfect import schema as S
from pyfect.exit import Failure


@guards("ef8f293a", "big-decimal-digits-unbounded")
def test_digits_up_to_the_limit_read_and_past_it_do_not() -> None:
    limit = big_decimal.MAX_DIGITS
    assert big_decimal.from_string("7" * limit) is not None
    assert big_decimal.from_string("0" * 50 + "7" * limit) is not None
    assert big_decimal.from_string("7" * (limit + 1)) is None
    assert big_decimal.from_string("7" * (limit - 1) + "." + "77") is None
    assert isinstance(S.decode_unknown_exit(S.BigDecimalFromString)("7" * (limit + 1)), Failure)


def test_the_limit_is_set_per_call() -> None:
    assert big_decimal.from_string("12345", max_digits=4) is None
    assert big_decimal.from_string("1234.5", max_digits=5) == big_decimal.from_string("1234.5")


def test_an_exponent_past_the_safe_integers_is_refused() -> None:
    assert big_decimal.from_string("1e" + "9" * 17) is None
    assert big_decimal.from_string("1e-0000000000000000000005") is not None
