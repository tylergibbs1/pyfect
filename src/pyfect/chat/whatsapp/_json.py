"""Reading the JSON of a WhatsApp payload: narrowing helpers that never raise,
and the parse of a webhook body with its nesting capped."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from pyfect._json_text import PARSE_ERRORS
from pyfect._json_text import parse as _parse

type JsonObject = Mapping[str, object]

MAX_DEPTH = 64
"""How deeply a webhook body may nest. Meta's deepest is under ten; a deeper
body is refused before it is parsed, so nothing downstream walks it."""


def as_object(value: object) -> JsonObject | None:
    """``value`` when it is a JSON object."""
    return cast("JsonObject", value) if isinstance(value, dict) else None


def as_list(value: object) -> list[object]:
    """``value`` when it is a JSON array, else an empty list."""
    return cast("list[object]", value) if isinstance(value, list) else []


def string(value: object, key: str) -> str | None:
    """A non-empty string field of ``value``, when it is an object."""
    obj = as_object(value)
    field = None if obj is None else obj.get(key)
    return field if isinstance(field, str) and field else None


def object_(value: object, key: str) -> JsonObject | None:
    """An object field of ``value``, when it is an object."""
    obj = as_object(value)
    return None if obj is None else as_object(obj.get(key))


def code(value: object) -> int | None:
    """An integer ``code`` field of ``value`` (not a boolean), when it is an
    object. Graph codes are integers; anything else is no code."""
    obj = as_object(value)
    field = None if obj is None else obj.get("code")
    return field if isinstance(field, int) and not isinstance(field, bool) else None


def parse(body: bytes) -> object:
    """The parsed JSON of a webhook body, or ``None`` when it is not JSON or
    nests past ``MAX_DEPTH``."""
    try:
        return _parse(body.decode("utf-8", "replace"), max_depth=MAX_DEPTH)
    except PARSE_ERRORS:
        return None
