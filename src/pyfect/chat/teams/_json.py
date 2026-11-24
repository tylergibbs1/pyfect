"""Reading the JSON of a Teams activity: narrowing helpers that never raise."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from pyfect._json_text import PARSE_ERRORS
from pyfect._json_text import parse as _parse

type JsonObject = Mapping[str, object]


def as_object(value: object) -> JsonObject | None:
    """``value`` when it is a JSON object."""
    return cast("JsonObject", value) if isinstance(value, dict) else None


def as_list(value: object) -> list[object] | None:
    """``value`` when it is a JSON array."""
    return cast("list[object]", value) if isinstance(value, list) else None


def string(value: object, key: str) -> str | None:
    """A non-empty string field of ``value``, when it is an object."""
    obj = as_object(value)
    field = None if obj is None else obj.get(key)
    return field if isinstance(field, str) and field else None


def object_(value: object, key: str) -> JsonObject | None:
    """An object field of ``value``, when it is an object."""
    obj = as_object(value)
    return None if obj is None else as_object(obj.get(key))


def parse(text: str) -> object:
    """The parsed JSON, or ``None`` when ``text`` is not JSON. Nesting is
    bounded by the parser: text nested too deep to decode is not JSON."""
    try:
        return _parse(text)
    except PARSE_ERRORS:
        return None
