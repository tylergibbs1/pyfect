"""The JSON Schema document types, meta-schema URIs and the walkers shared by
the dialect converters."""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Generic, Literal, TypeIs, TypeVar, cast

from pyfect.json_pointer import parse_uri_fragment

type JsonSchema = dict[str, object]
"""One JSON Schema node: any keyword to any value."""

type Definitions = dict[str, JsonSchema]
"""Named schemas, referenced as ``#/$defs/<name>`` (Draft 2020-12),
``#/definitions/<name>`` (Draft-04 and Draft-07) or
``#/components/schemas/<name>`` (OpenAPI)."""

type Dialect = Literal["draft-04", "draft-07", "draft-2020-12", "openapi-3.1", "openapi-3.0"]

type Type = Literal["string", "number", "boolean", "array", "object", "null", "integer"]
"""The JSON Schema ``type`` names."""


D_co = TypeVar("D_co", bound=Dialect, covariant=True)


@dataclass(frozen=True, slots=True)
class Document(Generic[D_co]):
    """A root schema (without its definitions) and the definitions it
    references, in one dialect."""

    dialect: D_co
    schema: JsonSchema
    definitions: Definitions


@dataclass(frozen=True, slots=True)
class MultiDocument(Generic[D_co]):
    """Several root schemas sharing one set of definitions."""

    dialect: D_co
    schemas: tuple[JsonSchema, ...]
    definitions: Definitions


META_SCHEMA_URI_DRAFT_04 = "http://json-schema.org/draft-04/schema#"
META_SCHEMA_URI_DRAFT_07 = "http://json-schema.org/draft-07/schema#"
META_SCHEMA_URI_DRAFT_2020_12 = "https://json-schema.org/draft/2020-12/schema"
META_SCHEMA_URI_OPEN_API_3_1 = "https://spec.openapis.org/oas/3.1/dialect/base"

VALID_OPEN_API_COMPONENTS_SCHEMAS_KEY_REGEXP = re.compile(r"^[a-zA-Z0-9.\-_]+\Z")
"""The keys OpenAPI allows under ``components.schemas``."""


def is_object(value: object) -> bool:
    """A JSON object (Effect's ``Predicate.isObject``)."""
    return isinstance(value, Mapping)


def as_object(value: object) -> Mapping[str, object]:
    return cast("Mapping[str, object]", value)


def is_array(value: object) -> bool:
    return isinstance(value, (list, tuple))


def as_array(value: object) -> Sequence[object]:
    return cast("Sequence[object]", value)


def is_number(value: object) -> TypeIs[int | float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def is_meta_schema_uri(value: object, uri: str) -> bool:
    """``value`` is ``uri``, with or without its trailing empty fragment."""
    return value in (uri, uri[:-1] if uri.endswith("#") else f"{uri}#")


def creates_resource(identifier: object) -> bool:
    """An ``$id`` that starts a new schema resource (not a bare fragment)."""
    return isinstance(identifier, str) and len(identifier) > 0 and identifier[0] != "#"


def unsupported(keyword: str, dialect: str, details: str) -> ValueError:
    return ValueError(f'Cannot convert JSON Schema keyword "{keyword}" to {dialect}: {details}')


def reject_keyword_collisions(
    source: Mapping[str, object], keywords: Sequence[str], target: str, origin: str
) -> None:
    """Raise for the first keyword of ``keywords`` in ``source``: inert in
    the source dialect, it would gain a meaning in the target."""
    for keyword in keywords:
        if keyword in source:
            raise unsupported(
                keyword,
                target,
                f"it is not active in {origin} but would become active in the target",
            )


type SubschemaKind = Literal["schema", "map", "array"]

_SUBSCHEMA_KINDS: dict[str, SubschemaKind] = {
    "$defs": "map",
    "properties": "map",
    "patternProperties": "map",
    "dependentSchemas": "map",
    "allOf": "array",
    "anyOf": "array",
    "oneOf": "array",
    "prefixItems": "array",
    "not": "schema",
    "additionalProperties": "schema",
    "propertyNames": "schema",
    "unevaluatedProperties": "schema",
    "items": "schema",
    "contains": "schema",
    "unevaluatedItems": "schema",
    "if": "schema",
    "then": "schema",
    "else": "schema",
    "contentSchema": "schema",
}


def subschema_kind(keyword: str) -> SubschemaKind | None:
    """How a Draft 2020-12 keyword holds subschemas, if it does."""
    return _SUBSCHEMA_KINDS.get(keyword)


def map_object(
    value: Mapping[str, object], f: Callable[[object, str], object]
) -> dict[str, object]:
    return {key: f(item, key) for key, item in value.items()}


def transform_schema(node: object, transform: Callable[[JsonSchema, bool], None]) -> object:
    """A copy of a Draft 2020-12 schema with ``transform(schema,
    in_embedded_resource)`` run on every schema node, children first."""

    return _transform_node(transform, node, False, True)


def _transform_node(
    transform: Callable[[JsonSchema, bool], None], node: object, inherited: bool, is_root: bool
) -> object:
    if not is_object(node):
        return node
    source = as_object(node)
    in_embedded = inherited or (not is_root and creates_resource(source.get("$id")))
    out: JsonSchema = {}
    for key, value in source.items():
        match subschema_kind(key):
            case "map":
                out[key] = (
                    map_object(
                        as_object(value),
                        lambda item, _: _transform_node(transform, item, in_embedded, False),
                    )
                    if is_object(value)
                    else value
                )
            case "array":
                out[key] = (
                    [
                        _transform_node(transform, item, in_embedded, False)
                        for item in as_array(value)
                    ]
                    if is_array(value)
                    else value
                )
            case "schema":
                out[key] = _transform_node(transform, value, in_embedded, False)
            case None:
                out[key] = value
    transform(out, in_embedded)
    return out


def rewrite_schema_ref(schema: JsonSchema, rewrite: Callable[[str, str], str]) -> None:
    """Rewrite ``schema``'s ``$ref`` and ``$dynamicRef`` in place;
    ``rewrite`` gets the reference and the keyword."""
    for keyword in ("$ref", "$dynamicRef"):
        reference = schema.get(keyword)
        if isinstance(reference, str):
            schema[keyword] = rewrite(reference, keyword)


def rewrite_refs(schema: Mapping[str, object], rewrite: Callable[[str], str]) -> JsonSchema:
    """A copy of ``schema`` with every ``$ref`` and ``$dynamicRef`` replaced
    by ``rewrite(ref)``."""
    return cast(
        "JsonSchema",
        transform_schema(schema, lambda node, _: rewrite_schema_ref(node, lambda r, _: rewrite(r))),
    )


def sanitize_open_api_components_schemas_key(key: str) -> str:
    """``key`` with every character OpenAPI forbids in a
    ``components.schemas`` key replaced by ``_`` (``"_"`` for ``""``)."""
    return re.sub(r"[^a-zA-Z0-9._-]", "_", key) if key else "_"


def get_reference_key(ref: str) -> str | None:
    """The definition name of a ``#/$defs/<name>`` reference, else ``None``."""
    path = parse_uri_fragment(ref) if ref.startswith("#") else None
    return path[1] if path is not None and len(path) == 2 and path[0] == "$defs" else None
