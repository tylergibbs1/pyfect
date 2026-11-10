"""Ports of Effect's ``schema/toJsonSchemaDocument.test.ts``. Each test's docstring
is the Effect test title, prefixed by its ``describe`` blocks. The pattern and
string-length titles are in ``test_to_json_schema_document_patterns.py``, the
"fromJsonString" ones in ``test_to_json_schema_document_content.py``.

``assertJsonSchemaDocument`` is ``_check`` (``on_excess_property="error"``
unless a test says otherwise); its Ajv meta-schema validation is left out.

Python differs in a few places, each kept as the expected value:
- ``len`` of a ``str`` counts code points, as ``minLength`` does, so string
  length bounds are exact (Effect loosens ``minLength`` by half for UTF-16).
- An ``int`` record key is read from its digits, so ``Record(Int, ...)``
  selects keys by an exact pattern.
- A ``timedelta`` cannot be infinite: ``Duration`` has no infinity forms.
- ``is_pattern`` takes a Python ``re`` pattern, which JSON Schema cannot
  carry: it is left out. ``is_ecma_pattern`` is Effect's ``isPattern``.
- ``Schema.Date`` is ``S.DateTimeUtc``, ``MutableJson`` is ``S.Json`` and
  ``UndefinedOr`` is ``NullOr`` (section 4).

Not ported here:
- Symbols, ``undefined``, ``void`` and bigint literals (no Python
  counterpart): "rejects symbol property names", "Record(Symbol, Finite)",
  "Symbol", "UniqueSymbol", "Literal / bigint".
- Ported in ``test_schema_errors.py`` ("Declaration / Error"),
  ``test_schema_struct_with_rest.py`` (the ``StructWithRest`` titles) and
  ``test_schema_object_keyword.py`` ("Void", "Undefined", "ObjectKeyword").
- "rejects non-finite cardinality bounds": a size check takes an ``int``, so
  pyright rejects ``NaN`` and the infinities.
- Keys optional on the decoded side only (``optionalKey(...)`` then
  ``encodeTo``) are in ``tests/_effect_title_omissions.py``.
"""

import enum
from collections.abc import Callable
from typing import Any, Literal, Never, NotRequired, TypedDict

import pytest

from pyfect import effect as fx
from pyfect import schema as S
from pyfect.json_schema import JsonSchema
from pyfect.option import Option, Some
from pyfect.schema import getter as G
from pyfect.schema import transformation as T

_MAX_SAFE = 2**53 - 1
_MIN_SAFE = -_MAX_SAFE
_INT: dict[str, object] = {"type": "integer", "minimum": _MIN_SAFE, "maximum": _MAX_SAFE}

_NUMBER_KEY = "^(?:[+-]?(?:\\d+(?:\\.\\d+)?|\\.\\d+)(?:[Ee][+-]?\\d+)?|Infinity|-Infinity|NaN)$"
_NUMBER: JsonSchema = {
    "anyOf": [{"type": "number"}, {"type": "string", "enum": ["Infinity", "-Infinity", "NaN"]}]
}


def _check(
    schema: S.Top,
    expected: JsonSchema,
    definitions: dict[str, JsonSchema] | None = None,
    *,
    on_excess_property: S.OnExcessProperty = "error",
    generate_descriptions: bool = False,
    include_annotation_key: Callable[[str], bool] | None = None,
) -> None:
    document = S.to_json_schema_document(
        schema,
        on_excess_property=on_excess_property,
        generate_descriptions=generate_descriptions,
        include_annotation_key=include_annotation_key,
    )
    assert document.dialect == "draft-2020-12"
    assert document.schema == expected
    assert document.definitions == (definitions or {})


class _Empty(TypedDict):
    pass


class _A(TypedDict):
    a: str


class _OptionalA(TypedDict):
    a: NotRequired[str]


class _Value(TypedDict):
    value: float


class _Name(TypedDict):
    name: str


class _Company(TypedDict):
    company: str


class _Team(TypedDict):
    team: str


class _Labels(TypedDict):
    name: str
    tag: str


def test_approximates_tuple_post_rest_elements():
    """unsupported schemas / approximates tuple post-rest elements"""
    _check(
        S.TupleWithRest(S.Tuple(S.Finite), S.String, S.Boolean),
        {"type": "array", "prefixItems": [{"type": "number"}], "minItems": 2},
    )


def test_record_number_string():
    """Record(Number, String)"""
    _check(
        S.Record(S.Number, S.String),
        {
            "type": "object",
            "patternProperties": {_NUMBER_KEY: {"type": "string"}},
            "additionalProperties": False,
        },
    )


def test_checked_number_keys_ignored():
    """approximates checked number record keys when excess properties are ignored"""
    # Python: an int key is read from its digits, selected exactly.
    _check(
        S.Record(S.Int, S.String),
        {
            "type": "object",
            "patternProperties": {"^-?\\d+$": {"type": "string"}},
            "additionalProperties": True,
        },
        on_excess_property="ignore",
    )


def test_checked_number_keys_rejected():
    """approximates checked number record keys when excess properties are rejected"""
    _check(
        S.Record(S.Int.annotate(identifier="IntKey"), S.String),
        {
            "type": "object",
            "patternProperties": {"^-?\\d+$": {"type": "string"}},
            "additionalProperties": False,
        },
        {"IntKeyEncoded": {"type": "string", "pattern": "^-?\\d+$"}},
    )


def test_emits_content_annotations():
    """emits content annotations"""
    _check(
        S.String.annotate(
            description="encoded payload",
            content_media_type="application/json",
            content_schema={"type": "number"},
        ),
        {
            "type": "string",
            "description": "encoded payload",
            "contentMediaType": "application/json",
            "contentSchema": {"type": "number"},
        },
    )


def test_generate_descriptions():
    """options / generateDescriptions: true"""
    _check(
        S.String.annotate(expected="b"),
        {"type": "string", "description": "b"},
        generate_descriptions=True,
    )
    _check(
        S.String.annotate(description="a", expected="b"),
        {"type": "string", "description": "a"},
        generate_descriptions=True,
    )


def test_on_excess_property_defaults_to_ignore():
    """options / onExcessProperty / defaults to ignore"""
    assert S.to_json_schema_document(S.Struct(_Empty)).schema == {"not": {"type": "null"}}
    assert S.to_json_schema_document(S.Struct(_A)).schema == {
        "type": "object",
        "properties": {"a": {"type": "string"}},
        "required": ["a"],
        "additionalProperties": True,
    }


def test_on_excess_property_ignore():
    """options / onExcessProperty / ignore (default)"""
    _check(
        S.Struct(_A),
        {
            "type": "object",
            "properties": {"a": {"type": "string"}},
            "required": ["a"],
            "additionalProperties": True,
        },
        on_excess_property="ignore",
    )


def test_on_excess_property_error():
    """options / onExcessProperty / error"""
    _check(
        S.Struct(_A),
        {
            "type": "object",
            "properties": {"a": {"type": "string"}},
            "required": ["a"],
            "additionalProperties": False,
        },
    )


def test_representable_part_of_index_key():
    """options / onExcessProperty / uses the representable part of an index-signature key"""
    key = S.String.check(S.make_filter(lambda value: value.startswith("x-")))
    _check(
        S.Record(key, S.String),
        {
            "type": "object",
            "propertyNames": {"type": "string"},
            "additionalProperties": {"type": "string"},
        },
    )


def _markdown(key: str) -> bool:
    return key == "markdownDescription"


def _vendor(key: str) -> bool:
    return key.startswith("x-")


def _nothing(_: str) -> bool:
    return False


def _labels(key: str) -> bool:
    return key in ("markdownDescription", "defaultSnippets")


def test_include_annotation_key_schema_level():
    """options / includeAnnotationKey / passthroughs matching annotation keys at schema level"""
    _check(
        S.String.annotate(
            title="Name", description="A name", markdownDescription="The **name** field"
        ),
        {
            "type": "string",
            "title": "Name",
            "description": "A name",
            "markdownDescription": "The **name** field",
        },
        include_annotation_key=_markdown,
    )


