"""``Rational`` and ``RationalFromString`` (Effect's), over ``pyfect.rational``. A rational
is written in JSON as its canonical ``numerator/denominator`` text."""

from __future__ import annotations

from collections.abc import Mapping
from typing import TypeIs

from pyfect import rational
from pyfect.schema import ast
from pyfect.schema._arbitrary_constraint import ArbitraryConstraint
from pyfect.schema._checks_number import is_greater_than_or_equal_to_big_int
from pyfect.schema._codec_links import link
from pyfect.schema._declare import declare
from pyfect.schema._primitives import BigInt, String
from pyfect.schema._schema import Bottom
from pyfect.schema._transform import DecodeToSchema, decode_to
from pyfect.schema.transformation._builtins import rational_from_string

_TEXT = String.annotate(expected="a string that will be decoded as a Rational")
_PAIR = ast.Objects(
    (
        ast.PropertySignature("numerator", BigInt.ast),
        ast.PropertySignature(
            "denominator", BigInt.check(is_greater_than_or_equal_to_big_int(1)).ast
        ),
    )
)


def _is_rational(value: object) -> TypeIs[rational.Rational]:
    return isinstance(value, rational.Rational)


def _json(_: tuple[ast.AST, ...]) -> ast.Link:
    return ast.Link(_TEXT.ast, rational_from_string)


def _of_pair(pair: Mapping[str, int]) -> rational.Rational:
    return rational.make_unsafe(pair["numerator"], pair["denominator"])


def _to_pair(value: rational.Rational) -> Mapping[str, int]:
    return {"numerator": value.numerator, "denominator": value.denominator}


def _arbitrary(_: tuple[ast.AST, ...], __: ArbitraryConstraint) -> ast.Link:
    return link(_PAIR, decode=_of_pair, encode=_to_pair)


def _formatter(_: tuple[object, ...]) -> object:
    return rational.Rational.format


Rational: Bottom[rational.Rational] = declare(
    _is_rational,
    expected="Rational",
    representation={"id": "effect/schema/Rational", "payload": None},
    to_codec_json=_json,
    to_codec_arbitrary=_arbitrary,
    to_formatter=_formatter,
)
"""A ``rational.Rational`` (Effect's ``Rational``)."""
RationalFromString: DecodeToSchema[rational.Rational, str] = _TEXT.pipe(
    decode_to(Rational, rational_from_string)
)
"""A ``Rational`` read from ``[+-]digits`` or ``[+-]digits/[+-]digits`` (Effect's
``RationalFromString``); it encodes as the reduced ``numerator/denominator``."""
