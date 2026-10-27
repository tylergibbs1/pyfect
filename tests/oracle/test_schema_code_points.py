"""Ports of Effect's ``schema/CodePoints.test.ts`` ("code point checks").

Ported in part: "rounds down bounds and clamps negative bounds to zero"
(bounds are ``int``, so there is nothing to round; the clamping half is
ported).

Omitted: "preserves length checks based on UTF-16 code units": Python's
``len`` counts code points, so ``is_min_length`` agrees with
``is_min_code_points`` on strings.
"""

import pytest

from pyfect import schema as S
from pyfect.testing import SchemaAsserts

CASES = [
    ("", 0),
    ("a", 1),
    ("abc", 3),
    ("😀", 1),
    ("a😀b", 3),
    ("é", 1),
    ("e\u0301", 2),
    ("👨‍👩‍👧‍👦", 7),
    ("\ud800", 1),
    ("\udc00", 1),
    ("\ud800\U00010000", 2),
    ("\r\n", 2),
]


def test_counts_code_points_at_inclusive_minimum_and_maximum_boundaries():
    """counts code points at inclusive minimum and maximum boundaries"""
    for bound in range(9):
        at_least = S.is_(S.String.check(S.is_min_code_points(bound)))
        at_most = S.is_(S.String.check(S.is_max_code_points(bound)))
        exactly = S.is_(S.String.check(S.is_between_code_points(bound, bound)))
        for value, count in CASES:
            assert at_least(value) is (count >= bound)
            assert at_most(value) is (count <= bound)
            assert exactly(value) is (count == bound)


def test_checks_inclusive_ranges_and_rejects_inverted_ranges():
    """checks inclusive ranges and rejects inverted ranges"""
    between = S.is_(S.String.check(S.is_between_code_points(1, 3)))
    inverted = S.is_(S.String.check(S.is_between_code_points(3, 1)))
    for value, count in CASES:
        assert between(value) is (1 <= count <= 3)
        assert inverted(value) is False


def test_rounds_down_bounds_and_clamps_negative_bounds_to_zero():
    """rounds down bounds and clamps negative bounds to zero"""
    assert S.is_(S.String.check(S.is_min_code_points(-1)))("")
    assert S.is_(S.String.check(S.is_max_code_points(-1)))("")
    assert not S.is_(S.String.check(S.is_max_code_points(-1)))("a")
    assert S.is_(S.String.check(S.is_between_code_points(-2, -1)))("")


@pytest.mark.parametrize(
    ("check", "invalid", "message"),
    [
        (S.is_min_code_points(1), "", "Expected a string with at least 1 code points"),
        (S.is_max_code_points(1), "😀a", "Expected a string with at most 1 code points"),
        (
            S.is_between_code_points(1, 2),
            "😀ab",
            "Expected a string with between 1 and 2 code points",
        ),
        (S.is_between_code_points(1, 1), "😀a", "Expected a string with 1 code points"),
    ],
)
def test_validates_decoding_and_encoding_with_code_point_error_messages(
    check: S.Check[str], invalid: str, message: str
):
    """validates decoding and encoding with code point error messages"""
    asserts = SchemaAsserts(S.String.check(check))
    asserts.decoding().succeed("😀")
    asserts.encoding().succeed("😀")
    asserts.decoding().fail(invalid, message)
    asserts.encoding().fail(invalid, message)


def test_allows_custom_annotations():
    """allows custom annotations"""
    schema = S.String.check(S.is_max_code_points(1, expected="a single code point"))
    SchemaAsserts(schema).decoding().fail("ab", "Expected a single code point")
