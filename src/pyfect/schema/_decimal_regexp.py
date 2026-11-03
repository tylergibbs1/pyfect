"""``BigDecimal`` and ``RegExp`` declarations (Effect's), with the
``BigDecimal`` order checks.

A ``BigDecimal`` is a ``pyfect.big_decimal.BigDecimal``, written in JSON as
its text. A ``RegExp`` is a compiled ``re.Pattern[str]``, written in JSON as
``{"source": ..., "flags": ...}`` with JavaScript's flag letters: Python
patterns carry ``i``, ``m`` and ``s`` (``re.IGNORECASE``, ``re.MULTILINE``,
``re.DOTALL``); other letters, or a source Python cannot compile, are
``Expected valid RegExp source and flags``, and a pattern with other flags
(``re.VERBOSE``, ``re.ASCII``) cannot be encoded.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import TypedDict, TypeIs, cast

from pyfect import big_decimal as bd
from pyfect.exit import Exit, Success
from pyfect.exit import fail as fail_exit
from pyfect.schema import ast
from pyfect.schema import transformation as T
from pyfect.schema._arbitrary_constraint import ArbitraryConstraint
from pyfect.schema._checks_order import (
    Annotate,
    Between,
    Bound,
    make_is_between,
    make_is_greater_than,
    make_is_greater_than_or_equal_to,
    make_is_less_than,
    make_is_less_than_or_equal_to,
)
from pyfect.schema._codec_links import link
from pyfect.schema._declare import declare
from pyfect.schema._options import ParseOptions
from pyfect.schema._primitives import String
from pyfect.schema._schema import Bottom
from pyfect.schema._struct import Struct
from pyfect.schema._transform import DecodeToSchema, decode_to
from pyfect.schema._value_codecs import string_codec
from pyfect.schema.issue import InvalidValue, Issue, reported


def _format(value: bd.BigDecimal) -> str:
    return value.format()


def _is_big_decimal(value: object) -> TypeIs[bd.BigDecimal]:
    return isinstance(value, bd.BigDecimal)


def _formatter(_: tuple[object, ...]) -> object:
    return _format


BigDecimal: Bottom[bd.BigDecimal] = declare(
    _is_big_decimal,
    expected="BigDecimal",
    representation={"id": "effect/schema/BigDecimal", "payload": None},
    to_codec_json=string_codec(T.big_decimal_from_string),
    to_formatter=_formatter,
)
"""A ``big_decimal.BigDecimal`` (Effect's ``BigDecimal``)."""
BigDecimalFromString: DecodeToSchema[bd.BigDecimal, str] = String.annotate(
    expected="a string that will be decoded as a BigDecimal"
).pipe(decode_to(BigDecimal, T.big_decimal_from_string))
"""A ``BigDecimal`` read from its text (Effect's ``BigDecimalFromString``)."""


def _bounded(constraint: ArbitraryConstraint) -> Mapping[str, object]:
    """The bounds ``to_strategy`` builds ``BigDecimal`` values within."""
    return {"arbitrary_constraint": constraint}


def _above(exclusive: bool) -> Annotate[bd.BigDecimal]:
    return lambda bound: _bounded(ArbitraryConstraint(minimum=bound, exclusive_minimum=exclusive))


def _below(exclusive: bool) -> Annotate[bd.BigDecimal]:
    return lambda bound: _bounded(ArbitraryConstraint(maximum=bound, exclusive_maximum=exclusive))


def _within(
    minimum: bd.BigDecimal, maximum: bd.BigDecimal, exclusive_minimum: bool, exclusive_maximum: bool
) -> Mapping[str, object]:
    constraint = ArbitraryConstraint(
        minimum=minimum,
        exclusive_minimum=exclusive_minimum,
        maximum=maximum,
        exclusive_maximum=exclusive_maximum,
    )
    return _bounded(constraint)


is_greater_than_big_decimal: Bound[bd.BigDecimal] = make_is_greater_than(
    formatter=_format, annotate=_above(True)
)
is_greater_than_or_equal_to_big_decimal: Bound[bd.BigDecimal] = make_is_greater_than_or_equal_to(
    formatter=_format, annotate=_above(False)
)
is_less_than_big_decimal: Bound[bd.BigDecimal] = make_is_less_than(
    formatter=_format, annotate=_below(True)
)
is_less_than_or_equal_to_big_decimal: Bound[bd.BigDecimal] = make_is_less_than_or_equal_to(
    formatter=_format, annotate=_below(False)
)
is_between_big_decimal: Between[bd.BigDecimal] = make_is_between(
    formatter=_format, annotate=_within
)

# ------------------------------------------------------------------- RegExp

_FLAGS = (("i", re.IGNORECASE), ("m", re.MULTILINE), ("s", re.DOTALL))
"""JavaScript's flag letters Python patterns carry, in JavaScript's order."""
_VALID_FLAGS = re.compile(r"(?!.*(.).*\1)[ims]*")
_WRITTEN_FLAGS = re.IGNORECASE | re.MULTILINE | re.DOTALL | re.UNICODE
"""The flags ``{source, flags}`` carries (``re.UNICODE`` is every ``str`` pattern's)."""


def _is_pattern(value: object) -> TypeIs[re.Pattern[str]]:
    if not isinstance(value, re.Pattern):
        return False
    pattern = cast("re.Pattern[str] | re.Pattern[bytes]", value)
    return isinstance(pattern.pattern, str)


def flags_of(pattern: re.Pattern[str]) -> str:
    """``pattern``'s flags as JavaScript's letters (``RegExp.flags``)."""
    return "".join(letter for letter, flag in _FLAGS if pattern.flags & flag)


def _compile(source: str, flags: str) -> re.Pattern[str] | None:
    known = dict(_FLAGS)
    # Each known letter at most once, as JavaScript's ``RegExp`` requires.
    if _VALID_FLAGS.fullmatch(flags) is None:
        return None
    value = 0
    for letter in flags:
        value |= known[letter]
    try:
        return re.compile(source, value)
    except re.error:
        return None


def _decode(input: RegExpJson, options: ParseOptions) -> Exit[re.Pattern[str], Issue]:
    pattern = _compile(input["source"], input["flags"])
    if pattern is None:
        shown = reported(input, options)
        return fail_exit(InvalidValue({"expected": "valid RegExp source and flags"}, shown))
    return Success(pattern)


def _encode(pattern: re.Pattern[str], options: ParseOptions) -> Exit[RegExpJson, Issue]:
    if pattern.flags & ~_WRITTEN_FLAGS:
        expected = "a pattern whose flags are among i, m and s"
        return fail_exit(InvalidValue({"expected": expected}, reported(pattern, options)))
    return Success(RegExpJson(source=pattern.pattern, flags=flags_of(pattern)))


class RegExpJson(TypedDict):
    """A ``RegExp`` in JSON."""

    source: str
    flags: str


_REG_EXP_JSON = Struct(RegExpJson).ast


def _reg_exp_codec(_: tuple[ast.AST, ...]) -> ast.Link:
    return ast.Link(_REG_EXP_JSON, T.transform_effect(decode=_decode, encode=_encode))


def _format_reg_exp(pattern: re.Pattern[str]) -> str:
    return f"/{pattern.pattern}/{flags_of(pattern)}"


def _reg_exp_formatter(_: tuple[object, ...]) -> object:
    return _format_reg_exp


def _same_reg_exp(a: re.Pattern[str], b: re.Pattern[str]) -> bool:
    return a.pattern == b.pattern and a.flags == b.flags


def _reg_exp_equivalence(_: tuple[object, ...]) -> object:
    return _same_reg_exp


_SOURCES = (
    "",
    ".",
    ".*",
    "\\d+",
    "\\w+",
    "[a-z]+",
    "[A-Z]+",
    "[0-9]+",
    "^[a-zA-Z0-9]+$",
    "^\\d{4}-\\d{2}-\\d{2}$",
)
"""Effect's generated sources."""
_DRAWN_REG_EXP = ast.Objects(
    (
        ast.PropertySignature("source", ast.Union(tuple(map(ast.Literal, _SOURCES)))),
        *(ast.PropertySignature(letter, ast.boolean) for letter, _ in _FLAGS),
    )
)


def _drawn_pattern(drawn: Mapping[str, object]) -> re.Pattern[str]:
    flags = 0
    for letter, flag in _FLAGS:
        if drawn[letter]:
            flags |= flag
    return re.compile(cast("str", drawn["source"]), flags)


def _drawn_parts(pattern: re.Pattern[str]) -> Mapping[str, object]:
    return {
        "source": pattern.pattern,
        **{letter: bool(pattern.flags & flag) for letter, flag in _FLAGS},
    }


def _reg_exp_arbitrary(_: tuple[ast.AST, ...], __: ArbitraryConstraint) -> ast.Link:
    """Effect's: a source of a few shapes and each flag on or off."""
    return link(_DRAWN_REG_EXP, decode=_drawn_pattern, encode=_drawn_parts)


RegExp: Bottom[re.Pattern[str]] = declare(
    _is_pattern,
    expected="RegExp",
    to_codec_arbitrary=_reg_exp_arbitrary,
    to_codec_json=_reg_exp_codec,
    to_formatter=_reg_exp_formatter,
    to_equivalence=_reg_exp_equivalence,
)
"""A compiled ``re.Pattern[str]`` (Effect's ``RegExp``)."""
