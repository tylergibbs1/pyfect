"""Compiling a mapping (Effect's ``compileObjects``): ``properties`` and
``required`` for its keys, ``patternProperties`` for index signatures whose
keys a pattern selects, ``additionalProperties`` for the rest."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from pyfect.json_schema import JsonSchema
from pyfect.schema import ast
from pyfect.schema._codec_links import NUMBER_KEY_PATTERN
from pyfect.schema._jsonschema._exact import Exactness, is_exact
from pyfect.schema._jsonschema._merge import append_json_schema, has_only_keywords

if TYPE_CHECKING:
    from pyfect.schema._jsonschema._compile import Compiler

_PATTERN_SCHEMA_KEYWORDS = frozenset(
    {"type", "pattern", "title", "description", "default", "examples", "readOnly", "writeOnly"}
)

type _Value = JsonSchema | bool


def _encoded_optional(p: ast.PropertySignature) -> bool:
    if p.encoded_optional is not None:
        return p.encoded_optional
    return p.optional or p.default is not None or p.type.flip().optional_key


def compile_objects(
    compiler: Compiler, node: ast.Objects, dependencies: list[Exactness]
) -> JsonSchema:
    properties_in, indexes_in = node.properties, node.index_signatures
    if not properties_in and not indexes_in:
        return {"not": {"type": "null"}}
    out: JsonSchema = {"type": "object"}
    _properties(compiler, node, out, dependencies)
    indexes: list[tuple[_Value, list[str] | None]] = []
    for index in indexes_in:
        schema = compiler.recur(index.type, dependencies)
        value: _Value = False if schema == {"not": {}} else schema
        patterns = _patterns(compiler, index.parameter, frozenset())
        if patterns is None:
            dependencies.append(False)
        indexes.append((value, patterns))
    pattern_properties = _pattern_properties(compiler, indexes)
    if pattern_properties:
        out["patternProperties"] = pattern_properties
    _additional(compiler, node, out, indexes, dependencies)
    additional = out.get("additionalProperties")
    if isinstance(additional, dict) and not additional:
        del out["additionalProperties"]
    return out


def _properties(
    compiler: Compiler, node: ast.Objects, out: JsonSchema, dependencies: list[Exactness]
) -> None:
    properties: JsonSchema = {}
    required: list[str] = []
    for p in node.properties:
        if not isinstance(p.name, str):
            raise ValueError("Objects property names must be strings")
        properties[p.name] = compiler.member(p.type, p.type.key_annotations, dependencies)
        if not _encoded_optional(p):
            required.append(p.name)
    if node.properties:
        out["properties"] = properties
    if required:
        out["required"] = required


def _pattern_properties(
    compiler: Compiler, indexes: list[tuple[_Value, list[str] | None]]
) -> dict[str, _Value]:
    """Index signatures with a pattern; a key two of them take must fit both."""
    out: dict[str, _Value] = {}
    for value, patterns in indexes:
        for pattern in patterns or ():
            previous = out.get(pattern)
            if previous is None:
                out[pattern] = value
            elif previous is False or value is False:
                out[pattern] = False
            else:
                merged = append_json_schema(cast("JsonSchema", previous), cast("JsonSchema", value))
                out[pattern] = compiler.register_one_of(merged)
    return out


def _additional(
    compiler: Compiler,
    node: ast.Objects,
    out: JsonSchema,
    indexes: list[tuple[_Value, list[str] | None]],
    dependencies: list[Exactness],
) -> None:
    """``additionalProperties`` (and ``propertyNames``) for the keys no
    property nor pattern takes."""
    unpatterned = [value for value, patterns in indexes if patterns == []]
    unrepresentable = any(patterns is None for _, patterns in indexes)
    error = compiler.options.on_excess_property == "error"
    if unrepresentable and error:
        names: list[JsonSchema] = []
        if node.properties:
            names.append({"enum": [p.name for p in node.properties]})
        names.extend(
            _property_name_schema(compiler, index.parameter, dependencies, frozenset())
            for index in node.index_signatures
        )
        out["propertyNames"] = names[0] if len(names) == 1 else {"anyOf": names}
        values = [value for value, _ in indexes]
        out["additionalProperties"] = values[0] if len(values) == 1 else {"anyOf": values}
        if unpatterned:
            out["allOf"] = [{"type": "object", "additionalProperties": v} for v in unpatterned]
    elif not unpatterned:
        out["additionalProperties"] = unrepresentable or not error
    elif len(unpatterned) == 1 and not node.properties and "patternProperties" not in out:
        out["additionalProperties"] = unpatterned[0]
    else:
        out["allOf"] = [{"type": "object", "additionalProperties": v} for v in unpatterned]


def _property_name_schema(
    compiler: Compiler,
    parameter: ast.AST,
    dependencies: list[Exactness],
    seen: frozenset[str],
) -> JsonSchema:
    candidate = compiler.references.candidate(parameter)
    reference = candidate.reference
    if reference is None:
        return _name_schema(compiler, candidate.ast, dependencies, seen, parameter)
    if reference in seen:
        return {"type": "string"}
    return _name_schema(compiler, candidate.ast, dependencies, seen | {reference}, None)


def _name_schema(
    compiler: Compiler,
    node: ast.AST,
    dependencies: list[Exactness],
    seen: frozenset[str],
    parameter: ast.AST | None,
) -> JsonSchema:
    """``parameter`` is the node as written, ``None`` for a definition's
    own node (compiled in place, not referenced)."""
    match node:
        case ast.Number():
            return {"type": "string", "pattern": NUMBER_KEY_PATTERN}
        case ast.Union():
            return {
                "anyOf": [
                    _property_name_schema(compiler, t, dependencies, seen) for t in node.types
                ]
            }
        case _ if parameter is None:
            return compiler.compile(node, dependencies)
        case _:
            return compiler.recur(parameter, dependencies)


def _patterns(compiler: Compiler, parameter: ast.AST, seen: frozenset[str]) -> list[str] | None:
    """The patterns selecting the keys ``parameter`` takes: ``[]`` for any
    key, ``None`` when no pattern can (an approximation)."""
    candidate = compiler.references.candidate(parameter)
    reference = candidate.reference
    if reference is None:
        return _local_patterns(compiler, candidate.ast, seen)
    compiler.definition_of(candidate)
    if reference in seen:
        return None
    return _local_patterns(compiler, candidate.ast, seen | {reference})


def _local_patterns(compiler: Compiler, node: ast.AST, seen: frozenset[str]) -> list[str] | None:
    match node:
        case ast.String():
            return _string_patterns(compiler, node)
        case ast.Union():
            if not node.types or node.checks or node.mode == "one_of":
                return None
            patterns: list[str] = []
            for member in node.types:
                member_patterns = _patterns(compiler, member, seen)
                if member_patterns is None:
                    return None
                if not member_patterns:
                    return []
                patterns.extend(member_patterns)
            return patterns
        case ast.Number():
            return None if node.checks else [NUMBER_KEY_PATTERN]
        case _:
            raise ValueError(f"Invalid index signature parameter {node.tag}")


def _string_patterns(compiler: Compiler, node: ast.String) -> list[str] | None:
    checks = node.checks
    if not checks:
        return []
    if len(checks) != 1 or not isinstance(checks[0], ast.Filter):
        return None
    dependencies: list[Exactness] = []
    schema = compiler.compile(node, dependencies)
    if not is_exact(dependencies):
        return None
    pattern = schema.get("pattern")
    if (
        schema.get("type") == "string"
        and isinstance(pattern, str)
        and has_only_keywords(schema, _PATTERN_SCHEMA_KEYWORDS)
    ):
        return [pattern]
    return None
