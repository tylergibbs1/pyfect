"""The JSON value type shared by the schema, JSON Patch and JSON Schema
modules."""

from collections.abc import Mapping, Sequence

type JsonValue = bool | int | float | str | Sequence[JsonValue] | Mapping[str, JsonValue] | None
"""A JSON value (Effect's ``Json`` type): a list or tuple for an array, a
string-keyed mapping for an object. ``pyfect.encoding.Json`` (what
``json.loads`` returns) is one."""
