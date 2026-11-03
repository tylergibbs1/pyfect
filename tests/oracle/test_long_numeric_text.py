"""Digit runs past Python's 4300-digit ``int(str)`` limit (collections
review). Effect reads them with ``Number`` / ``BigInt``; the expected values
were printed by Effect's source under Node."""

from __future__ import annotations

from pyfect import big_decimal, semver, semver_range
from pyfect.result import Err, Result

LONG = "1" * 5000


def _message(result: Result[object, object]) -> str:
    assert isinstance(result, Err)
    return str(result.error)


def test_a_long_semver_component_is_not_a_safe_integer() -> None:
    assert _message(semver.parse(f"{LONG}.0.0")).endswith(
        "major must be a non-negative safe integer, received Infinity"
    )
    assert _message(semver.parse(f"1.0.0-{LONG}")).endswith(
        "numeric pre-release identifier must be a non-negative safe integer, received Infinity"
    )
    assert _message(semver_range.parse(f">={LONG}")).endswith(
        "major must be a non-negative safe integer, received Infinity"
    )


def test_an_unsafe_semver_component_prints_as_a_javascript_number() -> None:
    assert _message(semver.parse("11111111111111111111.0.0")) == (
        'Invalid SemVer "11111111111111111111.0.0": major must be a non-negative safe'
        " integer, received 11111111111111110000"
    )
    assert _message(semver.parse("9007199254740993.0.0")).endswith("received 9007199254740992")
    assert _message(semver.parse("1.0.0-11111111111111111111")).endswith(
        "numeric pre-release identifier must be a non-negative safe integer,"
        " received 11111111111111110000"
    )


def test_big_decimal_reads_any_number_of_digits() -> None:
    parsed = big_decimal.from_string(f"{LONG}.5")
    assert parsed is not None
    assert parsed.scale == 1
    assert len(parsed.format()) == 5002
    assert parsed.format() == f"{LONG}.5"
