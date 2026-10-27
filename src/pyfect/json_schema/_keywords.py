"""Keyword conversions shared by the dialect adapters."""

from __future__ import annotations

import re
from collections.abc import Mapping, Set
from typing import Literal, cast

from pyfect.json_schema._converter import Context
from pyfect.json_schema._model import (
    META_SCHEMA_URI_DRAFT_2020_12,
    JsonSchema,
    as_array,
    as_object,
    is_array,
    is_meta_schema_uri,
    is_number,
    is_object,
    unsupported,
)

SCHEMA_MAP_KEYWORDS = frozenset({"properties", "patternProperties"})
SCHEMA_ARRAY_KEYWORDS = frozenset({"allOf", "anyOf", "oneOf"})
JSON_SCHEMA_SINGLE_KEYWORDS = frozenset(
    {
        "not",
        "additionalProperties",
        "propertyNames",
        "contains",
        "if",
        "then",
        "else",
        "contentSchema",
    }
)

ANCHOR_REGEXP = re.compile(r"[A-Za-z_][-A-Za-z0-9._]*")
LEGACY_ID_FRAGMENT_REGEXP = re.compile(r"[A-Za-z][-A-Za-z0-9._:]*")

MISSING: object = object()
"""A keyword the schema does not have (JavaScript's ``undefined``)."""


def convert_subschema_keyword(
    out: JsonSchema,
    key: str,
    value: object,
    context: Context,
    *,
    single_keywords: Set[str],
    map_keywords: Set[str] = SCHEMA_MAP_KEYWORDS,
) -> bool:
    """Convert ``key`` into ``out`` when it holds subschemas; ``False``
    when it does not."""
    if key in map_keywords:
        out[key] = context.schema_map(value, key)
    elif key in SCHEMA_ARRAY_KEYWORDS:
        out[key] = context.schema_array(value, key)
    elif key in single_keywords:
        out[key] = context.schema(value, key)
    else:
        return False
    return True


def append_all_of(out: JsonSchema, schema: JsonSchema) -> None:
    all_of = out.get("allOf")
    if isinstance(all_of, list):
        cast("list[object]", all_of).append(schema)
    else:
        out["allOf"] = [schema]


def all_of_length(out: JsonSchema) -> int:
    all_of = out.get("allOf")
    return len(as_array(all_of)) if is_array(all_of) else 0


def convert_meta_schema_keyword(
    out: JsonSchema, value: object, context: Context, target_uri: str, target_dialect: str
) -> None:
    if context.is_document_root:
        out["$schema"] = (
            target_uri if is_meta_schema_uri(value, META_SCHEMA_URI_DRAFT_2020_12) else value
        )
    elif not is_meta_schema_uri(value, META_SCHEMA_URI_DRAFT_2020_12):
        raise unsupported(
            "$schema", target_dialect, "an embedded resource cannot declare a different dialect"
        )


def convert_tuple(out: JsonSchema, prefix_items: object, items: object, context: Context) -> None:
    """Draft 2020-12's ``prefixItems`` / ``items`` as the legacy ``items`` /
    ``additionalItems``."""
    if prefix_items is MISSING:
        if items is not MISSING:
            out["items"] = context.schema(items, "items")
        return
    out["items"] = context.schema_array(prefix_items, "prefixItems", "items")
    if items is not MISSING:
        out["additionalItems"] = context.schema(items, "items", "additionalItems")


def convert_reference(out: JsonSchema, reference: object, context: Context) -> None:
    """A legacy dialect ignores ``$ref`` siblings, so a ``$ref`` next to other
    keywords moves into ``allOf``."""
    if reference is MISSING:
        return
    if isinstance(reference, str) and len(out) > 0:
        reference_schema: JsonSchema = {}
        context.reference(reference_schema, reference)
        append_all_of(out, reference_schema)
    else:
        context.reference(out, reference)


def convert_dependencies(
    source: JsonSchema,
    out: JsonSchema,
    context: Context,
    target_dialect: Literal["draft-04", "draft-07"],
) -> None:
    """``dependentRequired`` and ``dependentSchemas`` as ``dependencies``."""
    required_map = source.get("dependentRequired")
    schemas_map = source.get("dependentSchemas")
    dependent_required: Mapping[str, object] | None = (
        as_object(required_map) if is_object(required_map) else None
    )
    dependent_schemas: Mapping[str, object] | None = (
        as_object(schemas_map) if is_object(schemas_map) else None
    )
    if dependent_required is None and dependent_schemas is None:
        return
    required_by: Mapping[str, object] = dependent_required or {}
    schemas_by: Mapping[str, object] = dependent_schemas or {}
    dependencies: JsonSchema = {}
    keys: dict[str, None] = dict.fromkeys([*required_by, *schemas_by])
    for key in keys:
        required = required_by.get(key, MISSING)
        dependency = schemas_by.get(key, MISSING)
        omit_required = (
            target_dialect == "draft-04" and is_array(required) and len(as_array(required)) == 0
        )
        if dependency is MISSING:
            if not omit_required:
                dependencies[key] = required
        elif required is MISSING or omit_required:
            dependencies[key] = context.schema_at(
                dependency, ["dependentSchemas", key], ["dependencies", key]
            )
        else:
            dependencies[key] = {
                "allOf": [
                    context.schema_at(
                        dependency, ["dependentSchemas", key], ["dependencies", key, "allOf", "0"]
                    ),
                    {"required": required},
                ]
            }
    if dependencies:
        out["dependencies"] = dependencies


def convert_legacy_id(
    source: JsonSchema, out: JsonSchema, target_key: Literal["$id", "id"], dialect: str
) -> None:
    """``$id`` and ``$anchor`` as one legacy id (``#anchor`` for an anchor)."""
    identifier = source.get("$id", MISSING)
    anchor = source.get("$anchor", MISSING)
    if anchor is MISSING:
        if identifier is not MISSING:
            out[target_key] = identifier
        return
    if not isinstance(anchor, str) or not ANCHOR_REGEXP.fullmatch(anchor):
        raise unsupported("$anchor", dialect, "the anchor is not valid")
    if not LEGACY_ID_FRAGMENT_REGEXP.fullmatch(anchor):
        raise unsupported(
            "$anchor",
            dialect,
            "the anchor cannot be represented as a plain-name fragment identifier",
        )
    if identifier is not MISSING:
        raise unsupported("$anchor", dialect, "it cannot be combined with the schema $id")
    out[target_key] = f"#{anchor}"


def contains_cardinality(source: JsonSchema, out: JsonSchema, dialect: str) -> bool:
    """Copy ``minContains`` / ``maxContains`` when there is no ``contains``
    (they are inert then); with ``contains``, only the default cardinality
    can be kept. ``True`` when ``contains`` is there."""
    if "contains" not in source:
        for key in ("minContains", "maxContains"):
            if key in source:
                out[key] = source[key]
        return False
    min_contains = source.get("minContains", MISSING)
    default_min = min_contains is MISSING or (is_number(min_contains) and min_contains == 1)
    if not default_min or "maxContains" in source:
        raise unsupported(
            "minContains/maxContains", dialect, "contains cardinality cannot be represented"
        )
    return True
