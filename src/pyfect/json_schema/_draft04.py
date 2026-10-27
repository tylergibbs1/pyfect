"""Draft 2020-12 to Draft-04: conditionals, ``contains`` and ``const`` are
lowered to the boolean keywords Draft-04 has."""

from __future__ import annotations

from collections.abc import Sequence

from pyfect.json_schema._converter import Context
from pyfect.json_schema._keywords import (
    MISSING,
    all_of_length,
    append_all_of,
    contains_cardinality,
    convert_dependencies,
    convert_legacy_id,
    convert_meta_schema_keyword,
    convert_reference,
    convert_subschema_keyword,
    convert_tuple,
)
from pyfect.json_schema._model import (
    META_SCHEMA_URI_DRAFT_04,
    JsonSchema,
    as_array,
    as_object,
    is_array,
    is_number,
    is_object,
    reject_keyword_collisions,
    subschema_kind,
    unsupported,
)

_SINGLE_KEYWORDS = frozenset({"not", "additionalProperties", "contentSchema"})
_TARGET_COLLISIONS = ("additionalItems", "definitions", "dependencies", "id")
_NO_EQUIVALENT = frozenset(
    {
        "$dynamicRef",
        "$dynamicAnchor",
        "$vocabulary",
        "unevaluatedProperties",
        "unevaluatedItems",
        "propertyNames",
    }
)
# Converted after the walk over the keywords (or dropped).
_LATER = frozenset(
    {
        "$id",
        "$anchor",
        "dependentRequired",
        "dependentSchemas",
        "contains",
        "minContains",
        "maxContains",
        "if",
        "then",
        "else",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
    }
)


_AFTER_LOOP = frozenset({"$ref", "prefixItems", "items", "const"})


def to_draft_04(source: JsonSchema, context: Context) -> JsonSchema:
    """The Draft-04 adapter for ``Converter``."""
    reject_keyword_collisions(source, _TARGET_COLLISIONS, "Draft-04", "Draft 2020-12")
    out: JsonSchema = {}
    for key, value in source.items():
        if convert_subschema_keyword(out, key, value, context, single_keywords=_SINGLE_KEYWORDS):
            continue
        if key in _NO_EQUIVALENT:
            raise unsupported(key, "Draft-04", "the target dialect has no equivalent")
        if key in _LATER or key in _AFTER_LOOP:
            continue
        match key:
            case "$schema":
                convert_meta_schema_keyword(
                    out, value, context, META_SCHEMA_URI_DRAFT_04, "Draft-04"
                )
            case "$defs":
                out["definitions"] = context.schema_map(value, key, "definitions")
            case "required" if is_array(value) and len(as_array(value)) == 0:
                pass
            case _:
                out[key] = value
    convert_tuple(out, source.get("prefixItems", MISSING), source.get("items", MISSING), context)
    _convert_exclusive_bound(source, out, "minimum", "exclusiveMinimum")
    _convert_exclusive_bound(source, out, "maximum", "exclusiveMaximum")
    convert_dependencies(source, out, context, "draft-04")
    convert_legacy_id(source, out, "id", "Draft-04")
    _convert_conditionals(source, out, context)
    _convert_contains(source, out, context)
    if "const" in source:
        if "enum" in source:
            append_all_of(out, {"enum": [source["const"]]})
        else:
            out["enum"] = [source["const"]]
    convert_reference(out, source.get("$ref", MISSING), context)
    return out


def _convert_conditionals(source: JsonSchema, out: JsonSchema, context: Context) -> None:
    has_if, has_then, has_else = ("if" in source, "then" in source, "else" in source)
    if not has_if or (not has_then and not has_else):
        for key in ("if", "then", "else"):
            if key in source:
                out[key] = context.schema(source[key], key)
        return
    base = ("allOf", str(all_of_length(out)), "anyOf")

    def branch(key: str, target_path: Sequence[str]) -> object:
        return context.schema_at(source[key], [key], [*base, *target_path])

    conditional: JsonSchema
    if has_then and has_else:
        if _has_schema_identifier(source["if"]):
            raise unsupported(
                "if", "Draft-04", "lowering both branches would duplicate a schema identifier"
            )
        # (if AND then) OR ((NOT if) AND else)
        conditional = {
            "anyOf": [
                {"allOf": [branch("if", ["0", "allOf", "0"]), branch("then", ["0", "allOf", "1"])]},
                {
                    "allOf": [
                        {"not": branch("if", ["1", "allOf", "0", "not"])},
                        branch("else", ["1", "allOf", "1"]),
                    ]
                },
            ]
        }
    elif has_then:
        # (NOT if) OR then
        conditional = {"anyOf": [{"not": branch("if", ["0", "not"])}, branch("then", ["1"])]}
    else:
        # if OR else
        conditional = {"anyOf": [branch("if", ["0"]), branch("else", ["1"])]}
    append_all_of(out, conditional)


def _has_schema_identifier(node: object) -> bool:
    if not is_object(node):
        return False
    schema = as_object(node)
    if "$id" in schema or "$anchor" in schema:
        return True
    for key, value in schema.items():
        match subschema_kind(key):
            case "map":
                if is_object(value) and any(map(_has_schema_identifier, as_object(value).values())):
                    return True
            case "array":
                if is_array(value) and any(map(_has_schema_identifier, as_array(value))):
                    return True
            case "schema":
                if _has_schema_identifier(value):
                    return True
            case None:
                pass
    return False


def _convert_contains(source: JsonSchema, out: JsonSchema, context: Context) -> None:
    if not contains_cardinality(source, out, "Draft-04"):
        return
    index = str(all_of_length(out))
    contains = context.schema_at(
        source["contains"], ["contains"], ["allOf", index, "anyOf", "1", "not", "items", "not"]
    )
    append_all_of(
        out, {"anyOf": [{"not": {"type": "array"}}, {"not": {"items": {"not": contains}}}]}
    )


def _convert_exclusive_bound(
    source: JsonSchema, out: JsonSchema, bound_key: str, exclusive_key: str
) -> None:
    """Draft 2020-12's numeric ``exclusiveMinimum`` as Draft-04's boolean
    flag on ``minimum`` (the stricter of the two bounds wins)."""
    bound = source.get(bound_key, MISSING)
    exclusive = source.get(exclusive_key, MISSING)
    if is_number(exclusive):
        is_bound_stricter = is_number(bound) and (
            bound > exclusive if bound_key == "minimum" else bound < exclusive
        )
        if is_bound_stricter:
            out[bound_key] = bound
        else:
            out[bound_key] = exclusive
            out[exclusive_key] = True
    elif bound is not MISSING:
        out[bound_key] = bound
