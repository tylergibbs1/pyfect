"""The links of Effect's canonical JSON codec (``Schema.toCodecJson``): what
a node decodes from when its values are not JSON.

A declaration says how it is written in JSON with a ``to_codec_json``
annotation (or ``to_codec``, its form for every codec): a ``CodecLink``,
given the encoded sides of its type parameters, returns the link from the
node it decodes from, or ``None`` when its values are JSON already.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import replace

from pyfect._js import js_number
from pyfect.exit import Exit, Success
from pyfect.exit import fail as fail_exit
from pyfect.json_schema import JsonSchema
from pyfect.schema import ast
from pyfect.schema import transformation as T
from pyfect.schema._checks_number import is_finite
from pyfect.schema._checks_string import is_string_big_int, is_string_finite
from pyfect.schema._options import ParseOptions
from pyfect.schema.getter._coerce import to_number, to_string
from pyfect.schema.issue import InvalidValue, Issue, reported

type CodecLink = Callable[[tuple[ast.AST, ...]], ast.Link | None]
"""A declaration's ``to_codec_json`` / ``to_codec`` annotation."""


def link[T2, E2](
    to: ast.AST, *, decode: Callable[[E2], T2], encode: Callable[[T2], E2]
) -> ast.Link:
    """``to``'s values decoded with ``decode``, encoded back with ``encode``."""
    return ast.Link(to, T.transform(decode=decode, encode=encode))


def partial_link[T2, E2](
    to: ast.AST, *, decode: Callable[[E2], T2 | None], encode: Callable[[T2], E2], expected: str
) -> ast.Link:
    """``link`` for an encoded value with no decoded form (``decode`` gives
    ``None``): it is an ``InvalidValue`` expecting ``expected``."""

    def run(value: E2, options: ParseOptions) -> Exit[T2, Issue]:
        out = decode(value)
        if out is None:
            return fail_exit(InvalidValue({"expected": expected}, reported(value, options)))
        return Success(out)

    return ast.Link(
        to, T.transform_effect(decode=run, encode=lambda value, _: Success(encode(value)))
    )


def tagged(tag: str, **fields: ast.AST) -> ast.Objects:
    """``{"_tag": tag, **fields}``: one member of a tagged union."""
    properties = (ast.PropertySignature("_tag", ast.Literal(tag)),)
    return ast.Objects(
        (*properties, *(ast.PropertySignature(name, node) for name, node in fields.items()))
    )


FINITE = ast.append_checks(ast.number, (is_finite(),))
NON_FINITE = ast.Union((ast.Literal("Infinity"), ast.Literal("-Infinity"), ast.Literal("NaN")))


def _number_of(value: object) -> float:
    # A JSON number is kept as it is (an ``int`` stays one); only the
    # non-finite spellings are read.
    return value if isinstance(value, (int, float)) else to_number(value)


def _json_number(value: float) -> float | str:
    return value if isinstance(value, int) or math.isfinite(value) else js_number(value)


NUMBER_TO_JSON = link(ast.Union((FINITE, NON_FINITE)), decode=_number_of, encode=_json_number)
"""A number, its non-finite values as ``"NaN"``, ``"Infinity"``, ``"-Infinity"``."""

BIG_INT_STRING = ast.append_checks(
    ast.string, (is_string_big_int(expected="a string representing a bigint"),)
)
BIG_INT_TO_STRING = ast.Link(BIG_INT_STRING, T.big_int_from_string)
"""A bigint as its digits."""

_PASSTHROUGH: T.Transformation[object, object] = T.passthrough()
UNKNOWN_TO_JSON = ast.Link(ast.json, _PASSTHROUGH)
"""Any JSON value, unchanged: what an opaque declaration is written as."""


def _int_of(text: str) -> int:
    return int(text)


_INT_TO_STRING = ast.Link(BIG_INT_STRING, T.transform(decode=_int_of, encode=str))
_FINITE_TEXT = r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:[Ee][+-]?\d+)?"
NUMBER_KEY_PATTERN = f"^(?:{_FINITE_TEXT}|Infinity|-Infinity|NaN)$"
"""The text of any number (a JavaScript pattern): a number-keyed mapping's keys."""
_NUMBER_KEY = re.compile(f"^(?:{_FINITE_TEXT}|Infinity|-Infinity|NaN)\\Z", re.ASCII)


