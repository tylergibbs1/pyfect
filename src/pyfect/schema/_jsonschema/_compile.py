"""Compiling encoded nodes to JSON Schema Draft 2020-12 (Effect's
``compileJsonSchema``).

Each node gives its schema, then its annotations' keywords, then each
check's fragment (``_merge.append_json_schema``). Whether a schema is exact
is tracked as it is built: a check without an exact fragment, an opaque
declaration or an unrepresentable key makes the enclosing schema an
approximation, and a ``one_of`` union with an approximate member is written
``anyOf``, so that the approximation cannot reject a valid value.
"""

from __future__ import annotations

import copy
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import cast

from pyfect import _json_text
from pyfect.json_pointer import format_uri_fragment, parse_uri_fragment
from pyfect.json_schema import JsonSchema, rewrite_refs
from pyfect.schema import ast
from pyfect.schema._jsonschema._annotations import Options, collect
from pyfect.schema._jsonschema._checks import CheckContext, exporter
from pyfect.schema._jsonschema._exact import Exactness, is_exact
from pyfect.schema._jsonschema._merge import (
    INLINEABLE_ANNOTATED_CHECK_KEYWORDS,
    INLINEABLE_CHECK_KEYWORDS,
    PROMOTABLE_ANNOTATION_KEYWORDS,
    append_json_schema,
    compact_enums,
    has_only_keywords,
)
from pyfect.schema._jsonschema._objects import compile_objects
from pyfect.schema._jsonschema._references import Candidate, Content, References
from pyfect.schema._jsonschema._template import template_pattern

_JSON_TYPES = frozenset({"string", "number", "boolean", "array", "object", "null", "integer"})


def json_type(value: object) -> str:
    """The JSON type of a literal value."""
    match value:
        case bool():
            return "boolean"
        case int() | float():
            return "number"
        case str():
            return "string"
        case None:
            return "null"
        case _:
            return "object"


_NUMBER: JsonSchema = {
    "anyOf": [{"type": "number"}, {"type": "string", "enum": ["Infinity", "-Infinity", "NaN"]}]
}
_KEYWORDS: dict[type[ast.AST], JsonSchema] = {
    ast.Any: {},
    ast.Unknown: {},
    ast.Null: {"type": "null"},
    ast.BigInt: {"type": "string", "allOf": [{"pattern": r"^-?\d+$"}]},
    ast.Never: {"not": {}},
    ast.String: {"type": "string"},
    ast.Number: _NUMBER,
    ast.Boolean: {"type": "boolean"},
}


def _leaf(node: ast.AST) -> JsonSchema | None:
    """The schema of a node without parts."""
    keyword = _KEYWORDS.get(type(node))
    if keyword is not None:
        return copy.deepcopy(keyword)
    match node:
        case ast.Literal():
            return {"type": json_type(node.literal), "enum": [node.literal]}
        case ast.Enum() if node.side == "decode":
            members = [
                {"type": json_type(member.value), "enum": [member.value], "title": member.name}
                for member in node.enum
            ]
            return {"anyOf": members} if members else {"not": {}}
        case _:
            return None


def definition_reference(key: str) -> str:
    return format_uri_fragment(["$defs", key])


@dataclass
class _Definition:
    schema: JsonSchema = field(default_factory=dict[str, object])
    dependencies: list[Exactness] = field(default_factory=list[Exactness])


@dataclass
class _OneOf:
    branches: list[Exactness]
    schemas: list[JsonSchema] = field(default_factory=list[JsonSchema])


