"""OpenAPI 3.0 and 3.1 schemas to Draft 2020-12, and shared definitions to
``components.schemas``."""

from __future__ import annotations

from typing import Literal, cast

from pyfect._js import js_sort_key
from pyfect.json_pointer import format_uri_fragment, parse_uri_fragment
from pyfect.json_schema._converter import Context, convert_schema
from pyfect.json_schema._draft07 import OPEN_API_30_TO_2020_COLLISIONS
from pyfect.json_schema._keywords import MISSING, convert_subschema_keyword
from pyfect.json_schema._model import (
    META_SCHEMA_URI_DRAFT_2020_12,
    META_SCHEMA_URI_OPEN_API_3_1,
    VALID_OPEN_API_COMPONENTS_SCHEMAS_KEY_REGEXP,
    Definitions,
    JsonSchema,
    MultiDocument,
    as_array,
    as_object,
    creates_resource,
    is_array,
    is_meta_schema_uri,
    is_number,
    is_object,
    reject_keyword_collisions,
    rewrite_schema_ref,
    sanitize_open_api_components_schemas_key,
    transform_schema,
    unsupported,
)

_SCHEMA_MAP_KEYWORDS = frozenset({"properties"})
_SCHEMA_SINGLE_KEYWORDS = frozenset({"not", "items", "additionalProperties"})
_OPEN_API_31_TARGET_COLLISIONS = ("example", "discriminator", "xml", "externalDocs")


def rewrite_components_reference(reference: str) -> str:
    """``#/components/schemas/X`` as ``#/$defs/X``."""
    path = parse_uri_fragment(reference) if reference.startswith("#") else None
    if path is not None and path[:2] == ["components", "schemas"]:
        return format_uri_fragment(["$defs", *path[2:]])
    return reference


def from_open_api_3_1(js: JsonSchema) -> JsonSchema:
    is_root_resource = creates_resource(js.get("$id"))

    def transform(schema: JsonSchema, in_embedded_resource: bool) -> None:
        if not is_root_resource and not in_embedded_resource:
            rewrite_schema_ref(schema, lambda reference, _: rewrite_components_reference(reference))
        if is_meta_schema_uri(schema.get("$schema"), META_SCHEMA_URI_OPEN_API_3_1):
            schema["$schema"] = META_SCHEMA_URI_DRAFT_2020_12
        if "example" in schema:
            examples = schema.get("examples", MISSING)
            if examples is MISSING or is_array(examples):
                previous = [] if examples is MISSING else list(as_array(examples))
                schema["examples"] = [schema["example"], *previous]
                del schema["example"]

    return cast("JsonSchema", transform_schema(js, transform))


def from_open_api_3_0(root: JsonSchema) -> JsonSchema:
    return convert_schema(root, _from_open_api_3_0)


def _from_open_api_3_0(source: JsonSchema, context: Context) -> JsonSchema:
    out: JsonSchema = {}
    reference = source.get("$ref")
    if isinstance(reference, str):
        context.reference(out, rewrite_components_reference(reference))
        return out
    reject_keyword_collisions(
        source, OPEN_API_30_TO_2020_COLLISIONS, "Draft 2020-12", "OpenAPI 3.0"
    )
    nullable_all_of = _is_nullable_all_of(source)
    for key, value in source.items():
        if nullable_all_of and key == "allOf":
            out["anyOf"] = [
                context.schema_at(as_array(value)[0], ["allOf", "0"], ["anyOf", "0"]),
                {"type": "null"},
            ]
            continue
        if convert_subschema_keyword(
            out,
            key,
            value,
            context,
            single_keywords=_SCHEMA_SINGLE_KEYWORDS,
            map_keywords=_SCHEMA_MAP_KEYWORDS,
        ):
            continue
        match key:
            case "example":
                out["examples"] = [value]
            case "nullable" | "exclusiveMinimum" | "exclusiveMaximum":
                pass
            case _:
                out[key] = value
    _convert_exclusive_bound(source, out, "minimum", "exclusiveMinimum")
    _convert_exclusive_bound(source, out, "maximum", "exclusiveMaximum")
    schema_type = source.get("type")
    if source.get("nullable") is True and isinstance(schema_type, str):
        out["type"] = [schema_type, "null"]
    return out


