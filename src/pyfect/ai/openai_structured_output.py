"""Schemas as OpenAI structured output (Effect's
``effect/ai/OpenAiStructuredOutput``).

``to_codec_openai(schema)`` gives the JSON Schema to send to OpenAI's
strict mode and the codec decoding the model's output back into the
schema's values. Shapes strict mode cannot express are sent in the
provider-safe form ``anthropic_structured_output`` describes (tuples as
objects, records as ``[key, value]`` pairs, optional keys as required
nullable ones, ``one_of`` as ``anyOf``). OpenAI takes no ``allOf``: patterns
of its members are merged into one, bounds into the tightest, and the
other keywords kept only when that keeps their meaning. Keywords OpenAI
does not support, or that do not apply to the schema's type, are left out
(an unsupported ``format`` becomes part of the description) and still
checked by the codec. The root must be an object without ``anyOf``.
Compatibility targets standard models; fine-tuned ones take less.
"""

from __future__ import annotations

from pyfect.ai import _structured_output_json as J
from pyfect.ai._openai_all_of import normalize_all_of
from pyfect.ai._structured_output_codec import StructuredOutputCodec, to_codec
from pyfect.json_schema import JsonSchema
from pyfect.schema import Codec

__all__ = ["StructuredOutputCodec", "to_codec_openai"]

_SUPPORTED = frozenset(
    {
        "$ref",
        "type",
        "title",
        "description",
        "enum",
        "anyOf",
        "properties",
        "required",
        "additionalProperties",
        "items",
        "pattern",
        "multipleOf",
        "minimum",
        "exclusiveMinimum",
        "maximum",
        "exclusiveMaximum",
        "minItems",
        "maxItems",
    }
)
_FORMATS = frozenset(
    {"date-time", "time", "date", "duration", "email", "hostname", "ipv4", "ipv6", "uuid"}
)
_TYPED_KEYWORDS: dict[str, frozenset[str]] = {
    "pattern": frozenset({"string"}),
    "format": frozenset({"string"}),
    **dict.fromkeys(
        ("multipleOf", "minimum", "exclusiveMinimum", "maximum", "exclusiveMaximum"),
        frozenset({"number", "integer"}),
    ),
    **dict.fromkeys(("items", "minItems", "maxItems"), frozenset({"array"})),
    **dict.fromkeys(
        ("properties", "patternProperties", "required", "additionalProperties"),
        frozenset({"object"}),
    ),
}
"""The keywords that apply to some types only: dropped from another."""


def to_codec_openai[T, E, RD, RE](
    schema: Codec[T, E, RD, RE], /
) -> StructuredOutputCodec[T, RD, RE]:
    """``schema``'s OpenAI JSON Schema and the codec of its output (see the
    module); raises ``ValueError`` when the root is not an object."""
    codec = to_codec(schema)
    document = J.document(codec)
    root = _rewrite(J.resolve_root(document))
    if root.get("type") != "object" or "anyOf" in root:
        raise ValueError(
            'OpenAiStructuredOutput: Root JSON Schema must have type "object" '
            'and must not use "anyOf"'
        )
    return StructuredOutputCodec(codec, J.with_definitions(root, document.definitions, _rewrite))


def _rewrite(schema: JsonSchema) -> JsonSchema:
    return J.walk(schema, _rewrite_node)


def _applies(key: str, type: object) -> bool:
    return not isinstance(type, str) or type in _TYPED_KEYWORDS.get(key, (type,))


def _rewrite_node(schema: JsonSchema) -> JsonSchema:
    normalized = normalize_all_of(schema)
    type = normalized.get("type")
    out: JsonSchema = {}
    unsupported_format: str | None = None
    for key, value in normalized.items():
        if key == "format":
            if isinstance(value, str) and value in _FORMATS and _applies(key, type):
                out["format"] = value
            elif isinstance(value, str):
                unsupported_format = value
        elif (
            key in _SUPPORTED
            and _applies(key, type)
            and (key != "additionalProperties" or value is False)
        ):
            out[key] = value
    if unsupported_format is not None:
        J.append_description(out, f"a value with a format of {unsupported_format}")
    if (
        out.get("type") == "object"
        and "properties" not in out
        and out.get("additionalProperties") is False
    ):
        out["properties"] = {}
    return out
