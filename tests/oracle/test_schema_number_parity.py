"""JavaScript has one number, and ``Schema.isInt`` is ``Number.isSafeInteger``.

Every expected value here was printed by Effect 4.0.6 under Node, with a
Python ``int`` and ``float`` standing for the same JavaScript number.
"""

import json
from typing import Any, TypedDict

import pytest

from pyfect import schema as S

_LITERALS: list[tuple[S.LiteralValue, object, bool]] = [
    (1, 1, True),
    (1, 1.0, True),
    (2.0, 2, True),
    (2.0, 2.0, True),
    (0, -0.0, True),
    (-0.0, 0, True),
    (1e21, 10**21, True),
    (10**21, 1e21, True),
    (1.5, 1.5, True),
    (1, 1.5, False),
    (1, "1", False),
    # A boolean is not a number.
    (1, True, False),
    (1.0, True, False),
    (0, False, False),
    (True, 1, False),
    (True, 1.0, False),
    (False, 0, False),
    (True, True, True),
    (None, 0, False),
]


@pytest.mark.parametrize(("literal", "value", "accepted"), _LITERALS)
def test_a_number_literal_is_one_number_whatever_its_python_kind(
    literal: S.LiteralValue, value: object, accepted: bool
):
    assert S.is_(S.Literal(literal))(value) is accepted


def test_the_decoded_value_is_the_input():
    """``decodeUnknownSync(Literal(0))(-0)`` keeps the sign, so the input is kept."""
    assert str(S.decode_unknown_sync(S.Literal(0))(-0.0)) == "-0.0"
    assert S.decode_unknown_sync(S.Literal(1))(1.0) == 1


class _A(TypedDict):
    kind: float
    a: str


class _B(TypedDict):
    kind: float
    b: str


def test_literals_and_discriminators_match_across_int_and_float():
    assert S.is_(S.Literals(1, 2, "a"))(2.0)
    assert not S.is_(S.Literals(1, 2, "a"))(True)
    assert S.is_(S.Union([S.Literal(1), S.String]))(1.0)
    members = S.Union(
        [S.Struct(_A, kind=S.Literal(1)), S.Struct(_B, kind=S.Literal(2.0))],
    )
    assert S.is_(members)({"kind": 1.0, "a": "x"})
    assert S.is_(members)({"kind": 2, "b": "x"})
    assert not S.is_(members)({"kind": True, "a": "x"})


_SAFE = 2**53 - 1


@pytest.mark.parametrize(
    ("value", "accepted"),
    [
        (_SAFE, True),
        (-_SAFE, True),
        (float(_SAFE), True),
        (2**53, False),
        (-(2**53), False),
        (2.0**53, False),
        (2**53 + 2, False),
        (10**30, False),
        (1e300, False),
        (1, True),
        (1.0, True),
        (1.5, False),
    ],
)
def test_is_int_is_number_is_safe_integer(value: float, accepted: bool):
    assert S.is_(S.Number.check(S.is_int()))(value) is accepted


def _document(schema: S.Top) -> Any:
    return json.loads(json.dumps(S.to_json_schema_document(schema).schema))


def test_is_int_exports_the_safe_integer_bounds():
    assert _document(S.Number.check(S.is_int())) == {
        "type": "integer",
        "minimum": -_SAFE,
        "maximum": _SAFE,
    }
    assert _document(S.Int) == {"type": "integer", "minimum": -_SAFE, "maximum": _SAFE}


def test_a_following_bound_merges_with_the_safe_integer_bounds():
    """As Effect's merge of a check into the node before it."""
    assert _document(S.Number.check(S.is_int(), S.is_greater_than(1))) == {
        "type": "integer",
        "maximum": _SAFE,
        "exclusiveMinimum": 1,
    }
    assert _document(S.Number.check(S.is_int(), S.is_between(minimum=0, maximum=5))) == {
        "type": "integer",
        "minimum": 0,
        "maximum": 5,
    }
    assert _document(S.Finite.check(S.is_int32())) == {
        "type": "integer",
        "allOf": [
            {"minimum": -_SAFE, "maximum": _SAFE},
            {"minimum": -2147483648, "maximum": 2147483647},
        ],
    }
    assert _document(S.Int.check(S.is_less_than(5))) == {
        "type": "integer",
        "minimum": -_SAFE,
        "exclusiveMaximum": 5,
    }
    assert _document(S.Natural) == {"type": "integer", "minimum": 0, "maximum": _SAFE}
    assert _document(S.Number.check(S.is_greater_than(1), S.is_int())) == {
        "exclusiveMinimum": 1,
        "type": "integer",
        "maximum": _SAFE,
    }


@pytest.mark.parametrize(
    ("schema", "value", "expected"),
    [
        (S.Int, 1.0, 1),
        (S.Int, -3.0, -3),
        (S.Int, 0.0, 0),
        (S.Int, -0.0, 0),
        (S.Int, float(_SAFE), _SAFE),
        (S.Natural, 2.0, 2),
        (S.Port, 80.0, 80),
    ],
)
def test_s_int_takes_a_whole_float_as_its_int(schema: Any, value: float, expected: int):
    """``Schema.Int`` takes these under Node, where 1.0 is 1; Python's has to
    give an ``int`` to be what its type says."""
    decoded = S.decode_unknown_sync(schema)(value)
    assert decoded == expected
    assert type(decoded) is int
    encoded = S.encode_unknown_sync(schema)(value)
    assert encoded == expected
    assert type(encoded) is int
    assert S.is_(schema)(value)


@pytest.mark.parametrize(
    ("value", "message"),
    [
        (1.5, "Expected an integer"),
        (2.0**53, "Expected an integer"),
        (float("nan"), "Expected an integer"),
        (float("inf"), "Expected an integer"),
        (True, "Expected number"),
        ("1", "Expected number"),
    ],
)
def test_s_int_still_refuses_what_effect_refuses(value: object, message: str):
    with pytest.raises(S.SchemaError) as error:
        S.decode_unknown_sync(S.Int)(value)
    assert str(error.value) == message


def test_s_natural_refuses_a_negative_whole_float():
    assert not S.is_(S.Natural)(-1.0)


def test_s_int_takes_a_whole_float_through_the_json_codec():
    assert S.decode_unknown_sync(S.to_codec_json(S.Int))(1.0) == 1
    assert type(S.decode_unknown_sync(S.to_codec_json(S.Int))(1.0)) is int
    assert S.encode_unknown_sync(S.to_codec_json(S.Int))(1.0) == 1