def test_include_annotation_key_not_matching():
    """options / includeAnnotationKey / does not include keys not matching the predicate"""
    _check(
        S.String.annotate(
            title="Name",
            description="A name",
            markdownDescription="The **name** field",
            customKey="value",
        ),
        {
            "type": "string",
            "title": "Name",
            "description": "A name",
            "markdownDescription": "The **name** field",
        },
        include_annotation_key=_markdown,
    )


def test_include_annotation_key_none_values():
    """options / includeAnnotationKey / does not include matching keys with undefined values"""
    # Python has no undefined: a value that is not JSON is the one left out.
    _check(
        S.String.annotate(**{"x-missing": object(), "x-value": "value"}),
        {"type": "string", "x-value": "value"},
        include_annotation_key=_vendor,
    )


def test_include_annotation_key_standard_keys():
    """options / includeAnnotationKey / standard keys are always included regardless of predicate"""
    _check(
        S.String.annotate(title="Name", description="A name", default="hello"),
        {"type": "string", "title": "Name", "description": "A name", "default": "hello"},
        include_annotation_key=_nothing,
    )


def test_include_annotation_key_property_level():
    """options / includeAnnotationKey / passthroughs at property level in structs"""
    schema = S.Struct(
        _Labels,
        name=S.String.annotate(description="A name", markdownDescription="The **name** field"),
        tag=S.String.annotate(
            description="A tag", defaultSnippets=({"label": "v1", "body": "v1"},)
        ),
    )
    _check(
        schema,
        {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "A name",
                    "markdownDescription": "The **name** field",
                },
                "tag": {
                    "type": "string",
                    "description": "A tag",
                    "defaultSnippets": [{"label": "v1", "body": "v1"}],
                },
            },
            "required": ["name", "tag"],
            "additionalProperties": False,
        },
        include_annotation_key=_labels,
    )


def test_include_annotation_key_check_level():
    """options / includeAnnotationKey / passthroughs at check level"""
    schema = S.String.annotate(description="A string").check(
        S.is_min_length(1, **{"x-check-annotation": True})
    )
    _check(
        schema,
        {
            "type": "string",
            "description": "A string",
            "allOf": [{"minLength": 1, "x-check-annotation": True}],
        },
        include_annotation_key=_vendor,
    )


def test_include_annotation_key_vendor_extensions():
    """options / includeAnnotationKey / passthroughs x- prefixed vendor extensions"""
    _check(
        S.String.annotate(
            description="A value", **{"x-custom": True, "x-extension": {"foo": "bar"}}
        ),
        {
            "type": "string",
            "description": "A value",
            "x-custom": True,
            "x-extension": {"foo": "bar"},
        },
        include_annotation_key=_vendor,
    )


def test_emits_standard_annotations():
    """emits standard annotations"""
    _check(
        S.String.annotate(
            title="a",
            description="b",
            default="c",
            examples=("d",),
            read_only=True,
            write_only=True,
        ),
        {
            "type": "string",
            "title": "a",
            "description": "b",
            "default": "c",
            "examples": ["d"],
            "readOnly": True,
            "writeOnly": True,
        },
    )


def test_escapes_json_pointer_references():
    """identifiers / escapes "~" and "/" in JSON Pointer references"""
    _check(
        S.String.annotate(identifier="id~a/b"),
        {"$ref": "#/$defs/id~0a~1b"},
        {"id~a/b": {"type": "string"}},
    )


def test_reuses_definition_for_repeated_occurrences():
    """identifiers / reuses a definition for repeated occurrences of the same identified AST"""
    s = S.String.annotate(identifier="id")
    _check(
        S.Union(s, s),
        {"anyOf": [{"$ref": "#/$defs/id"}, {"$ref": "#/$defs/id"}]},
        {"id": {"type": "string"}},
    )


def test_suffixes_duplicate_identifiers():
    """identifiers / suffixes duplicate identifiers on different schemas"""
    _check(
        S.Union(
            S.String.annotate(identifier="id", description="a"),
            S.String.annotate(identifier="id", description="b"),
        ),
        {"anyOf": [{"$ref": "#/$defs/id"}, {"$ref": "#/$defs/id_1"}]},
        {
            "id": {"type": "string", "description": "a"},
            "id_1": {"type": "string", "description": "b"},
        },
    )


def test_opaque_declaration():
    """Declaration / opaque Declaration"""
    _check(S.instance_of(int), {})


def test_url():
    """Declaration / URL"""
    _check(S.URL, {"type": "string"})


def test_uint8_array():
    """Declaration / Uint8Array"""
    _check(S.Bytes, {"type": "string", "format": "byte", "contentEncoding": "base64"})


def _tagged(tag: str, value: JsonSchema | None = None) -> JsonSchema:
    properties: JsonSchema = {"_tag": {"type": "string", "enum": [tag]}}
    if value is not None:
        properties["value"] = value
    return {
        "type": "object",
        "properties": properties,
        "required": ["_tag", "value"] if value is not None else ["_tag"],
        "additionalProperties": False,
    }


def test_duration():
    """Declaration / Duration"""
    # Python: a timedelta is never infinite.
    _check(
        S.Duration,
        {
            "anyOf": [
                _tagged("Nanos", {"type": "string", "pattern": "^-?\\d+$"}),
                _tagged("Millis", _INT),
            ]
        },
    )


def test_duration_from_iso_string():
    """Declaration / DurationFromIsoString"""
    _check(S.DurationFromIsoString, {"type": "string"})


def test_option_string():
    """Declaration / Option(String)"""
    _check(S.Option(S.String), {"anyOf": [_tagged("Some", {"type": "string"}), _tagged("None")]})


def test_any():
    """Any"""
    _check(S.Any, {})
    _check(S.Any.annotate(description="a"), {"description": "a"})


def test_json():
    """Json"""
    _check(S.Json, {})


def test_unknown():
    """Unknown"""
    _check(S.Unknown, {})
    _check(S.Unknown.annotate(description="a"), {})


def test_big_int():
    """BigInt"""
    _check(S.BigInt, {"type": "string", "pattern": "^-?\\d+$"})


def test_never():
    """Never"""
    _check(S.Never, {"not": {}})
    _check(S.Never.annotate(description="a"), {"description": "a", "not": {}})


def test_null():
    """Null"""
    _check(S.Null, {"type": "null"})
    _check(S.Null.annotate(description="a"), {"type": "null", "description": "a"})


def test_string():
    """String / String"""
    _check(S.String, {"type": "string"})


def test_string_annotate():
    """String / String & annotate"""
    _check(S.String.annotate(description="a"), {"type": "string", "description": "a"})


def test_string_annotate_key_not_contextual():
    """String / ignores annotateKey annotations when the schema is not contextual"""
    _check(S.String.annotate_key(description="a"), {"type": "string"})


def test_string_check():
    """String / String & check"""
    # Python: a string's length is its code points, as minLength's is.
    _check(S.String.check(S.is_min_length(2)), {"type": "string", "minLength": 2})


def test_string_custom_check():
    """String / String & custom check without annotation"""
    _check(S.String.check(S.make_filter(lambda _: True)), {"type": "string"})


def test_string_annotate_check():
    """String / String & annotate & check"""
    _check(
        S.String.annotate(description="a").check(S.is_min_length(2)),
        {"type": "string", "description": "a", "minLength": 2},
    )


def test_string_check_annotate():
    """String / String & check & annotate"""
    _check(
        S.String.check(S.is_min_length(2)).annotate(description="a"),
        {"type": "string", "minLength": 2, "description": "a"},
    )


def test_string_check_check():
    """String / String & check & check"""
    _check(
        S.String.check(S.is_min_length(2), S.is_max_length(3)),
        {"type": "string", "minLength": 2, "maxLength": 3},
    )


def test_string_annotate_check_check():
    """String / String & annotate & check & check"""
    _check(
        S.String.annotate(description="a").check(S.is_min_length(2), S.is_max_length(3)),
        {"type": "string", "description": "a", "minLength": 2, "maxLength": 3},
    )


def test_string_check_check_annotate():
    """String / String & check & check & annotate"""
    _check(
        S.String.check(S.is_min_length(2), S.is_max_length(3)).annotate(description="a"),
        {"type": "string", "minLength": 2, "maxLength": 3, "description": "a"},
    )


def test_string_annotate_check_check_annotate():
    """String / String & annotate & check & check & annotate"""
    _check(
        S.String.annotate(description="a").check(
            S.is_min_length(2), S.is_max_length(3, description="c")
        ),
        {
            "type": "string",
            "description": "a",
            "minLength": 2,
            "allOf": [{"maxLength": 3, "description": "c"}],
        },
    )


