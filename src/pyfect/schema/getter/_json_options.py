"""``JSON.parse``'s reviver and ``JSON.stringify``'s replacer, on Python's
JSON values (Effect's ``ParseJsonOptions`` / ``JsonReplacer``)."""

from __future__ import annotations

from collections.abc import Callable, Mapping

type JsonReviver = Callable[[str, object], object]
"""Called with each key (``""`` for the root, an index as text) and its
parsed value, children first; what it returns replaces the value."""

type JsonReplacer = Callable[[str, object], object] | list[str | int] | tuple[str | int, ...]
"""A function called with each key (``""`` for the root) and value, parents
first, whose result is written instead; or the keys an object keeps, in
that order."""


def revive(value: object, reviver: JsonReviver) -> object:
    """``value`` walked as ``JSON.parse`` walks it with ``reviver``."""
    return _revive(reviver, "", value)


def _revive(reviver: JsonReviver, key: str, node: object) -> object:
    if isinstance(node, list):
        items: list[object] = node  # pyright: ignore[reportUnknownVariableType]
        node = [_revive(reviver, str(i), item) for i, item in enumerate(items)]
    elif isinstance(node, dict):
        entries: dict[str, object] = node  # pyright: ignore[reportUnknownVariableType]
        node = {k: _revive(reviver, k, v) for k, v in entries.items()}
    return reviver(key, node)


def replace_json(value: object, replacer: JsonReplacer) -> object:
    """``value`` as ``JSON.stringify`` sees it through ``replacer``."""
    if callable(replacer):
        return _replace(replacer, "", value)
    return _keep(list(dict.fromkeys(str(key) for key in replacer)), value)


def _replace(replace: Callable[[str, object], object], key: str, node: object) -> object:
    node = replace(key, node)
    if isinstance(node, (list, tuple)):
        items: tuple[object, ...] = tuple(node)  # pyright: ignore[reportUnknownArgumentType, reportUnknownVariableType]
        return [_replace(replace, str(i), item) for i, item in enumerate(items)]
    if isinstance(node, Mapping):
        entries: Mapping[str, object] = node  # pyright: ignore[reportUnknownVariableType]
        return {k: _replace(replace, k, v) for k, v in entries.items()}
    return node


def _keep(keys: list[str], node: object) -> object:
    if isinstance(node, (list, tuple)):
        items: tuple[object, ...] = tuple(node)  # pyright: ignore[reportUnknownArgumentType, reportUnknownVariableType]
        return [_keep(keys, item) for item in items]
    if isinstance(node, Mapping):
        entries: Mapping[str, object] = node  # pyright: ignore[reportUnknownVariableType]
        return {k: _keep(keys, entries[k]) for k in keys if k in entries}
    return node
