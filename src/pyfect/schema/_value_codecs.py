"""How the single-value declarations are written in JSON (their
``to_codec_json`` links, as Effect writes them).

A date-time or a zone is its text; a zone offset its milliseconds; a byte
size its count, as a bigint; a duration ``{"_tag": "Millis", "value": n}``
when it is a whole number of milliseconds, else
``{"_tag": "Nanos", "value": n}`` (a ``timedelta`` is never infinite, so
Effect's ``Infinity`` forms are not used).
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from fractions import Fraction
from typing import Any

from pyfect.schema import ast
from pyfect.schema import transformation as T
from pyfect.schema._checks_number import int_value, is_greater_than_or_equal_to_big_int
from pyfect.schema._codec_links import CodecLink, partial_link, tagged

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


def _duration_of(encoded: Mapping[str, Any]) -> timedelta | None:
    # A ``timedelta`` holds less than a billion days (Effect's are not bounded).
    try:
        if encoded["_tag"] == "Millis":
            return timedelta(milliseconds=encoded["value"])
        return timedelta(microseconds=round(Fraction(encoded["value"], _NS_PER_US)))
    except OverflowError:
        return None


def _duration_to(duration: timedelta) -> Mapping[str, object]:
    micros = duration // timedelta(microseconds=1)
    if micros % _US_PER_MS == 0:
        return {"_tag": "Millis", "value": micros // _US_PER_MS}
    return {"_tag": "Nanos", "value": micros * _NS_PER_US}


_DURATION = ast.Union((tagged("Nanos", value=ast.big_int), tagged("Millis", value=_INT)))


def duration_codec(_: tuple[ast.AST, ...]) -> ast.Link:
    return partial_link(
        _DURATION,
        decode=_duration_of,
        encode=_duration_to,
        expected="a duration a timedelta can hold",
    )


_BYTE_SIZE_STRING = ast.annotate(
    ast.string, {"expected": "a string that will be decoded as a ByteSize"}
)


def byte_size_string_tree_codec(_: tuple[ast.AST, ...]) -> ast.Link:
    """A byte size in a string tree: its text (``"10 MB"``), as Effect's."""
    return ast.Link(_BYTE_SIZE_STRING, T.byte_size_from_string)
