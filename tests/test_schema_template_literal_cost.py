"""A ``TemplateLiteral`` tries each split point of a string without copying
the text on either side of it, so a string that does not match fails in time
linear in its length (it used to copy both sides at every split). The string
ends in an astral character: copying a slice of it then costs four bytes a
character and a scan, so the copies show at sizes a test can afford."""

import pytest
from _copies import Copies
from _growth import Work, assert_near_linear
from _guards import guards

import pyfect as fx
from pyfect import schema as S

_SCHEMAS = [
    S.TemplateLiteral(S.String, "-", S.Number),
    S.TemplateLiteral(S.String, "-", S.BigInt),
    S.TemplateLiteral(S.String, "-", S.Union(S.Number, S.Literal("y"))),
]
_COPIES = guards("b05d8f13", "template-literal-copies-each-split")


@pytest.mark.parametrize(
    "schema",
    [
        pytest.param(S.TemplateLiteral(S.String, "-", S.Number), id="number"),
        pytest.param(S.TemplateLiteral(S.String, "-", S.BigInt), id="bigint"),
        # Fails at its last literal before trying a split.
        pytest.param(S.TemplateLiteral(S.String, "-", "x"), id="literal"),
        pytest.param(
            S.TemplateLiteral(S.String, "-", S.Union(S.Number, S.Literal("y"))),
            id="union",
        ),
    ],
)
def test_a_string_of_many_split_points_fails_in_near_linear_time(
    schema: S.TemplateLiteralSchema,
) -> None:
    decode = S.decode_unknown_exit(schema)

    def sized(n: int) -> Work:
        text = "-" * n + "\N{GRINNING FACE}"
        return lambda: decode(text)

    assert isinstance(decode("-" * 1000 + "\N{GRINNING FACE}"), fx.Failure)
    assert_near_linear(sized, 10_000, 8 * 10_000)


@_COPIES
@pytest.mark.parametrize("schema", _SCHEMAS, ids=["number", "bigint", "union"])
def test_a_string_of_many_split_points_is_not_copied_at_each(
    schema: S.TemplateLiteralSchema,
) -> None:
    """Counted with ``_copies``: timing sees the copies only at sizes a test can't afford."""
    copies = Copies()
    text = copies.text("-" * 2000 + "\N{GRINNING FACE}")
    assert isinstance(S.decode_unknown_exit(schema)(text), fx.Failure)
    assert copies.characters <= len(text)


def test_matching_strings_still_split_as_before() -> None:
    decode = S.decode_unknown_sync(S.TemplateLiteralParser(S.String, "-", S.Number))
    assert decode("a-b-1.5") == ("a-b", "-", 1.5)
    assert decode("--1") == ("-", "-", 1)
