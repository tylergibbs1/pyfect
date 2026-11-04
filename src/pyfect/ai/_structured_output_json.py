"""What the providers' JSON Schema rewriters share (Effect's
``internal/structured-output.ts``): the codec's JSON Schema document, a
bottom-up walk over a schema's subschemas, and descriptions joined with
``" and "``."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from typing import Literal, TypeIs, cast

from pyfect import schema as S
from pyfect.json_schema import Definitions, Document, JsonSchema, get_reference_key

type Draft2020 = Literal["draft-2020-12"]

_SCHEMA_MAPS = ("properties", "patternProperties")
_SCHEMA_VALUES = ("additionalProperties", "items", "propertyNames")
_SCHEMA_LISTS = ("prefixItems", "allOf", "anyOf", "oneOf")


def document(codec: S.Top) -> Document[Draft2020]:
    """The codec's JSON Schema, objects closed, checks described."""
    return S.to_json_schema_document(codec, generate_descriptions=True, on_excess_property="error")


def resolve_reference(ref: str, definitions: Definitions) -> JsonSchema:
    key = get_reference_key(ref)
    if key is None:
        raise ValueError(f"Unsupported reference {_quote(ref)}")
    if key not in definitions:
        raise ValueError(f"Invalid reference {_quote(ref)}")
    return definitions[key]


def _quote(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


def resolve_root(document: Document[Draft2020]) -> JsonSchema:
    """The root schema, a top-level ``$ref`` replaced by its definition."""
    ref = document.schema.get("$ref")
    return resolve_reference(ref, document.definitions) if isinstance(ref, str) else document.schema


def is_json_schema(value: object) -> TypeIs[JsonSchema]:
    return isinstance(value, dict)


def _walk_member(value: object, visit: Callable[[JsonSchema], JsonSchema]) -> object:
    return walk(value, visit) if is_json_schema(value) else value


def _members(value: object) -> Iterator[JsonSchema]:
    """The schemas among a list's items or a mapping's values."""
    if is_json_schema(value):
        values: Iterable[object] = value.values()
    elif isinstance(value, list):
        values = cast("list[object]", value)
    else:
        values = ()
    for member in values:
        if is_json_schema(member):
            yield member


def walk(schema: JsonSchema, visit: Callable[[JsonSchema], JsonSchema]) -> JsonSchema:
    """``visit`` applied to each subschema, innermost first, then to the
    copy of ``schema`` holding the results."""
    out: JsonSchema = {}
    for key, value in schema.items():
        if key in _SCHEMA_MAPS and is_json_schema(value):
            out[key] = {name: _walk_member(member, visit) for name, member in value.items()}
        elif key in _SCHEMA_VALUES and is_json_schema(value):
            out[key] = walk(value, visit)
        elif key in _SCHEMA_LISTS and isinstance(value, list):
            out[key] = [_walk_member(member, visit) for member in cast("list[object]", value)]
        else:
            out[key] = value
    return visit(out)


def subschemas(schema: JsonSchema) -> Iterator[JsonSchema]:
    """``schema`` and every subschema ``walk`` visits."""
    yield schema
    for key, value in schema.items():
        if key in _SCHEMA_VALUES and is_json_schema(value):
            yield from subschemas(value)
        elif key in _SCHEMA_MAPS or key in _SCHEMA_LISTS:
            for member in _members(value):
                yield from subschemas(member)


def append_description(schema: JsonSchema, description: str) -> None:
    """``description`` joined to the schema's with ``" and "``, unless one
    of its parts already."""
    current = schema.get("description")
    if not isinstance(current, str):
        schema["description"] = description
    elif description not in current.split(" and "):
        schema["description"] = f"{current} and {description}"


def with_definitions(
    root: JsonSchema, definitions: Definitions, rewrite: Callable[[JsonSchema], JsonSchema]
) -> JsonSchema:
    """``root`` with the rewritten definitions under ``$defs``."""
    if definitions:
        root["$defs"] = {name: rewrite(schema) for name, schema in definitions.items()}
    return root
