"""Reading the JSON of a Telegram update: narrowing helpers that never raise,
and the bounded parse of a webhook body."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from pyfect._json_text import PARSE_ERRORS
from pyfect._json_text import parse as _parse
from pyfect.chat._json_depth import within_depth as _within_depth

type JsonObject = Mapping[str, object]

MAX_DEPTH = 64
"""The deepest nesting a webhook body may have: an update is a few levels
deep, and a parser recurses once per level."""

_SAFE = 2**53 - 1


def as_object(value: object) -> JsonObject | None:
    """``value`` when it is a JSON object."""
    return cast("JsonObject", value) if isinstance(value, dict) else None


def as_list(value: object) -> list[object]:
    """``value`` when it is a JSON array, else an empty list."""
    return cast("list[object]", value) if isinstance(value, list) else []


def object_(value: object, key: str) -> JsonObject | None:
    """An object field of ``value``, when it is an object."""
    obj = as_object(value)
    return None if obj is None else as_object(obj.get(key))


def string(value: object, key: str) -> str | None:
    """A string field of ``value`` (maybe empty), when it is an object."""
    obj = as_object(value)
    field = None if obj is None else obj.get(key)
    return field if isinstance(field, str) else None


def integer(value: object, key: str) -> int | None:
    """A safe integer field of ``value``, as JavaScript's
    ``Number.isSafeInteger`` reads one: ``3.0`` is one, a boolean is not."""
    obj = as_object(value)
    field = None if obj is None else obj.get(key)
    if isinstance(field, bool):
        return None
    if isinstance(field, int):
        return field if -_SAFE <= field <= _SAFE else None
    if isinstance(field, float) and field.is_integer() and -_SAFE <= field <= _SAFE:
        return int(field)
    return None


def within_depth(body: bytes, limit: int = MAX_DEPTH) -> bool:
    """Whether the JSON text ``body`` nests at most ``limit`` deep, strings
    skipped. Text that is not JSON may pass; the parse refuses it."""
    return _within_depth(body, limit)


def parse(body: bytes) -> object:
    """The parsed JSON of a webhook body, or ``None`` when it is not JSON or
    nests past ``MAX_DEPTH``. Bad UTF-8 is replaced, as ``TextDecoder``
    does."""
    if not within_depth(body):
        return None
    try:
        return _parse(body.decode("utf-8", "replace"))
    except PARSE_ERRORS:
        return None
