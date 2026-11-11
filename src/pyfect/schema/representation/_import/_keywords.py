"""What single JSON Schema keywords mean: the annotations a schema object
gives, its value types and JSON literals."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Literal as _L
from typing import TypeIs

from pyfect.json_schema import JsonSchema
from pyfect.schema.ast import is_json
from pyfect.schema.issue import Path
from pyfect.schema.representation._from import error_with_path
from pyfect.schema.representation._import import _nodes as N

type PatternMode = _L["error", "ignore", "apply"]

VALUE_TYPES = ("null", "string", "number", "boolean", "object", "array")

TYPE_SPECIFIC_KEYS = (
    "minLength",
    "maxLength",
    "pattern",
    "minimum",
    "maximum",
    "exclusiveMinimum",
    "exclusiveMaximum",
    "multipleOf",
    "properties",
    "required",
    "additionalProperties",
    "patternProperties",
    "propertyNames",
    "minProperties",
    "maxProperties",
    "items",
    "prefixItems",
    "minItems",
    "maxItems",
    "uniqueItems",
)

_STRING_ANNOTATIONS = {
    "title": "title",
    "description": "description",
    "format": "format",
    "contentEncoding": "content_encoding",
    "contentMediaType": "content_media_type",
}
_BOOLEAN_ANNOTATIONS = {"readOnly": "read_only", "writeOnly": "write_only"}

_PYFECT_RESERVED = frozenset(
    {
        "representation",
        "arbitrary_constraint",
        "to_json_schema",
        "to_code",
        "to_equivalence",
        "to_formatter",
        "to_codec",
        "to_codec_json",
        "to_codec_string_tree",
        "to_codec_iso",
        "to_codec_arbitrary",
        "read_only",
        "write_only",
        "content_encoding",
        "content_media_type",
        "content_schema",
        "message_missing_key",
        "message_unexpected_key",
    }
)
"""Effect's reserved annotation keys as pyfect spells them: selecting one would
give an annotation that means something here."""

_ANNOTATION_EXCLUDED_KEYS = frozenset(
    {
        *TYPE_SPECIFIC_KEYS,
        *_STRING_ANNOTATIONS,
        *_BOOLEAN_ANNOTATIONS,
        *_PYFECT_RESERVED,
        "default",
        "examples",
        "contentSchema",
        "arbitraryConstraint",
        "toJsonSchema",
        "toCode",
        "toEquivalence",
        "toFormatter",
        "toCodec",
        "toCodecJson",
        "toCodecStringTree",
        "toCodecIso",
        "toCodecArbitrary",
        "$schema",
        "$id",
        "$ref",
        "$defs",
        "$anchor",
        "$dynamicRef",
        "$dynamicAnchor",
        "$vocabulary",
        "$comment",
        "type",
        "const",
        "enum",
        "allOf",
        "anyOf",
        "oneOf",
        "not",
        "if",
        "then",
        "else",
        "contains",
        "minContains",
        "maxContains",
        "dependentRequired",
        "dependentSchemas",
        "unevaluatedItems",
        "unevaluatedProperties",
        "definitions",
        "dependencies",
        "additionalItems",
        "identifier",
        "expected",
        "message",
        "messageMissingKey",
        "messageUnexpectedKey",
    }
)


def is_object(value: object) -> TypeIs[Mapping[str, object]]:
    return isinstance(value, Mapping)


def is_array(value: object) -> TypeIs[list[object] | tuple[object, ...]]:
    return isinstance(value, (list, tuple))


def is_number(value: object) -> TypeIs[int | float]:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def is_type_name(value: object) -> TypeIs[str]:
    return value == "integer" or (isinstance(value, str) and value in VALUE_TYPES)


def has_type_specific_keywords(schema: JsonSchema) -> bool:
    return any(key in schema for key in TYPE_SPECIFIC_KEYS)


def json_literal(value: object, path: Path) -> N.Node | None:
    """The node of a ``const`` or ``enum`` value; ``None`` for one that is not
    JSON (no constraint)."""
    if value is None:
        return N.Null()
    if isinstance(value, (str, int, float)):
        return N.Literal(literal=value)
    if is_object(value) or is_array(value):
        raise error_with_path('Only primitive values are supported in "const" and "enum".', path)
    return None


def annotations_of(
    schema: JsonSchema, include_annotation_key: Callable[[str], bool] | None
) -> N.ImportedAnnotations:
    annotations: dict[str, object] = {}
    for keyword, key in _STRING_ANNOTATIONS.items():
        if isinstance(schema.get(keyword), str):
            annotations[key] = schema[keyword]
    if "default" in schema:
        annotations["default"] = schema["default"]
    if is_array(schema.get("examples")):
        annotations["examples"] = schema["examples"]
    for keyword, key in _BOOLEAN_ANNOTATIONS.items():
        if isinstance(schema.get(keyword), bool):
            annotations[key] = schema[keyword]
    if "contentSchema" in schema and is_json(schema["contentSchema"]):
        annotations["content_schema"] = schema["contentSchema"]
    return N.ImportedAnnotations(
        annotations=_ordered(annotations) or None,
        custom_annotations=_custom(schema, include_annotation_key),
    )


_ORDER = (
    "title",
    "description",
    "default",
    "examples",
    "read_only",
    "write_only",
    "format",
    "content_encoding",
    "content_media_type",
    "content_schema",
)


def _ordered(annotations: dict[str, object]) -> dict[str, object]:
    return {key: annotations[key] for key in _ORDER if key in annotations}


def _custom(
    schema: JsonSchema, include_annotation_key: Callable[[str], bool] | None
) -> Mapping[str, object] | None:
    if include_annotation_key is None:
        return None
    selected = {
        key: value
        for key, value in schema.items()
        if not key.startswith("~")
        and key not in _ANNOTATION_EXCLUDED_KEYS
        and include_annotation_key(key)
        and is_json(value)
    }
    return selected or None


def strings_of(value: object) -> tuple[str, ...]:
    """The strings of a ``required`` array."""
    return tuple(k for k in value if isinstance(k, str)) if is_array(value) else ()
