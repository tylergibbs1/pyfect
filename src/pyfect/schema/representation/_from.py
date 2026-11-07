"""``from_representation`` / ``from_representations``: runtime schemas
rebuilt from a document (Effect's ``fromRepresentation``).

Structural nodes become their schemas; a declaration or a check is
rebuilt by the reviver of its ``representation`` id (none is installed
implicitly), which gets its decoded payload. A reference is revived once
and named by its key (``identifier``); a recursive one goes through a
``suspend``. Errors name the document path they happened at.
"""

from __future__ import annotations

import enum
from collections.abc import Mapping, Sequence
from typing import Any, cast

from pyfect import schema as S
from pyfect.result import Err
from pyfect.schema import ast
from pyfect.schema._schema import Bottom
from pyfect.schema.issue import Path, format_path
from pyfect.schema.representation import _model as R
from pyfect.schema.representation._revivers import (
    AnyReviver,
    AnySchema,
    CheckInput,
    DeclarationInput,
    DeclarationReviver,
    FilterGroupReviver,
    FilterReviver,
)


class RepresentationError(ValueError):
    """A document that cannot be revived; the message names where."""


def error_with_path(message: str, path: Path) -> RepresentationError:
    return RepresentationError(f"{message}\n  at {format_path(path)}" if path else message)


def from_representation(document: R.Document, /, *, revivers: Sequence[AnyReviver]) -> AnySchema:
    """The schema ``document`` describes."""
    return Reviving(document.references, revivers).root(
        document.representation, ("representation",)
    )


def from_representations(
    document: R.MultiDocument, /, *, revivers: Sequence[AnyReviver]
) -> tuple[AnySchema, *tuple[AnySchema, ...]]:
    """The schemas of ``document``'s roots, sharing their references; only
    references reachable from a root are revived."""
    reviving = Reviving(document.references, revivers)
    first, *rest = (
        reviving.root(r, ("representations", i)) for i, r in enumerate(document.representations)
    )
    return (first, *rest)


class ReferenceSlot:
    def __init__(self, key: str) -> None:
        self.body: ast.AST | None = None
        self.resolving = False

        def thunk() -> ast.AST:
            if self.body is None:
                raise RepresentationError(f"Reference {key} was evaluated before it was resolved")
            return self.body

        self.wrapper = ast.Suspend(thunk)


