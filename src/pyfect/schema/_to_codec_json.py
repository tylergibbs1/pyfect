"""``to_codec_json``: a schema's canonical JSON codec (Effect's
``Schema.toCodecJson``).

The derived schema decodes the same values from JSON: each node whose
values are not JSON gets an encoding from one that is, at the end of its
existing encoding chain. A number that may be non-finite is written as
``"NaN"`` / ``"Infinity"`` / ``"-Infinity"``, a bigint as its digits, an
``Unknown`` value as JSON, a declaration through its ``to_codec_json`` /
``to_codec`` annotation (``Option`` as ``{"_tag": "Some", "value": ...}``,
...) or as JSON when it has none, a mapping's ``int`` keys as text. The
other nodes are rebuilt from their derived parts; ``Any`` is kept as it is.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import cast

from pyfect._json_value import JsonValue
from pyfect.schema import ast
from pyfect.schema._codec_links import (
    BIG_INT_TO_STRING,
    NUMBER_TO_JSON,
    UNKNOWN_TO_JSON,
    is_finite_number,
    key_from_string,
)
from pyfect.schema._schema import Bottom, Codec


def to_codec_json[T, E, RD, RE](schema: Codec[T, E, RD, RE], /) -> Bottom[T, JsonValue, RD, RE]:
    """``schema`` decoding its values from JSON (Effect's ``toCodecJson``)."""
    return Bottom(_Derivation()(schema.__codec__().ast))


def to_codec_json_asts(nodes: Sequence[ast.AST]) -> list[ast.AST]:
    """The JSON forms of ``nodes`` from one derivation, so a node given
    twice (or shared between them) has one derived node, as Effect's
    memoized derivation gives."""
    derive = _Derivation()
    return [derive(node) for node in nodes]


@dataclass(frozen=True, slots=True)
class _JsonShape:
    """A schema class read from JSON: its fields' derived struct."""

    base: ast.ClassShape
    fields: ast.Objects

    @property
    def cls(self) -> type:
        return self.base.cls

    @property
    def encoded(self) -> ast.AST:
        return self.fields.flip().to_type()

    @property
    def checks(self) -> ast.Checks | None:
        return self.base.checks

    def construct(self, values: dict[object, object]) -> object:
        return self.base.construct(values)

    def values_of(self, instance: object) -> dict[object, object]:
        return self.base.values_of(instance)


@dataclass(frozen=True, slots=True)
class _JsonThunk:
    """A derived ``Suspend``'s target: marks it derived, so deriving it
    again keeps it (the derivation is idempotent)."""

    derivation: _Derivation
    source: ast.Suspend

    def __call__(self) -> ast.AST:
        return self.derivation(self.source.target)


class _Derivation:
    """One derivation: each node is derived once, so a schema shared in
    several places (or recursive, through ``Suspend``) stays shared."""

    def __init__(self) -> None:
        self._done: dict[int, tuple[ast.AST, ast.AST]] = {}
        self._shapes: dict[int, tuple[ast.Objects, _JsonShape]] = {}

    def __call__(self, node: ast.AST) -> ast.AST:
        hit = self._done.get(id(node))
        if hit is not None:
            return hit[1]
        out = self._last_link(node)
        self._done[id(node)] = (node, out)
        self._done[id(out)] = (out, out)
        return out

    def _last_link(self, node: ast.AST) -> ast.AST:
        if node.encoding is None:
            return self._step(node)
        *init, last = node.encoding
        to = self(last.to)
        if to is last.to:
            return node
        return replace(node, encoding=(*init, ast.Link(to, last.transformation)))

    def _step(self, node: ast.AST) -> ast.AST:  # noqa: PLR0911
        match node:
            case ast.Declaration():
                return self._declaration(node)
            case ast.Unknown():
                return replace(node, encoding=(UNKNOWN_TO_JSON,))
            case ast.Number():
                return node if is_finite_number(node) else replace(node, encoding=(NUMBER_TO_JSON,))
            case ast.BigInt():
                return replace(node, encoding=(BIG_INT_TO_STRING,))
            case ast.Objects():
                return self._objects(node)
            case ast.Union():
                return self._union(node)
            case ast.Arrays():
                elements = tuple(ast.Element(self(e.type), e.optional) for e in node.elements)
                rest = tuple(map(self, node.rest))
                same = all(
                    a.type is b.type for a, b in zip(elements, node.elements, strict=True)
                ) and all(a is b for a, b in zip(rest, node.rest, strict=True))
                return node if same else replace(node, elements=elements, rest=rest)
            case ast.Suspend():
                if isinstance(node.thunk, _JsonThunk):
                    return node
                return replace(node, thunk=_JsonThunk(self, node))
            case ast.Class():
                return self._class(node)
            case _:
                return node

    def _declaration(self, node: ast.Declaration) -> ast.AST:
        annotations = node.annotations or {}
        get_link = annotations.get("to_codec_json") or annotations.get("to_codec")
        if not callable(get_link):
            return replace(node, encoding=(UNKNOWN_TO_JSON,))
        make = cast("Callable[[tuple[ast.AST, ...]], ast.Link | None]", get_link)
        link = make(tuple(ast.to_encoded(p) for p in node.type_parameters))
        if link is None:
            return node
        return replace(node, encoding=(ast.Link(self(link.to), link.transformation),))

    def _objects(self, node: ast.Objects) -> ast.Objects:
        if any(not isinstance(p.name, str) for p in node.properties):
            raise ValueError("Objects property names must be strings")
        properties = tuple(replace(p, type=self(p.type)) for p in node.properties)
        indexes = tuple(
            ast.IndexSignature(key_from_string(i.parameter), self(i.type))
            for i in node.index_signatures
        )
        same = all(
            a.type is b.type for a, b in zip(properties, node.properties, strict=True)
        ) and all(
            a.parameter is b.parameter and a.type is b.type
            for a, b in zip(indexes, node.index_signatures, strict=True)
        )
        return node if same else replace(node, properties=properties, index_signatures=indexes)

    def _union(self, node: ast.Union) -> ast.Union:
        # A bigint member goes first: its text could be taken by a string member.
        ordered = sorted(
            node.types, key=lambda t: 0 if isinstance(ast.to_encoded(t), ast.BigInt) else 1
        )
        types = tuple(map(self, ordered))
        if all(a is b for a, b in zip(types, node.types, strict=True)):
            return node
        return replace(node, types=types)

    def _class(self, node: ast.Class) -> ast.AST:
        match node.side:
            case "decode":
                shape = self._json_shape(node.shape, node.shape.fields)
                return node if shape.fields is node.shape.fields else replace(node, shape=shape)
            case "type":
                # Instances read from JSON: as Effect's class declaration
                # links its typed struct.
                fields = cast("ast.Objects", node.shape.fields.to_type())
                return replace(node, side="decode", shape=self._json_shape(node.shape, fields))
            case "encoded":
                return self(node.shape.encoded)
            case "encode":
                return replace(node, encoding=(UNKNOWN_TO_JSON,))

    def _json_shape(self, shape: ast.ClassShape, fields: ast.Objects) -> _JsonShape:
        hit = self._shapes.get(id(fields))
        if hit is None:
            hit = (fields, _JsonShape(shape, cast("ast.Objects", self(fields))))
            self._shapes[id(fields)] = hit
        return hit[1]