def test_string_check_annotations_check_annotations():
    """String / String & check & annotations & check & annotations"""
    _check(
        S.String.check(S.is_min_length(2, description="b"), S.is_max_length(3, description="c")),
        {
            "type": "string",
            "minLength": 2,
            "description": "b",
            "allOf": [{"maxLength": 3, "description": "c"}],
        },
    )


def test_string_annotations_checks_annotations():
    """String / String & annotations & check & annotations & check & annotations"""
    _check(
        S.String.annotate(description="a").check(
            S.is_min_length(2, description="b"), S.is_max_length(3, description="c")
        ),
        {
            "type": "string",
            "description": "a",
            "allOf": [
                {"minLength": 2, "description": "b"},
                {"maxLength": 3, "description": "c"},
            ],
        },
    )


def test_is_pattern():
    """String / checks / isPattern"""
    # Python: a re pattern is not a JSON Schema pattern; it is left out.
    _check(S.String.check(S.is_pattern("^abb+$")), {"type": "string"})


def test_escapes_literal_string_checks():
    """String / checks / escapes regexp syntax in literal string checks"""
    for check, pattern in (
        (S.is_starting_with("a.b"), "^a\\.b"),
        (S.is_ending_with("a+b"), "a\\+b$"),
        (S.is_including("["), "\\["),
    ):
        _check(S.String.check(check), {"type": "string", "pattern": pattern})


def test_is_trimmed():
    """String / checks / isTrimmed"""
    _check(S.Trimmed, {"type": "string", "pattern": "^\\S[\\s\\S]*\\S$|^\\S$|^$"})


def test_is_lowercased():
    """String / checks / isLowercased"""
    _check(S.String.check(S.is_lowercased()), {"type": "string", "pattern": "^[^A-Z]*$"})


def test_is_uppercased():
    """String / checks / isUppercased"""
    _check(S.String.check(S.is_uppercased()), {"type": "string", "pattern": "^[^a-z]*$"})


def test_is_capitalized():
    """String / checks / isCapitalized"""
    _check(
        S.String.check(S.is_capitalized()),
        {"type": "string", "pattern": "^(?:[^a-z][\\s\\S]*)?$"},
    )


def test_is_uncapitalized():
    """String / checks / isUncapitalized"""
    _check(
        S.String.check(S.is_uncapitalized()),
        {"type": "string", "pattern": "^(?:[^A-Z][\\s\\S]*)?$"},
    )


def test_is_between_length_string():
    """String / checks / isBetweenLength / String"""
    _check(
        S.String.check(S.is_between_length(2, 2)),
        {"type": "string", "minLength": 2, "maxLength": 2},
    )


def test_is_between_length_array():
    """String / checks / isBetweenLength / Array"""
    _check(
        S.Array(S.String).check(S.is_between_length(2, 2)),
        {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 2},
    )


def test_is_between_length_non_empty_array():
    """String / checks / isBetweenLength / NonEmptyArray"""
    _check(
        S.NonEmptyArray(S.String).check(S.is_between_length(2, 2)),
        {
            "type": "array",
            "prefixItems": [{"type": "string"}],
            "items": {"type": "string"},
            "minItems": 2,
            "maxItems": 2,
        },
    )


def test_code_point_checks():
    """String / checks / exports code point checks with matching JSON Schema validation"""
    for check, keywords in (
        (S.is_min_code_points(2), {"minLength": 2}),
        (S.is_max_code_points(1), {"maxLength": 1}),
        (S.is_between_code_points(1, 2), {"allOf": [{"minLength": 1}, {"maxLength": 2}]}),
    ):
        _check(S.String.check(check), {"type": "string", **keywords})


def test_is_min_length_string():
    """String / checks / isMinLength / String"""
    _check(S.String.check(S.is_min_length(2)), {"type": "string", "minLength": 2})


def test_is_min_length_loose_lower_bound():
    """String / checks / isMinLength / exports a loose lower bound for strings"""
    # Python: the bound is exact.
    _check(S.String.check(S.is_min_length(3)), {"type": "string", "minLength": 3})


def test_is_min_length_array():
    """String / checks / isMinLength / Array"""
    _check(
        S.Array(S.String).check(S.is_min_length(2)),
        {"type": "array", "items": {"type": "string"}, "minItems": 2},
    )


def test_is_min_length_non_empty_array():
    """String / checks / isMinLength / NonEmptyArray"""
    _check(
        S.NonEmptyArray(S.String).check(S.is_min_length(2)),
        {
            "type": "array",
            "prefixItems": [{"type": "string"}],
            "items": {"type": "string"},
            "minItems": 2,
        },
    )


def test_is_max_length_string():
    """String / checks / isMaxLength / String"""
    _check(S.String.check(S.is_max_length(2)), {"type": "string", "maxLength": 2})


def test_is_max_length_loose_upper_bound():
    """String / checks / isMaxLength / exports a loose upper bound for strings"""
    _check(S.String.check(S.is_max_length(2)), {"type": "string", "maxLength": 2})


def test_is_max_length_array():
    """String / checks / isMaxLength / Array"""
    _check(
        S.Array(S.String).check(S.is_max_length(2)),
        {"type": "array", "items": {"type": "string"}, "maxItems": 2},
    )


def test_is_max_length_non_empty_array():
    """String / checks / isMaxLength / NonEmptyArray"""
    _check(
        S.NonEmptyArray(S.String).check(S.is_max_length(2)),
        {
            "type": "array",
            "maxItems": 2,
            "minItems": 1,
            "prefixItems": [{"type": "string"}],
            "items": {"type": "string"},
        },
    )


def test_is_uuid():
    """String / checks / isUUID"""
    _check(
        S.String.annotate(description="description").check(S.is_uuid()),
        {
            "type": "string",
            "description": "description",
            "format": "uuid",
            "pattern": "^([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[1-8][0-9a-fA-F]{3}-[89abAB][0-9a-fA-F]{3}-[0-9a-fA-F]{12}|00000000-0000-0000-0000-000000000000|[fF]{8}-[fF]{4}-[fF]{4}-[fF]{4}-[fF]{12})$",  # noqa: E501
        },
    )


def test_is_guid():
    """String / checks / isGUID"""
    _check(
        S.String.annotate(description="description").check(S.is_guid()),
        {
            "type": "string",
            "description": "description",
            "pattern": "^([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})$",  # noqa: E501
        },
    )


def test_is_ulid():
    """String / checks / isULID"""
    _check(
        S.String.annotate(description="description").check(S.is_ulid()),
        {
            "type": "string",
            "description": "description",
            "pattern": "^[0-7][0-9A-HJKMNP-TV-Za-hjkmnp-tv-z]{25}$",
        },
    )


def test_is_ascii():
    """String / checks / isAscii"""
    _check(
        S.String.annotate(description="description").check(S.is_ascii()),
        {"type": "string", "description": "description", "pattern": "^[\\x00-\\x7F]*$"},
    )


def test_is_base64():
    """String / checks / isBase64"""
    _check(
        S.String.annotate(description="description").check(S.is_base64()),
        {
            "type": "string",
            "description": "description",
            "pattern": "^([0-9a-zA-Z+/]{4})*(([0-9a-zA-Z+/]{2}==)|([0-9a-zA-Z+/]{3}=))?$",
        },
    )


def test_is_base64_url():
    """String / checks / isBase64Url"""
    _check(
        S.String.annotate(description="description").check(S.is_base64_url()),
        {
            "type": "string",
            "description": "description",
            "pattern": "^([0-9a-zA-Z-_]{4})*(([0-9a-zA-Z-_]{2}(==)?)|([0-9a-zA-Z-_]{3}(=)?))?$",
        },
    )


def test_number():
    """Number / Number"""
    _check(S.Number, _NUMBER)
    _check(S.Number.annotate(description="a"), _NUMBER)


def test_number_annotate_key():
    """Number / Number & annotateKey"""
    _check(
        S.Struct(_Value, value=S.Number.annotate_key(description="the field")),
        {
            "type": "object",
            "properties": {"value": {**_NUMBER, "allOf": [{"description": "the field"}]}},
            "required": ["value"],
            "additionalProperties": False,
        },
    )


