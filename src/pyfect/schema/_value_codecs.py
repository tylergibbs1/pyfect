"""How the single-value declarations are written in JSON (their
``to_codec_json`` links, as Effect writes them).

A date-time or a zone is its text; a zone offset its milliseconds; a byte
size its count, as a bigint; a duration by its form (``Duration.value``):
``{"_tag": "Millis", "value": n}``, ``{"_tag": "Nanos", "value": n}``,
``{"_tag": "Infinity"}`` or ``{"_tag": "NegativeInfinity"}``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pyfect import duration as _duration
from pyfect.schema import ast
from pyfect.schema import transformation as T
from pyfect.schema._checks_number import int_value, is_greater_than_or_equal_to_big_int
from pyfect.schema._codec_links import CodecLink, tagged

_INT = ast.append_checks(ast.whole_number, (int_value(),))
_US_PER_MS = 1000
_NS_PER_US = 1000


def string_codec(transformation: T.Transformation[Any, str]) -> CodecLink:
    """A declaration written as text through ``transformation``."""

    def make(_: tuple[ast.AST, ...]) -> ast.Link:
        return ast.Link(ast.string, transformation)

    return make


def time_zone_offset_codec(_: tuple[ast.AST, ...]) -> ast.Link:
    return ast.Link(_INT, T.time_zone_offset_from_number)


_NON_NEGATIVE_BIG_INT = ast.append_checks(ast.big_int, (is_greater_than_or_equal_to_big_int(0),))


def byte_size_codec(_: tuple[ast.AST, ...]) -> ast.Link:
    return ast.Link(_NON_NEGATIVE_BIG_INT, T.byte_size_from_big_int)


_MAX_SAFE = 2**53 - 1


def _duration_of(encoded: Mapping[str, Any]) -> _duration.Duration:
    match encoded["_tag"]:
        case "Infinity":
            return _duration.infinity
        case "NegativeInfinity":
            return _duration.negative_infinity
        case "Nanos":
            return _duration.nanos(encoded["value"])
        case _:
            return _duration.millis(encoded["value"])


def _duration_to(duration: _duration.Duration) -> Mapping[str, object]:
    match duration.value:
        case _duration.Infinity():
            return {"_tag": "Infinity"}
        case _duration.NegativeInfinity():
            return {"_tag": "NegativeInfinity"}
        case _duration.Nanos(nanos=count):
            return {"_tag": "Nanos", "value": count}
        case _duration.Millis(millis=count):
            # A JavaScript number: an int while exact, past that the float.
            return {"_tag": "Millis", "value": int(count) if abs(count) <= _MAX_SAFE else count}


_DURATION = ast.Union(
    (
        tagged("Infinity"),
        tagged("NegativeInfinity"),
        tagged("Nanos", value=ast.big_int),
        tagged("Millis", value=_INT),
    )
)


def duration_codec(_: tuple[ast.AST, ...]) -> ast.Link:
    return ast.Link(_DURATION, T.transform(decode=_duration_of, encode=_duration_to))


_BYTE_SIZE_STRING = ast.annotate(
    ast.string, {"expected": "a string that will be decoded as a ByteSize"}
)


def byte_size_string_tree_codec(_: tuple[ast.AST, ...]) -> ast.Link:
    """A byte size in a string tree: its text (``"10 MB"``), as Effect's."""
    return ast.Link(_BYTE_SIZE_STRING, T.byte_size_from_string)
