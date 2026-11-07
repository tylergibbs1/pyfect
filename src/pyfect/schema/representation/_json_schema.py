"""JSON Schema of a document (Effect's ``SchemaRepresentation.toJsonSchemaDocument``).

The document is compiled by the same compiler as ``S.to_json_schema_document``:
each node is rebuilt as a structural AST, a declaration or a check as an
opaque stand-in carrying the node's annotations (its ``to_json_schema``,
its ``representation`` id, which names a built-in check's fragment), and
every reference becomes the definition of its key. A document describes an
encoded side already, so no JSON codec is derived first.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import replace
from typing import Any, Literal

from pyfect.json_schema import Document, MultiDocument
from pyfect.schema import ast
from pyfect.schema._jsonschema._annotations import OnExcessProperty, Options, ReferenceCandidate
from pyfect.schema._jsonschema._compile import Compiler
from pyfect.schema._jsonschema._references import References
from pyfect.schema._options import ParseOptions
from pyfect.schema.issue import Issue
from pyfect.schema.representation import _model as R
from pyfect.schema.representation._from import RepresentationError, Reviving
from pyfect.schema.transformation import _transformation as T

type Draft2020 = Literal["draft-2020-12"]


def _opaque(_: object, node: ast.AST, __: ParseOptions) -> Issue | None:
    raise RepresentationError(f"A compiled representation cannot parse ({node.tag})")


def _opaque_declaration(_: tuple[ast.AST, ...]) -> ast.DeclarationParser:
    def parse(input: object, node: ast.Declaration, options: ParseOptions) -> ast.ParseResult:
        raise RepresentationError("A compiled representation cannot parse (Declaration)")

    return parse


def _encoded(node: ast.AST) -> ast.AST:
    """The node at the end of ``node``'s encoding chain."""
    while node.encoding:
        node = node.encoding[-1].to
    return node


class _Structural(Reviving):
    """Rebuilds a document's nodes without revivers."""

    def __init__(self, references: R.References) -> None:
        super().__init__(references, ())
        self.keys: dict[int, str] = {}

    def named(self, body: ast.AST, key: str) -> ast.AST:
        # The compiler names it by the policy: its own identifier (or
        # fallback) stays, so equivalent fallback definitions dedupe.
        self.keys[id(_encoded(body))] = key
        return body

    def identity(
        self,
        identity: R.CheckRepresentationAnnotation | R.RepresentationAnnotation | None,
        path: Any,
    ) -> dict[str, object]:
        if identity is None:
            return {}
        out: dict[str, object] = {"id": identity.id, "payload": identity.payload}
        if isinstance(identity, R.CheckRepresentationAnnotation) and identity.schemas is not None:
            out["schemas"] = tuple(
                self.recur(s, (*path, "schemas", i)) for i, s in enumerate(identity.schemas)
            )
        return {"representation": out}

    def recur(self, representation: R.Representation, path: Any) -> ast.AST:
        match representation:
            case R.Undefined() | R.Void():
                return self.finish(ast.null, representation, path)
            case R.ObjectKeyword():
                return self.finish(_OBJECT_OR_ARRAY, representation, path)
            case _:
                pass
        if not isinstance(representation, R.String) or representation.content is None:
            return super().recur(representation, path)
        # A string holding a document: the content schema, encoded to it
        # through a link that says so, as ``from_json_string`` builds.
        content = representation.content
        text = super().recur(replace(representation, content=None), path)
        held = (
            ast.unknown
            if content.schema is None
            else self.recur(content.schema, (*path, "content", "schema"))
        )
        marker = T.Content(content.media_type, preserve_schema=content.schema is not None)
        unchanged: T.Transformation[object, object] = T.passthrough()
        return ast.decode_to(text, held, replace(unchanged, content=marker))

    def declaration(self, node: R.Declaration, path: Any) -> ast.AST:
        parameters = tuple(
            self.recur(p, (*path, "type_parameters", i)) for i, p in enumerate(node.type_parameters)
        )
        annotations = {**(node.annotations or {}), **self.identity(node.representation, path)}
        declared = ast.Declaration(parameters, _opaque_declaration, annotations=annotations or None)
        return self.append_checks(declared, node.checks, path)

    def check(self, check: R.Check, path: Any) -> ast.Check[Any]:
        at = (*path, "representation")
        annotations = {**(check.annotations or {}), **self.identity(check.representation, at)}
        if isinstance(check, R.Filter):
            return ast.Filter(_opaque, annotations or None, check.aborted)
        first, *rest = (self.check(c, (*path, "checks", i)) for i, c in enumerate(check.checks))
        return ast.FilterGroup((first, *rest), annotations or None)


_OBJECT_OR_ARRAY = ast.Union(
    (
        ast.Objects(index_signatures=(ast.IndexSignature(ast.string, ast.json),)),
        ast.Arrays(rest=(ast.json,)),
    )
)


def to_json_schema_multi_document(
    document: R.MultiDocument,
    /,
    *,
    on_excess_property: OnExcessProperty = "ignore",
    generate_descriptions: bool = False,
    include_annotation_key: Callable[[str], bool] | None = None,
) -> MultiDocument[Draft2020]:
    """The JSON Schemas of ``document``'s roots, its references their
    definitions (every one is compiled, reachable or not). The options are
    ``S.to_json_schema_multi_document``'s; references are already decided."""
    paths = [("representations", i) for i in range(len(document.representations))]
    return _compile(
        document, paths, Options(on_excess_property, generate_descriptions, include_annotation_key)
    )


def _compile(
    document: R.MultiDocument, paths: list[tuple[str | int, ...]], options: Options
) -> MultiDocument[Draft2020]:
    structural = _Structural(document.references)
    roots = [
        structural.recur(r, path) for r, path in zip(document.representations, paths, strict=True)
    ]
    bodies = [structural.reference(key, ("references",)) for key in document.references]
    keys = structural.keys

    def policy(candidate: ReferenceCandidate) -> str | None:
        return keys.get(id(candidate.ast))

    references = References([*roots, *bodies], policy)
    compiler = Compiler(references, options)
    schemas = [compiler.recur(root, []) for root in roots]
    for body in bodies:
        compiler.definition_of(references.candidate(body))
    out, definitions = compiler.finish(schemas)
    return MultiDocument("draft-2020-12", tuple(out), definitions)


def to_json_schema_document(
    document: R.Document,
    /,
    *,
    on_excess_property: OnExcessProperty = "ignore",
    generate_descriptions: bool = False,
    include_annotation_key: Callable[[str], bool] | None = None,
) -> Document[Draft2020]:
    """The JSON Schema of ``document``'s representation, its references
    the definitions."""
    multi = _compile(
        R.to_multi_document(document),
        [("representation",)],
        Options(on_excess_property, generate_descriptions, include_annotation_key),
    )
    return Document("draft-2020-12", multi.schemas[0], multi.definitions)
