"""Draft-07 to Draft 2020-12 and back."""

from __future__ import annotations

from pyfect.json_schema._converter import Context, convert_schema
from pyfect.json_schema._keywords import (
    ANCHOR_REGEXP,
    JSON_SCHEMA_SINGLE_KEYWORDS,
    MISSING,
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
    META_SCHEMA_URI_DRAFT_07,
    META_SCHEMA_URI_DRAFT_2020_12,
    JsonSchema,
    as_array,
    as_object,
    is_array,
    is_meta_schema_uri,
    is_object,
    reject_keyword_collisions,
    unsupported,
)

_PRE_2020_TO_2020_COLLISIONS = (
    "$anchor",
    "$defs",
    "$dynamicAnchor",
    "$dynamicRef",
    "$vocabulary",
    "contentSchema",
    "dependentRequired",
    "dependentSchemas",
    "maxContains",
    "minContains",
    "prefixItems",
    "unevaluatedItems",
    "unevaluatedProperties",
)
DRAFT_07_TO_2020_COLLISIONS = (*_PRE_2020_TO_2020_COLLISIONS, "deprecated")
OPEN_API_30_TO_2020_COLLISIONS = (
    *_PRE_2020_TO_2020_COLLISIONS,
    "$comment",
    "$id",
    "$schema",
    "const",
    "contains",
    "contentEncoding",
    "contentMediaType",
    "else",
    "examples",
    "if",
    "patternProperties",
    "propertyNames",
    "then",
)


def from_draft_07(root: JsonSchema) -> JsonSchema:
    return convert_schema(root, _from_draft_07, track_ids=True, ignore_ref_siblings=True)


def _from_draft_07(source: JsonSchema, context: Context) -> JsonSchema:
    out: JsonSchema = {}
    reference = source.get("$ref")
    if isinstance(reference, str):
        # Draft-07 ignores the siblings of a ``$ref``, but keeps its definitions.
        context.reference(out, reference)
        if "definitions" in source:
            out["$defs"] = context.schema_map(source["definitions"], "definitions", "$defs")
        return out
    reject_keyword_collisions(source, DRAFT_07_TO_2020_COLLISIONS, "Draft 2020-12", "Draft-07")
    for key, value in source.items():
        if convert_subschema_keyword(
            out, key, value, context, single_keywords=JSON_SCHEMA_SINGLE_KEYWORDS
        ):
            continue
        match key:
            case "$schema":
                out[key] = (
                    META_SCHEMA_URI_DRAFT_2020_12
                    if is_meta_schema_uri(value, META_SCHEMA_URI_DRAFT_07)
                    else value
                )
            case "$id":
                _convert_id(out, value)
            case "definitions":
                out["$defs"] = context.schema_map(value, key, "$defs")
            case "dependencies":
                _convert_dependencies(out, value, context)
            case "items" | "additionalItems":
                pass
            case _:
                out[key] = value
    _convert_items(source, out, context)
    return out


def _convert_items(source: JsonSchema, out: JsonSchema, context: Context) -> None:
    if "items" not in source:
        return
    items = source["items"]
    if is_array(items):
        out["prefixItems"] = context.schema_array(items, "items", "prefixItems")
        if "additionalItems" in source:
            out["items"] = context.schema(source["additionalItems"], "additionalItems", "items")
    else:
        out["items"] = context.schema(items, "items")


def _convert_dependencies(out: JsonSchema, value: object, context: Context) -> None:
    if not is_object(value):
        out["dependencies"] = value
        return
    dependent_required: JsonSchema = {}
    dependent_schemas: JsonSchema = {}
    for dependency, dependency_value in as_object(value).items():
        if is_array(dependency_value):
            dependent_required[dependency] = dependency_value
        else:
            dependent_schemas[dependency] = context.schema_at(
                dependency_value, ["dependencies", dependency], ["dependentSchemas", dependency]
            )
    if dependent_required:
        out["dependentRequired"] = dependent_required
    if dependent_schemas:
        out["dependentSchemas"] = dependent_schemas


def _convert_id(out: JsonSchema, value: object) -> None:
    """A Draft-07 ``$id`` with a plain-name fragment is an ``$anchor``."""
    if not isinstance(value, str) or "#" not in value:
        out["$id"] = value
        return
    identifier, _, anchor = value.partition("#")
    if not anchor:
        if identifier:
            out["$id"] = identifier
        return
    if not ANCHOR_REGEXP.fullmatch(anchor):
        raise unsupported("$id", "Draft 2020-12", f'fragment "#{anchor}" is not a valid $anchor')
    if identifier:
        out["$id"] = identifier
    out["$anchor"] = anchor


_DRAFT_07_TARGET_COLLISIONS = ("additionalItems", "definitions", "dependencies")
_NO_EQUIVALENT = frozenset(
    {"$dynamicRef", "$dynamicAnchor", "$vocabulary", "unevaluatedProperties", "unevaluatedItems"}
)

_HANDLED_LATER = frozenset(
    {
        "$ref",
        "$id",
        "$anchor",
        "dependentRequired",
        "dependentSchemas",
        "minContains",
        "maxContains",
        "prefixItems",
        "items",
    }
)


def to_draft_07(source: JsonSchema, context: Context) -> JsonSchema:
    """The Draft-07 adapter for ``Converter``."""
    reject_keyword_collisions(source, _DRAFT_07_TARGET_COLLISIONS, "Draft-07", "Draft 2020-12")
    out: JsonSchema = {}
    for key, value in source.items():
        if convert_subschema_keyword(
            out, key, value, context, single_keywords=JSON_SCHEMA_SINGLE_KEYWORDS
        ):
            continue
        if key in _NO_EQUIVALENT:
            raise unsupported(key, "Draft-07", "the target dialect has no equivalent")
        if key in _HANDLED_LATER:
            continue
        match key:
            case "$schema":
                convert_meta_schema_keyword(
                    out, value, context, META_SCHEMA_URI_DRAFT_07, "Draft-07"
                )
            case "$defs":
                out["definitions"] = context.schema_map(value, key, "definitions")
            case "required" | "enum" if is_array(value) and len(as_array(value)) == 0:
                pass
            case _:
                out[key] = value
    convert_tuple(out, source.get("prefixItems", MISSING), source.get("items", MISSING), context)
    if contains_cardinality(source, out, "Draft-07") and "minContains" in source:
        out["minContains"] = source["minContains"]
    convert_dependencies(source, out, context, "draft-07")
    convert_legacy_id(source, out, "$id", "Draft-07")
    enum = source.get("enum", MISSING)
    if is_array(enum) and len(as_array(enum)) == 0:
        # Draft-07 requires a non-empty ``enum``; nothing matches either way.
        append_all_of(out, {"not": {}})
    convert_reference(out, source.get("$ref", MISSING), context)
    return out