def test_finite():
    """Finite / Finite"""
    _check(S.Finite, {"type": "number"})
    _check(S.Finite.annotate(description="a"), {"type": "number", "description": "a"})


def test_is_int():
    """Finite / checks / isInt"""
    _check(S.Finite.check(S.is_int()), _INT)


def test_keeps_one_of_for_exact_integer_branches():
    """Finite / checks / keeps oneOf for exact integer branches"""
    _check(
        S.Union(S.Int, S.Boolean, mode="one_of"),
        {"oneOf": [_INT, {"type": "boolean"}]},
    )


def test_merges_colliding_inclusive_bounds():
    """Finite / checks / merges colliding inclusive bounds into the tighter bound"""
    _check(
        S.Int.check(S.is_between(minimum=1, maximum=100)).annotate(description="a", default=5),
        {"type": "integer", "minimum": 1, "maximum": 100, "description": "a", "default": 5},
    )


def test_keeps_only_tightest_bound():
    """Finite / checks / keeps only the tightest inclusive or exclusive bound"""
    _check(
        S.Finite.check(
            S.is_greater_than(0),
            S.is_greater_than(1),
            S.is_greater_than_or_equal_to(1),
            S.is_less_than(10),
            S.is_less_than(9),
            S.is_less_than_or_equal_to(8),
        ),
        {"type": "number", "exclusiveMinimum": 1, "maximum": 8},
    )


def test_merges_colliding_property_count_bounds():
    """Finite / checks / merges colliding property-count bounds into the tighter bound"""
    _check(
        S.Record(S.String, S.String).check(
            S.is_min_properties(2),
            S.is_min_properties(1),
            S.is_max_properties(5),
            S.is_max_properties(3),
        ),
        {
            "type": "object",
            "additionalProperties": {"type": "string"},
            "minProperties": 2,
            "maxProperties": 3,
        },
    )


def test_is_int32():
    """Finite / checks / isInt32"""
    _check(
        S.Finite.check(S.is_int32()),
        {
            "type": "integer",
            "allOf": [
                {"minimum": _MIN_SAFE, "maximum": _MAX_SAFE},
                {"maximum": 2147483647, "minimum": -2147483648},
            ],
        },
    )


def test_is_uint32():
    """Finite / checks / isUint32"""
    _check(
        S.Finite.check(S.is_uint32()),
        {
            "type": "integer",
            "allOf": [
                {"minimum": _MIN_SAFE, "maximum": _MAX_SAFE},
                {"maximum": 4294967295, "minimum": 0},
            ],
        },
    )
    _check(
        S.Finite.check(S.is_uint32(description="a")),
        {
            "type": "integer",
            "allOf": [
                {
                    "description": "a",
                    "allOf": [
                        {"minimum": _MIN_SAFE, "maximum": _MAX_SAFE},
                        {"maximum": 4294967295, "minimum": 0},
                    ],
                }
            ],
        },
    )


def test_is_greater_than():
    """Finite / checks / isGreaterThan"""
    _check(S.Finite.check(S.is_greater_than(1)), {"type": "number", "exclusiveMinimum": 1})


def test_is_greater_than_or_equal_to():
    """Finite / checks / isGreaterThanOrEqualTo"""
    _check(S.Finite.check(S.is_greater_than_or_equal_to(1)), {"type": "number", "minimum": 1})


def test_is_less_than():
    """Finite / checks / isLessThan"""
    _check(S.Finite.check(S.is_less_than(1)), {"type": "number", "exclusiveMaximum": 1})


def test_is_less_than_or_equal_to():
    """Finite / checks / isLessThanOrEqualTo"""
    _check(S.Finite.check(S.is_less_than_or_equal_to(1)), {"type": "number", "maximum": 1})


def test_is_between():
    """Finite / checks / isBetween"""
    _check(
        S.Finite.check(S.is_between(minimum=1, maximum=10)),
        {"type": "number", "minimum": 1, "maximum": 10},
    )
    _check(
        S.Finite.check(S.is_between(minimum=1, maximum=10, exclusive_minimum=True)),
        {"type": "number", "exclusiveMinimum": 1, "maximum": 10},
    )
    _check(
        S.Finite.check(S.is_between(minimum=1, maximum=10, exclusive_maximum=True)),
        {"type": "number", "minimum": 1, "exclusiveMaximum": 10},
    )
    _check(
        S.Finite.check(
            S.is_between(minimum=1, maximum=10, exclusive_minimum=True, exclusive_maximum=True)
        ),
        {"type": "number", "exclusiveMinimum": 1, "exclusiveMaximum": 10},
    )


def test_is_multiple_of():
    """Finite / checks / isMultipleOf"""
    _check(S.Int.check(S.is_multiple_of(2)), {**_INT, "multipleOf": 2})
    _check(S.Int.check(S.is_multiple_of(-2)), {**_INT, "multipleOf": 2})


def test_boolean():
    """Boolean"""
    _check(S.Boolean, {"type": "boolean"})
    _check(S.Boolean.annotate(description="a"), {"type": "boolean", "description": "a"})


def test_literal_string():
    """Literal / string"""
    _check(S.Literal("a"), {"type": "string", "enum": ["a"]})
    _check(
        S.Literal("a").annotate(description="a"),
        {"type": "string", "enum": ["a"], "description": "a"},
    )


def test_literal_number():
    """Literal / number"""
    _check(S.Literal(1), {"type": "number", "enum": [1]})
    _check(
        S.Literal(1).annotate(description="a"),
        {"type": "number", "enum": [1], "description": "a"},
    )


def test_literal_boolean():
    """Literal / boolean"""
    _check(S.Literal(True), {"type": "boolean", "enum": [True]})
    _check(
        S.Literal(True).annotate(description="a"),
        {"type": "boolean", "enum": [True], "description": "a"},
    )


def test_empty_literals():
    """Literals / empty literals"""
    empty: S.LiteralsSchema[Literal["a"]] = S.Literals()
    _check(empty, {"not": {}})
    _check(empty.annotate(description="a"), {"not": {}, "description": "a"})


def test_literals_strings():
    """Literals / strings"""
    _check(S.Literals("a", "b"), {"type": "string", "enum": ["a", "b"]})
    _check(
        S.Literals("a", "b").annotate(description="a"),
        {"type": "string", "enum": ["a", "b"], "description": "a"},
    )


def test_literals_numbers():
    """Literals / numbers"""
    _check(S.Literals(1, 2), {"type": "number", "enum": [1, 2]})


def test_literals_booleans():
    """Literals / booleans"""
    _check(S.Literals(True, False), {"type": "boolean", "enum": [True, False]})


def test_literals_strings_and_numbers():
    """Literals / strings & numbers"""
    members: list[JsonSchema] = [
        {"type": "string", "enum": ["a"]},
        {"type": "number", "enum": [1]},
    ]
    _check(S.Literals("a", 1), {"anyOf": members})
    _check(S.Literals("a", 1).annotate(description="a"), {"anyOf": members, "description": "a"})


_JSON_ANNOTATIONS: dict[str, Any] = {
    "title": "title",
    "description": "description",
    "default": "a",
}


def test_union_of_literals_strings():
    """Union of literals / strings"""
    schema = S.Union(S.Literal("a"), S.Literal("b"))
    _check(schema, {"type": "string", "enum": ["a", "b"]})
    _check(
        schema.annotate(**_JSON_ANNOTATIONS, examples=("a", "b")),
        {"type": "string", "enum": ["a", "b"], **_JSON_ANNOTATIONS, "examples": ["a", "b"]},
    )


def test_union_of_nested_literals():
    """Union of literals / nested literals"""
    _check(
        S.Union(S.Literal("a"), S.Literals("b", "c")),
        {"type": "string", "enum": ["a", "b", "c"]},
    )


def test_union_of_literals_inner_annotate():
    """Union of literals / strings & inner annotate"""
    schema = S.Union(S.Literal("a"), S.Literal("b").annotate(description="b-description"))
    members: list[JsonSchema] = [
        {"type": "string", "enum": ["a"]},
        {"type": "string", "enum": ["b"], "description": "b-description"},
    ]
    _check(schema, {"anyOf": members})
    _check(schema.annotate(**_JSON_ANNOTATIONS), {"anyOf": members, **_JSON_ANNOTATIONS})


