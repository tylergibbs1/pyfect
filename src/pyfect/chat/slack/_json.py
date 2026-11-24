"""Reading the JSON of a Slack payload: narrowing helpers that never raise."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import cast

from pyfect._json_text import PARSE_ERRORS
from pyfect._json_text import parse as _parse

type JsonObject = Mapping[str, object]


def is_object(value: object) -> bool:
    """Whether ``value`` is a JSON object."""
    return isinstance(value, dict)


def as_object(value: object) -> JsonObject | None:
    """``value`` when it is a JSON object."""
    return cast("JsonObject", value) if isinstance(value, dict) else None


def is_list(value: object) -> bool:
    """Whether ``value`` is a JSON array."""
    return isinstance(value, list)


def as_list(value: object) -> list[object]:
    """``value`` when it is a JSON array, else an empty list."""
    return cast("list[object]", value) if isinstance(value, list) else []


def string(value: object, key: str) -> str | None:
    """A non-empty string field of ``value``, when it is an object."""
    obj = as_object(value)
    field = None if obj is None else obj.get(key)
    return field if isinstance(field, str) and field else None


def any_string(value: object, key: str) -> str | None:
    """A string field of ``value`` (maybe empty), when it is an object."""
    obj = as_object(value)
    field = None if obj is None else obj.get(key)
    return field if isinstance(field, str) else None


def object_(value: object, key: str) -> JsonObject | None:
    """An object field of ``value``, when it is an object."""
    obj = as_object(value)
    return None if obj is None else as_object(obj.get(key))


def number(value: object, key: str) -> float | None:
    """A number field of ``value`` (not a boolean), when it is an object, as
    the double JavaScript reads: an integer past a double's range is an
    infinity, so no caller meets an unbounded ``int`` from a peer."""
    obj = as_object(value)
    field = None if obj is None else obj.get(key)
    if isinstance(field, bool) or not isinstance(field, (int, float)):
        return None
    try:
        return float(field)
    except OverflowError:
        return math.inf if field > 0 else -math.inf


def parse(text: str) -> object:
    """The parsed JSON, or ``None`` when ``text`` is not JSON."""
    try:
        return _parse(text)
    except PARSE_ERRORS:
        return None
