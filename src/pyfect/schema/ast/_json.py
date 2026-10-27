"""JSON values (Effect's ``isJson`` and ``Json`` declaration)."""

from __future__ import annotations

import math
from collections.abc import Iterator, Mapping, Sequence
from typing import cast

from pyfect.exit import Exit, Success
from pyfect.schema._options import ParseOptions
from pyfect.schema.ast._base import invalid_type
from pyfect.schema.ast._declaration import Declaration, DeclarationParser
from pyfect.schema.issue import Issue


def _is_leaf(value: object) -> bool:
    if value is None or isinstance(value, str | bool | int):
        return True
    return isinstance(value, float) and math.isfinite(value)


def _children(value: object) -> Iterator[object] | None:
    """The values inside a JSON container; ``None`` for anything else."""
    if isinstance(value, list | tuple):
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
    done: set[int] = set()
    on_path: set[int] = set()
    stack: list[tuple[object, Iterator[object]]] = []
    current = value
    while True:
        if _is_leaf(current) or id(current) in done:
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


json = Declaration((), _run, annotations={"expected": "JSON value"})
"""Any JSON value (``is_json``), unchanged."""
