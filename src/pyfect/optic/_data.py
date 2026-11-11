"""Reading and copying the parts of plain data: ``dict`` (any ``Mapping``,
copied to a ``dict``), ``list``, ``tuple``, and values ``copy.replace``
updates (dataclasses, ``S.Class`` instances, named tuples), by attribute.

Only the containers on the path are copied; everything else is shared. A
missing key or index reads as ``None`` (Effect's ``undefined``).
"""

from __future__ import annotations

import copy
from collections.abc import Hashable, Mapping, Sequence
from typing import Any, cast

type Key = Hashable


def _sequence(value: object) -> Sequence[Any] | None:
    return cast("Sequence[Any]", value) if isinstance(value, (list, tuple)) else None


def has(value: object, key: Key) -> bool:
    """``value`` has its own ``key``."""
    if isinstance(value, Mapping):
        return key in value
    items = _sequence(value)
    if items is not None:
        return isinstance(key, int) and 0 <= key < len(items)
    return isinstance(key, str) and hasattr(value, key)


def get(value: object, key: Key) -> Any:
    if isinstance(value, Mapping):
        return cast("Mapping[Key, Any]", value).get(key)
    items = _sequence(value)
    if items is not None:
        index = cast("int", key)
        return items[index] if 0 <= index < len(items) else None
    return getattr(value, cast("str", key))


def _replaced(value: object, key: Key, part: object) -> Any:
    if not isinstance(key, str) or not hasattr(value, "__replace__"):
        raise TypeError(
            f"Cannot copy a {type(value).__name__} to replace its {key!r}: optics update"
            " dicts, lists, tuples and values copy.replace supports (dataclasses, named tuples)"
        )
    return copy.replace(cast("Any", value), **{key: part})


def assign(value: object, key: Key, part: object) -> Any:
    """A copy of ``value`` with ``part`` at ``key``. An index past the end
    pads with ``None`` (a JavaScript array's holes)."""
    if isinstance(value, Mapping):
        out = dict(cast("Mapping[Key, Any]", value))
        out[key] = part
        return out
    items = _sequence(value)
    if items is None:
        return _replaced(value, key, part)
    index = cast("int", key)
    copied = list(items)
    copied.extend([None] * (index + 1 - len(copied)))
    copied[index] = part
    return copied if isinstance(value, list) else tuple(copied)


def remove(value: object, key: Key) -> Any:
    """A copy of ``value`` without ``key``: a key deleted, an element
    removed (later ones move down); an attribute set to ``None``."""
    if isinstance(value, Mapping):
        out = dict(cast("Mapping[Key, Any]", value))
        out.pop(key, None)
        return out
    items = _sequence(value)
    if items is None:
        return _replaced(value, key, None)
    index = cast("int", key)
    copied = [item for i, item in enumerate(items) if i != index]
    return copied if isinstance(value, list) else tuple(copied)


def get_path(value: object, path: Sequence[Key]) -> Any:
    for key in path:
        value = get(value, key)
    return value


def assign_path(value: object, path: Sequence[Key], part: object) -> Any:
    """A copy of ``value`` with ``part`` at ``path``, copying each container
    on the way."""
    sources = [value]
    for key in path[:-1]:
        sources.append(get(sources[-1], key))
    for source, key in zip(reversed(sources), reversed(path), strict=True):
        part = assign(source, key, part)
    return part