def test_union_of_literals_numbers():
    """Union of literals / numbers"""
    _check(S.Union(S.Literal(1), S.Literal(2)), {"type": "number", "enum": [1, 2]})


def test_union_of_literals_booleans():
    """Union of literals / booleans"""
    _check(S.Union(S.Literal(True), S.Literal(False)), {"type": "boolean", "enum": [True, False]})


def test_union_of_literals_strings_and_numbers():
    """Union of literals / strings & numbers"""
    _check(
        S.Union(S.Literal("a"), S.Literal(1)),
        {"anyOf": [{"type": "string", "enum": ["a"]}, {"type": "number", "enum": [1]}]},
    )


class _NoFruits(enum.Enum):
    pass


class _Apple(enum.Enum):
    Apple = 0


class _Fruits(enum.Enum):
    Apple = 0
    Banana = 1
    Orange = "orange"


class _ConstFruits(enum.Enum):
    Apple = "apple"
    Banana = "banana"
    Cantaloupe = 3


def test_empty_enum():
    """Enum / empty enum"""
    _check(S.Enum(_NoFruits), {"not": {}})
    _check(S.Enum(_NoFruits).annotate(description="a"), {"not": {}, "description": "a"})


def test_single_enum():
    """Enum / single enum"""
    members: list[JsonSchema] = [{"type": "number", "enum": [0], "title": "Apple"}]
    _check(S.Enum(_Apple), {"anyOf": members})
    _check(S.Enum(_Apple).annotate(description="a"), {"anyOf": members, "description": "a"})


def test_mixed_enums():
    """Enum / mixed enums (number & string)"""
    _check(
        S.Enum(_Fruits),
        {
            "anyOf": [
                {"type": "number", "enum": [0], "title": "Apple"},
                {"type": "number", "enum": [1], "title": "Banana"},
                {"type": "string", "enum": ["orange"], "title": "Orange"},
            ]
        },
    )


def test_const_enum():
    """Enum / const enum"""
    _check(
        S.Enum(_ConstFruits),
        {
            "anyOf": [
                {"type": "string", "title": "Apple", "enum": ["apple"]},
                {"type": "string", "title": "Banana", "enum": ["banana"]},
                {"type": "number", "title": "Cantaloupe", "enum": [3]},
            ]
        },
    )


def test_empty_struct():
    """Struct / empty struct"""
    _check(S.Struct(_Empty), {"not": {"type": "null"}})
    _check(
        S.Struct(_Empty).annotate(description="a"),
        {"not": {"type": "null"}, "description": "a"},
    )


def _object_a(a: JsonSchema, *, required: bool = True) -> JsonSchema:
    out: JsonSchema = {"type": "object", "properties": {"a": a}}
    if required:
        out["required"] = ["a"]
    out["additionalProperties"] = False
    return out


def test_struct_required_string():
    """Struct / required property / String"""
    _check(S.Struct(_A), _object_a({"type": "string"}))


def test_struct_required_string_annotate():
    """Struct / required property / String & annotate"""
    _check(
        S.Struct(_A, a=S.String.annotate(description="a")),
        _object_a({"type": "string", "description": "a"}),
    )


def test_struct_required_string_annotate_key():
    """Struct / required property / String & annotateKey"""
    _check(
        S.Struct(_A, a=S.String.annotate_key(description="a")),
        _object_a({"type": "string", "allOf": [{"description": "a"}]}),
    )


def test_struct_required_string_annotate_and_annotate_key():
    """Struct / required property / String & annotate & annotateKey"""
    _check(
        S.Struct(_A, a=S.String.annotate(description="a").annotate_key(description="a-key")),
        _object_a({"type": "string", "description": "a", "allOf": [{"description": "a-key"}]}),
    )


def test_struct_optional_key_string():
    """Struct / optionalKey / String"""
    _check(S.Struct(_OptionalA), _object_a({"type": "string"}, required=False))


def test_struct_optional_key_string_annotate():
    """Struct / optionalKey / String & annotate"""
    _check(
        S.Struct(_OptionalA, a=S.String.annotate(description="a")),
        _object_a({"type": "string", "description": "a"}, required=False),
    )


def test_record_string_never():
    """Record / Record(String, Never)"""
    _check(S.Record(S.String, S.Never), {"type": "object", "additionalProperties": False})
    _check(
        S.Record(S.String, S.Never.annotate(description="a")),
        {"type": "object", "additionalProperties": {"description": "a", "not": {}}},
    )


def test_record_string_empty_struct():
    """Record / Record(String, Struct({}))"""
    _check(
        S.Record(S.String, S.Struct(_Empty)),
        {"type": "object", "additionalProperties": {"not": {"type": "null"}}},
    )


def test_record_starting_with_empty_struct():
    """Record / Record(isStartingWith, Struct({}))"""
    _check(
        S.Record(S.String.check(S.is_starting_with("a")), S.Struct(_Empty)),
        {
            "type": "object",
            "patternProperties": {"^a": {"not": {"type": "null"}}},
            "additionalProperties": False,
        },
    )


def test_record_string_finite():
    """Record / Record(String, Finite)"""
    _check(
        S.Record(S.String, S.Finite),
        {"type": "object", "additionalProperties": {"type": "number"}},
    )
    _check(
        S.Record(S.String.annotate(description="k"), S.Finite.annotate(description="v")).annotate(
            description="r"
        ),
        {
            "type": "object",
            "additionalProperties": {"type": "number", "description": "v"},
            "description": "r",
        },
    )


def test_record_literals_finite():
    """Record / Record(Literals(['a', 'b']), Finite)"""
    _check(
        S.Record(S.Literals("a", "b"), S.Finite),
        {
            "type": "object",
            "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
            "required": ["a", "b"],
            "additionalProperties": False,
        },
    )


def test_record_is_uppercased_number():
    """Record / Record(isUppercased, Number)"""
    _check(
        S.Record(S.String.check(S.is_uppercased()), S.Finite),
        {
            "type": "object",
            "propertyNames": {"type": "string", "pattern": "^[^a-z]*$"},
            "additionalProperties": {"type": "number"},
        },
    )


def test_conjunctive_record_key_patterns():
    """Record / uses propertyNames for conjunctive record key patterns"""
    _check(
        S.Record(S.String.check(S.is_starting_with("A"), S.is_uppercased()), S.Finite),
        {
            "type": "object",
            "propertyNames": {
                "type": "string",
                "pattern": "^A",
                "allOf": [{"pattern": "^[^a-z]*$"}],
            },
            "additionalProperties": {"type": "number"},
        },
    )


def test_partial_pattern_not_index_selector():
    """Record / does not use a partial pattern as an index selector"""
    schema = S.Record(S.String.check(S.is_starting_with("x"), S.is_min_length(3)), S.Finite)
    _check(schema, {"type": "object", "additionalProperties": True}, on_excess_property="ignore")
    _check(
        schema,
        {
            "type": "object",
            "propertyNames": {"type": "string", "pattern": "^x", "minLength": 3},
            "additionalProperties": {"type": "number"},
        },
    )


def test_record_is_min_properties():
    """Record / checks / isMinProperties"""
    _check(
        S.Record(S.String, S.Finite).check(S.is_min_properties(2)),
        {"type": "object", "additionalProperties": {"type": "number"}, "minProperties": 2},
    )


def test_record_is_max_properties():
    """Record / checks / isMaxProperties"""
    _check(
        S.Record(S.String, S.Finite).check(S.is_max_properties(2)),
        {"type": "object", "additionalProperties": {"type": "number"}, "maxProperties": 2},
    )


def test_record_is_between_properties():
    """Record / checks / isBetweenProperties"""
    _check(
        S.Record(S.String, S.Finite).check(S.is_between_properties(2, 2)),
        {
            "type": "object",
            "additionalProperties": {"type": "number"},
            "minProperties": 2,
            "maxProperties": 2,
        },
    )


def test_empty_tuple():
    """Tuple / empty tuple"""
    _check(S.Tuple(), {"type": "array", "items": False})
    _check(
        S.Tuple().annotate(description="a"),
        {"type": "array", "items": False, "description": "a"},
    )


