"""Reading Discord's JSON: the bounded parse of a body or a gateway frame,
and field readers for the decoders, which treat a field that is absent or
``null`` alike, as Discord does, and raise ``Invalid`` for a field of the
wrong type, as Effect's ``Schema.decodeUnknownOption`` gives none."""

from __future__ import annotations

import math
from collections.abc import Mapping
from typing import cast

from pyfect._json_text import PARSE_ERRORS
from pyfect._json_text import parse as _parse

type JsonObject = Mapping[str, object]

MAX_DEPTH = 64
"""The deepest nesting of arrays and objects a payload may have. Discord's own
payloads nest about a dozen deep (a message, its reference, its components);
anything deeper is refused before it is parsed."""


class Invalid(Exception):
    """A field of the wrong type: the decoder gives ``None``."""


def parse(text: str) -> object:
    """The parsed JSON, or ``None`` when ``text`` is not JSON or nests deeper
    than ``MAX_DEPTH``."""
    try:
        return _parse(text, max_depth=MAX_DEPTH)
    except PARSE_ERRORS:
        return None


def as_object(value: object) -> JsonObject | None:
    """``value`` when it is a JSON object."""
    return cast("JsonObject", value) if isinstance(value, dict) else None


def as_list(value: object) -> list[object]:
    """``value`` when it is a JSON array, else an empty list."""
    return cast("list[object]", value) if isinstance(value, list) else []


def non_empty(value: str | None) -> str | None:
    """``value`` unless it is empty."""
    return value or None


def string_field(value: object, key: str) -> str | None:
    """A string field of ``value`` (maybe empty), when it is an object. Never raises."""
    obj = as_object(value)
    field = None if obj is None else obj.get(key)
    return field if isinstance(field, str) else None


def is_number(value: object) -> bool:
    """A JSON number: an ``int`` or ``float``, not a ``bool``."""
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# Decoder fields: absent and ``null`` are ``None``; the wrong type raises ``Invalid``.


def req_str(obj: JsonObject, key: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str):
        raise Invalid
    return value


def opt_str(obj: JsonObject, key: str) -> str | None:
    value = obj.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        raise Invalid
    return value


def req_number(obj: JsonObject, key: str) -> float:
    value = obj.get(key)
    if not is_number(value):
        raise Invalid
    return cast("float", value)


def opt_number(obj: JsonObject, key: str) -> float | None:
    value = obj.get(key)
    if value is None:
        return None
    if not is_number(value):
        raise Invalid
    return cast("float", value)


def opt_int(obj: JsonObject, key: str) -> int | None:
    """A whole number (``Schema.Int``), within a double's safe range."""
    value = opt_number(obj, key)
    if value is None:
        return None
    if isinstance(value, float) and not (math.isfinite(value) and value.is_integer()):
        raise Invalid
    whole = int(value)
    if abs(whole) > 2**53 - 1:
        raise Invalid
    return whole


def opt_bool(obj: JsonObject, key: str) -> bool | None:
    value = obj.get(key)
    if value is None:
        return None
    if not isinstance(value, bool):
        raise Invalid
    return value


def req_obj(obj: JsonObject, key: str) -> JsonObject:
    found = as_object(obj.get(key))
    if found is None:
        raise Invalid
    return found


def opt_obj(obj: JsonObject, key: str) -> JsonObject | None:
    value = obj.get(key)
    if value is None:
        return None
    found = as_object(value)
    if found is None:
        raise Invalid
    return found


def opt_list(obj: JsonObject, key: str) -> list[object] | None:
    value = obj.get(key)
    if value is None:
        return None
    if not isinstance(value, list):
        raise Invalid
    return cast("list[object]", value)


def opt_str_list(obj: JsonObject, key: str) -> list[str] | None:
    items = opt_list(obj, key)
    if items is None:
        return None
    if not all(isinstance(item, str) for item in items):
        raise Invalid
    return cast("list[str]", items)


def objects(items: list[object] | None) -> list[JsonObject]:
    """Each item, which must be an object."""
    out: list[JsonObject] = []
    for item in items or ():
        found = as_object(item)
        if found is None:
            raise Invalid
        out.append(found)
    return out
