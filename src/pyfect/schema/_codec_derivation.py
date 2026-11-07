"""What Effect's canonical codec derivations share (``makeCodecDerivation``):
a walk that gives each node whose values the target form cannot hold an
encoding from one that can, at the end of its existing encoding chain.

A subclass says how a leaf is written (``_leaf``) and which union members
go first (``_priority``); the walk rebuilds the containers from their
derived parts. Each node is derived once per derivation, so a schema
shared in several places (or recursive, through ``Suspend``) stays shared,
and deriving a derived node again changes nothing.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, replace
from typing import cast

from pyfect.schema import ast
from pyfect.schema._codec_links import key_from_string


class _DerivedShape:
    """A schema class read from the target form: its fields' derived struct.

    The fields are derived on first use, after the class node itself is
    memoized, so a class whose fields refer back to it (a cycle through its
    lazy shape, not a ``Suspend``) meets its own derived node there."""

    __slots__ = ("_fields", "_started", "base", "derivation", "source")

    def __init__(self, base: ast.ClassShape, source: ast.Objects, derivation: CodecDerivation):
        self.base = base
        self.source = source
        self.derivation = derivation
        self._fields: ast.Objects | None = None
        self._started = False

    @property
    def fields(self) -> ast.Objects:
        if self._fields is None:
            self._started = True
            self._fields = cast("ast.Objects", self.derivation(self.source))
        return self._fields

    def start(self) -> None:
        """Derive the fields unless that already began (a field of the
        class refers back to it)."""
        if not self._started:
            self.fields  # noqa: B018

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
class _DerivedThunk:
    """A derived ``Suspend``'s target: marks it derived by this kind of
    derivation, so deriving it again keeps it."""

    derivation: CodecDerivation
    source: ast.Suspend

    def __call__(self) -> ast.AST:
        return self.derivation(self.source.target)


def _in_context_of(node: ast.AST, derived: ast.AST) -> ast.AST:
    """``derived`` in ``node``'s key context, also on what its last link reads, which takes no
    constructor default: a constructor fills the key on the schema's own side only."""
    in_context = ast.replace_context(
        derived, key_annotations=node.key_annotations, optional_key=node.optional_key
    )
    if in_context.encoding is not None:
        *init, last = in_context.encoding
        to = ast.replace_context(
            last.to, key_annotations=node.key_annotations, optional_key=node.optional_key
        )
        linked = replace(in_context, encoding=(*init, ast.Link(to, last.transformation)))
        object.__setattr__(linked, "context_owner", in_context.owner())
        in_context = linked
    default = node.constructor_default
    return in_context if default is None else ast.with_constructor_default(in_context, default)


class CodecDerivation(ABC):
    """One derivation of a canonical codec."""

    opaque: ast.Link
    """The link an instance-encoding class side is written through."""

    def __init__(self) -> None:
        self._done: dict[int, tuple[ast.AST, ast.AST]] = {}
        self._shapes: dict[int, tuple[ast.Objects, _DerivedShape]] = {}
        self._typed: dict[int, tuple[ast.ClassShape, _DerivedShape]] = {}

    @abstractmethod
    def _leaf(self, node: ast.AST) -> ast.AST:
        """A node that is not a container, written in the target form."""

    @abstractmethod
    def _priority(self, encoded: ast.AST) -> int:
        """Union members whose encoded node has a lower priority go first:
        their text could be taken by a string member."""

    def __call__(self, node: ast.AST) -> ast.AST:
        hit = self._done.get(id(node))
        if hit is not None:
            return hit[1]
        owner = node.key_context_owner()
        if owner is not node:
            # A copy with another key context: the owner's codec, in this context.
            out = _in_context_of(node, self(owner))
            self._done[id(node)] = (node, out)
            return out
        out = self._last_link(node)
        self._done[id(node)] = (node, out)
        self._done[id(out)] = (out, out)
        if isinstance(out, ast.Class) and isinstance(out.shape, _DerivedShape):
            # Derive the fields now, with the class memoized: a missing codec
            # raises here, and a field referring back meets ``out``.
            out.shape.start()
        return out

    def _last_link(self, node: ast.AST) -> ast.AST:
        if node.encoding is None:
            return self._step(node)
        *init, last = node.encoding
        if self._stops_at(last):
            return node
        to = self(last.to)
        if to is last.to:
            return node
        return replace(node, encoding=(*init, ast.Link(to, last.transformation)))

    def _stops_at(self, _link: ast.Link) -> bool:
        """Whether ``link`` is already in the target form, so the walk keeps it as it is."""
        return False

    def _step(self, node: ast.AST) -> ast.AST:  # noqa: PLR0911
        match node:
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
                thunk = node.thunk
                if isinstance(thunk, _DerivedThunk) and type(thunk.derivation) is type(self):
                    return node
                return replace(node, thunk=_DerivedThunk(self, node))
            case ast.Class():
                return self._class(node)
            case _:
                return self._leaf(node)

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
        ordered = sorted(node.types, key=lambda t: self._priority(ast.to_encoded(t)))
        types = tuple(map(self, ordered))
        if all(a is b for a, b in zip(types, node.types, strict=True)):
            return node
        return replace(node, types=types)

    def _class(self, node: ast.Class) -> ast.AST:
        match node.side:
            case "decode":
                shape = node.shape
                if isinstance(shape, _DerivedShape) and type(shape.derivation) is type(self):
                    return node
                return replace(node, shape=self._shape(shape, shape.fields))
            case "type":
                # Instances read from the target form: as Effect's class
                # declaration links its typed struct. Each type side of the
                # class shares one derived shape (``to_type`` makes new nodes).
                hit = self._typed.get(id(node.shape))
                if hit is None:
                    fields = cast("ast.Objects", node.shape.fields.to_type())
                    hit = (node.shape, self._shape(node.shape, fields))
                    self._typed[id(node.shape)] = hit
                return replace(node, side="decode", shape=hit[1])
            case "encoded":
                return self(node.shape.encoded)
            case "encode":
                return replace(node, encoding=(self.opaque,))

    def _shape(self, shape: ast.ClassShape, fields: ast.Objects) -> _DerivedShape:
        hit = self._shapes.get(id(fields))
        if hit is None:
            hit = (fields, _DerivedShape(shape, fields, self))
            self._shapes[id(fields)] = hit
        return hit[1]
