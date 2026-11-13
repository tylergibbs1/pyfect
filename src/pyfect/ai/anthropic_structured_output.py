"""Schemas as Anthropic structured output (Effect's
``effect/ai/AnthropicStructuredOutput``).

``to_codec_anthropic(schema)`` gives the JSON Schema to send to Anthropic
and the codec decoding the model's output back into the schema's values.
Shapes strict mode cannot express are sent in a provider-safe form the
codec decodes: a tuple as an object with keys ``"0"``, ``"1"``, ... (its
rest under ``"__rest__"``), an object with index signatures as an array of
``[key, value]`` pairs, an optional key as a required nullable one, a
``one_of`` union as ``anyOf``. Keywords Anthropic does not support are left
out of the JSON Schema (an unsupported ``format`` becomes part of the
description) and still checked by the codec. A recursive schema raises.
"""

from __future__ import annotations

from typing import cast

from pyfect.ai import _structured_output_json as J
from pyfect.ai._structured_output_codec import StructuredOutputCodec, to_codec
from pyfect.json_schema import Definitions, JsonSchema
from pyfect.schema import Codec

__all__ = ["StructuredOutputCodec", "to_codec_anthropic"]

_SUPPORTED = frozenset(
    {
        "$ref",
        "type",
        "title",
        "description",
        "enum",
        "const",
        "anyOf",
        "allOf",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "pattern",
    }
)
_FORMATS = frozenset(
    {"date-time", "time", "date", "duration", "email", "hostname", "uri", "ipv4", "ipv6", "uuid"}
)


def to_codec_anthropic[T, E, RD, RE](
    schema: Codec[T, E, RD, RE], /
) -> StructuredOutputCodec[T, RD, RE]:
    """``schema``'s Anthropic JSON Schema and the codec of its output (see
    the module); raises ``ValueError`` on a recursive schema."""
    codec = to_codec(schema)
    document = J.document(codec)
    if _has_reference_cycle(document.schema, document.definitions):
        raise ValueError("AnthropicStructuredOutput: Recursive schemas are not supported")
    root = _rewrite(J.resolve_root(document))
    return StructuredOutputCodec(codec, J.with_definitions(root, document.definitions, _rewrite))


def _has_reference_cycle(root: JsonSchema, definitions: Definitions) -> bool:
    return _reaches_cycle(root, root, definitions, set(), set())


def _reaches_cycle(
    schema: JsonSchema,
    root: JsonSchema,
    definitions: Definitions,
    visiting: set[int],
    visited: set[int],
) -> bool:
    if id(schema) in visiting:
        return True
    if id(schema) in visited:
        return False
    visiting.add(id(schema))
    cycle = False
    for node in J.subschemas(schema):
        ref = node.get("$ref")
        if isinstance(ref, str):
            target = root if ref == "#" else J.resolve_reference(ref, definitions)
            if _reaches_cycle(target, root, definitions, visiting, visited):
                cycle = True
                break
    visiting.discard(id(schema))
    visited.add(id(schema))
    return cycle


def _rewrite(schema: JsonSchema) -> JsonSchema:
    return J.walk(schema, _rewrite_node)


def _rewrite_node(schema: JsonSchema) -> JsonSchema:
    normalized = _hoist_all_of_descriptions(schema)
    out: JsonSchema = {}
    unsupported_format: str | None = None
    for key, value in normalized.items():
        if key == "format":
            if (
                isinstance(value, str)
                and value in _FORMATS
                and normalized.get("type") in (None, "string")
            ):
                out["format"] = value
            elif isinstance(value, str):
                unsupported_format = value
        elif key in _SUPPORTED and (key != "additionalProperties" or value is False):
            out[key] = value
    if unsupported_format is not None:
        J.append_description(out, f"a value with a format of {unsupported_format}")
    return out


def _hoist_all_of_descriptions(schema: JsonSchema) -> JsonSchema:
    """``allOf`` members' descriptions joined to the schema's, their first
    ``format`` and ``title`` moved up when the schema has none."""
    members_in = schema.get("allOf")
    if not isinstance(members_in, list):
        return schema
    out: JsonSchema = {key: value for key, value in schema.items() if key != "allOf"}
    members: list[JsonSchema] = []
    for member in cast("list[object]", members_in):
        if not J.is_json_schema(member):
            continue
        rest: JsonSchema = {
            k: v for k, v in member.items() if k not in ("description", "format", "title")
        }
        if schema.get("type") not in (None, "string"):
            rest.pop("pattern", None)
        description, format, title = (member.get(k) for k in ("description", "format", "title"))
        if isinstance(description, str):
            J.append_description(out, description)
        if "format" not in out and isinstance(format, str):
            out["format"] = format
        if "title" not in out and isinstance(title, str):
            out["title"] = title
        if rest:
            members.append(rest)
    if members:
        out["allOf"] = members
    return out
