"""``to_codec_array_from_single``: a schema whose arrays also decode from a
single string (Effect's ``Schema.toCodecArrayFromSingle``), for query
strings and forms, where a key given once is a string and a key given
several times a list."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, replace

from pyfect.schema import ast
from pyfect.schema import transformation as T
from pyfect.schema._schema import Bottom, Codec


def _to_array(value: Sequence[object] | str) -> Sequence[object]:
    return [value] if isinstance(value, str) else value


def _same(value: Sequence[object]) -> Sequence[object]:
    return value


FROM_SINGLE = T.transform(decode=_to_array, encode=_same)


def to_codec_array_from_single[T_, E, RD, RE](
    schema: Codec[T_, E, RD, RE], /
) -> Bottom[T_, E, RD, RE]:
    """``schema`` with every array (in structs, unions and arrays) also
    decoding a single string as a one-element list; encoding is
    unchanged. A comma-separated string is not split."""
    return Bottom(_Walk()(schema.__codec__().ast))


@dataclass(frozen=True, slots=True)
class _WalkedThunk:
    """A walked ``Suspend``'s target: marks it walked, so walking it again keeps it."""

    walk: _Walk
    source: ast.Suspend

    def __call__(self) -> ast.AST:
        return self.walk(self.source.target)


class _Walk:
    def __init__(self) -> None:
        self._done: dict[int, ast.AST] = {}

    def __call__(self, node: ast.AST) -> ast.AST:
        done = self._done.get(id(node))
        if done is not None:
            return done
        out = self._last_link(node)
        self._done[id(node)] = out
        self._done[id(out)] = out
        return out

    def _last_link(self, node: ast.AST) -> ast.AST:
        if node.encoding is None:
            return self._step(node)
        *init, last = node.encoding
        if last.transformation is FROM_SINGLE:
            return node
        to = self(last.to)
        if to is last.to:
            return node
        return replace(node, encoding=(*init, ast.Link(to, last.transformation)))

    def _step(self, node: ast.AST) -> ast.AST:
        out = self._children(node)
        if not isinstance(out, ast.Arrays):
            return out
        source = ast.Union(
            (
                ast.Arrays(
                    tuple(ast.Element(ast.unknown, e.optional) for e in out.elements),
                    tuple(ast.unknown for _ in out.rest),
                ),
                ast.string,
            )
        )
        ensure = ast.decode_to(source, out, FROM_SINGLE)
        return ast.optional_key(ensure) if node.optional_key else ensure

    def _children(self, node: ast.AST) -> ast.AST:
        match node:
            case ast.Objects():
                properties = tuple(replace(p, type=self(p.type)) for p in node.properties)
                indexes = tuple(replace(i, type=self(i.type)) for i in node.index_signatures)
                same = all(
                    a.type is b.type for a, b in zip(properties, node.properties, strict=True)
                ) and all(
                    a.type is b.type for a, b in zip(indexes, node.index_signatures, strict=True)
                )
                return (
                    node if same else replace(node, properties=properties, index_signatures=indexes)
                )
            case ast.Arrays():
                return replace(
                    node,
                    elements=tuple(replace(e, type=self(e.type)) for e in node.elements),
                    rest=tuple(map(self, node.rest)),
                )
            case ast.Union():
                types = tuple(map(self, node.types))
                same = all(a is b for a, b in zip(types, node.types, strict=True))
                return node if same else replace(node, types=types)
            case ast.Suspend() if isinstance(node.thunk, _WalkedThunk):
                return node
            case ast.Suspend():
                return replace(node, thunk=_WalkedThunk(self, node))
            case _:
                return node
