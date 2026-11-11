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

    def walk(key: str, node: object) -> object:
        if isinstance(node, list):
            items: list[object] = node  # pyright: ignore[reportUnknownVariableType]
            node = [walk(str(i), item) for i, item in enumerate(items)]
        elif isinstance(node, dict):
            entries: dict[str, object] = node  # pyright: ignore[reportUnknownVariableType]
            node = {k: walk(k, v) for k, v in entries.items()}
        return reviver(key, node)

    return walk("", value)


def replace_json(value: object, replacer: JsonReplacer) -> object:
    """``value`` as ``JSON.stringify`` sees it through ``replacer``."""
    if callable(replacer):
        replace = replacer

        def walk(key: str, node: object) -> object:
            node = replace(key, node)
            if isinstance(node, (list, tuple)):
                items: tuple[object, ...] = tuple(node)  # pyright: ignore[reportUnknownArgumentType, reportUnknownVariableType]
                return [walk(str(i), item) for i, item in enumerate(items)]
            if isinstance(node, Mapping):
                entries: Mapping[str, object] = node  # pyright: ignore[reportUnknownVariableType]
                return {k: walk(k, v) for k, v in entries.items()}
            return node

        return walk("", value)
    keys = list(dict.fromkeys(str(key) for key in replacer))

    def keep(node: object) -> object:
        if isinstance(node, (list, tuple)):
            items: tuple[object, ...] = tuple(node)  # pyright: ignore[reportUnknownArgumentType, reportUnknownVariableType]
            return [keep(item) for item in items]
        if isinstance(node, Mapping):
            entries: Mapping[str, object] = node  # pyright: ignore[reportUnknownVariableType]
            return {k: keep(entries[k]) for k in keys if k in entries}
        return node

    return keep(value)
