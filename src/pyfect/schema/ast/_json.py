"""JSON values and string trees (Effect's ``isJson`` / ``isStringTree`` and
their ``Json`` / ``StringTree`` declarations)."""

from __future__ import annotations

import math
from collections.abc import Callable, Iterator, Mapping, Sequence
from typing import cast

from pyfect.exit import Exit, Success
from pyfect.schema._options import ParseOptions
from pyfect.schema.ast._base import invalid_type
from pyfect.schema.ast._declaration import Declaration, DeclarationParser
from pyfect.schema.ast._encoding import Link
from pyfect.schema.issue import Issue


def _is_json_leaf(value: object) -> bool:
    if value is None or isinstance(value, (str, bool, int)):
        return True
    return isinstance(value, float) and math.isfinite(value)


def _children(value: object) -> Iterator[object] | None:
    """The values inside a JSON container; ``None`` for anything else."""
    if isinstance(value, (list, tuple)):
        return iter(cast("Sequence[object]", value))
    if isinstance(value, Mapping):
        mapping = cast("Mapping[object, object]", value)
        if all(isinstance(key, str) for key in mapping):
            return iter(mapping.values())
    return None


def is_json(value: object) -> bool:
    """``value`` is ``None``, a string, a boolean, an ``int``, a finite
    ``float``, or a ``list`` / ``tuple`` / string-keyed ``Mapping`` of JSON
    values. A cycle is not JSON; a value shared twice (a DAG) is. Iterative,
    so any depth works."""
    return _is_tree(value, _is_json_leaf)


def _is_string_tree_leaf(value: object) -> bool:
    return value is None or isinstance(value, str)


def is_string_tree(value: object) -> bool:
    """``value`` is a string, ``None`` (Effect's ``undefined``), or a
    ``list`` / ``tuple`` / string-keyed ``Mapping`` of string trees (Effect's
    ``isStringTree``); a cycle is not one."""
    return _is_tree(value, _is_string_tree_leaf)


def _is_tree(value: object, is_leaf: Callable[[object], bool]) -> bool:
    done: set[int] = set()
    on_path: set[int] = set()
    stack: list[tuple[object, Iterator[object]]] = []
    current = value
    while True:
        if is_leaf(current) or id(current) in done:
            pass
        elif id(current) in on_path:
            return False
        else:
            children = _children(current)
            if children is None:
                return False
            on_path.add(id(current))
            stack.append((current, children))
        while stack:
            container, children = stack[-1]
            nxt = next(children, _END)
            if nxt is not _END:
                current = nxt
                break
            stack.pop()
            on_path.discard(id(container))
            done.add(id(container))
        else:
            return True


_END = object()


def _run(_: tuple[object, ...]) -> DeclarationParser:
    def parse(input: object, ast: Declaration, options: ParseOptions) -> Exit[object, Issue]:
        return Success(input) if is_json(input) else invalid_type(ast, input, options)

    return parse


def _string_tree_run(_: tuple[object, ...]) -> DeclarationParser:
    def parse(input: object, ast: Declaration, options: ParseOptions) -> Exit[object, Issue]:
        return Success(input) if is_string_tree(input) else invalid_type(ast, input, options)

    return parse


def _already_canonical(_: tuple[object, ...]) -> None:
    return None


def _from_string_tree(_: tuple[object, ...]) -> Link:
    from pyfect.schema._codec_links import UNKNOWN_TO_STRING_TREE

    return UNKNOWN_TO_STRING_TREE


string_tree = Declaration(
    (),
    _string_tree_run,
    annotations={"expected": "StringTree", "to_codec_string_tree": _already_canonical},
)
"""Any string tree (``is_string_tree``), unchanged: an opaque value's
``to_codec_string_tree`` form."""


json = Declaration(
    (),
    _run,
    annotations={
        "expected": "JSON value",
        "representation": {"id": "effect/schema/Json", "payload": None},
        "to_codec_json": _already_canonical,
        "to_codec_string_tree": _from_string_tree,
    },
)
"""Any JSON value (``is_json``), unchanged."""