class Reviving:
    def __init__(self, references: R.References, revivers: Sequence[AnyReviver]) -> None:
        self.references = references
        self.slots: dict[str, ReferenceSlot] = {}
        self.revivers: dict[str, AnyReviver] = {}
        for index, reviver in enumerate(revivers):
            if reviver.id in self.revivers:
                raise error_with_path(
                    f"Duplicate reviver for {reviver.id}", ("revivers", index, "id")
                )
            self.revivers[reviver.id] = reviver

    def root(self, representation: R.Representation, path: Path) -> AnySchema:
        return Bottom(self.recur(representation, path))

    # ------------------------------------------------------------ references

    def reference(self, key: str, path: Path) -> ast.AST:
        slot = self.slots.get(key)
        if slot is None:
            if key not in self.references:
                raise error_with_path(f"Invalid reference {key}", (*path, "$ref"))
            slot = self.slots[key] = ReferenceSlot(key)
        if slot.body is not None:
            return slot.body
        if slot.resolving:
            return slot.wrapper
        slot.resolving = True
        try:
            slot.body = self.named(self.recur(self.references[key], ("references", key)), key)
            return slot.body
        finally:
            slot.resolving = False

    def named(self, body: ast.AST, key: str) -> ast.AST:
        """The body of reference ``key``: it keeps the key as its identifier."""
        return ast.annotate(body, {"identifier": key})

    def part(self, representation: R.Representation, path: Path) -> ast.AST:
        """A template literal part: a reference is resolved in place, and
        a recursive one has no finite pattern."""
        if isinstance(representation, R.Reference):
            slot = self.slots.get(representation.ref)
            if slot is not None and slot.resolving:
                raise error_with_path(
                    f"Invalid recursive TemplateLiteral part {representation.ref}", path
                )
        return self.recur(representation, path)

    # --------------------------------------------------------------- revivers

    def reviver(self, id: str, kind: str, path: Path) -> AnyReviver:
        reviver = self.revivers.get(id)
        if reviver is None or reviver.kind != kind:
            raise error_with_path(f"Missing reviver for {id}", path)
        return reviver

    def payload(self, reviver: AnyReviver, payload: R.Json, path: Path) -> object:
        decoded = S.decode_unknown_result(S.to_codec_json(reviver.payload_schema))(payload)
        if isinstance(decoded, Err):
            raise error_with_path(f"Invalid representation payload for {reviver.id}", path)
        return decoded.value

    def schemas(
        self, representations: Sequence[R.Representation], path: Path
    ) -> tuple[AnySchema, ...]:
        return tuple(Bottom(self.recur(r, (*path, i))) for i, r in enumerate(representations))

    def declaration(self, node: R.Declaration, path: Path) -> ast.AST:
        at = (*path, "representation")
        identity = node.representation
        if identity is None:
            raise error_with_path("Missing representation annotation", at)
        reviver = cast("DeclarationReviver[Any]", self.reviver(identity.id, "declaration", at))
        payload = self.payload(reviver, identity.payload, (*at, "payload"))
        parameters = self.schemas(node.type_parameters, (*path, "type_parameters"))
        schema = reviver.revive(DeclarationInput(payload, parameters, node.annotations))
        return self.append_checks(schema.__codec__().ast, node.checks, path)

    def check(self, check: R.Check, path: Path) -> ast.Check[Any]:
        at = (*path, "representation")
        identity = check.representation
        if isinstance(check, R.FilterGroup) and identity is None:
            first, *rest = (self.check(c, (*path, "checks", i)) for i, c in enumerate(check.checks))
            return ast.FilterGroup((first, *rest), check.annotations)
        if identity is None:
            raise error_with_path("Missing representation annotation", at)
        kind = "filter" if isinstance(check, R.Filter) else "filter_group"
        reviver = cast(
            "FilterReviver[Any] | FilterGroupReviver[Any]", self.reviver(identity.id, kind, at)
        )
        payload = self.payload(reviver, identity.payload, (*at, "payload"))
        schemas = self.schemas(identity.schemas or (), (*at, "schemas"))
        revived = reviver.revive(CheckInput(payload, schemas, check.annotations))
        if isinstance(check, R.Filter) and check.aborted and isinstance(revived, ast.Filter):
            return revived.abort()
        return revived

    def append_checks(self, node: ast.AST, checks: Sequence[R.Check], path: Path) -> ast.AST:
        revived = [self.check(c, (*path, "checks", i)) for i, c in enumerate(checks)]
        if not revived:
            return node
        first, *rest = revived
        return ast.append_checks(node, (first, *rest))

    # ------------------------------------------------------------- structure

    def finish(self, node: ast.AST, representation: R.Representation, path: Path) -> ast.AST:
        annotations = getattr(representation, "annotations", None)
        if annotations:
            node = ast.annotate(node, annotations)
        checks: tuple[R.Check, ...] = getattr(representation, "checks", ())
        return self.append_checks(node, checks, path)

    def recur(self, representation: R.Representation, path: Path) -> ast.AST:  # noqa: PLR0911, PLR0912
        match representation:
            case R.Reference(ref=key):
                return self.reference(key, path)
            case R.Declaration():
                return self.declaration(representation, path)
            case R.Suspend(thunk=thunk, annotations=annotations):
                at = (*path, "thunk")
                if isinstance(thunk, R.Reference):
                    self.reference(thunk.ref, at)
                    node: ast.AST = self.slots[thunk.ref].wrapper
                else:
                    target = self.recur(thunk, at)
                    node = ast.Suspend(lambda: target)
                return ast.annotate(node, annotations) if annotations else node
            case R.Null():
                return self.finish(ast.null, representation, path)
            case R.Undefined():
                return self.finish(S.Undefined.ast, representation, path)
            case R.Void():
                return self.finish(S.Void.ast, representation, path)
            case R.ObjectKeyword():
                return self.finish(S.ObjectKeyword.ast, representation, path)
            case R.Never():
                return self.finish(ast.never, representation, path)
            case R.Unknown():
                return self.finish(ast.unknown, representation, path)
            case R.Any():
                return self.finish(ast.any_, representation, path)
            case R.String():
                return self.finish(ast.string, representation, path)
            case R.Number():
                return self.finish(ast.number, representation, path)
            case R.Boolean():
                return self.finish(ast.boolean, representation, path)
            case R.BigInt():
                return self.finish(ast.big_int, representation, path)
            case R.Literal(literal=literal):
                return self.finish(ast.Literal(literal), representation, path)
            case R.Enum(enums=enums):
                members = enum.Enum("Enum", list(enums))
                return self.finish(ast.Enum(cast("type[enum.Enum]", members)), representation, path)
            case R.TemplateLiteral(parts=parts):
                nodes = tuple(self.part(p, (*path, "parts", i)) for i, p in enumerate(parts))
                return self.finish(ast.TemplateLiteral(nodes), representation, path)
            case R.Arrays():
                return self.finish(self.arrays(representation, path), representation, path)
            case R.Objects():
                return self.finish(self.objects(representation, path), representation, path)
            case R.Union(types=types, mode=mode):
                members = tuple(self.recur(t, (*path, "types", i)) for i, t in enumerate(types))
                return self.finish(ast.Union(members, mode), representation, path)

    def arrays(self, node: R.Arrays, path: Path) -> ast.Arrays:
        elements = tuple(
            ast.Element(
                _keyed(self.recur(e.type, (*path, "elements", i, "type")), e.annotations),
                e.is_optional,
            )
            for i, e in enumerate(node.elements)
        )
        rest = tuple(self.recur(r, (*path, "rest", i)) for i, r in enumerate(node.rest))
        return ast.Arrays(elements, rest)

    def objects(self, node: R.Objects, path: Path) -> ast.Objects:
        properties = tuple(
            ast.PropertySignature(
                p.name,
                _keyed(
                    self.recur(p.type, (*path, "property_signatures", i, "type")), p.annotations
                ),
                p.is_optional,
            )
            for i, p in enumerate(node.property_signatures)
        )
        at = (*path, "index_signatures")
        indexes = tuple(
            ast.IndexSignature(
                self.recur(s.parameter, (*at, i, "parameter")), self.recur(s.type, (*at, i, "type"))
            )
            for i, s in enumerate(node.index_signatures)
        )
        return ast.Objects(properties, indexes)


def _keyed(node: ast.AST, annotations: Mapping[str, object] | None) -> ast.AST:
    if not annotations:
        return node
    return ast.replace_context(
        node, key_annotations={**(node.key_annotations or {}), **annotations}
    )