def test_tuple_required_string():
    """Tuple / required element / String"""
    _check(
        S.Tuple(S.String),
        {"type": "array", "prefixItems": [{"type": "string"}], "minItems": 1, "maxItems": 1},
    )


def test_tuple_required_string_annotate_key():
    """Tuple / required element / String & annotateKey"""
    _check(
        S.Tuple(S.String.annotate_key(description="a")),
        {
            "type": "array",
            "prefixItems": [{"type": "string", "allOf": [{"description": "a"}]}],
            "minItems": 1,
            "maxItems": 1,
        },
    )


def test_tuple_optional_key_string():
    """Tuple / optionalKey / String"""
    _check(
        S.Tuple(S.optional_key(S.String)),
        {"type": "array", "prefixItems": [{"type": "string"}], "maxItems": 1},
    )


def test_array_string():
    """Array / Array(String)"""
    _check(S.Array(S.String), {"type": "array", "items": {"type": "string"}})
    _check(
        S.Array(S.String).annotate(description="a"),
        {"type": "array", "items": {"type": "string"}, "description": "a"},
    )


def test_array_is_min_length():
    """Array / checks / isMinLength"""
    _check(
        S.Array(S.String).check(S.is_min_length(2)),
        {"type": "array", "items": {"type": "string"}, "minItems": 2},
    )


def test_array_is_max_length():
    """Array / checks / isMaxLength"""
    _check(
        S.Array(S.String).check(S.is_max_length(2)),
        {"type": "array", "items": {"type": "string"}, "maxItems": 2},
    )


def test_array_is_between_length():
    """Array / checks / isBetweenLength"""
    _check(
        S.Array(S.String).check(S.is_between_length(2, 3)),
        {"type": "array", "items": {"type": "string"}, "minItems": 2, "maxItems": 3},
    )


def test_unique_array():
    """Array / checks / UniqueArray"""
    _check(
        S.UniqueArray(S.String),
        {"type": "array", "items": {"type": "string"}, "uniqueItems": True},
    )


def test_tuple_with_rest():
    """TupleWithRest"""
    _check(
        S.TupleWithRest(S.Tuple(S.String), S.Finite),
        {
            "type": "array",
            "prefixItems": [{"type": "string"}],
            "items": {"type": "number"},
            "minItems": 1,
        },
    )


def _object(key: str) -> JsonSchema:
    return {
        "type": "object",
        "properties": {key: {"type": "string"}},
        "required": [key],
        "additionalProperties": False,
    }


def test_flattens_union_inside_null_or():
    """Union / nested unions / flattens a union inside NullOr"""
    _check(
        S.NullOr(S.Union(S.Struct(_Name), S.Struct(_Company))),
        {"anyOf": [_object("name"), _object("company"), {"type": "null"}]},
    )


def test_flattens_union_inside_any_of():
    """Union / nested unions / flattens a union inside another anyOf"""
    _check(
        S.Union(S.Union(S.Struct(_Name), S.Struct(_Company)), S.Struct(_Team)),
        {"anyOf": [_object("name"), _object("company"), _object("team")]},
    )


def test_preserves_annotations_on_nested_any_of():
    """Union / nested unions / preserves annotations on a nested anyOf"""
    inner = S.Union(S.String, S.Boolean).annotate(description="inner")
    _check(
        S.Union(inner, S.Null),
        {
            "anyOf": [
                {"anyOf": [{"type": "string"}, {"type": "boolean"}], "description": "inner"},
                {"type": "null"},
            ]
        },
    )


def test_preserves_references_to_nested_any_of():
    """Union / nested unions / preserves references to a nested anyOf"""
    inner = S.Union(S.String, S.Boolean).annotate(identifier="Inner")
    _check(
        S.Union(inner, S.Null),
        {"anyOf": [{"$ref": "#/$defs/Inner"}, {"type": "null"}]},
        {"Inner": {"anyOf": [{"type": "string"}, {"type": "boolean"}]}},
    )


def test_preserves_inner_mode_inside_outer_mode():
    """Union / nested unions / preserves an inner %s inside an outer %s"""
    modes: tuple[tuple[S.ast.UnionMode, S.ast.UnionMode, str, str], ...] = (
        ("any_of", "one_of", "anyOf", "oneOf"),
        ("one_of", "any_of", "oneOf", "anyOf"),
        ("one_of", "one_of", "oneOf", "oneOf"),
    )
    for inner_mode, outer_mode, inner_key, outer_key in modes:
        inner = S.Union(S.String, S.Boolean, mode=inner_mode)
        _check(
            S.Union(inner, S.String, mode=outer_mode),
            {
                outer_key: [
                    {inner_key: [{"type": "string"}, {"type": "boolean"}]},
                    {"type": "string"},
                ]
            },
        )


def test_empty_union():
    """Union / empty union"""
    _check(S.Union(), {"not": {}})
    _check(S.Union().annotate(description="a"), {"not": {}, "description": "a"})


def test_single_member():
    """Union / single member"""
    _check(S.Union(S.String), {"anyOf": [{"type": "string"}]})
    _check(
        S.Union(S.String).annotate(description="a"),
        {"anyOf": [{"type": "string"}], "description": "a"},
    )
    _check(
        S.Union(S.String.annotate(description="inner")).annotate(description="outer"),
        {"anyOf": [{"type": "string", "description": "inner"}], "description": "outer"},
    )


def test_approximated_one_of_branches():
    """Union / uses anyOf when approximated oneOf branches can overlap"""
    # Python: string lengths are exact, so an approximate branch here is a
    # check without a fragment.
    approximate = S.String.check(S.make_filter(lambda _: True))
    _check(
        S.Union(approximate, S.String.check(S.is_max_length(1)), mode="one_of"),
        {"anyOf": [{"type": "string"}, {"type": "string", "maxLength": 1}]},
    )


def test_keeps_one_of_when_exact():
    """Union / keeps oneOf when its branches are exact"""
    _check(
        S.Union(S.String, S.Boolean, mode="one_of"),
        {"oneOf": [{"type": "string"}, {"type": "boolean"}]},
    )


def test_does_not_compact_duplicate_enum_values():
    """Union / does not compact duplicate enum values"""
    _check(
        S.Union(S.Literal("a"), S.Literal("a")),
        {"anyOf": [{"type": "string", "enum": ["a"]}, {"type": "string", "enum": ["a"]}]},
    )


def test_string_or_number():
    """Union / String | Number"""
    _check(S.Union(S.String, S.Finite), {"anyOf": [{"type": "string"}, {"type": "number"}]})
    _check(
        S.Union(S.String, S.Finite).annotate(description="description"),
        {"anyOf": [{"type": "string"}, {"type": "number"}], "description": "description"},
    )


def test_string_or_big_int():
    """Union / String | BigInt"""
    _check(
        S.Union(S.String, S.BigInt),
        {"anyOf": [{"type": "string", "pattern": "^-?\\d+$"}, {"type": "string"}]},
    )


class _Expression(TypedDict):
    type: str
    value: object


class _Operation(TypedDict):
    type: str
    operator: str
    left: object
    right: object


def _operation() -> Any:
    return _OPERATION


_EXPRESSION = S.Struct(
    _Expression,
    type=S.Literal("expression"),
    value=S.Union(S.Finite, S.suspend(_operation)),
).annotate(identifier="Expression")
_OPERATION: Any = S.Struct(
    _Operation,
    type=S.Literal("operation"),
    operator=S.Literals("+", "-"),
    left=_EXPRESSION,
    right=_EXPRESSION,
).annotate(identifier="Operation")


def test_mutually_recursive_schemas():
    """mutually recursive schemas"""
    definitions: dict[str, JsonSchema] = {
        "Operation": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["operation"]},
                "operator": {"type": "string", "enum": ["+", "-"]},
                "left": {"$ref": "#/$defs/Expression"},
                "right": {"$ref": "#/$defs/Expression"},
            },
            "required": ["type", "operator", "left", "right"],
            "additionalProperties": False,
        },
        "Expression": {
            "type": "object",
            "properties": {
                "type": {"type": "string", "enum": ["expression"]},
                "value": {"anyOf": [{"type": "number"}, {"$ref": "#/$defs/Operation"}]},
            },
            "required": ["type", "value"],
            "additionalProperties": False,
        },
    }
    _check(_OPERATION, {"$ref": "#/$defs/Operation"}, definitions)
    _check(_EXPRESSION, {"$ref": "#/$defs/Expression"}, definitions)


