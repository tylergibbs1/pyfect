"""The key order a JSON Schema document has in JavaScript, where Effect reads
it: an object lists its array-index keys first, ascending, then the others as
written. The importer reads keys in order, so the order reaches the imported
struct's fields, what it outputs and the code generated from it."""

from __future__ import annotations

from typing import cast

from pyfect._digits import array_index


def _array_index(key: object) -> int | None:
    return array_index(key) if isinstance(key, str) else None


def _has_array_index_key(document: object) -> bool:
    """A document may hold anything under an annotation, cycles too."""
    pending = [document]
    seen: set[int] = set()
    while pending:
        value = pending.pop()
        if id(value) in seen:
            continue
        seen.add(id(value))
        if isinstance(value, dict):
            entries = cast("dict[object, object]", value)
            if any(_array_index(key) is not None for key in entries):
                return True
            pending.extend(entries.values())
        elif isinstance(value, list | tuple):
            pending.extend(cast("list[object] | tuple[object, ...]", value))
    return False


def _reordered(value: object, made: dict[int, object]) -> object:
    identity = id(value)
    if identity in made:
        return made[identity]
    if isinstance(value, dict):
        entries = cast("dict[object, object]", value)
        out: dict[object, object] = {}
        made[identity] = out
        indexes = {key: i for key in entries if (i := _array_index(key)) is not None}
        for key in sorted(indexes, key=indexes.__getitem__):
            out[key] = _reordered(entries[key], made)
        for key, item in entries.items():
            if key not in indexes:
                out[key] = _reordered(item, made)
        return out
    if isinstance(value, list):
        items: list[object] = []
        made[identity] = items
        items.extend(_reordered(item, made) for item in cast("list[object]", value))
        return items
    if isinstance(value, tuple):
        return tuple(_reordered(item, made) for item in cast("tuple[object, ...]", value))
    return value


def js_ordered[J](document: J) -> J:
    """``document`` with every object's keys in JavaScript's order; the same
    value when none of its keys is an array index."""
    if not _has_array_index_key(document):
        return document
    return cast("J", _reordered(document, {}))
