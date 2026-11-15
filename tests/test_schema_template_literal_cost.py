"""A ``TemplateLiteral`` tries each split point of a string without copying
the text on either side of it, so a string that does not match fails in time
linear in its length (it used to copy both sides at every split)."""

import pytest
from _growth import Work, assert_near_linear

import pyfect as fx
from pyfect import schema as S


@pytest.mark.parametrize(
    "schema",
    [
        S.TemplateLiteral(S.String, "-", S.Number),
        S.TemplateLiteral(S.String, "-", S.BigInt),
        S.TemplateLiteral(S.String, "-", "x"),
        S.TemplateLiteral(S.String, "-", S.Union(S.Number, S.Literal("y"))),
    ],
    ids=["number", "bigint", "literal", "union"],
)
def test_a_string_of_many_split_points_fails_in_near_linear_time(
    schema: S.TemplateLiteralSchema,
) -> None:
    decode = S.decode_unknown_exit(schema)

    def sized(n: int) -> Work:
        text = "-" * n + "a"
        return lambda: decode(text)

    assert isinstance(decode("-" * 1000 + "a"), fx.Failure)
    assert_near_linear(sized, 50_000, 8 * 50_000, bound=32, floor=0.0032)


def test_matching_strings_still_split_as_before() -> None:
    decode = S.decode_unknown_sync(S.TemplateLiteralParser(S.String, "-", S.Number))
    assert decode("a-b-1.5") == ("a-b", "-", 1.5)
    assert decode("--1") == ("-", "-", 1)