def test_class_preserves_its_identifier():
    """Class preserves its identifier as a canonical reference"""

    class A(S.Class, identifier="A"):
        a: str

    _check(
        A,
        {"$ref": "#/$defs/AEncoded"},
        {
            "AEncoded": {
                "type": "object",
                "properties": {"a": {"type": "string"}},
                "required": ["a"],
                "additionalProperties": False,
            }
        },
        include_annotation_key=lambda _: True,
    )


def test_error_preserves_its_identifier():
    """Error preserves its identifier as a canonical reference"""

    class E(S.Error, identifier="E"):
        a: str

    _check(
        E,
        {"$ref": "#/$defs/EEncoded"},
        {
            "EEncoded": {
                "type": "object",
                "properties": {"a": {"type": "string"}},
                "required": ["a"],
                "additionalProperties": False,
            }
        },
    )


# --------------------------------------------------------- TemplateLiteral


def test_template_literal():
    """TemplateLiteral"""
    schema = S.TemplateLiteral("a", S.String)
    _check(schema, {"type": "string", "pattern": "^a[\\s\\S]*?$"})
    _check(
        schema.annotate(description="a"),
        {"type": "string", "pattern": "^a[\\s\\S]*?$", "description": "a"},
    )


def test_template_literal_with_big_int():
    """TemplateLiteral with BigInt"""
    _check(S.TemplateLiteral(S.BigInt), {"type": "string", "pattern": "^-?\\d+$"})


_SEGMENT = S.String.check(S.make_filter(lambda s: s == "abc"))
_TEMPLATES: list[tuple[str, Any]] = [
    ("direct", S.TemplateLiteral("item.", _SEGMENT)),
    ("named", S.TemplateLiteral("item.", _SEGMENT.annotate(identifier="Segment"))),
    ("named template", S.TemplateLiteral("item.", _SEGMENT).annotate(identifier="Item")),
    ("nested template", S.TemplateLiteral("item.", S.TemplateLiteral(_SEGMENT))),
    ("union", S.TemplateLiteral("item.", S.Union(_SEGMENT, S.Literal("def")))),
]


def test_template_resolves_repeated_named_segments():
    """TemplateLiteral segments / resolves repeated named segments without checks"""
    named = S.String.annotate(identifier="Segment")
    _check(
        S.TemplateLiteral(named, ".", named),
        {"type": "string", "pattern": "^[\\s\\S]*?\\.[\\s\\S]*?$"},
        {"Segment": {"type": "string"}},
    )


def test_template_resolves_named_nested_templates_and_union_segments():
    """TemplateLiteral segments / resolves named nested templates and union segments"""
    named = S.String.annotate(identifier="Segment")
    nested = S.TemplateLiteral("item.", named).annotate(identifier="Nested")
    choice = S.Union(nested, S.Literal("other")).annotate(identifier="Choice")
    document = S.to_json_schema_document(S.TemplateLiteral(choice, ".", named))
    assert document.schema == {
        "type": "string",
        "pattern": "^(?:item\\.[\\s\\S]*?|other)\\.[\\s\\S]*?$",
    }


def test_template_resolves_named_segments_in_record_keys():
    """TemplateLiteral segments / resolves named segments in record keys"""
    named = S.String.annotate(identifier="Segment")
    _check(
        S.Record(S.TemplateLiteral("item.", named), S.Finite),
        {
            "type": "object",
            "patternProperties": {"^item\\.[\\s\\S]*?$": {"type": "number"}},
            "additionalProperties": False,
        },
        {"Segment": {"type": "string"}},
    )


@pytest.mark.parametrize("part", [_SEGMENT, _SEGMENT.annotate(identifier="Segment")])
def test_template_approximates_segment_checks(part: S.Codec[str, str]):
    """TemplateLiteral segments / approximates %s segment checks while preserving runtime validation"""  # noqa: E501
    schema = S.TemplateLiteral("item.", part)
    assert S.is_(schema)("item.abc")
    assert not S.is_(schema)("item.xyz")
    document = S.to_json_schema_document(schema)
    assert document.schema == {"type": "string", "pattern": "^item\\.[\\s\\S]*?$"}


@pytest.mark.parametrize(("name", "part"), _TEMPLATES)
def test_template_uses_any_of_when_segment_checks_are_omitted(name: str, part: Any):
    """TemplateLiteral segments / uses anyOf when %s segment checks are omitted"""
    schema = S.Union(part, S.Literal("item.xyz"), mode="one_of")
    assert S.is_(schema)("item.abc")
    assert S.is_(schema)("item.xyz")
    document = S.to_json_schema_document(schema)
    assert "anyOf" in document.schema
    assert "oneOf" not in document.schema


def test_template_uses_any_of_when_numeric_segment_checks_are_omitted():
    """TemplateLiteral segments / uses anyOf when numeric segment checks are omitted"""
    schema = S.Union(S.TemplateLiteral("item.", S.Int), S.Literal("item.1.5"), mode="one_of")
    assert S.is_(schema)("item.1")
    assert S.is_(schema)("item.1.5")
    document = S.to_json_schema_document(schema)
    assert "anyOf" in document.schema
    assert "oneOf" not in document.schema


@pytest.mark.parametrize("name", ["unnamed", "named"])
def test_template_uses_any_of_when_segments_lose_one_of_exclusivity(name: str):
    """TemplateLiteral segments / uses anyOf when %s segments lose oneOf exclusivity"""
    segment = S.Union(S.String, S.Literal("abc"), mode="one_of")
    part = segment.annotate(identifier="Segment") if name == "named" else segment
    template = S.TemplateLiteral("item.", part)
    schema = S.Union(template, S.Literal("item.abc"), mode="one_of")
    assert not S.is_(template)("item.abc")
    assert S.is_(schema)("item.abc")
    assert S.is_(schema)("item.xyz")
    document = S.to_json_schema_document(schema)
    assert "anyOf" in document.schema
    assert "oneOf" not in document.schema
    if name == "named":
        assert "oneOf" in document.definitions["Segment"]


_EMPTY_ANY_OF: S.UnionSchema[str, str, Never, Never] = S.Union()
_EMPTY_ONE_OF: S.UnionSchema[str, str, Never, Never] = S.Union(mode="one_of")
_EMPTY_SEGMENTS: list[S.Codec[str, str]] = [
    _EMPTY_ANY_OF,
    _EMPTY_ANY_OF.annotate(identifier="EmptySegment"),
    _EMPTY_ONE_OF,
    _EMPTY_ONE_OF.annotate(identifier="EmptySegment"),
]


@pytest.mark.parametrize("part", _EMPTY_SEGMENTS)
def test_template_empty_union_preserves_surrounding_one_of(part: S.Codec[str, str]):
    """TemplateLiteral segments / empty union segments / preserves surrounding oneOf for %s"""
    template = S.TemplateLiteral("item.", part)
    schema = S.Union(template, S.Literal("item."), mode="one_of")
    assert not S.is_(template)("item.")
    assert S.is_(schema)("item.")
    assert not S.is_(schema)("item.abc")
    document = S.to_json_schema_document(schema)
    assert "oneOf" in document.schema
    assert "anyOf" not in document.schema


@pytest.mark.parametrize("part", _EMPTY_SEGMENTS)
def test_template_empty_union_does_not_select_record_keys(part: S.Codec[str, str]):
    """TemplateLiteral segments / empty union segments / does not select record keys for %s"""
    schema = S.Record(S.TemplateLiteral("item.", part), S.Finite)
    assert S.decode_unknown_sync(schema)({"item.": "ignored"}) == {}
    assert "patternProperties" in S.to_json_schema_document(schema).schema


@pytest.mark.parametrize("part", [S.String, S.Union(S.String, S.Literal("abc"))])
def test_template_keeps_one_of_when_segment_is_exported_exactly(part: S.Codec[str, str]):
    """TemplateLiteral segments / keeps oneOf when the %s segment is exported exactly"""
    schema = S.Union(S.TemplateLiteral("item.", part), S.Literal("item.xyz"), mode="one_of")
    assert S.is_(schema)("item.abc")
    assert not S.is_(schema)("item.xyz")
    assert "oneOf" in S.to_json_schema_document(schema).schema


