"""(pyfect) ``yaml.parse`` converts at most ``MAX_INTEGER_DIGITS`` digits of an integer (#32).

A key is printed while parsing, and converting or printing an int of n digits costs
superlinear time, so 0.6.5 spent seconds on one long integer key. Timing that needed
megabyte inputs and still only just cleared its bound, so the digits converted are counted
instead, by wrapping the conversion: every key past the limit converts none.

The decimal keys run with Python's own limit on ``int`` turned off, as a program may
(``sys.set_int_max_str_digits(0)``): pyfect reads long digit runs past that limit elsewhere
(``_digits.to_int``, for JavaScript's ``BigInt``), so its limit must hold on its own.
"""

from __future__ import annotations

import contextlib
import sys
from collections.abc import Iterator

import pytest
from _guards import guards

from pyfect.encoding import yaml

_LIMIT = yaml.MAX_INTEGER_DIGITS
_PYTHON_LIMIT = sys.int_info.default_max_str_digits
_SIZES = [_LIMIT + 1, _PYTHON_LIMIT + 1, 1 << 16]


@pytest.fixture
def no_python_limit() -> Iterator[None]:
    before = sys.get_int_max_str_digits()
    sys.set_int_max_str_digits(0)
    try:
        yield
    finally:
        sys.set_int_max_str_digits(before)


def _most_digits_converted(text: str, monkeypatch: pytest.MonkeyPatch) -> int:
    converted = [0]
    convert = yaml._radix_int  # pyright: ignore[reportPrivateUsage]

    def counted(sign: int, digits: str, radix: int) -> int:
        value = convert(sign, digits, radix)
        converted.append(len(digits.lstrip("0")))
        return value

    monkeypatch.setattr(yaml, "_radix_int", counted)
    with contextlib.suppress(ValueError):  # a key past the limit is refused
        yaml.parse(text)
    return max(converted)


@pytest.mark.parametrize("prefix", ["0x", ""], ids=["hex", "decimal"])
def test_a_key_at_the_limit_is_converted(
    prefix: str, monkeypatch: pytest.MonkeyPatch, no_python_limit: None
) -> None:
    assert _most_digits_converted(f"{prefix}{'7' * _LIMIT}: 1", monkeypatch) == _LIMIT


@guards("12c66350", "yaml-hex-key-converted-in-full")
@pytest.mark.parametrize("size", _SIZES)
def test_a_hexadecimal_key_past_the_limit_is_not_converted(
    size: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert _most_digits_converted(f"0x{'f' * size}: 1", monkeypatch) <= _LIMIT


@guards("12c66350", "yaml-decimal-key-read-in-full")
@pytest.mark.parametrize("size", _SIZES)
def test_a_decimal_key_past_the_limit_is_not_converted(
    size: int, monkeypatch: pytest.MonkeyPatch, no_python_limit: None
) -> None:
    assert _most_digits_converted(f"{'7' * size}: 1", monkeypatch) <= _LIMIT