class Compiler:
    """One compilation: the definitions it emits and the ``oneOf`` unions
    it may have to loosen."""

    def __init__(self, references: References, options: Options) -> None:
        self.references = references
        self.options = options
        self._definitions: dict[str, _Definition] = {}
        self._order: list[str] = []
        self._fallbacks: dict[str, str] = {}
        self._one_ofs: dict[int, _OneOf] = {}

    # ------------------------------------------------------------ results

    def finish(self, roots: Sequence[JsonSchema]) -> tuple[list[JsonSchema], dict[str, JsonSchema]]:
        """The final root schemas and definitions."""
        for one_of in self._one_ofs.values():
            if not is_exact(one_of.branches):
                for schema in one_of.schemas:
                    if isinstance(schema.get("oneOf"), list):
                        schema["anyOf"] = schema.pop("oneOf")
        aliases = self._aliases()

        def rewrite(reference: str) -> str:
            path = parse_uri_fragment(reference) if reference.startswith("#") else None
            if path is None:
                if reference[:2] == "#/" or reference[:4].lower() == "#%2f":
                    raise ValueError(
                        f"Invalid JSON Pointer URI fragment {_json_text.stringify(reference)}"
                    )
                return reference
            canonical = aliases.get(path[1]) if len(path) > 1 and path[0] == "$defs" else None
            if canonical is None:
                return reference
            return format_uri_fragment(["$defs", canonical, *path[2:]])

        schemas = [rewrite_refs(schema, rewrite) for schema in roots]
        definitions = {
            key: rewrite_refs(self._definitions[key].schema, rewrite)
            for key in self._order
            if key not in aliases
        }
        return schemas, definitions

    def _aliases(self) -> dict[str, str]:
        """Definitions named after the same identifier (a class's struct
        reached through two of its encodings, ...) that compiled to the same
        schema: each later one is an alias of the first."""
        aliases: dict[str, str] = {}
        seen: dict[str, list[str]] = {}
        for key in self._order:
            fallback = self._fallbacks.get(key)
            if fallback is None:
                continue
            schema = self._definitions[key].schema
            same = seen.setdefault(fallback, [])
            match = next((k for k in same if self._definitions[k].schema == schema), None)
            if match is None:
                same.append(key)
            else:
                aliases[key] = match
        return aliases

    # ----------------------------------------------------------- compiling

    def register_one_of(self, schema: JsonSchema) -> JsonSchema:
        entry = self._one_ofs.get(id(schema.get("oneOf")))
        if entry is not None:
            entry.schemas.append(schema)
        return schema

    def recur(self, node: ast.AST, dependencies: list[Exactness]) -> JsonSchema:
        return self.recur_candidate(self.references.candidate(node), dependencies)

    def recur_candidate(self, candidate: Candidate, dependencies: list[Exactness]) -> JsonSchema:
        if candidate.reference is not None:
            definition = self._definition(candidate, candidate.reference)
            dependencies.append(definition.dependencies)
            return {"$ref": definition_reference(candidate.reference)}
        return self.compile(candidate.ast, dependencies, candidate.content)

    def definition_of(self, candidate: Candidate) -> None:
        """Compile ``candidate``'s definition (if it has one) now."""
        if candidate.reference is not None:
            self._definition(candidate, candidate.reference)

    def _definition(self, candidate: Candidate, key: str) -> _Definition:
        definition = self._definitions.get(key)
        if definition is not None:
            return definition
        # Registered before compiling, so a recursive reference shares it.
        definition = _Definition()
        self._definitions[key] = definition
        if candidate.fallback is not None:
            self._fallbacks[key] = candidate.fallback
        definition.schema = self.compile(candidate.ast, definition.dependencies, candidate.content)
        self._order.append(key)
        return definition

    def compile(
        self, node: ast.AST, dependencies: list[Exactness], content: Content | None = None
    ) -> JsonSchema:
        local: list[Exactness] = []
        dependencies.append(local)
        output = {**self._on(node, local), **collect(node.annotations, self.options)}
        if content is not None and node.tag == "String":
            output["contentMediaType"] = content.media_type
            output.pop("contentSchema", None)
            if content.schema is not None:
                output["contentSchema"] = self.recur_candidate(content.schema, [])
        checks = () if isinstance(node, ast.Suspend) else node.checks or ()
        for check in checks:
            kind = output.get("type")
            context_type = kind if isinstance(kind, str) and kind in _JSON_TYPES else None
            compiled = self._check(check, context_type, local)
            if compiled is not None:
                output = append_json_schema(output, *compiled)
        return self.register_one_of(output)

    def member(
        self, node: ast.AST, annotations: ast.Annotations | None, dependencies: list[Exactness]
    ) -> JsonSchema:
        """An element's or a property's schema, with its key annotations."""
        schema = self.recur(node, dependencies)
        extra = collect(annotations, self.options)
        return self.register_one_of(append_json_schema(schema, extra)) if extra else schema

    def _check(
        self, check: ast.Check[object], kind: str | None, dependencies: list[Exactness]
    ) -> tuple[JsonSchema, bool] | None:
        annotations = check.annotations
        export = exporter(annotations)
        if export is not None:
            schemas = [self.recur(s, dependencies) for s in self.references.check_schemas(check)]
            result = export(CheckContext(kind, schemas))
            if isinstance(result, tuple):
                dependencies.append(False)
                fragment = result[0]
            else:
                fragment = result
            ordinary = collect(annotations, self.options)
            schema = {**fragment, **ordinary}
            allowed = INLINEABLE_ANNOTATED_CHECK_KEYWORDS if ordinary else INLINEABLE_CHECK_KEYWORDS
            inline = (
                isinstance(check, ast.Filter)
                and has_only_keywords(schema, allowed)
                and has_only_keywords(ordinary, PROMOTABLE_ANNOTATION_KEYWORDS)
            )
            return schema, inline
        if isinstance(check, ast.Filter):
            dependencies.append(False)
            return None
        parts = [self._check(child, kind, dependencies) for child in check.checks]
        schemas = [part[0] for part in parts if part is not None]
        if not schemas:
            return None
        return {"allOf": schemas, **collect(annotations, self.options)}, False

    def _on(self, node: ast.AST, dependencies: list[Exactness]) -> JsonSchema:  # noqa: PLR0911
        leaf = _leaf(node)
        if leaf is not None:
            return leaf
        match node:
            case ast.Suspend():
                return self.recur(node.target, dependencies)
            case ast.Arrays():
                return self._arrays(node, dependencies)
            case ast.Objects():
                return compile_objects(self, node, dependencies)
            case ast.Union():
                return self._union(node, dependencies)
            case ast.TemplateLiteral():
                pattern, exact = template_pattern(self, node)
                if not exact:
                    dependencies.append(False)
                return {"type": "string", "pattern": pattern}
            case _:
                # An opaque node: a declaration's parameters' definitions are
                # still emitted, as in Effect.
                if isinstance(node, ast.Declaration):
                    for parameter in node.type_parameters:
                        self.recur(parameter, [])
                dependencies.append(False)
                return {}

    def _arrays(self, node: ast.Arrays, dependencies: list[Exactness]) -> JsonSchema:
        out: JsonSchema = {"type": "array"}
        elements = node.elements
        min_items = len(elements) - sum(1 for e in elements if e.optional)
        prefix = [self.member(e.type, e.type.key_annotations, dependencies) for e in elements]
        if prefix:
            out["prefixItems"] = prefix
            out["maxItems"] = len(elements)
            if min_items > 0:
                out["minItems"] = min_items
        else:
            out["items"] = False
        if len(node.rest) == 1:
            out.pop("maxItems", None)
            rest = self.recur(node.rest[0], dependencies)
            if rest:
                out["items"] = rest
            else:
                out.pop("items", None)
        elif len(node.rest) > 1:
            out.pop("maxItems", None)
            out.pop("items", None)
            out["minItems"] = min_items + len(node.rest) - 1
            dependencies.append(False)
        return out

    def _union(self, node: ast.Union, dependencies: list[Exactness]) -> JsonSchema:
        branches: list[Exactness] = []
        types = [self.recur(t, branches) for t in node.types]
        dependencies.append(branches)
        if not types:
            return {"not": {}}
        if node.mode == "one_of":
            self._one_ofs[id(types)] = _OneOf(branches)
            return {"oneOf": types}
        if len(types) > 1:
            compacted = compact_enums(types)
            if compacted is not None:
                return compacted
        # A member that is only an ``anyOf`` adds no constraint of its own.
        spliced: list[object] = []
        for schema in types:
            any_of = schema.get("anyOf")
            if isinstance(any_of, list) and len(schema) == 1:
                spliced.extend(cast("list[object]", any_of))
            else:
                spliced.append(schema)
        return {"anyOf": spliced}
