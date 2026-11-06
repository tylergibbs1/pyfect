"""Builds the runtime schemas of normalized import nodes."""

from __future__ import annotations

from typing import Any, Never

from pyfect import schema as S
from pyfect.schema import ast
from pyfect.schema._schema import Bottom
from pyfect.schema.representation._from import ReferenceSlot, error_with_path
from pyfect.schema.representation._import import _nodes as N
from pyfect.schema.representation._import._translate import Translator

type ImportedSchema = Bottom[object, object, Never, Never]
"""A schema read from JSON Schema: nothing is known of its values statically,
and it needs no services."""


class Finalizer:
    def __init__(self, translator: Translator) -> None:
        self.translator = translator
        self.references: dict[str, ReferenceSlot] = {}

    def root(self, node: N.Node) -> ImportedSchema:
        return Bottom(self.finalize(node))

    def finalize(self, node: N.Node) -> ast.AST:  # noqa: PLR0912
        annotations = N.merge_annotations(node.annotations, node.custom_annotations)
        if isinstance(node, N.Reference):
            return self._reference(node, annotations)
        match node:
            case N.Unknown():
                return ast.annotate(ast.json, {**(annotations or {}), "expected": "JSON value"})
            case N.Never():
                out: ast.AST = ast.never
            case N.Null():
                out = ast.null
            case N.String():
                out = ast.string
            case N.Number():
                out = ast.number
            case N.Boolean():
                out = ast.boolean
            case N.Literal(literal=literal):
                out = ast.Literal(literal)
            case N.Arrays():
                out = self._arrays(node)
            case N.Objects():
                out = self._objects(node)
            case N.Union(types=types, mode=mode):
                out = ast.Union(tuple(self.finalize(t) for t in types), mode or "any_of")
        if annotations is not None:
            out = ast.annotate(out, annotations)
        if not node.checks:
            return out
        first, *rest = (self._check(check) for check in node.checks)
        return ast.append_checks(out, (first, *rest))

    def _reference(self, node: N.Reference, annotations: N.Annotations | None) -> ast.AST:
        if annotations is not None:
            self.translator.resolve_reference(node, node.path)
        slot = self.references.get(node.ref)
        if slot is None:
            slot = self.references[node.ref] = ReferenceSlot(node.ref)
            body = self.finalize(self.translator.definition(node.ref, node.path))
            slot.body = ast.annotate(body, {"identifier": node.ref})
        if annotations is not None:
            return ast.annotate(slot.wrapper, annotations)
        return slot.wrapper if slot.body is None else slot.body

    def _check(self, check: N.Check) -> ast.Check[Any]:
        match check:
            case N.FilterGroup(checks=checks, annotations=annotations):
                first, *rest = (self._check(c) for c in checks)
                return ast.FilterGroup((first, *rest), annotations)
            case N.PropertyNames(type=type, annotations=annotations):
                filter = S.is_property_names(Bottom(self.finalize(type)))
            case N.Filter(filter=filter, annotations=annotations):
                pass
        return filter if annotations is None else filter.annotate(**annotations)

    def _arrays(self, node: N.Arrays) -> ast.AST:
        elements = tuple(
            ast.Element(self._optional(self.finalize(e.type), e.is_optional), e.is_optional)
            for e in node.elements
        )
        rest = () if node.rest is None else (self.finalize(node.rest),)
        return ast.Arrays(elements, rest)

    def _optional(self, type: ast.AST, is_optional: bool) -> ast.AST:
        return ast.replace_context(type, optional_key=True) if is_optional else type

    def _objects(self, node: N.Objects) -> ast.AST:
        # Intersections may remove open patterns, so this looks at the
        # normalized object.
        index = node.index_signature
        if (
            index is not None
            and index.parameter is N.STRING
            and any(scope.patterns for scope in node.scopes)
        ):
            raise error_with_path(
                'Cannot import open "patternProperties": unmatched keys cannot be typed correctly.',
                node.path,
            )
        properties = tuple(
            ast.PropertySignature(
                p.name, self._optional(self.finalize(p.type), p.is_optional), p.is_optional
            )
            for p in node.property_signatures
        )
        record = (
            None
            if index is None
            else ast.record(self.finalize(index.parameter), self.finalize(index.type))
        )
        if record is None:
            return ast.Objects(properties)
        if not properties:
            return record
        return ast.struct_with_rest(ast.Objects(properties), [record])
