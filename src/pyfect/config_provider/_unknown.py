"""``from_unknown``: a provider over nested Python data (JSON-like)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, cast

from pyfect._js import js_number
from pyfect.config_provider._node import Array, Node, Path, Record, Value
from pyfect.config_provider._provider import ConfigProvider, make
from pyfect.effect import succeed


def from_unknown(root: object, *, preserve_empty_strings: bool = False) -> ConfigProvider:
    """A provider over nested mappings, lists and tuples. Mappings are
    records (string segments), lists and tuples arrays (int segments); a
    string is a value, as are numbers and booleans (``"42"``, ``"true"``);
    ``None`` is absent. An empty string is absent unless
    ``preserve_empty_strings``."""
    return make(lambda path: succeed(_node_at(root, path, preserve_empty_strings)))


def _node_at(root: object, path: Path, preserve_empty_strings: bool) -> Node | None:
    current = root
    for seg in path:
        if isinstance(current, (list, tuple)):
            items = cast(tuple[object, ...] | list[object], current)
            if isinstance(seg, bool) or not isinstance(seg, int) or not 0 <= seg < len(items):
                return None
            current = items[seg]
        elif isinstance(current, Mapping):
            mapping = cast(Mapping[object, object], current)
            if not isinstance(seg, str) or seg not in mapping:
                return None
            current = mapping[seg]
        else:
            return None
    return _describe(current, preserve_empty_strings)


def _describe(value: object, preserve_empty_strings: bool) -> Node | None:
    match value:
        case None:
            return None
        case str():
            return None if value == "" and not preserve_empty_strings else Value(value)
        case list() | tuple():
            return Array(len(cast(tuple[Any, ...], value)))
        case Mapping():
            return Record(frozenset(str(k) for k in cast(Mapping[object, object], value)))
        case _:
            return Value(_scalar_text(value))


def _scalar_text(value: object) -> str:
    match value:
        case bool():
            return "true" if value else "false"
        case float():
            return js_number(value)
        case _:
            return str(value)
