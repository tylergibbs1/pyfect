"""``header_codec``: a schema of header records whose empty cells of optional
keys decode as missing keys (Effect's ``prepareHeader`` in ``Csv``).

CSV cannot tell an empty cell from a missing one. Each struct, also inside
a union or a suspend, gets its own copy of the row with those cells
removed, before either its properties or its index signatures run, so a
union applies the optional keys of the member it selects."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any, TypeIs

from pyfect.schema import Bottom, Codec, ast, declare
from pyfect.schema import transformation as T


def header_codec[T_, RD, RE](schema: Codec[T_, Any, RD, RE]) -> Codec[T_, Any, RD, RE]:
    node = schema.__codec__().ast
    prepared = _Prepare()(node)
    return schema if prepared is node else Bottom(prepared)


def _is_mapping(input: object) -> TypeIs[Mapping[Any, Any]]:
    return isinstance(input, Mapping)


def _same(row: Mapping[str, object]) -> Mapping[str, object]:
    return row


@dataclass(frozen=True, slots=True)
class _PreparedThunk:
    prepare: _Prepare
    source: ast.Suspend

    def __call__(self) -> ast.AST:
        return self.prepare(self.source.target)


class _Prepare:
    def __init__(self) -> None:
        self._done: dict[int, ast.AST] = {}

    def __call__(self, node: ast.AST) -> ast.AST:
        done = self._done.get(id(node))
        if done is None:
            done = self._last_link(node)
            self._done[id(node)] = done
        return done

    def _last_link(self, node: ast.AST) -> ast.AST:
        if node.encoding is None:
            return self._step(node)
        *init, last = node.encoding
        to = self(last.to)
        if to is last.to:
            return node
        return replace(node, encoding=(*init, ast.Link(to, last.transformation)))

    def _step(self, node: ast.AST) -> ast.AST:
        match node:
            case ast.Union():
                return node.map_types(self)
            case ast.Suspend() if isinstance(node.thunk, _PreparedThunk):
                return node
            case ast.Suspend():
                return replace(node, thunk=_PreparedThunk(self, node))
            case ast.Objects():
                return _omit_empty_optional_cells(node)
            case _:
                return node


def _omit_empty_optional_cells(node: ast.Objects) -> ast.AST:
    keys = tuple(
        p.name for p in node.properties if isinstance(p.name, str) and p.optional_when_encoded()
    )
    if not keys:
        return node

    def omit(row: Mapping[str, object]) -> Mapping[str, object]:
        if all(row.get(key) != "" for key in keys):
            return row
        return {k: v for k, v in row.items() if not (k in keys and v == "")}

    row = declare(
        _is_mapping,
        # A one-member union describes the row by its discriminants, as union
        # errors do; the sentinels keep them visible to the union's parser.
        expected=ast.Union((node,)).get_expected(),
        **{ast.SENTINELS: ast.collect_sentinels(ast.to_encoded(node))},
    )
    return ast.decode_to(row.ast, node, T.transform(decode=omit, encode=_same))