def _number_key_schema(_: object) -> JsonSchema:
    return {"pattern": NUMBER_KEY_PATTERN}


_NUMBER_TEXT = ast.append_checks(
    ast.string,
    (
        ast.filter_of(
            lambda text: _NUMBER_KEY.search(text) is not None,
            {"expected": "a string representing a number", "to_json_schema": _number_key_schema},
        ),
    ),
)
_NUMBER_TO_STRING = link(_NUMBER_TEXT, decode=to_number, encode=js_number)


def literal_to_string(node: ast.Literal) -> ast.AST:
    """``node`` decoded from its text (``"1"``, ``"true"``, ``"null"``)."""
    literal = node.literal
    text = to_string(literal)
    return ast.decode_to(
        ast.Literal(text), node, T.transform(decode=lambda _: literal, encode=lambda _: text)
    )


def _has_check(node: ast.AST, id: str) -> bool:
    return ast.has_check(node.checks, id)


def is_finite_number(node: ast.AST) -> bool:
    """A ``Number`` node whose checks keep it finite (``Finite``, ``Int``)."""
    return _has_check(node, "effect/schema/isFinite") or _has_check(node, "effect/schema/isInt")


def key_from_string(node: ast.AST) -> ast.AST:
    """An index signature's key schema read from JSON text: a mapping's keys
    are strings in JSON, while a Python mapping may have ``int`` keys
    (Effect's keys are strings already)."""
    if node.encoding is not None:
        *init, last = node.encoding
        to = key_from_string(last.to)
        if to is last.to:
            return node
        return replace(node, encoding=(*init, ast.Link(to, last.transformation)))
    return _key_node(node)


def _key_node(node: ast.AST) -> ast.AST:
    match node:
        case ast.Number() | ast.BigInt() if _has_check(node, "effect/schema/isInt") or isinstance(
            node, ast.BigInt
        ):
            return replace(node, encoding=(_INT_TO_STRING,))
        case ast.Number():
            return replace(node, encoding=(_NUMBER_TO_STRING,))
        case ast.Literal() if not isinstance(node.literal, str):
            return literal_to_string(node)
        case ast.Union():
            types = tuple(map(key_from_string, node.types))
            same = all(a is b for a, b in zip(types, node.types, strict=True))
            return node if same else replace(node, types=types)
        case _:
            return node


# --- the canonical StringTree codec (``Schema.toCodecStringTree``) ------------------

UNKNOWN_TO_STRING_TREE = ast.Link(ast.string_tree, _PASSTHROUGH)
"""Any string tree, unchanged: what an opaque value is written as."""


def _null_of(_: str) -> None:
    return None


def _null_text(_: None) -> str:
    return "null"


NULL_TO_STRING = link(ast.Literal("null"), decode=_null_of, encode=_null_text)
"""``None`` as ``"null"``."""


def _boolean_of(text: str) -> bool:
    return text == "true"


BOOLEAN_TO_STRING = link(
    ast.Union((ast.Literal("true"), ast.Literal("false"))), decode=_boolean_of, encode=to_string
)
"""A boolean as ``"true"`` / ``"false"``."""

_SAFE_INTEGER = 2**53 - 1


def _text_to_number(text: str) -> float:
    # An integral value within the safe integers is an ``int``, as
    # ``json.loads`` gives for one: ``S.Int`` takes only an ``int``.
    value = to_number(text)
    if value.is_integer() and abs(value) <= _SAFE_INTEGER:
        return int(value)
    return value


FINITE_STRING = ast.append_checks(ast.string, (is_string_finite(),))
FINITE_TO_STRING = link(FINITE_STRING, decode=_text_to_number, encode=js_number)
"""A finite number as its text."""
NUMBER_TO_STRING = link(
    ast.Union((FINITE_STRING, NON_FINITE)), decode=_text_to_number, encode=js_number
)
"""A number as its text, ``"NaN"`` / ``"Infinity"`` / ``"-Infinity"`` included."""


def enum_to_string(node: ast.Enum) -> ast.AST:
    """An enum with a numeric value decoded from the text of its values."""
    coercions = {to_string(member.value): member.value for member in node.enum}
    texts = ast.Union(tuple(ast.Literal(text) for text in coercions))
    return replace(node, encoding=(link(texts, decode=coercions.__getitem__, encode=to_string),))