_ITEM_KEYS = {"type": "string", "pattern": "^item\\.[\\s\\S]*?$"}
_RECORD_DEFINITIONS: dict[str, dict[str, Any]] = {
    "named": {"Segment": {"type": "string"}},
    "named template": {"Item": _ITEM_KEYS},
}


@pytest.mark.parametrize(("name", "part"), _TEMPLATES)
def test_template_record_value_checks_skip_keys_outside_the_template(name: str, part: Any):
    """TemplateLiteral segments / does not apply record value checks to keys outside the %s filtered template"""  # noqa: E501
    # Effect's test expects ``{"type": "object"}``; Effect under Node writes
    # the approximate key pattern as ``propertyNames``, as pyfect does.
    schema = S.Record(part, S.Finite)
    decoded = S.decode_unknown_sync(schema)({"item.abc": 1, "item.xyz": "ignored"})
    assert decoded == {"item.abc": 1}
    names = (
        {"type": "string", "pattern": "^item\\.(?:[\\s\\S]*?|def)$"}
        if name == "union"
        else _ITEM_KEYS
    )
    _check(
        schema,
        {"type": "object", "propertyNames": names, "additionalProperties": {"type": "number"}},
        _RECORD_DEFINITIONS.get(name),
    )


def test_record_template_literal_and_annotate():
    """Record(`a${string}`, Number) & annotate"""
    _check(
        S.Record(S.TemplateLiteral("a", S.String), S.Finite),
        {
            "type": "object",
            "patternProperties": {"^a[\\s\\S]*?$": {"type": "number"}},
            "additionalProperties": False,
        },
    )


def test_on_excess_property_applies_to_properties_not_covered_by_pattern_properties():
    """onExcessProperty / applies to properties not covered by patternProperties"""
    _check(
        S.Record(S.TemplateLiteral("x-", S.String), S.Number),
        {
            "type": "object",
            "patternProperties": {"^x-[\\s\\S]*?$": _NUMBER},
            "additionalProperties": False,
        },
    )


# --- Titles the module once listed as omitted.

_STRING: JsonSchema = {"type": "string"}


class _NullableA(TypedDict):
    a: str | None


def test_struct_undefined_or_string_to_string():
    """Struct / UndefinedOr / UndefinedOr(String) to String"""
    # ``UndefinedOr`` is ``NullOr`` here (section 4); ``s ?? ""`` is ``s or ""``.
    field = S.String.pipe(
        S.decode_to(
            S.NullOr(S.String),
            T.Transformation(G.passthrough_subtype(), G.transform(lambda s: s or "")),
        )
    )
    _check(S.Struct(_NullableA, a=field), _object_a(_STRING))


class _Shapes(TypedDict):
    a: str
    b: str | None
    c: NotRequired[str]
    d: NotRequired[str | None]
    e: str | None


def _or_else_null(o: Option[str]) -> Option[str | None]:
    """``Option.orElseSome(() => null)``."""
    return Some(None) if o is None else o


def _not_null(o: Option[str | None]) -> Option[str]:
    """``Option.filter(Predicate.isNotNull)``."""
    return None if o is None or o.value is None else Some(o.value)


def test_reuses_one_definition_for_an_identified_ast_in_different_shapes():
    """reuses one definition when the same identified AST appears in different schema shapes"""
    x = S.String.annotate(title="X", identifier="X")
    e = S.NullOr(x).pipe(
        S.encode_to(
            S.optional_key(x),
            T.Transformation(G.transform_optional(_or_else_null), G.transform_optional(_not_null)),
        )
    )
    ref: JsonSchema = {"$ref": "#/$defs/X"}
    nullable: JsonSchema = {"anyOf": [ref, {"type": "null"}]}
    _check(
        S.Struct(_Shapes, a=x, b=S.NullOr(x), c=x, d=S.NullOr(x), e=e),
        {
            "type": "object",
            "properties": {"a": ref, "b": nullable, "c": ref, "d": nullable, "e": ref},
            "required": ["a", "b"],
            "additionalProperties": False,
        },
        {"X": {"type": "string", "title": "X"}},
    )


def test_mutable_json():
    """MutableJson"""
    # ``S.Json`` is already mutable (section 4: ``MutableJson`` is ``S.Json``).
    _check(S.Json, {})


def test_json_object():
    """Record / JsonObject"""
    _check(S.JsonObject, {"type": "object"})


def test_date():
    """Declaration / Date"""
    # ``Schema.Date`` is ``S.DateTimeUtc`` (section 4).
    _check(S.DateTimeUtc, {"type": "string"})


class _GoFields(TypedDict):
    a: str
    b: NotRequired[float]
    c: tuple[str, ...]


def test_to_codec_go_json_describes_the_nil_values_written_by_go_as_null():
    """toCodecGoJson / describes the nil values written by Go as null"""
    schema = S.to_codec_go_json(S.Struct(_GoFields, b=S.FiniteFromString, c=S.Array(S.String)))
    _check(
        schema,
        {
            "type": "object",
            "properties": {
                "a": _STRING,
                "b": {"anyOf": [_STRING, {"type": "null"}]},
                "c": {"anyOf": [{"type": "array", "items": _STRING}, {"type": "null"}]},
            },
            "required": ["a", "c"],
            "additionalProperties": False,
        },
    )


class _GoNode(TypedDict):
    Children: tuple["_GoNode", ...]


def test_to_codec_go_json_describes_recursive_schemas():
    """toCodecGoJson / describes recursive schemas"""
    node: Any = None
    node = S.Struct(_GoNode, Children=S.Array(S.suspend(lambda: node))).annotate(identifier="Node")
    _check(
        S.to_codec_go_json(node),
        {"$ref": "#/$defs/Node"},
        {
            "Node": {
                "type": "object",
                "properties": {
                    "Children": {
                        "anyOf": [
                            {"type": "array", "items": {"$ref": "#/$defs/Node"}},
                            {"type": "null"},
                        ]
                    }
                },
                "required": ["Children"],
                "additionalProperties": False,
            }
        },
    )


# --- optional on the type side only ------------------------------------------------------


def _or_empty() -> T.Transformation[str, str]:
    """``{ decode: passthrough(), encode: withDefault(Effect.succeed("")) }``."""
    return T.Transformation(G.passthrough(), G.with_default(fx.succeed("")))


class _OptionalNullableA(TypedDict):
    a: NotRequired[str | None]


def test_struct_optional_key_string_to_string():
    """Struct / optionalKey / optionalKey(String) to String"""
    field = S.optional_key(S.String).pipe(S.encode_to(S.String, _or_empty()))
    schema = S.Struct(_OptionalA, a=field.schema)
    _check(schema, _object_a(_STRING))
    assert S.decode_unknown_sync(schema)({}) == {}
    assert S.encode_sync(schema)({}) == {"a": ""}


def test_struct_optional_string_to_string():
    """Struct / optional / optional(String) to String"""
    # ``optional`` is ``optional_key`` of ``NullOr`` here (section 4).
    transformation: T.Transformation[str | None, str] = T.Transformation(
        G.passthrough_supertype(), G.with_default(fx.succeed(""))
    )
    field = S.optional_key(S.NullOr(S.String)).pipe(S.encode_to(S.String, transformation))
    schema = S.Struct(_OptionalNullableA, a=field.schema)
    _check(schema, _object_a(_STRING))
    assert S.encode_sync(schema)({}) == {"a": ""}


def _optional_element_to_string() -> S.Codec[tuple[str, ...], tuple[str, ...]]:
    return S.Tuple(S.optional_key(S.String).pipe(S.encode_to(S.String, _or_empty())))


def test_tuple_optional_key_string_to_string():
    """Tuple / optionalKey / optionalKey(String) to String"""
    schema = _optional_element_to_string()
    _check(schema, {"type": "array", "prefixItems": [_STRING], "minItems": 1, "maxItems": 1})
    assert S.decode_unknown_sync(schema)(()) == ()
    assert S.encode_sync(schema)(()) == ("",)


def test_tuple_optional_key_to_required_key():
    """Tuple / optionalKey to required key"""
    _check(
        _optional_element_to_string(),
        {"type": "array", "prefixItems": [_STRING], "minItems": 1, "maxItems": 1},
    )