def _is_nullable_all_of(source: JsonSchema) -> bool:
    all_of = source.get("allOf")
    return (
        source.get("nullable") is True
        and not isinstance(source.get("type"), str)
        and "anyOf" not in source
        and is_array(all_of)
        and len(as_array(all_of)) == 1
    )


def _convert_exclusive_bound(
    source: JsonSchema, out: JsonSchema, bound_key: str, exclusive_key: str
) -> None:
    """OpenAPI 3.0's boolean ``exclusiveMinimum`` as the numeric keyword."""
    exclusive = source.get(exclusive_key, MISSING)
    if not isinstance(exclusive, bool):
        if exclusive is not MISSING:
            out[exclusive_key] = exclusive
        return
    if exclusive and is_number(source.get(bound_key)):
        out[exclusive_key] = source[bound_key]
        del out[bound_key]


def _component_keys(definition_keys: list[str]) -> dict[str, str]:
    """The ``components.schemas`` key of each definition whose key OpenAPI
    forbids: sanitized, then suffixed ``_1``, ``_2``... on a collision."""
    key_map: dict[str, str] = {}
    used = {
        key for key in definition_keys if VALID_OPEN_API_COMPONENTS_SCHEMAS_KEY_REGEXP.match(key)
    }
    invalid = [
        (key, sanitize_open_api_components_schemas_key(key))
        for key in sorted((k for k in definition_keys if k not in used), key=js_sort_key)
    ]
    for key, base in invalid:
        if base not in used:
            used.add(base)
            key_map[key] = base
    for key, base in invalid:
        if key in key_map:
            continue
        suffix = 1
        while f"{base}_{suffix}" in used:
            suffix += 1
        candidate = f"{base}_{suffix}"
        used.add(candidate)
        key_map[key] = candidate
    return key_map


def to_open_api_3_1(
    multi_document: MultiDocument[Literal["draft-2020-12"]],
) -> MultiDocument[Literal["openapi-3.1"]]:
    definitions = multi_document.definitions
    key_map = _component_keys(list(definitions))

    def rewrite(schema: JsonSchema, reject_shared_definition_refs: bool = False) -> JsonSchema:
        is_root_resource = creates_resource(schema.get("$id"))
        local = schema.get("$defs")
        local_definitions = as_object(local) if is_object(local) else None

        def transform(node: JsonSchema, in_embedded_resource: bool) -> None:
            reject_keyword_collisions(
                node, _OPEN_API_31_TARGET_COLLISIONS, "OpenAPI 3.1", "Draft 2020-12"
            )

            def rewrite_ref(reference: str, keyword: str) -> str:
                path = parse_uri_fragment(reference) if reference.startswith("#") else None
                if path is None or len(path) < 2 or path[0] != "$defs":
                    return reference
                key = path[1]
                if is_root_resource:
                    if (
                        reject_shared_definition_refs
                        and not in_embedded_resource
                        and key in definitions
                        and (local_definitions is None or key not in local_definitions)
                    ):
                        raise unsupported(
                            keyword,
                            "OpenAPI 3.1",
                            "a schema resource cannot reference the shared definitions pool",
                        )
                    return reference
                if in_embedded_resource:
                    return reference
                return format_uri_fragment(
                    ["components", "schemas", key_map.get(key, key), *path[2:]]
                )

            rewrite_schema_ref(node, rewrite_ref)

        return cast("JsonSchema", transform_schema(schema, transform))

    schemas = tuple(rewrite(schema, True) for schema in multi_document.schemas)
    out: Definitions = {key_map.get(key, key): rewrite(value) for key, value in definitions.items()}
    return MultiDocument("openapi-3.1", schemas, out)
