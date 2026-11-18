"""``Decimal``: a finite ``decimal.Decimal``, the schema of a
``decimal.Decimal`` annotation. Python-only: Effect's decimal is
``BigDecimal`` (``pyfect.big_decimal``). JSON writes it as its text
(``str``), which reads back to the same digits and exponent; the text read
is ASCII digits with an optional sign, point and exponent (no ``NaN``,
spaces or underscores, which Python's ``Decimal`` would take)."""

from __future__ import annotations

import decimal
import re
from typing import TypeIs

from pyfect.exit import Exit, Success
from pyfect.exit import fail as fail_exit
from pyfect.schema import ast
from pyfect.schema import transformation as T
from pyfect.schema._arbitrary_constraint import ArbitraryConstraint
from pyfect.schema._arrays import Tuple
from pyfect.schema._checks_number import is_between
from pyfect.schema._codec_links import link
from pyfect.schema._declare import declare
from pyfect.schema._literals import Literals
from pyfect.schema._options import ParseOptions
from pyfect.schema._primitives import Int
from pyfect.schema._schema import Bottom
from pyfect.schema._value_codecs import string_codec
from pyfect.schema.issue import InvalidValue, Issue, reported

_TEXT = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]+)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


def _is_finite_decimal(value: object) -> TypeIs[decimal.Decimal]:
    return isinstance(value, decimal.Decimal) and value.is_finite()


def _decode(text: str, options: ParseOptions) -> Exit[decimal.Decimal, Issue]:
    if _TEXT.fullmatch(text) is None:
        expected = {"expected": "a decimal number string"}
        return fail_exit(InvalidValue(expected, reported(text, options)))
    try:
        return Success(decimal.Decimal(text))
    except decimal.InvalidOperation:
        # An exponent past what ``decimal`` represents.
        expected = {"expected": "a decimal number within range"}
        return fail_exit(InvalidValue(expected, reported(text, options)))


def _encode(value: decimal.Decimal, _: ParseOptions) -> Exit[str, Issue]:
    return Success(str(value))


_decimal_from_string: T.Transformation[decimal.Decimal, str] = T.transform_effect(
    decode=_decode, encode=_encode
)

_PARTS = Tuple(
    Literals(0, 1),
    Int.check(is_between(minimum=0, maximum=10**15)),
    Int.check(is_between(minimum=-20, maximum=20)),
).ast


def _from_parts(parts: tuple[int, int, int]) -> decimal.Decimal:
    sign, coefficient, exponent = parts
    return decimal.Decimal((sign, tuple(map(int, str(coefficient))), exponent))


def _to_parts(value: decimal.Decimal) -> tuple[int, int, int]:
    sign, digits, exponent = value.as_tuple()
    return sign, int("".join(map(str, digits))), int(exponent)


def _arbitrary(_: tuple[ast.AST, ...], __: ArbitraryConstraint) -> ast.Link:
    """Sign, coefficient and exponent: an exact decimal, unlike text drawn
    at random, which rarely is one."""
    return link(_PARTS, decode=_from_parts, encode=_to_parts)


def _formatter(_: tuple[object, ...]) -> object:
    return str


Decimal: Bottom[decimal.Decimal] = declare(
    _is_finite_decimal,
    expected="a finite Decimal",
    to_codec_json=string_codec(_decimal_from_string),
    to_codec_arbitrary=_arbitrary,
    to_formatter=_formatter,
)
"""A finite ``decimal.Decimal`` (Python-only), written in JSON as its text."""
