"""``to_representation`` / ``to_representations``: a schema's encoded side
as a document (Effect's ``toRepresentation``).

Each position is the node at the end of its encoding chain (a class: its
fields' struct), so the document describes what the schema decodes from;
``S.to_type(schema)`` gives the decoded side instead. Which nodes become
named ``references`` is decided as for JSON Schema definitions (shared
with ``to_json_schema_document``): by default a node with an
``identifier``, and every recursive node.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import cast

from pyfect.schema import ast
from pyfect.schema._jsonschema._annotations import ReferencePolicy
from pyfect.schema._jsonschema._checks import schemas_of
from pyfect.schema._jsonschema._references import FALLBACK_KEY, Candidate, Content, References
from pyfect.schema._schema import Top
from pyfect.schema._undefined import OBJECT_KEYWORD_ID, UNDEFINED_ID, VOID_ID
from pyfect.schema.representation import _model as R


def to_representation(
    schema: Top, /, *, reference_policy: ReferencePolicy | None = None
) -> R.Document:
    """The document of ``schema``'s encoded side. ``reference_policy``
    names the nodes that become references (default: their
    ``identifier``); a recursive node is one whatever it says."""
    multi = to_representations((schema,), reference_policy=reference_policy)
    return R.Document(multi.representations[0], multi.references)


def to_representations(
    schemas: tuple[Top, *tuple[Top, ...]], /, *, reference_policy: ReferencePolicy | None = None
) -> R.MultiDocument:
    """The documents of several schemas, sharing their references."""
    roots = [schema.__codec__().ast for schema in schemas]
    lowering = _Lowering(References(roots, reference_policy))
    first, *rest = (lowering.recur(root) for root in roots)
    return R.MultiDocument((first, *rest), lowering.references)


class _Lowering:
    def __init__(self, candidates: References) -> None:
        self.candidates = candidates
        self.references: dict[str, R.Representation] = {}
        self._emitted: set[int] = set()

    def recur(self, node: ast.AST) -> R.Representation:
        return self.recur_candidate(self.candidates.candidate(node))

    def recur_candidate(self, candidate: Candidate) -> R.Representation:
        reference = candidate.reference
        if reference is None:
            return self.on(candidate.ast, candidate.content)
        if id(candidate) not in self._emitted:
            self._emitted.add(id(candidate))
            node = candidate.ast
            if candidate.identifier is not None:
                node = _annotate_reference(node, candidate, reference)
            # Inserted after lowering: a recursive body's references come
            # first, as in Effect.
            self.references[reference] = self.on(node, candidate.content)
        return R.Reference(reference)

    def on(self, node: ast.AST, content: Content | None) -> R.Representation:  # noqa: PLR0911, PLR0912
        checks = tuple(self.check(c) for c in node.checks or ())
        annotations = _annotations(node.annotations)
        match node:
            case ast.Null():
                return R.Null(annotations=annotations, checks=checks)
            case ast.Never():
                return R.Never(annotations=annotations, checks=checks)
            case ast.Unknown():
                return R.Unknown(annotations=annotations, checks=checks)
            case ast.Any():
                return R.Any(annotations=annotations, checks=checks)
            case ast.String():
                held = None
                if content is not None:
                    schema = content.schema
                    inner = None if schema is None else self.recur_candidate(schema)
                    held = R.Content(content.media_type, inner)
                return R.String(annotations=annotations, checks=checks, content=held)
            case ast.Number():
                return R.Number(annotations=annotations, checks=checks)
            case ast.Boolean():
                return R.Boolean(annotations=annotations, checks=checks)
            case ast.BigInt():
                return R.BigInt(annotations=annotations, checks=checks)
            case ast.Literal(literal=None):
                return R.Null(annotations=annotations, checks=checks)
            case ast.Literal(literal=literal) if literal is not None:
                return R.Literal(literal, annotations=annotations, checks=checks)
            case ast.Enum():
                enums = tuple((m.name, cast("R.EnumValue", m.value)) for m in node.enum)
                return R.Enum(enums, annotations=annotations, checks=checks)
            case ast.TemplateLiteral():
                parts = tuple(self.recur(p) for p in node.parts)
                return R.TemplateLiteral(parts, annotations=annotations, checks=checks)
            case ast.Arrays():
                elements = tuple(
                    R.Element(
                        self.recur(e.type),
                        e.optional_when_encoded(),
                        _annotations(e.type.key_annotations),
                    )
                    for e in node.elements
                )
                rest = tuple(self.recur(r) for r in node.rest)
                return R.Arrays(elements, rest, annotations=annotations, checks=checks)
            case ast.Objects():
                return self.objects(node, annotations, checks)
            case ast.Union():
                types = tuple(self.recur(t) for t in node.types)
                return R.Union(types, node.mode, annotations=annotations, checks=checks)
            case ast.Suspend():
                return R.Suspend(self.recur(node.target), annotations)
            case ast.Declaration():
                keyword = _keyword_of(node.annotations)
                if keyword is not None:
                    return keyword(annotations=_without_builtin(node.annotations), checks=checks)
                return self.declaration(node.type_parameters, node.annotations, checks)
            case ast.Class():
                # A class's instances (its decoded side): a declaration of
                # its fields.
                fields = node.shape.fields.to_type()
                return self.declaration((fields,), node.annotations, checks)
            case _:
                raise TypeError(f"Cannot represent a {node.tag} node")

    def objects(
        self, node: ast.Objects, annotations: R.Annotations | None, checks: tuple[R.Check, ...]
    ) -> R.Objects:
        properties: list[R.PropertySignature] = []
        for p in node.properties:
            name = p.name
            if not isinstance(name, str | int | float) or isinstance(name, bool):
                raise TypeError(f"Cannot represent the property name {name!r}")
            optional = p.optional_when_encoded()
            key_annotations = _annotations(p.type.key_annotations)
            properties.append(
                R.PropertySignature(name, self.recur(p.type), optional, key_annotations)
            )
        indexes = tuple(
            R.IndexSignature(self.recur(i.parameter), self.recur(i.type))
            for i in node.index_signatures
        )
        return R.Objects(tuple(properties), indexes, annotations=annotations, checks=checks)

    def declaration(
        self,
        parameters: Sequence[ast.AST],
        annotations: ast.Annotations | None,
        checks: tuple[R.Check, ...],
    ) -> R.Declaration:
        representation, ordinary = _split(annotations)
        declared = None
        if representation is not None:
            declared = R.RepresentationAnnotation(
                cast("str", representation.get("id")), cast("R.Json", representation.get("payload"))
            )
        return R.Declaration(
            tuple(self.recur(p) for p in parameters),
            annotations=ordinary,
            checks=checks,
            representation=declared,
        )

    def check(self, check: ast.Check[object]) -> R.Check:
        representation, ordinary = _split(check.annotations)
        identity = None
        if representation is not None:
            schemas = (
                tuple(self.recur(s) for s in self.candidates.check_schemas(check))
                if "schemas" in representation and schemas_of(check.annotations)
                else None
            )
            identity = R.CheckRepresentationAnnotation(
                cast("str", representation.get("id")),
                cast("R.Json", representation.get("payload")),
                schemas,
            )
        if isinstance(check, ast.Filter):
            return R.Filter(identity, ordinary, check.aborted)
        first, *rest = (self.check(c) for c in check.checks)
        return R.FilterGroup((first, *rest), identity, ordinary)


def _annotations(annotations: ast.Annotations | None) -> R.Annotations | None:
    return annotations or None


_KEYWORD_DECLARATIONS: Mapping[object, type[R.Undefined | R.Void | R.ObjectKeyword]] = {
    UNDEFINED_ID: R.Undefined,
    VOID_ID: R.Void,
    OBJECT_KEYWORD_ID: R.ObjectKeyword,
}
"""What pyfect declares (Python's AST has no such keywords) and Effect has as nodes."""

_BUILTIN_ANNOTATIONS = frozenset(
    {"expected", "representation", "to_arbitrary", "to_codec_json", "to_codec_string_tree"}
)


def _keyword_of(
    annotations: ast.Annotations | None,
) -> type[R.Undefined | R.Void | R.ObjectKeyword] | None:
    representation = (annotations or {}).get("representation")
    if not isinstance(representation, Mapping):
        return None
    return _KEYWORD_DECLARATIONS.get(cast("Mapping[str, object]", representation).get("id"))


def _without_builtin(annotations: ast.Annotations | None) -> R.Annotations | None:
    return {k: v for k, v in (annotations or {}).items() if k not in _BUILTIN_ANNOTATIONS} or None


def _split(
    annotations: ast.Annotations | None,
) -> tuple[Mapping[str, object] | None, R.Annotations | None]:
    """A check's or a declaration's ``representation`` annotation apart
    from its other annotations."""
    if not annotations:
        return None, None
    representation = annotations.get("representation")
    ordinary = {k: v for k, v in annotations.items() if k != "representation"}
    found = (
        cast("Mapping[str, object]", representation)
        if isinstance(representation, Mapping)
        else None
    )
    return found, ordinary or None


def _annotate_reference(node: ast.AST, candidate: Candidate, reference: str) -> ast.AST:
    """``node`` annotated with the name its reference got (or, when it is
    named after the node it was reached from, that node's identifier)."""
    fallback = candidate.fallback
    if fallback is not None:
        if (node.resolve() or {}).get(FALLBACK_KEY) == fallback:
            return node
        return ast.annotate(node, {FALLBACK_KEY: fallback})
    if reference == candidate.identifier:
        return node
    return ast.annotate(node, {"identifier": reference})
