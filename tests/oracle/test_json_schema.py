"""Ports of Effect's ``JsonSchema.test.ts``. Each test's docstring is the
Effect test title, prefixed by its ``describe`` blocks.

Every expected value was printed by Effect: the test file was run under Node
with each ``JsonSchema`` call recorded (its input, and its result or error
message), and each recorded call is replayed here against pyfect. Each call
is also checked not to mutate its input. A ``Document`` compares as Effect's
``{dialect, schema, definitions}`` object.

Python mappings: Effect's thrown ``Error`` is a ``ValueError`` with the same
message; Effect's camel-case names are snake case
(``fromSchemaDraft2020_12`` is ``from_schema_draft_2020_12``).

Omitted: the Ajv assertions inside the titles (``validateSchema`` and
``compile(...)(value)``, which check that a converted schema accepts the
same values): pyfect has no JSON Schema validator. The conversions those
titles make are replayed.
"""

import copy
from collections.abc import Callable
from typing import cast

import pytest

from pyfect import json_schema
from pyfect.json_patch import JsonValue
from pyfect.json_schema import Document, JsonSchema, MultiDocument


def _to_json(value: object) -> object:
    if isinstance(value, Document):
        document = cast("Document[json_schema.Dialect]", value)
        return {
            "dialect": document.dialect,
            "schema": document.schema,
            "definitions": document.definitions,
        }
    if isinstance(value, MultiDocument):
        multi = cast("MultiDocument[json_schema.Dialect]", value)
        return {
            "dialect": multi.dialect,
            "schemas": list(multi.schemas),
            "definitions": multi.definitions,
        }
    return value


def _document(arg: object) -> Document[json_schema.Dialect]:
    fields = cast("dict[str, object]", arg)
    return Document(
        cast("json_schema.Dialect", fields["dialect"]),
        cast("JsonSchema", fields["schema"]),
        cast("json_schema.Definitions", fields["definitions"]),
    )


def _multi_document(arg: object) -> MultiDocument[json_schema.Dialect]:
    fields = cast("dict[str, object]", arg)
    return MultiDocument(
        cast("json_schema.Dialect", fields["dialect"]),
        tuple(cast("list[JsonSchema]", fields["schemas"])),
        cast("json_schema.Definitions", fields["definitions"]),
    )


def _call(name: str, arg: object) -> Callable[[], object]:
    f = cast("Callable[[object], object]", getattr(json_schema, name))
    if name.startswith("to_document"):
        document = _document(arg)
        return lambda: f(document)
    if name.startswith("to_multi_document"):
        multi = _multi_document(arg)
        return lambda: f(multi)
    return lambda: f(arg)


def _check(name: str, arg: JsonValue, expected: JsonValue) -> None:
    before = copy.deepcopy(arg)
    assert _to_json(_call(name, arg)()) == expected
    assert arg == before


def _raises(name: str, arg: JsonValue, message: str) -> None:
    with pytest.raises(ValueError) as info:
        _call(name, arg)()
    assert str(info.value) == message


def test_meta_schema_uris():
    """meta-schema URIs / exports the URI for every supported dialect"""
    assert json_schema.META_SCHEMA_URI_DRAFT_04 == "http://json-schema.org/draft-04/schema#"
    assert json_schema.META_SCHEMA_URI_DRAFT_07 == "http://json-schema.org/draft-07/schema#"
    assert (
        json_schema.META_SCHEMA_URI_DRAFT_2020_12 == "https://json-schema.org/draft/2020-12/schema"
    )


def test_sanitizeopenapicomponentsschemaskey_returns_for_empty_input():
    """sanitizeOpenApiComponentsSchemasKey / returns '_' for empty input"""
    _check("sanitize_open_api_components_schemas_key", "", "_")


def test_sanitizeopenapicomponentsschemaskey_returns_input_when_alrea():
    """sanitizeOpenApiComponentsSchemasKey / returns input when already valid"""
    _check("sanitize_open_api_components_schemas_key", "Simple", "Simple")
    _check("sanitize_open_api_components_schemas_key", "with-dash", "with-dash")
    _check("sanitize_open_api_components_schemas_key", "with_underscore", "with_underscore")
    _check("sanitize_open_api_components_schemas_key", "with.dot", "with.dot")
    _check("sanitize_open_api_components_schemas_key", "A1.B2-_", "A1.B2-_")


def test_sanitizeopenapicomponentsschemaskey_replaces_invalid_charact():
    """sanitizeOpenApiComponentsSchemasKey / replaces invalid characters with '_'"""
    _check("sanitize_open_api_components_schemas_key", "a b", "a_b")
    _check("sanitize_open_api_components_schemas_key", "a/b", "a_b")
    _check("sanitize_open_api_components_schemas_key", "a:b", "a_b")
    _check("sanitize_open_api_components_schemas_key", "a@b", "a_b")
    _check("sanitize_open_api_components_schemas_key", "a#b", "a_b")
    _check("sanitize_open_api_components_schemas_key", "a?b", "a_b")
    _check("sanitize_open_api_components_schemas_key", "a+b", "a_b")
    _check("sanitize_open_api_components_schemas_key", "a*b", "a_b")
    _check("sanitize_open_api_components_schemas_key", "a,b", "a_b")
    _check("sanitize_open_api_components_schemas_key", "a;b", "a_b")
    _check("sanitize_open_api_components_schemas_key", "a|b", "a_b")
    _check("sanitize_open_api_components_schemas_key", "a=b", "a_b")


def test_sanitizeopenapicomponentsschemaskey_preserves_length_when_on():
    """sanitizeOpenApiComponentsSchemasKey / preserves length when only replacements are needed"""
    _check("sanitize_open_api_components_schemas_key", "a b", "a_b")
    _check("sanitize_open_api_components_schemas_key", "..", "..")
    _check("sanitize_open_api_components_schemas_key", "a--b", "a--b")


def test_sanitizeopenapicomponentsschemaskey_replaces_non_ascii_chara():
    """sanitizeOpenApiComponentsSchemasKey / replaces non-ascii characters with '_'"""
    _check("sanitize_open_api_components_schemas_key", "café", "caf_")
    _check("sanitize_open_api_components_schemas_key", "你好", "__")
    _check("sanitize_open_api_components_schemas_key", "🤖", "_")
    _check("sanitize_open_api_components_schemas_key", "a🤖b", "a_b")


def test_sanitizeopenapicomponentsschemaskey_is_idempotent():
    """sanitizeOpenApiComponentsSchemasKey / is idempotent"""
    _check("sanitize_open_api_components_schemas_key", "", "_")
    _check("sanitize_open_api_components_schemas_key", "_", "_")
    _check("sanitize_open_api_components_schemas_key", "Simple", "Simple")
    _check("sanitize_open_api_components_schemas_key", "Simple", "Simple")
    _check("sanitize_open_api_components_schemas_key", "a b", "a_b")
    _check("sanitize_open_api_components_schemas_key", "a_b", "a_b")
    _check("sanitize_open_api_components_schemas_key", "a/b", "a_b")
    _check("sanitize_open_api_components_schemas_key", "a_b", "a_b")
    _check("sanitize_open_api_components_schemas_key", "a..b", "a..b")
    _check("sanitize_open_api_components_schemas_key", "a..b", "a..b")
    _check("sanitize_open_api_components_schemas_key", "café", "caf_")
    _check("sanitize_open_api_components_schemas_key", "caf_", "caf_")
    _check("sanitize_open_api_components_schemas_key", "🤖", "_")
    _check("sanitize_open_api_components_schemas_key", "_", "_")
    _check("sanitize_open_api_components_schemas_key", "A1.B2-_", "A1.B2-_")
    _check("sanitize_open_api_components_schemas_key", "A1.B2-_", "A1.B2-_")


def test_fromschemadraft07_rewrites_the_draft_07_meta_schema_uri_with():
    """fromSchemaDraft07 / rewrites the Draft-07 meta-schema URI without an empty fragment"""
    _check(
        "from_schema_draft_07",
        {"$schema": "http://json-schema.org/draft-07/schema"},
        {
            "dialect": "draft-2020-12",
            "schema": {"$schema": "https://json-schema.org/draft/2020-12/schema"},
            "definitions": {},
        },
    )


def test_fromschemadraft07_preserves_all_draft_07_semantics_and_opaqu():
    """fromSchemaDraft07 / preserves all Draft-07 semantics and opaque custom keywords"""
    _check(
        "from_schema_draft_07",
        {
            "if": {"properties": {"kind": {"const": "full"}}},
            "then": {"required": ["value"]},
            "else": {"not": {"required": ["value"]}},
            "contains": {"type": "number"},
            "dependencies": {"enabled": ["value"], "kind": {"required": ["label"]}},
            "x-custom": {"$ref": "#/definitions/Literal"},
        },
        {
            "dialect": "draft-2020-12",
            "schema": {
                "if": {"properties": {"kind": {"const": "full"}}},
                "then": {"required": ["value"]},
                "else": {"not": {"required": ["value"]}},
                "contains": {"type": "number"},
                "dependentRequired": {"enabled": ["value"]},
                "dependentSchemas": {"kind": {"required": ["label"]}},
                "x-custom": {"$ref": "#/definitions/Literal"},
            },
            "definitions": {},
        },
    )


def test_fromschemadraft07_preserves_draft_07_validation_semantics_in():
    """fromSchemaDraft07 / preserves Draft-07 validation semantics in the canonical dialect"""
    _check(
        "from_schema_draft_07",
        {
            "type": "object",
            "properties": {
                "kind": {"enum": ["full", "compact"]},
                "value": {"type": "string"},
                "extra": True,
                "values": {"type": "array", "contains": {"type": "number"}},
            },
            "required": ["kind", "values"],
            "dependencies": {"value": ["extra"]},
            "if": {"properties": {"kind": {"const": "full"}}},
            "then": {"required": ["value"]},
            "else": {"not": {"required": ["value"]}},
        },
        {
            "dialect": "draft-2020-12",
            "schema": {
                "type": "object",
                "properties": {
                    "kind": {"enum": ["full", "compact"]},
                    "value": {"type": "string"},
                    "extra": True,
                    "values": {"type": "array", "contains": {"type": "number"}},
                },
                "required": ["kind", "values"],
                "dependentRequired": {"value": ["extra"]},
                "if": {"properties": {"kind": {"const": "full"}}},
                "then": {"required": ["value"]},
                "else": {"not": {"required": ["value"]}},
            },
            "definitions": {},
        },
    )


def test_fromschemadraft07_converts_draft_07_plain_name_identifiers_t():
    """fromSchemaDraft07 / converts Draft-07 plain-name identifiers to canonical anchors"""
    _check(
        "from_schema_draft_07",
        {"$id": "https://example.com/node#entry", "type": "string"},
        {
            "dialect": "draft-2020-12",
            "schema": {"$id": "https://example.com/node", "$anchor": "entry", "type": "string"},
            "definitions": {},
        },
    )


def test_fromschemadraft07_converts_canonical_anchors_without_schema():
    """fromSchemaDraft07 / converts canonical anchors without schema identifiers"""
    _check(
        "to_document_draft_07",
        {"dialect": "draft-2020-12", "schema": {"$anchor": "entry"}, "definitions": {}},
        {"dialect": "draft-07", "schema": {"$id": "#entry"}, "definitions": {}},
    )
    _check(
        "to_document_draft_04",
        {"dialect": "draft-2020-12", "schema": {"$anchor": "entry"}, "definitions": {}},
        {"dialect": "draft-04", "schema": {"id": "#entry"}, "definitions": {}},
    )


def test_fromschemadraft07_rejects_canonical_anchors_combined_with_sc():
    """fromSchemaDraft07 / rejects canonical anchors combined with schema identifiers"""
    _raises(
        "to_document_draft_07",
        {
            "dialect": "draft-2020-12",
            "schema": {"$id": "https://example.com/node", "$anchor": "entry"},
            "definitions": {},
        },
        'Cannot convert JSON Schema keyword "$anchor" to Draft-07: it cannot be combined with the schema $id',  # noqa: E501
    )
    _raises(
        "to_document_draft_04",
        {
            "dialect": "draft-2020-12",
            "schema": {"$id": "https://example.com/node", "$anchor": "entry"},
            "definitions": {},
        },
        'Cannot convert JSON Schema keyword "$anchor" to Draft-04: it cannot be combined with the schema $id',  # noqa: E501
    )
    _raises(
        "to_document_draft_07",
        {
            "dialect": "draft-2020-12",
            "schema": {"$id": "https://example.com/node#", "$anchor": "entry"},
            "definitions": {},
        },
        'Cannot convert JSON Schema keyword "$anchor" to Draft-07: it cannot be combined with the schema $id',  # noqa: E501
    )
    _raises(
        "to_document_draft_04",
        {
            "dialect": "draft-2020-12",
            "schema": {"$id": "https://example.com/node#", "$anchor": "entry"},
            "definitions": {},
        },
        'Cannot convert JSON Schema keyword "$anchor" to Draft-04: it cannot be combined with the schema $id',  # noqa: E501
    )


def test_fromschemadraft07_rejects_canonical_anchors_that_cannot_beco():
    """fromSchemaDraft07 / rejects canonical anchors that cannot become legacy plain-name identifiers"""  # noqa: E501
    _raises(
        "to_document_draft_07",
        {"dialect": "draft-2020-12", "schema": {"$anchor": "_node"}, "definitions": {}},
        'Cannot convert JSON Schema keyword "$anchor" to Draft-07: the anchor cannot be represented as a plain-name fragment identifier',  # noqa: E501
    )
    _raises(
        "to_document_draft_04",
        {"dialect": "draft-2020-12", "schema": {"$anchor": "_node"}, "definitions": {}},
        'Cannot convert JSON Schema keyword "$anchor" to Draft-04: the anchor cannot be represented as a plain-name fragment identifier',  # noqa: E501
    )


def test_fromschemadraft07_rejects_draft_07_identifiers_with_fragment():
    """fromSchemaDraft07 / rejects Draft-07 identifiers with fragments that cannot become anchors"""
    _raises(
        "from_schema_draft_07",
        {"$id": "https://example.com/node#not/a/plain-name"},
        'Cannot convert JSON Schema keyword "$id" to Draft 2020-12: fragment "#not/a/plain-name" is not a valid $anchor',  # noqa: E501
    )


def test_fromschemadraft07_rejects_draft_07_custom_keywords_that_woul():
    """fromSchemaDraft07 / rejects Draft-07 custom keywords that would become active in the canonical dialect"""  # noqa: E501
    _raises(
        "from_schema_draft_07",
        {"dependentRequired": {"value": ["other"]}},
        'Cannot convert JSON Schema keyword "dependentRequired" to Draft 2020-12: it is not active in Draft-07 but would become active in the target',  # noqa: E501
    )
    _raises(
        "from_schema_draft_07",
        {"$vocabulary": {"https://example.com/vocabulary": True}},
        'Cannot convert JSON Schema keyword "$vocabulary" to Draft 2020-12: it is not active in Draft-07 but would become active in the target',  # noqa: E501
    )
    _raises(
        "from_schema_draft_07",
        {"contentSchema": {}},
        'Cannot convert JSON Schema keyword "contentSchema" to Draft 2020-12: it is not active in Draft-07 but would become active in the target',  # noqa: E501
    )
    _raises(
        "from_schema_draft_07",
        {"deprecated": True},
        'Cannot convert JSON Schema keyword "deprecated" to Draft 2020-12: it is not active in Draft-07 but would become active in the target',  # noqa: E501
    )


def test_fromschemadraft07_preserves_not():
    """fromSchemaDraft07 / preserves not"""
    _check(
        "from_schema_draft_07",
        {"not": {"type": "string"}},
        {"dialect": "draft-2020-12", "schema": {"not": {"type": "string"}}, "definitions": {}},
    )


def test_fromschemadraft07_normalizes_a_schema_without_definitions_to():
    """fromSchemaDraft07 / normalizes a schema without definitions to the canonical document shape"""  # noqa: E501
    _check(
        "from_schema_draft_07",
        {"type": "string"},
        {"dialect": "draft-2020-12", "schema": {"type": "string"}, "definitions": {}},
    )


def test_fromschemadraft07_extracts_root_definitions_and_rewrites_dra():
    """fromSchemaDraft07 / extracts root definitions and rewrites Draft-07 refs to $defs refs"""
    _check(
        "from_schema_draft_07",
        {
            "type": "object",
            "properties": {"a": {"$ref": "#/definitions/A"}, "b": {"$ref": "#/definitions/B"}},
            "definitions": {
                "A": {"type": "string", "$ref": "#/definitions/B"},
                "B": {"type": "number"},
            },
        },
        {
            "dialect": "draft-2020-12",
            "schema": {
                "type": "object",
                "properties": {"a": {"$ref": "#/$defs/A"}, "b": {"$ref": "#/$defs/B"}},
            },
            "definitions": {"A": {"$ref": "#/$defs/B"}, "B": {"type": "number"}},
        },
    )


def test_fromschemadraft07_ignores_id_next_to_draft_07_refs_when_trac():
    """fromSchemaDraft07 / ignores $id next to Draft-07 refs when tracking resources"""
    _check(
        "from_schema_draft_07",
        {
            "definitions": {
                "Target": {"type": "string"},
                "Reference": {"$id": "nested.json", "$ref": "#/definitions/Target"},
            }
        },
        {
            "dialect": "draft-2020-12",
            "schema": {},
            "definitions": {"Target": {"type": "string"}, "Reference": {"$ref": "#/$defs/Target"}},
        },
    )


def test_fromschemadraft07_converts_draft_07_tuple_items_to_prefixite():
    """fromSchemaDraft07 / converts Draft-07 tuple items to prefixItems"""
    _check(
        "from_schema_draft_07",
        {
            "type": "array",
            "items": [{"type": "string"}, {"type": "number"}],
            "additionalItems": {"type": "boolean"},
        },
        {
            "dialect": "draft-2020-12",
            "schema": {
                "type": "array",
                "prefixItems": [{"type": "string"}, {"type": "number"}],
                "items": {"type": "boolean"},
            },
            "definitions": {},
        },
    )


def test_fromschemadraft07_relocates_refs_into_converted_tuple_items():
    """fromSchemaDraft07 / relocates refs into converted tuple items and schema dependencies"""
    _check(
        "from_schema_draft_07",
        {
            "properties": {
                "container": {
                    "items": [{"type": "string"}],
                    "dependencies": {"value": {"type": "number"}},
                },
                "tupleItem": {"$ref": "#/properties/container/items/0"},
                "dependency": {"$ref": "#/properties/container/dependencies/value"},
            }
        },
        {
            "dialect": "draft-2020-12",
            "schema": {
                "properties": {
                    "container": {
                        "dependentSchemas": {"value": {"type": "number"}},
                        "prefixItems": [{"type": "string"}],
                    },
                    "tupleItem": {"$ref": "#/properties/container/prefixItems/0"},
                    "dependency": {"$ref": "#/properties/container/dependentSchemas/value"},
                }
            },
            "definitions": {},
        },
    )


def test_fromschemadraft07_preserves_a_single_items_schema_as_items():
    """fromSchemaDraft07 / preserves a single items schema as items"""
    _check(
        "from_schema_draft_07",
        {"type": "array", "items": {"type": "string"}},
        {
            "dialect": "draft-2020-12",
            "schema": {"type": "array", "items": {"type": "string"}},
            "definitions": {},
        },
    )


def test_fromschemadraft07_preserves_annotations():
    """fromSchemaDraft07 / preserves annotations"""
    _check(
        "from_schema_draft_07",
        {
            "type": "string",
            "title": "My String",
            "description": "A string value",
            "default": "default",
            "examples": ["example1", "example2"],
            "format": "email",
            "readOnly": True,
            "writeOnly": True,
        },
        {
            "dialect": "draft-2020-12",
            "schema": {
                "type": "string",
                "title": "My String",
                "description": "A string value",
                "default": "default",
                "examples": ["example1", "example2"],
                "format": "email",
                "readOnly": True,
                "writeOnly": True,
            },
            "definitions": {},
        },
    )


def test_fromschemadraft07_preserves_string_constraints():
    """fromSchemaDraft07 / preserves string constraints"""
    _check(
        "from_schema_draft_07",
        {"type": "string", "pattern": "^[a-z]+$", "minLength": 1, "maxLength": 100},
        {
            "dialect": "draft-2020-12",
            "schema": {"type": "string", "pattern": "^[a-z]+$", "minLength": 1, "maxLength": 100},
            "definitions": {},
        },
    )


def test_fromschemadraft07_preserves_number_constraints():
    """fromSchemaDraft07 / preserves number constraints"""
    _check(
        "from_schema_draft_07",
        {
            "type": "number",
            "minimum": 0,
            "maximum": 100,
            "exclusiveMinimum": 0,
            "exclusiveMaximum": 100,
            "multipleOf": 2,
        },
        {
            "dialect": "draft-2020-12",
            "schema": {
                "type": "number",
                "minimum": 0,
                "maximum": 100,
                "exclusiveMinimum": 0,
                "exclusiveMaximum": 100,
                "multipleOf": 2,
            },
            "definitions": {},
        },
    )


def test_fromschemadraft07_preserves_array_constraints():
    """fromSchemaDraft07 / preserves array constraints"""
    _check(
        "from_schema_draft_07",
        {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": 10,
            "uniqueItems": True,
        },
        {
            "dialect": "draft-2020-12",
            "schema": {
                "type": "array",
                "minItems": 1,
                "maxItems": 10,
                "uniqueItems": True,
                "items": {"type": "string"},
            },
            "definitions": {},
        },
    )


def test_fromschemadraft07_preserves_object_constraints():
    """fromSchemaDraft07 / preserves object constraints"""
    _check(
        "from_schema_draft_07",
        {
            "type": "object",
            "properties": {"name": {"type": "string"}, "age": {"type": "number"}},
            "required": ["name"],
            "patternProperties": {"^S_": {"type": "string"}},
            "additionalProperties": {"type": "boolean"},
            "propertyNames": {"pattern": "^[A-Z]"},
            "minProperties": 1,
            "maxProperties": 10,
        },
        {
            "dialect": "draft-2020-12",
            "schema": {
                "type": "object",
                "properties": {"name": {"type": "string"}, "age": {"type": "number"}},
                "required": ["name"],
                "patternProperties": {"^S_": {"type": "string"}},
                "additionalProperties": {"type": "boolean"},
                "propertyNames": {"pattern": "^[A-Z]"},
                "minProperties": 1,
                "maxProperties": 10,
            },
            "definitions": {},
        },
    )


def test_fromschemadraft07_preserves_enum_const_allof_anyof_and_oneof():
    """fromSchemaDraft07 / preserves enum, const, allOf, anyOf, and oneOf"""
    _check(
        "from_schema_draft_07",
        {
            "enum": ["a", "b", "c"],
            "const": "constant",
            "allOf": [{"type": "array", "items": {"type": "string"}}, {"minItems": 1}],
            "anyOf": [{"type": "array", "items": [{"type": "string"}]}, {"type": "number"}],
            "oneOf": [
                {
                    "type": "array",
                    "items": [{"type": "string"}],
                    "additionalItems": {"type": "number"},
                },
                {"type": "boolean"},
            ],
        },
        {
            "dialect": "draft-2020-12",
            "schema": {
                "enum": ["a", "b", "c"],
                "const": "constant",
                "allOf": [{"type": "array", "items": {"type": "string"}}, {"minItems": 1}],
                "anyOf": [
                    {"type": "array", "prefixItems": [{"type": "string"}]},
                    {"type": "number"},
                ],
                "oneOf": [
                    {
                        "type": "array",
                        "prefixItems": [{"type": "string"}],
                        "items": {"type": "number"},
                    },
                    {"type": "boolean"},
                ],
            },
            "definitions": {},
        },
    )


def test_fromschemadraft07_moves_nested_definitions_to_defs_and_reloc():
    """fromSchemaDraft07 / moves nested definitions to $defs and relocates local JSON Pointer refs"""  # noqa: E501
    _check(
        "from_schema_draft_07",
        {
            "type": "object",
            "properties": {
                "nested": {
                    "definitions": {"NestedType": {"type": "number"}},
                    "$ref": "#/properties/nested/definitions/NestedType",
                }
            },
        },
        {
            "dialect": "draft-2020-12",
            "schema": {
                "type": "object",
                "properties": {
                    "nested": {
                        "$defs": {"NestedType": {"type": "number"}},
                        "$ref": "#/properties/nested/$defs/NestedType",
                    }
                },
            },
            "definitions": {},
        },
    )


def test_fromschemadraft07_relocates_fragment_refs_relative_to_nested():
    """fromSchemaDraft07 / relocates fragment refs relative to nested schema resources"""
    _check(
        "from_schema_draft_07",
        {
            "properties": {
                "nested": {
                    "$id": "nested.json",
                    "definitions": {"Value": {"type": "string"}},
                    "allOf": [{"$ref": "#/definitions/Value"}],
                }
            }
        },
        {
            "dialect": "draft-2020-12",
            "schema": {
                "properties": {
                    "nested": {
                        "$id": "nested.json",
                        "$defs": {"Value": {"type": "string"}},
                        "allOf": [{"$ref": "#/$defs/Value"}],
                    }
                }
            },
            "definitions": {},
        },
    )


def test_fromschemadraft07_relocates_uri_refs_to_nested_schema_resour():
    """fromSchemaDraft07 / relocates URI refs to nested schema resources"""
    _check(
        "from_schema_draft_07",
        {
            "$id": "https://example.com/root.json",
            "properties": {"value": {"$ref": "nested.json#/definitions/Value"}},
            "definitions": {
                "Nested": {
                    "$id": "schemas/../nested.json",
                    "definitions": {"Value": {"type": "string"}},
                }
            },
        },
        {
            "dialect": "draft-2020-12",
            "schema": {
                "$id": "https://example.com/root.json",
                "properties": {"value": {"$ref": "nested.json#/$defs/Value"}},
            },
            "definitions": {
                "Nested": {"$id": "schemas/../nested.json", "$defs": {"Value": {"type": "string"}}}
            },
        },
    )


def test_fromschemadraft07_relocates_json_pointer_uri_fragments():
    """fromSchemaDraft07 / relocates JSON Pointer URI fragments"""
    _check(
        "from_schema_draft_07",
        {
            "properties": {
                "value": {"$ref": "#/definitions/a%20b"},
                "equivalent": {"$ref": "#/definitions/%56alue"},
                "encodedSeparators": {"$ref": "#%2Fdefinitions%2FValue"},
                "percent": {"$ref": "#/definitions/a%25b"},
                "escaped": {"$ref": "#/definitions/a~1b"},
                "utf8": {"$ref": "#/definitions/caf%C3%A9"},
                "invalid": {"$ref": "#/%"},
                "invalidUtf8": {"$ref": "#/%FF"},
            },
            "definitions": {
                "a b": {"type": "string"},
                "Value": {"type": "number"},
                "a%b": {"type": "boolean"},
                "a/b": {"type": "object"},
                "café": {"type": "array"},
            },
        },
        {
            "dialect": "draft-2020-12",
            "schema": {
                "properties": {
                    "value": {"$ref": "#/$defs/a%20b"},
                    "equivalent": {"$ref": "#/$defs/Value"},
                    "encodedSeparators": {"$ref": "#/$defs/Value"},
                    "percent": {"$ref": "#/$defs/a%25b"},
                    "escaped": {"$ref": "#/$defs/a~1b"},
                    "utf8": {"$ref": "#/$defs/caf%C3%A9"},
                    "invalid": {"$ref": "#/%"},
                    "invalidUtf8": {"$ref": "#/%FF"},
                }
            },
            "definitions": {
                "a b": {"type": "string"},
                "Value": {"type": "number"},
                "a%b": {"type": "boolean"},
                "a/b": {"type": "object"},
                "café": {"type": "array"},
            },
        },
    )


def test_fromschemadraft07_preserves_custom_properties_in_draft_07_in():
    """fromSchemaDraft07 / preserves custom properties in Draft-07 input"""
    _check(
        "from_schema_draft_07",
        {"type": "string", "x-custom": "value"},
        {
            "dialect": "draft-2020-12",
            "schema": {"type": "string", "x-custom": "value"},
            "definitions": {},
        },
    )


def test_fromschemadraft07_preserves_malformed_values_for_recognized():
    """fromSchemaDraft07 / preserves malformed values for recognized keywords"""
    _check(
        "from_schema_draft_07",
        {
            "$ref": 1,
            "definitions": {"Invalid": [1, {"not": False}]},
            "properties": {
                "nested": {"definitions": "invalid", "not": [False, {"type": "string"}]}
            },
            "patternProperties": "invalid",
            "allOf": "invalid",
        },
        {
            "dialect": "draft-2020-12",
            "schema": {
                "$ref": 1,
                "properties": {"nested": {"$defs": "invalid", "not": [False, {"type": "string"}]}},
                "patternProperties": "invalid",
                "allOf": "invalid",
            },
            "definitions": {"Invalid": [1, {"not": False}]},
        },
    )


def test_fromschemadraft07_ignores_additionalitems_when_items_is_not():
    """fromSchemaDraft07 / ignores additionalItems when items is not a tuple"""
    _check(
        "from_schema_draft_07",
        {"type": "array", "items": {"type": "string"}, "additionalItems": False},
        {
            "dialect": "draft-2020-12",
            "schema": {"type": "array", "items": {"type": "string"}},
            "definitions": {},
        },
    )


def test_fromschemadraft2020_12_normalizes_a_schema_without_defs_to_t():
    """fromSchemaDraft2020_12 / normalizes a schema without $defs to the canonical document shape"""
    _check(
        "from_schema_draft_2020_12",
        {"type": "string"},
        {"dialect": "draft-2020-12", "schema": {"type": "string"}, "definitions": {}},
    )


def test_fromschemadraft2020_12_extracts_root_defs_without_rewriting():
    """fromSchemaDraft2020_12 / extracts root $defs without rewriting Draft-2020-12 refs"""
    _check(
        "from_schema_draft_2020_12",
        {
            "type": "object",
            "properties": {"a": {"$ref": "#/$defs/A"}, "b": {"$ref": "#/$defs/B"}},
            "$defs": {"A": {"type": "string", "$ref": "#/$defs/B"}, "B": {"type": "number"}},
        },
        {
            "dialect": "draft-2020-12",
            "schema": {
                "type": "object",
                "properties": {"a": {"$ref": "#/$defs/A"}, "b": {"$ref": "#/$defs/B"}},
            },
            "definitions": {"A": {"type": "string", "$ref": "#/$defs/B"}, "B": {"type": "number"}},
        },
    )


def test_fromschemadraft2020_12_preserves_nested_definitions_and_loca():
    """fromSchemaDraft2020_12 / preserves nested definitions and local JSON Pointer refs"""
    _check(
        "from_schema_draft_2020_12",
        {
            "type": "object",
            "properties": {
                "nested": {
                    "definitions": {"NestedType": {"type": "number"}},
                    "$ref": "#/properties/nested/definitions/NestedType",
                }
            },
        },
        {
            "dialect": "draft-2020-12",
            "schema": {
                "type": "object",
                "properties": {
                    "nested": {
                        "definitions": {"NestedType": {"type": "number"}},
                        "$ref": "#/properties/nested/definitions/NestedType",
                    }
                },
            },
            "definitions": {},
        },
    )


def test_fromschemadraft2020_12_keeps_non_standard_properties_for_dra():
    """fromSchemaDraft2020_12 / keeps non-standard properties for Draft-2020-12 input"""
    _check(
        "from_schema_draft_2020_12",
        {"type": "string", "x-custom": "value"},
        {
            "dialect": "draft-2020-12",
            "schema": {"type": "string", "x-custom": "value"},
            "definitions": {},
        },
    )


def test_fromschemaopenapi3_1_normalizes_the_openapi_3_1_base_dialect():
    """fromSchemaOpenApi3_1 / normalizes the OpenAPI 3.1 base dialect URI"""
    _check(
        "from_schema_open_api_3_1",
        {"$schema": "https://spec.openapis.org/oas/3.1/dialect/base"},
        {
            "dialect": "draft-2020-12",
            "schema": {"$schema": "https://json-schema.org/draft/2020-12/schema"},
            "definitions": {},
        },
    )


def test_fromschemaopenapi3_1_preserves_non_string_refs_and_malformed():
    """fromSchemaOpenApi3_1 / preserves non-string refs and malformed schema maps"""
    _check(
        "from_schema_open_api_3_1",
        {"$ref": None, "enum": [None], "properties": [{"$ref": "#/components/schemas/Literal"}]},
        {
            "dialect": "draft-2020-12",
            "schema": {
                "$ref": None,
                "enum": [None],
                "properties": [{"$ref": "#/components/schemas/Literal"}],
            },
            "definitions": {},
        },
    )


def test_fromschemaopenapi3_1_rewrites_openapi_component_schema_refs():
    """fromSchemaOpenApi3_1 / rewrites OpenAPI component schema refs to $defs refs"""
    _check(
        "from_schema_open_api_3_1",
        {
            "type": "object",
            "properties": {
                "a": {"$ref": "#/components/schemas/A"},
                "b": {"$ref": "#/components/schemas/B"},
                "dynamic": {"$dynamicRef": "#/components/schemas/Dynamic"},
            },
        },
        {
            "dialect": "draft-2020-12",
            "schema": {
                "type": "object",
                "properties": {
                    "a": {"$ref": "#/$defs/A"},
                    "b": {"$ref": "#/$defs/B"},
                    "dynamic": {"$dynamicRef": "#/$defs/Dynamic"},
                },
            },
            "definitions": {},
        },
    )


def test_fromschemaopenapi3_1_rewrites_percent_encoded_openapi_compon():
    """fromSchemaOpenApi3_1 / rewrites percent-encoded OpenAPI component refs"""
    _check(
        "from_schema_open_api_3_1",
        {"$ref": "#%2Fcomponents%2Fschemas%2FA%20B"},
        {"dialect": "draft-2020-12", "schema": {"$ref": "#/$defs/A%20B"}, "definitions": {}},
    )


def test_fromschemaopenapi3_1_normalizes_singular_examples_throughout():
    """fromSchemaOpenApi3_1 / normalizes singular examples throughout OpenAPI 3.1 schemas"""
    _check(
        "from_schema_open_api_3_1",
        {"example": "root", "properties": {"value": {"example": "nested"}}},
        {
            "dialect": "draft-2020-12",
            "schema": {"properties": {"value": {"examples": ["nested"]}}, "examples": ["root"]},
            "definitions": {},
        },
    )


def test_fromschemaopenapi3_1_merges_singular_and_array_examples_in_o():
    """fromSchemaOpenApi3_1 / merges singular and array examples in OpenAPI 3.1 schemas"""
    _check(
        "from_schema_open_api_3_1",
        {"example": "singular", "examples": ["first", "second"]},
        {
            "dialect": "draft-2020-12",
            "schema": {"examples": ["singular", "first", "second"]},
            "definitions": {},
        },
    )


def test_fromschemaopenapi3_1_rewrites_refs_only_in_schema_positions():
    """fromSchemaOpenApi3_1 / rewrites refs only in schema positions"""
    _check(
        "from_schema_open_api_3_1",
        {
            "properties": {"value": {"$ref": "#/components/schemas/Value"}},
            "const": {"$ref": "#/components/schemas/Literal"},
            "enum": [{"$ref": "#/components/schemas/Literal"}],
            "default": {"$ref": "#/components/schemas/Literal"},
            "examples": [{"$ref": "#/components/schemas/Literal"}],
        },
        {
            "dialect": "draft-2020-12",
            "schema": {
                "properties": {"value": {"$ref": "#/$defs/Value"}},
                "const": {"$ref": "#/components/schemas/Literal"},
                "enum": [{"$ref": "#/components/schemas/Literal"}],
                "default": {"$ref": "#/components/schemas/Literal"},
                "examples": [{"$ref": "#/components/schemas/Literal"}],
            },
            "definitions": {},
        },
    )


def test_fromschemaopenapi3_1_rewrites_refs_throughout_draft_2020_12():
    """fromSchemaOpenApi3_1 / rewrites refs throughout Draft 2020-12 subschemas"""
    _check(
        "from_schema_open_api_3_1",
        {
            "$defs": {"Alias": {"$ref": "#/components/schemas/Value"}},
            "properties": {"value": {"$ref": "#/components/schemas/Value"}},
            "patternProperties": {"pattern": {"$ref": "#/components/schemas/Value"}},
            "dependentSchemas": {"dependency": {"$ref": "#/components/schemas/Value"}},
            "allOf": [{"$ref": "#/components/schemas/Value"}],
            "anyOf": [{"$ref": "#/components/schemas/Value"}],
            "oneOf": [{"$ref": "#/components/schemas/Value"}],
            "prefixItems": [{"$ref": "#/components/schemas/Value"}],
            "additionalProperties": {"$ref": "#/components/schemas/Value"},
            "unevaluatedProperties": {"$ref": "#/components/schemas/Value"},
            "propertyNames": {"$ref": "#/components/schemas/Value"},
            "items": {"$ref": "#/components/schemas/Value"},
            "contains": {"$ref": "#/components/schemas/Value"},
            "unevaluatedItems": {"$ref": "#/components/schemas/Value"},
            "not": {"$ref": "#/components/schemas/Value"},
            "if": {"$ref": "#/components/schemas/Value"},
            "then": {"$ref": "#/components/schemas/Value"},
            "else": {"$ref": "#/components/schemas/Value"},
            "contentSchema": {"$ref": "#/components/schemas/Value"},
        },
        {
            "dialect": "draft-2020-12",
            "schema": {
                "properties": {"value": {"$ref": "#/$defs/Value"}},
                "patternProperties": {"pattern": {"$ref": "#/$defs/Value"}},
                "dependentSchemas": {"dependency": {"$ref": "#/$defs/Value"}},
                "allOf": [{"$ref": "#/$defs/Value"}],
                "anyOf": [{"$ref": "#/$defs/Value"}],
                "oneOf": [{"$ref": "#/$defs/Value"}],
                "prefixItems": [{"$ref": "#/$defs/Value"}],
                "additionalProperties": {"$ref": "#/$defs/Value"},
                "unevaluatedProperties": {"$ref": "#/$defs/Value"},
                "propertyNames": {"$ref": "#/$defs/Value"},
                "items": {"$ref": "#/$defs/Value"},
                "contains": {"$ref": "#/$defs/Value"},
                "unevaluatedItems": {"$ref": "#/$defs/Value"},
                "not": {"$ref": "#/$defs/Value"},
                "if": {"$ref": "#/$defs/Value"},
                "then": {"$ref": "#/$defs/Value"},
                "else": {"$ref": "#/$defs/Value"},
                "contentSchema": {"$ref": "#/$defs/Value"},
            },
            "definitions": {"Alias": {"$ref": "#/$defs/Value"}},
        },
    )


def test_fromschemaopenapi3_1_does_not_rewrite_refs_inside_root_schem():
    """fromSchemaOpenApi3_1 / does not rewrite refs inside root schema resources"""
    _check(
        "from_schema_open_api_3_1",
        {
            "$id": "inline.json",
            "allOf": [
                {"$ref": "#/components/schemas/Value"},
                {"$dynamicRef": "#/components/schemas/Value"},
            ],
        },
        {
            "dialect": "draft-2020-12",
            "schema": {
                "$id": "inline.json",
                "allOf": [
                    {"$ref": "#/components/schemas/Value"},
                    {"$dynamicRef": "#/components/schemas/Value"},
                ],
            },
            "definitions": {},
        },
    )


def test_fromschemaopenapi3_1_extracts_root_defs_after_rewriting_open():
    """fromSchemaOpenApi3_1 / extracts root $defs after rewriting OpenAPI component refs"""
    _check(
        "from_schema_open_api_3_1",
        {
            "type": "object",
            "properties": {"a": {"$ref": "#/components/schemas/A"}},
            "$defs": {"MyType": {"type": "string"}},
        },
        {
            "dialect": "draft-2020-12",
            "schema": {"type": "object", "properties": {"a": {"$ref": "#/$defs/A"}}},
            "definitions": {"MyType": {"type": "string"}},
        },
    )


def test_fromschemaopenapi3_1_preserves_nested_definitions_and_local():
    """fromSchemaOpenApi3_1 / preserves nested definitions and local JSON Pointer refs"""
    _check(
        "from_schema_open_api_3_1",
        {
            "type": "object",
            "properties": {
                "nested": {
                    "definitions": {"NestedType": {"type": "number"}},
                    "$ref": "#/properties/nested/definitions/NestedType",
                }
            },
        },
        {
            "dialect": "draft-2020-12",
            "schema": {
                "type": "object",
                "properties": {
                    "nested": {
                        "definitions": {"NestedType": {"type": "number"}},
                        "$ref": "#/properties/nested/definitions/NestedType",
                    }
                },
            },
            "definitions": {},
        },
    )


def test_fromschemaopenapi3_1_keeps_non_standard_properties_for_opena():
    """fromSchemaOpenApi3_1 / keeps non-standard properties for OpenAPI 3.1 input"""
    _check(
        "from_schema_open_api_3_1",
        {"type": "string", "x-custom": "value"},
        {
            "dialect": "draft-2020-12",
            "schema": {"type": "string", "x-custom": "value"},
            "definitions": {},
        },
    )


def test_fromschemaopenapi3_0_rewrites_openapi_3_0_component_schema_r():
    """fromSchemaOpenApi3_0 / rewrites OpenAPI 3.0 component schema refs to $defs refs"""
    _check(
        "from_schema_open_api_3_0",
        {
            "type": "object",
            "properties": {
                "a": {"$ref": "#/components/schemas/A"},
                "b": {"$ref": "#/components/schemas/B"},
            },
        },
        {
            "dialect": "draft-2020-12",
            "schema": {
                "type": "object",
                "properties": {"a": {"$ref": "#/$defs/A"}, "b": {"$ref": "#/$defs/B"}},
            },
            "definitions": {},
        },
    )


def test_fromschemaopenapi3_0_rewrites_percent_encoded_openapi_3_0_co():
    """fromSchemaOpenApi3_0 / rewrites percent-encoded OpenAPI 3.0 component refs"""
    _check(
        "from_schema_open_api_3_0",
        {"$ref": "#%2Fcomponents%2Fschemas%2FA%20B"},
        {"dialect": "draft-2020-12", "schema": {"$ref": "#/$defs/A%20B"}, "definitions": {}},
    )


def test_fromschemaopenapi3_0_preserves_definitions_as_an_opaque_open():
    """fromSchemaOpenApi3_0 / preserves definitions as an opaque OpenAPI 3.0 extension"""
    _check(
        "from_schema_open_api_3_0",
        {"definitions": {"Value": {"type": "string"}}},
        {
            "dialect": "draft-2020-12",
            "schema": {"definitions": {"Value": {"type": "string"}}},
            "definitions": {},
        },
    )


def test_fromschemaopenapi3_0_normalizes_singular_openapi_3_0_example():
    """fromSchemaOpenApi3_0 / normalizes singular OpenAPI 3.0 example to a draft examples array"""
    _check(
        "from_schema_open_api_3_0",
        {"type": "string", "example": "a"},
        {
            "dialect": "draft-2020-12",
            "schema": {"type": "string", "examples": ["a"]},
            "definitions": {},
        },
    )


def test_fromschemaopenapi3_0_preserves_the_openapi_3_0_deprecated_an():
    """fromSchemaOpenApi3_0 / preserves the OpenAPI 3.0 deprecated annotation"""
    _check(
        "from_schema_open_api_3_0",
        {"type": "string", "deprecated": True},
        {
            "dialect": "draft-2020-12",
            "schema": {"type": "string", "deprecated": True},
            "definitions": {},
        },
    )


def test_fromschemaopenapi3_0_rejects_examples_because_it_is_not_acti():
    """fromSchemaOpenApi3_0 / rejects examples because it is not active in OpenAPI 3.0"""
    _raises(
        "from_schema_open_api_3_0",
        {"examples": ["value"]},
        'Cannot convert JSON Schema keyword "examples" to Draft 2020-12: it is not active in OpenAPI 3.0 but would become active in the target',  # noqa: E501
    )


def test_fromschemaopenapi3_0_rejects_draft_2020_12_keywords_that_are():
    """fromSchemaOpenApi3_0 / rejects Draft 2020-12 keywords that are not supported by OpenAPI 3.0"""  # noqa: E501
    _raises(
        "from_schema_open_api_3_0",
        {"unevaluatedProperties": False},
        'Cannot convert JSON Schema keyword "unevaluatedProperties" to Draft 2020-12: it is not active in OpenAPI 3.0 but would become active in the target',  # noqa: E501
    )


def test_fromschemaopenapi3_0_does_not_traverse_opaque_openapi_values():
    """fromSchemaOpenApi3_0 / does not traverse opaque OpenAPI values"""
    _check(
        "from_schema_open_api_3_0",
        {
            "type": "object",
            "default": {"nullable": True, "$ref": "#/components/schemas/Literal"},
            "example": {"nullable": True, "$ref": "#/components/schemas/Literal"},
            "discriminator": {"mapping": {"value": "#/components/schemas/Value"}},
            "x-custom": {"nullable": True, "$ref": "#/components/schemas/Literal"},
        },
        {
            "dialect": "draft-2020-12",
            "schema": {
                "type": "object",
                "default": {"nullable": True, "$ref": "#/components/schemas/Literal"},
                "examples": [{"nullable": True, "$ref": "#/components/schemas/Literal"}],
                "discriminator": {"mapping": {"value": "#/components/schemas/Value"}},
                "x-custom": {"nullable": True, "$ref": "#/components/schemas/Literal"},
            },
            "definitions": {},
        },
    )


def test_fromschemaopenapi3_0_nullable_ignores_nullable_without_an_ex():
    """fromSchemaOpenApi3_0 / nullable / ignores nullable without an explicit type"""
    _check(
        "from_schema_open_api_3_0",
        {"nullable": True},
        {"dialect": "draft-2020-12", "schema": {}, "definitions": {}},
    )


def test_fromschemaopenapi3_0_nullable_adds_null_to_a_string_type():
    """fromSchemaOpenApi3_0 / nullable / adds null to a string type"""
    _check(
        "from_schema_open_api_3_0",
        {"type": "string", "nullable": True},
        {"dialect": "draft-2020-12", "schema": {"type": ["string", "null"]}, "definitions": {}},
    )


def test_fromschemaopenapi3_0_nullable_does_not_widen_enum_values():
    """fromSchemaOpenApi3_0 / nullable / does not widen enum values"""
    _check(
        "from_schema_open_api_3_0",
        {"type": "string", "enum": ["a", "b"], "nullable": True},
        {
            "dialect": "draft-2020-12",
            "schema": {"type": ["string", "null"], "enum": ["a", "b"]},
            "definitions": {},
        },
    )


def test_fromschemaopenapi3_0_nullable_does_not_duplicate_null_in_enu():
    """fromSchemaOpenApi3_0 / nullable / does not duplicate null in enum values"""
    _check(
        "from_schema_open_api_3_0",
        {"type": "string", "enum": ["a", "b", None], "nullable": True},
        {
            "dialect": "draft-2020-12",
            "schema": {"type": ["string", "null"], "enum": ["a", "b", None]},
            "definitions": {},
        },
    )


def test_fromschemaopenapi3_0_nullable_preserves_enum_when_null_is_it():
    """fromSchemaOpenApi3_0 / nullable / preserves enum when null is its only value"""
    _check(
        "from_schema_open_api_3_0",
        {"type": "string", "enum": [None], "nullable": True},
        {
            "dialect": "draft-2020-12",
            "schema": {"type": ["string", "null"], "enum": [None]},
            "definitions": {},
        },
    )


def test_fromschemaopenapi3_0_nullable_ignores_nullable_when_another():
    """fromSchemaOpenApi3_0 / nullable / ignores nullable when another constraint is present without type"""  # noqa: E501
    _check(
        "from_schema_open_api_3_0",
        {"nullable": True, "minimum": 0},
        {"dialect": "draft-2020-12", "schema": {"minimum": 0}, "definitions": {}},
    )


def test_fromschemaopenapi3_0_nullable_drops_nullable_false():
    """fromSchemaOpenApi3_0 / nullable / drops nullable false"""
    _check(
        "from_schema_open_api_3_0",
        {"type": "string", "nullable": False},
        {"dialect": "draft-2020-12", "schema": {"type": "string"}, "definitions": {}},
    )


def test_fromschemaopenapi3_0_nullable_normalizes_nullable_inside_all():
    """fromSchemaOpenApi3_0 / nullable / normalizes nullable inside allOf independently from the parent"""  # noqa: E501
    _check(
        "from_schema_open_api_3_0",
        {"type": "string", "allOf": [{"nullable": True}]},
        {
            "dialect": "draft-2020-12",
            "schema": {"type": "string", "allOf": [{}]},
            "definitions": {},
        },
    )


def test_fromschemaopenapi3_0_nullable_normalizes_nullable_on_both_a():
    """fromSchemaOpenApi3_0 / nullable / normalizes nullable on both a parent and its allOf member"""  # noqa: E501
    _check(
        "from_schema_open_api_3_0",
        {"type": "string", "nullable": True, "allOf": [{"nullable": True}]},
        {
            "dialect": "draft-2020-12",
            "schema": {"type": ["string", "null"], "allOf": [{}]},
            "definitions": {},
        },
    )


def test_fromschemaopenapi3_0_nullable_makes_a_single_member_allof_nu():
    """fromSchemaOpenApi3_0 / nullable / makes a single-member allOf nullable while preserving siblings and relocating refs"""  # noqa: E501
    _check(
        "from_schema_open_api_3_0",
        {
            "nullable": True,
            "allOf": [{"$ref": "#/components/schemas/A"}],
            "description": "a",
            "enum": ["a"],
            "properties": {"copy": {"$ref": "#/allOf/0"}},
        },
        {
            "dialect": "draft-2020-12",
            "schema": {
                "anyOf": [{"$ref": "#/$defs/A"}, {"type": "null"}],
                "description": "a",
                "enum": ["a"],
                "properties": {"copy": {"$ref": "#/anyOf/0"}},
            },
            "definitions": {},
        },
    )


def test_fromschemaopenapi3_0_nullable_does_not_rewrite_a_nullable_si():
    """fromSchemaOpenApi3_0 / nullable / does not rewrite a nullable single-member allOf when anyOf is present"""  # noqa: E501
    _check(
        "from_schema_open_api_3_0",
        {"nullable": True, "allOf": [{"type": "string"}], "anyOf": [{"minLength": 1}]},
        {
            "dialect": "draft-2020-12",
            "schema": {"allOf": [{"type": "string"}], "anyOf": [{"minLength": 1}]},
            "definitions": {},
        },
    )


def test_fromschemaopenapi3_0_exclusivity_turns_exclusiveminimum_true():
    """fromSchemaOpenApi3_0 / exclusivity / turns exclusiveMinimum true into the minimum value"""
    _check(
        "from_schema_open_api_3_0",
        {"type": "number", "minimum": 10, "exclusiveMinimum": True},
        {
            "dialect": "draft-2020-12",
            "schema": {"type": "number", "exclusiveMinimum": 10},
            "definitions": {},
        },
    )


def test_fromschemaopenapi3_0_exclusivity_turns_exclusivemaximum_true():
    """fromSchemaOpenApi3_0 / exclusivity / turns exclusiveMaximum true into the maximum value"""
    _check(
        "from_schema_open_api_3_0",
        {"type": "number", "maximum": 100, "exclusiveMaximum": True},
        {
            "dialect": "draft-2020-12",
            "schema": {"type": "number", "exclusiveMaximum": 100},
            "definitions": {},
        },
    )


def test_fromschemaopenapi3_0_exclusivity_drops_exclusiveminimum_fals():
    """fromSchemaOpenApi3_0 / exclusivity / drops exclusiveMinimum false"""
    _check(
        "from_schema_open_api_3_0",
        {"type": "number", "minimum": 10, "exclusiveMinimum": False},
        {
            "dialect": "draft-2020-12",
            "schema": {"type": "number", "minimum": 10},
            "definitions": {},
        },
    )


def test_fromschemaopenapi3_0_exclusivity_drops_exclusivemaximum_fals():
    """fromSchemaOpenApi3_0 / exclusivity / drops exclusiveMaximum false"""
    _check(
        "from_schema_open_api_3_0",
        {"type": "number", "maximum": 100, "exclusiveMaximum": False},
        {
            "dialect": "draft-2020-12",
            "schema": {"type": "number", "maximum": 100},
            "definitions": {},
        },
    )


def test_fromschemaopenapi3_0_exclusivity_drops_exclusiveminimum_true():
    """fromSchemaOpenApi3_0 / exclusivity / drops exclusiveMinimum true when minimum is absent"""
    _check(
        "from_schema_open_api_3_0",
        {"type": "number", "exclusiveMinimum": True},
        {"dialect": "draft-2020-12", "schema": {"type": "number"}, "definitions": {}},
    )


def test_fromschemaopenapi3_0_exclusivity_drops_exclusivemaximum_true():
    """fromSchemaOpenApi3_0 / exclusivity / drops exclusiveMaximum true when maximum is absent"""
    _check(
        "from_schema_open_api_3_0",
        {"type": "number", "exclusiveMaximum": True},
        {"dialect": "draft-2020-12", "schema": {"type": "number"}, "definitions": {}},
    )


def test_todocumentdraft07_rewrites_the_canonical_meta_schema_uri_wit():
    """toDocumentDraft07 / rewrites the canonical meta-schema URI with an empty fragment"""
    _check(
        "to_document_draft_07",
        {
            "dialect": "draft-2020-12",
            "schema": {"$schema": "https://json-schema.org/draft/2020-12/schema#"},
            "definitions": {},
        },
        {
            "dialect": "draft-07",
            "schema": {"$schema": "http://json-schema.org/draft-07/schema#"},
            "definitions": {},
        },
    )


def test_todocumentdraft07_omits_the_canonical_meta_schema_uri_from_e():
    """toDocumentDraft07 / omits the canonical meta-schema URI from embedded resources"""
    _check(
        "to_document_draft_07",
        {
            "dialect": "draft-2020-12",
            "schema": {},
            "definitions": {
                "Embedded": {
                    "$id": "embedded.json",
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "type": "string",
                }
            },
        },
        {
            "dialect": "draft-07",
            "schema": {},
            "definitions": {"Embedded": {"type": "string", "$id": "embedded.json"}},
        },
    )


def test_todocumentdraft07_rejects_custom_dialects_in_embedded_resour():
    """toDocumentDraft07 / rejects custom dialects in embedded resources"""
    _raises(
        "to_document_draft_07",
        {
            "dialect": "draft-2020-12",
            "schema": {},
            "definitions": {
                "Embedded": {
                    "$id": "embedded.json",
                    "$schema": "https://example.com/dialect",
                    "type": "string",
                }
            },
        },
        'Cannot convert JSON Schema keyword "$schema" to Draft-07: an embedded resource cannot declare a different dialect',  # noqa: E501
    )


def test_todocumentdraft07_lowers_canonical_keywords_and_preserves_op():
    """toDocumentDraft07 / lowers canonical keywords and preserves opaque custom keywords"""
    _check(
        "to_document_draft_07",
        {
            "dialect": "draft-2020-12",
            "schema": {
                "if": {"properties": {"kind": {"const": "full"}}},
                "then": {"required": ["value"]},
                "else": {"not": {"required": ["value"]}},
                "contains": {"type": "number"},
                "dependentRequired": {"enabled": ["value"], "kind": ["label"]},
                "dependentSchemas": {"kind": {"minProperties": 1}, "mode": {"required": ["value"]}},
                "x-custom": {"$ref": "#/$defs/Literal"},
            },
            "definitions": {},
        },
        {
            "dialect": "draft-07",
            "schema": {
                "if": {"properties": {"kind": {"const": "full"}}},
                "then": {"required": ["value"]},
                "else": {"not": {"required": ["value"]}},
                "contains": {"type": "number"},
                "x-custom": {"$ref": "#/$defs/Literal"},
                "dependencies": {
                    "enabled": ["value"],
                    "kind": {"allOf": [{"minProperties": 1}, {"required": ["label"]}]},
                    "mode": {"required": ["value"]},
                },
            },
            "definitions": {},
        },
    )


def test_todocumentdraft07_moves_nested_defs_to_definitions_and_reloc():
    """toDocumentDraft07 / moves nested $defs to definitions and relocates local JSON Pointer refs"""  # noqa: E501
    _check(
        "to_document_draft_07",
        {
            "dialect": "draft-2020-12",
            "schema": {
                "properties": {
                    "nested": {
                        "$defs": {"Value": {"type": "string"}},
                        "$ref": "#/properties/nested/$defs/Value",
                    }
                }
            },
            "definitions": {},
        },
        {
            "dialect": "draft-07",
            "schema": {
                "properties": {
                    "nested": {
                        "definitions": {"Value": {"type": "string"}},
                        "allOf": [{"$ref": "#/properties/nested/definitions/Value"}],
                    }
                }
            },
            "definitions": {},
        },
    )


def test_todocumentdraft07_relocates_fragment_refs_when_emitting_nest():
    """toDocumentDraft07 / relocates fragment refs when emitting nested schema resources"""
    _check(
        "to_document_draft_07",
        {
            "dialect": "draft-2020-12",
            "schema": {
                "allOf": [
                    {"$ref": "nested.json#/$defs/Value"},
                    {"$ref": "external.json#/$defs/Value"},
                ]
            },
            "definitions": {
                "Nested": {
                    "$id": "nested.json",
                    "$defs": {"Value": {"type": "string"}},
                    "allOf": [{"$ref": "#/$defs/Value"}],
                }
            },
        },
        {
            "dialect": "draft-07",
            "schema": {
                "allOf": [
                    {"$ref": "nested.json#/definitions/Value"},
                    {"$ref": "external.json#/$defs/Value"},
                ]
            },
            "definitions": {
                "Nested": {
                    "definitions": {"Value": {"type": "string"}},
                    "allOf": [{"$ref": "#/definitions/Value"}],
                    "$id": "nested.json",
                }
            },
        },
    )
    _check(
        "to_document_draft_04",
        {
            "dialect": "draft-2020-12",
            "schema": {
                "allOf": [
                    {"$ref": "nested.json#/$defs/Value"},
                    {"$ref": "external.json#/$defs/Value"},
                ]
            },
            "definitions": {
                "Nested": {
                    "$id": "nested.json",
                    "$defs": {"Value": {"type": "string"}},
                    "allOf": [{"$ref": "#/$defs/Value"}],
                }
            },
        },
        {
            "dialect": "draft-04",
            "schema": {
                "allOf": [
                    {"$ref": "nested.json#/definitions/Value"},
                    {"$ref": "external.json#/$defs/Value"},
                ]
            },
            "definitions": {
                "Nested": {
                    "definitions": {"Value": {"type": "string"}},
                    "allOf": [{"$ref": "#/definitions/Value"}],
                    "id": "nested.json",
                }
            },
        },
    )


def test_todocumentdraft07_converts_contentschema_bodies_and_referenc():
    """toDocumentDraft07 / converts contentSchema bodies and references"""
    _check(
        "to_document_draft_07",
        {
            "dialect": "draft-2020-12",
            "schema": {
                "contentSchema": {"$defs": {"Value": {"const": "value"}}},
                "allOf": [{"$ref": "#/contentSchema/$defs/Value"}],
            },
            "definitions": {},
        },
        {
            "dialect": "draft-07",
            "schema": {
                "contentSchema": {"definitions": {"Value": {"const": "value"}}},
                "allOf": [{"$ref": "#/contentSchema/definitions/Value"}],
            },
            "definitions": {},
        },
    )
    _check(
        "to_document_draft_04",
        {
            "dialect": "draft-2020-12",
            "schema": {
                "contentSchema": {"$defs": {"Value": {"const": "value"}}},
                "allOf": [{"$ref": "#/contentSchema/$defs/Value"}],
            },
            "definitions": {},
        },
        {
            "dialect": "draft-04",
            "schema": {
                "contentSchema": {"definitions": {"Value": {"enum": ["value"]}}},
                "allOf": [{"$ref": "#/contentSchema/definitions/Value"}],
            },
            "definitions": {},
        },
    )


def test_todocumentdraft07_rejects_canonical_constraints_that_draft_0():
    """toDocumentDraft07 / rejects canonical constraints that Draft-07 cannot represent"""
    _raises(
        "to_document_draft_07",
        {
            "dialect": "draft-2020-12",
            "schema": {"contains": {"type": "string"}, "minContains": 2},
            "definitions": {},
        },
        'Cannot convert JSON Schema keyword "minContains/maxContains" to Draft-07: contains cardinality cannot be represented',  # noqa: E501
    )
    _raises(
        "to_document_draft_07",
        {
            "dialect": "draft-2020-12",
            "schema": {"contains": {"type": "string"}, "maxContains": 3},
            "definitions": {},
        },
        'Cannot convert JSON Schema keyword "minContains/maxContains" to Draft-07: contains cardinality cannot be represented',  # noqa: E501
    )
    _raises(
        "to_document_draft_07",
        {"dialect": "draft-2020-12", "schema": {"unevaluatedProperties": False}, "definitions": {}},
        'Cannot convert JSON Schema keyword "unevaluatedProperties" to Draft-07: the target dialect has no equivalent',  # noqa: E501
    )
    _raises(
        "to_document_draft_07",
        {"dialect": "draft-2020-12", "schema": {"unevaluatedItems": False}, "definitions": {}},
        'Cannot convert JSON Schema keyword "unevaluatedItems" to Draft-07: the target dialect has no equivalent',  # noqa: E501
    )
    _raises(
        "to_document_draft_07",
        {"dialect": "draft-2020-12", "schema": {"$dynamicRef": "#node"}, "definitions": {}},
        'Cannot convert JSON Schema keyword "$dynamicRef" to Draft-07: the target dialect has no equivalent',  # noqa: E501
    )
    _raises(
        "to_document_draft_07",
        {
            "dialect": "draft-2020-12",
            "schema": {"$vocabulary": {"https://example.com/vocabulary": True}},
            "definitions": {},
        },
        'Cannot convert JSON Schema keyword "$vocabulary" to Draft-07: the target dialect has no equivalent',  # noqa: E501
    )
    _raises(
        "to_document_draft_07",
        {
            "dialect": "draft-2020-12",
            "schema": {"dependencies": {"value": ["other"]}},
            "definitions": {},
        },
        'Cannot convert JSON Schema keyword "dependencies" to Draft-07: it is not active in Draft 2020-12 but would become active in the target',  # noqa: E501
    )


def test_todocumentdraft07_preserves_schema_never():
    """toDocumentDraft07 / preserves Schema.Never"""
    _check(
        "to_document_draft_07",
        {"dialect": "draft-2020-12", "schema": {"not": {}}, "definitions": {}},
        {"dialect": "draft-07", "schema": {"not": {}}, "definitions": {}},
    )


def test_todocumentdraft07_omits_an_empty_required_array():
    """toDocumentDraft07 / omits an empty required array"""
    _check(
        "to_document_draft_07",
        {
            "dialect": "draft-2020-12",
            "schema": {"type": "object", "required": []},
            "definitions": {},
        },
        {"dialect": "draft-07", "schema": {"type": "object"}, "definitions": {}},
    )


def test_todocumentdraft07_preserves_every_supported_annotation_and_v():
    """toDocumentDraft07 / preserves every supported annotation and validation keyword"""
    _check(
        "to_document_draft_07",
        {
            "dialect": "draft-2020-12",
            "schema": {
                "type": "object",
                "required": ["value"],
                "enum": ["a", "b"],
                "const": "a",
                "title": "title",
                "description": "description",
                "default": "a",
                "examples": ["a"],
                "format": "custom",
                "readOnly": True,
                "writeOnly": True,
                "pattern": "^a$",
                "minimum": 0,
                "maximum": 10,
                "exclusiveMinimum": 0,
                "exclusiveMaximum": 10,
                "minLength": 1,
                "maxLength": 10,
                "minItems": 1,
                "maxItems": 10,
                "minProperties": 1,
                "maxProperties": 10,
                "multipleOf": 2,
                "uniqueItems": True,
                "properties": {"value": {"type": "string"}},
                "patternProperties": {"^x-": {"type": "string"}},
                "not": {"type": "null"},
                "additionalProperties": False,
                "propertyNames": {"minLength": 1},
                "allOf": [{"type": "object"}],
                "anyOf": [{"type": "string"}],
                "oneOf": [{"type": "number"}],
                "items": {"type": "string"},
            },
            "definitions": {},
        },
        {
            "dialect": "draft-07",
            "schema": {
                "type": "object",
                "required": ["value"],
                "enum": ["a", "b"],
                "const": "a",
                "title": "title",
                "description": "description",
                "default": "a",
                "examples": ["a"],
                "format": "custom",
                "readOnly": True,
                "writeOnly": True,
                "pattern": "^a$",
                "minimum": 0,
                "maximum": 10,
                "exclusiveMinimum": 0,
                "exclusiveMaximum": 10,
                "minLength": 1,
                "maxLength": 10,
                "minItems": 1,
                "maxItems": 10,
                "minProperties": 1,
                "maxProperties": 10,
                "multipleOf": 2,
                "uniqueItems": True,
                "properties": {"value": {"type": "string"}},
                "patternProperties": {"^x-": {"type": "string"}},
                "not": {"type": "null"},
                "additionalProperties": False,
                "propertyNames": {"minLength": 1},
                "allOf": [{"type": "object"}],
                "anyOf": [{"type": "string"}],
                "oneOf": [{"type": "number"}],
                "items": {"type": "string"},
            },
            "definitions": {},
        },
    )


def test_todocumentdraft07_preserves_validation_semantics():
    """toDocumentDraft07 / preserves validation semantics"""
    _check(
        "to_document_draft_07",
        {
            "dialect": "draft-2020-12",
            "schema": {
                "type": "object",
                "properties": {
                    "mode": {"const": "on"},
                    "value": {"type": "number", "exclusiveMinimum": 0},
                    "tuple": {"type": "array", "prefixItems": [{"type": "string"}], "items": False},
                    "empty": {"enum": [], "$ref": "#/$defs/Anything"},
                },
                "required": ["mode", "value", "tuple"],
                "additionalProperties": False,
            },
            "definitions": {"Anything": {}},
        },
        {
            "dialect": "draft-07",
            "schema": {
                "type": "object",
                "properties": {
                    "mode": {"const": "on"},
                    "value": {"type": "number", "exclusiveMinimum": 0},
                    "tuple": {
                        "type": "array",
                        "items": [{"type": "string"}],
                        "additionalItems": False,
                    },
                    # Draft-07 requires a non-empty ``enum``: an empty one matches nothing.
                    "empty": {"allOf": [{"not": {}}, {"$ref": "#/definitions/Anything"}]},
                },
                "required": ["mode", "value", "tuple"],
                "additionalProperties": False,
            },
            "definitions": {"Anything": {}},
        },
    )


def test_todocumentdraft07_rewrites_defs_refs_to_draft_07_definitions():
    """toDocumentDraft07 / rewrites $defs refs to Draft-07 definitions refs"""
    _check(
        "to_document_draft_07",
        {
            "dialect": "draft-2020-12",
            "schema": {
                "type": "object",
                "properties": {"a": {"$ref": "#/$defs/A"}, "b": {"$ref": "#/$defs/B"}},
            },
            "definitions": {"A": {"type": "string", "$ref": "#/$defs/B"}, "B": {"type": "number"}},
        },
        {
            "dialect": "draft-07",
            "schema": {
                "type": "object",
                "properties": {"a": {"$ref": "#/definitions/A"}, "b": {"$ref": "#/definitions/B"}},
            },
            "definitions": {
                "A": {"type": "string", "allOf": [{"$ref": "#/definitions/B"}]},
                "B": {"type": "number"},
            },
        },
    )


def test_todocumentdraft07_rewrites_refs_only_in_schema_positions():
    """toDocumentDraft07 / rewrites refs only in schema positions"""
    _check(
        "to_document_draft_07",
        {
            "dialect": "draft-2020-12",
            "schema": {
                "properties": {"value": {"$ref": "#/$defs/Value"}},
                "const": {"$ref": "#/$defs/Literal"},
                "enum": [{"$ref": "#/$defs/Literal"}],
                "default": {"$ref": "#/$defs/Literal"},
                "examples": [{"$ref": "#/$defs/Literal"}],
            },
            "definitions": {"Value": {"type": "string"}},
        },
        {
            "dialect": "draft-07",
            "schema": {
                "properties": {"value": {"$ref": "#/definitions/Value"}},
                "const": {"$ref": "#/$defs/Literal"},
                "enum": [{"$ref": "#/$defs/Literal"}],
                "default": {"$ref": "#/$defs/Literal"},
                "examples": [{"$ref": "#/$defs/Literal"}],
            },
            "definitions": {"Value": {"type": "string"}},
        },
    )


def test_todocumentdraft07_preserves_constraints_next_to_refs_and_exi():
    """toDocumentDraft07 / preserves constraints next to refs and existing allOf"""
    _check(
        "to_document_draft_07",
        {
            "dialect": "draft-2020-12",
            "schema": {"$ref": "#/$defs/S", "minLength": 3, "allOf": [{"maxLength": 5}]},
            "definitions": {"S": {"type": "string"}},
        },
        {
            "dialect": "draft-07",
            "schema": {"minLength": 3, "allOf": [{"maxLength": 5}, {"$ref": "#/definitions/S"}]},
            "definitions": {"S": {"type": "string"}},
        },
    )


def test_todocumentdraft07_keeps_existing_allof_locations_stable_when():
    """toDocumentDraft07 / keeps existing allOf locations stable when wrapping ref siblings"""
    _check(
        "to_document_draft_07",
        {
            "dialect": "draft-2020-12",
            "schema": {
                "$ref": "#/$defs/Base",
                "allOf": [{"type": "string"}],
                "properties": {"copy": {"$ref": "#/allOf/0"}},
            },
            "definitions": {"Base": {"type": "object"}},
        },
        {
            "dialect": "draft-07",
            "schema": {
                "allOf": [{"type": "string"}, {"$ref": "#/definitions/Base"}],
                "properties": {"copy": {"$ref": "#/allOf/0"}},
            },
            "definitions": {"Base": {"type": "object"}},
        },
    )


def test_todocumentdraft07_converts_prefixitems_to_a_draft_07_items_t():
    """toDocumentDraft07 / converts prefixItems to a Draft-07 items tuple"""
    _check(
        "to_document_draft_07",
        {
            "dialect": "draft-2020-12",
            "schema": {
                "type": "array",
                "prefixItems": [{"type": "string"}, {"type": "number"}],
                "items": {"type": "boolean"},
            },
            "definitions": {},
        },
        {
            "dialect": "draft-07",
            "schema": {
                "type": "array",
                "items": [{"type": "string"}, {"type": "number"}],
                "additionalItems": {"type": "boolean"},
            },
            "definitions": {},
        },
    )


def test_todocumentdraft07_preserves_a_single_items_schema_as_items():
    """toDocumentDraft07 / preserves a single items schema as items"""
    _check(
        "to_document_draft_07",
        {
            "dialect": "draft-2020-12",
            "schema": {"type": "array", "items": {"type": "string"}},
            "definitions": {},
        },
        {
            "dialect": "draft-07",
            "schema": {"type": "array", "items": {"type": "string"}},
            "definitions": {},
        },
    )


def test_todocumentdraft07_preserves_custom_properties_in_draft_07_ou():
    """toDocumentDraft07 / preserves custom properties in Draft-07 output"""
    _check(
        "to_document_draft_07",
        {
            "dialect": "draft-2020-12",
            "schema": {"type": "string", "x-custom": "value"},
            "definitions": {},
        },
        {
            "dialect": "draft-07",
            "schema": {"type": "string", "x-custom": "value"},
            "definitions": {},
        },
    )


def test_todocumentdraft07_preserves_malformed_values_for_recognized():
    """toDocumentDraft07 / preserves malformed values for recognized keywords"""
    _check(
        "to_document_draft_07",
        {
            "dialect": "draft-2020-12",
            "schema": {
                "$ref": 1,
                "properties": "invalid",
                "not": [False, {"type": "string"}],
                "allOf": "invalid",
                "prefixItems": "invalid",
            },
            "definitions": {},
        },
        {
            "dialect": "draft-07",
            "schema": {
                "properties": "invalid",
                "not": [False, {"type": "string"}],
                "allOf": "invalid",
                "items": "invalid",
                "$ref": 1,
            },
            "definitions": {},
        },
    )


def test_todocumentdraft04_rewrites_the_canonical_meta_schema_uri_wit():
    """toDocumentDraft04 / rewrites the canonical meta-schema URI with an empty fragment"""
    _check(
        "to_document_draft_04",
        {
            "dialect": "draft-2020-12",
            "schema": {"$schema": "https://json-schema.org/draft/2020-12/schema#"},
            "definitions": {},
        },
        {
            "dialect": "draft-04",
            "schema": {"$schema": "http://json-schema.org/draft-04/schema#"},
            "definitions": {},
        },
    )


def test_todocumentdraft04_omits_the_canonical_meta_schema_uri_from_e():
    """toDocumentDraft04 / omits the canonical meta-schema URI from embedded resources"""
    _check(
        "to_document_draft_04",
        {
            "dialect": "draft-2020-12",
            "schema": {},
            "definitions": {
                "Embedded": {
                    "$id": "embedded.json",
                    "$schema": "https://json-schema.org/draft/2020-12/schema",
                    "type": "string",
                }
            },
        },
        {
            "dialect": "draft-04",
            "schema": {},
            "definitions": {"Embedded": {"type": "string", "id": "embedded.json"}},
        },
    )


def test_todocumentdraft04_rejects_custom_dialects_in_embedded_resour():
    """toDocumentDraft04 / rejects custom dialects in embedded resources"""
    _raises(
        "to_document_draft_04",
        {
            "dialect": "draft-2020-12",
            "schema": {},
            "definitions": {
                "Embedded": {
                    "$id": "embedded.json",
                    "$schema": "https://example.com/dialect",
                    "type": "string",
                }
            },
        },
        'Cannot convert JSON Schema keyword "$schema" to Draft-04: an embedded resource cannot declare a different dialect',  # noqa: E501
    )


def test_todocumentdraft04_lowers_canonical_dependencies_directly_and():
    """toDocumentDraft04 / lowers canonical dependencies directly and preserves custom keywords"""
    _check(
        "to_document_draft_04",
        {
            "dialect": "draft-2020-12",
            "schema": {
                "dependentRequired": {"enabled": ["value"]},
                "dependentSchemas": {"mode": {"required": ["value"]}},
                "x-custom": {"value": True},
            },
            "definitions": {},
        },
        {
            "dialect": "draft-04",
            "schema": {
                "x-custom": {"value": True},
                "dependencies": {"enabled": ["value"], "mode": {"required": ["value"]}},
            },
            "definitions": {},
        },
    )


def test_todocumentdraft04_rewrites_defs_refs_to_draft_04_definitions():
    """toDocumentDraft04 / rewrites $defs refs to Draft-04 definitions refs"""
    _check(
        "to_document_draft_04",
        {
            "dialect": "draft-2020-12",
            "schema": {"type": "object", "properties": {"value": {"$ref": "#/$defs/Value"}}},
            "definitions": {"Value": {"type": "string"}},
        },
        {
            "dialect": "draft-04",
            "schema": {"type": "object", "properties": {"value": {"$ref": "#/definitions/Value"}}},
            "definitions": {"Value": {"type": "string"}},
        },
    )


def test_todocumentdraft04_preserves_every_supported_draft_04_keyword():
    """toDocumentDraft04 / preserves every supported Draft-04 keyword and newer annotations as extensions"""  # noqa: E501
    _check(
        "to_document_draft_04",
        {
            "dialect": "draft-2020-12",
            "schema": {
                "type": "object",
                "required": ["value"],
                "enum": ["a", "b"],
                "title": "title",
                "description": "description",
                "default": "a",
                "format": "custom",
                "pattern": "^a$",
                "minimum": 0,
                "maximum": 10,
                "minLength": 1,
                "maxLength": 10,
                "minItems": 1,
                "maxItems": 10,
                "minProperties": 1,
                "maxProperties": 10,
                "multipleOf": 2,
                "uniqueItems": True,
                "properties": {"value": {"type": "string"}},
                "patternProperties": {"^x-": {"type": "string"}},
                "not": {"type": "null"},
                "additionalProperties": False,
                "allOf": [{"type": "object"}],
                "anyOf": [{"type": "string"}],
                "oneOf": [{"type": "number"}],
                "items": {"type": "string"},
                "examples": ["a"],
                "readOnly": True,
                "writeOnly": True,
            },
            "definitions": {},
        },
        {
            "dialect": "draft-04",
            "schema": {
                "type": "object",
                "required": ["value"],
                "enum": ["a", "b"],
                "title": "title",
                "description": "description",
                "default": "a",
                "format": "custom",
                "pattern": "^a$",
                "minLength": 1,
                "maxLength": 10,
                "minItems": 1,
                "maxItems": 10,
                "minProperties": 1,
                "maxProperties": 10,
                "multipleOf": 2,
                "uniqueItems": True,
                "properties": {"value": {"type": "string"}},
                "patternProperties": {"^x-": {"type": "string"}},
                "not": {"type": "null"},
                "additionalProperties": {"not": {}},
                "allOf": [{"type": "object"}],
                "anyOf": [{"type": "string"}],
                "oneOf": [{"type": "number"}],
                "examples": ["a"],
                "readOnly": True,
                "writeOnly": True,
                "items": {"type": "string"},
                "minimum": 0,
                "maximum": 10,
            },
            "definitions": {},
        },
    )


def test_todocumentdraft04_rejects_validation_keywords_that_draft_04():
    """toDocumentDraft04 / rejects validation keywords that Draft-04 cannot represent"""
    _raises(
        "to_document_draft_04",
        {
            "dialect": "draft-2020-12",
            "schema": {"propertyNames": {"minLength": 1}},
            "definitions": {},
        },
        'Cannot convert JSON Schema keyword "propertyNames" to Draft-04: the target dialect has no equivalent',  # noqa: E501
    )
    _raises(
        "to_document_draft_04",
        {
            "dialect": "draft-2020-12",
            "schema": {"contains": {"type": "string"}, "minContains": 0},
            "definitions": {},
        },
        'Cannot convert JSON Schema keyword "minContains/maxContains" to Draft-04: contains cardinality cannot be represented',  # noqa: E501
    )
    _raises(
        "to_document_draft_04",
        {
            "dialect": "draft-2020-12",
            "schema": {"contains": {"type": "string"}, "minContains": 2},
            "definitions": {},
        },
        'Cannot convert JSON Schema keyword "minContains/maxContains" to Draft-04: contains cardinality cannot be represented',  # noqa: E501
    )
    _raises(
        "to_document_draft_04",
        {
            "dialect": "draft-2020-12",
            "schema": {"if": {"$id": "condition"}, "then": {}, "else": {}},
            "definitions": {},
        },
        'Cannot convert JSON Schema keyword "if" to Draft-04: lowering both branches would duplicate a schema identifier',  # noqa: E501
    )
    _raises(
        "to_document_draft_04",
        {"dialect": "draft-2020-12", "schema": {"unevaluatedProperties": False}, "definitions": {}},
        'Cannot convert JSON Schema keyword "unevaluatedProperties" to Draft-04: the target dialect has no equivalent',  # noqa: E501
    )
    _raises(
        "to_document_draft_04",
        {"dialect": "draft-2020-12", "schema": {"$dynamicRef": "#node"}, "definitions": {}},
        'Cannot convert JSON Schema keyword "$dynamicRef" to Draft-04: the target dialect has no equivalent',  # noqa: E501
    )
    _raises(
        "to_document_draft_04",
        {
            "dialect": "draft-2020-12",
            "schema": {"$vocabulary": {"https://example.com/vocabulary": True}},
            "definitions": {},
        },
        'Cannot convert JSON Schema keyword "$vocabulary" to Draft-04: the target dialect has no equivalent',  # noqa: E501
    )
    _raises(
        "to_document_draft_04",
        {"dialect": "draft-2020-12", "schema": {"id": "legacy-id"}, "definitions": {}},
        'Cannot convert JSON Schema keyword "id" to Draft-04: it is not active in Draft 2020-12 but would become active in the target',  # noqa: E501
    )


def test_todocumentdraft04_converts_inactive_conditional_schema_bodie():
    """toDocumentDraft04 / converts inactive conditional schema bodies"""
    _check(
        "to_document_draft_04",
        {
            "dialect": "draft-2020-12",
            "schema": {
                "if": {"$defs": {"Value": {"const": "value"}}},
                "allOf": [{"$ref": "#/if/$defs/Value"}],
            },
            "definitions": {},
        },
        {
            "dialect": "draft-04",
            "schema": {
                "allOf": [{"$ref": "#/if/definitions/Value"}],
                "if": {"definitions": {"Value": {"enum": ["value"]}}},
            },
            "definitions": {},
        },
    )
    _check(
        "to_document_draft_04",
        {
            "dialect": "draft-2020-12",
            "schema": {
                "then": {"$defs": {"Value": {"const": "value"}}},
                "allOf": [{"$ref": "#/then/$defs/Value"}],
            },
            "definitions": {},
        },
        {
            "dialect": "draft-04",
            "schema": {
                "allOf": [{"$ref": "#/then/definitions/Value"}],
                "then": {"definitions": {"Value": {"enum": ["value"]}}},
            },
            "definitions": {},
        },
    )
    _check(
        "to_document_draft_04",
        {
            "dialect": "draft-2020-12",
            "schema": {
                "else": {"$defs": {"Value": {"const": "value"}}},
                "allOf": [{"$ref": "#/else/$defs/Value"}],
            },
            "definitions": {},
        },
        {
            "dialect": "draft-04",
            "schema": {
                "allOf": [{"$ref": "#/else/definitions/Value"}],
                "else": {"definitions": {"Value": {"enum": ["value"]}}},
            },
            "definitions": {},
        },
    )


def test_todocumentdraft04_lowers_conditionals_and_contains_while_pre():
    """toDocumentDraft04 / lowers conditionals and contains while preserving validation semantics"""
    _check(
        "to_document_draft_04",
        {
            "dialect": "draft-2020-12",
            "schema": {
                "type": "object",
                "properties": {
                    "mode": {"enum": ["full", "compact"]},
                    "value": {"type": "string"},
                    "values": {"contains": {"type": "number"}},
                },
                "required": ["mode", "values"],
                "if": {"properties": {"mode": {"const": "full"}}},
                "then": {"required": ["value"]},
                "else": {"not": {"required": ["value"]}},
            },
            "definitions": {},
        },
        {
            "dialect": "draft-04",
            "schema": {
                "type": "object",
                "properties": {
                    "mode": {"enum": ["full", "compact"]},
                    "value": {"type": "string"},
                    "values": {
                        "allOf": [
                            {
                                "anyOf": [
                                    {"not": {"type": "array"}},
                                    {"not": {"items": {"not": {"type": "number"}}}},
                                ]
                            }
                        ]
                    },
                },
                "required": ["mode", "values"],
                "allOf": [
                    {
                        "anyOf": [
                            {
                                "allOf": [
                                    {"properties": {"mode": {"enum": ["full"]}}},
                                    {"required": ["value"]},
                                ]
                            },
                            {
                                "allOf": [
                                    {"not": {"properties": {"mode": {"enum": ["full"]}}}},
                                    {"not": {"required": ["value"]}},
                                ]
                            },
                        ]
                    }
                ],
            },
            "definitions": {},
        },
    )


def test_todocumentdraft04_omits_an_empty_required_array():
    """toDocumentDraft04 / omits an empty required array"""
    _check(
        "to_document_draft_04",
        {
            "dialect": "draft-2020-12",
            "schema": {"type": "object", "required": []},
            "definitions": {},
        },
        {"dialect": "draft-04", "schema": {"type": "object"}, "definitions": {}},
    )


def test_todocumentdraft04_omits_empty_dependentrequired_arrays():
    """toDocumentDraft04 / omits empty dependentRequired arrays"""
    _check(
        "to_document_draft_04",
        {
            "dialect": "draft-2020-12",
            "schema": {"dependentRequired": {"value": []}},
            "definitions": {},
        },
        {"dialect": "draft-04", "schema": {}, "definitions": {}},
    )
    _check(
        "to_document_draft_04",
        {
            "dialect": "draft-2020-12",
            "schema": {
                "dependentRequired": {"value": []},
                "dependentSchemas": {"value": {"type": "string"}},
            },
            "definitions": {},
        },
        {
            "dialect": "draft-04",
            "schema": {"dependencies": {"value": {"type": "string"}}},
            "definitions": {},
        },
    )


def test_todocumentdraft04_converts_const_to_enum():
    """toDocumentDraft04 / converts const to enum"""
    _check(
        "to_document_draft_04",
        {
            "dialect": "draft-2020-12",
            "schema": {"enum": ["a", "b"], "const": "b", "allOf": [{"type": "string"}]},
            "definitions": {},
        },
        {
            "dialect": "draft-04",
            "schema": {"enum": ["a", "b"], "allOf": [{"type": "string"}, {"enum": ["b"]}]},
            "definitions": {},
        },
    )
    _check(
        "to_document_draft_04",
        {"dialect": "draft-2020-12", "schema": {"const": "a"}, "definitions": {}},
        {"dialect": "draft-04", "schema": {"enum": ["a"]}, "definitions": {}},
    )
    _check(
        "to_document_draft_04",
        {
            "dialect": "draft-2020-12",
            "schema": {"enum": ["a", "b"], "const": "b"},
            "definitions": {},
        },
        {
            "dialect": "draft-04",
            "schema": {"enum": ["a", "b"], "allOf": [{"enum": ["b"]}]},
            "definitions": {},
        },
    )


def test_todocumentdraft04_preserves_refs_in_literal_values():
    """toDocumentDraft04 / preserves refs in literal values"""
    _check(
        "to_document_draft_04",
        {
            "dialect": "draft-2020-12",
            "schema": {"const": {"$ref": "#/$defs/Literal"}},
            "definitions": {},
        },
        {
            "dialect": "draft-04",
            "schema": {"enum": [{"$ref": "#/$defs/Literal"}]},
            "definitions": {},
        },
    )
    _check(
        "to_document_draft_04",
        {
            "dialect": "draft-2020-12",
            "schema": {
                "enum": [{"$ref": "#/$defs/Literal"}],
                "default": {"$ref": "#/$defs/Literal"},
            },
            "definitions": {},
        },
        {
            "dialect": "draft-04",
            "schema": {
                "enum": [{"$ref": "#/$defs/Literal"}],
                "default": {"$ref": "#/$defs/Literal"},
            },
            "definitions": {},
        },
    )


def test_todocumentdraft04_converts_numeric_exclusive_bounds_to_draft():
    """toDocumentDraft04 / converts numeric exclusive bounds to Draft-04 boolean exclusivity"""
    _check(
        "to_document_draft_04",
        {"dialect": "draft-2020-12", "schema": {"minimum": 1}, "definitions": {}},
        {"dialect": "draft-04", "schema": {"minimum": 1}, "definitions": {}},
    )
    _check(
        "to_document_draft_04",
        {"dialect": "draft-2020-12", "schema": {"exclusiveMinimum": 1}, "definitions": {}},
        {
            "dialect": "draft-04",
            "schema": {"minimum": 1, "exclusiveMinimum": True},
            "definitions": {},
        },
    )
    _check(
        "to_document_draft_04",
        {
            "dialect": "draft-2020-12",
            "schema": {"minimum": 2, "exclusiveMinimum": 1},
            "definitions": {},
        },
        {"dialect": "draft-04", "schema": {"minimum": 2}, "definitions": {}},
    )
    _check(
        "to_document_draft_04",
        {
            "dialect": "draft-2020-12",
            "schema": {"minimum": 1, "exclusiveMinimum": 1},
            "definitions": {},
        },
        {
            "dialect": "draft-04",
            "schema": {"minimum": 1, "exclusiveMinimum": True},
            "definitions": {},
        },
    )
    _check(
        "to_document_draft_04",
        {
            "dialect": "draft-2020-12",
            "schema": {"minimum": 1, "exclusiveMinimum": 2},
            "definitions": {},
        },
        {
            "dialect": "draft-04",
            "schema": {"minimum": 2, "exclusiveMinimum": True},
            "definitions": {},
        },
    )
    _check(
        "to_document_draft_04",
        {"dialect": "draft-2020-12", "schema": {"maximum": 2}, "definitions": {}},
        {"dialect": "draft-04", "schema": {"maximum": 2}, "definitions": {}},
    )
    _check(
        "to_document_draft_04",
        {"dialect": "draft-2020-12", "schema": {"exclusiveMaximum": 2}, "definitions": {}},
        {
            "dialect": "draft-04",
            "schema": {"maximum": 2, "exclusiveMaximum": True},
            "definitions": {},
        },
    )
    _check(
        "to_document_draft_04",
        {
            "dialect": "draft-2020-12",
            "schema": {"maximum": 1, "exclusiveMaximum": 2},
            "definitions": {},
        },
        {"dialect": "draft-04", "schema": {"maximum": 1}, "definitions": {}},
    )
    _check(
        "to_document_draft_04",
        {
            "dialect": "draft-2020-12",
            "schema": {"maximum": 2, "exclusiveMaximum": 2},
            "definitions": {},
        },
        {
            "dialect": "draft-04",
            "schema": {"maximum": 2, "exclusiveMaximum": True},
            "definitions": {},
        },
    )
    _check(
        "to_document_draft_04",
        {
            "dialect": "draft-2020-12",
            "schema": {"maximum": 2, "exclusiveMaximum": 1},
            "definitions": {},
        },
        {
            "dialect": "draft-04",
            "schema": {"maximum": 1, "exclusiveMaximum": True},
            "definitions": {},
        },
    )


def test_todocumentdraft04_converts_boolean_schemas_only_in_schema_po():
    """toDocumentDraft04 / converts boolean schemas only in schema positions"""
    _check(
        "to_document_draft_04",
        {
            "dialect": "draft-2020-12",
            "schema": {
                "type": "object",
                "properties": {"allowed": True, "denied": False, "nested": {"not": False}},
                "additionalProperties": False,
                "allOf": [True],
                "anyOf": [False],
            },
            "definitions": {},
        },
        {
            "dialect": "draft-04",
            "schema": {
                "type": "object",
                "properties": {
                    "allowed": {},
                    "denied": {"not": {}},
                    "nested": {"not": {"not": {}}},
                },
                "additionalProperties": {"not": {}},
                "allOf": [{}],
                "anyOf": [{"not": {}}],
            },
            "definitions": {},
        },
    )


def test_todocumentdraft04_converts_tuple_members_and_their_trailing():
    """toDocumentDraft04 / converts tuple members and their trailing boolean schema"""
    _check(
        "to_document_draft_04",
        {
            "dialect": "draft-2020-12",
            "schema": {"type": "array", "prefixItems": [True, False], "items": False},
            "definitions": {},
        },
        {
            "dialect": "draft-04",
            "schema": {"type": "array", "items": [{}, {"not": {}}], "additionalItems": {"not": {}}},
            "definitions": {},
        },
    )
    _check(
        "to_document_draft_04",
        {
            "dialect": "draft-2020-12",
            "schema": {"type": "array", "items": False},
            "definitions": {},
        },
        {
            "dialect": "draft-04",
            "schema": {"type": "array", "items": {"not": {}}},
            "definitions": {},
        },
    )


def test_todocumentdraft04_converts_schemas_in_additionalproperties_a():
    """toDocumentDraft04 / converts schemas in additionalProperties and additionalItems"""
    _check(
        "to_document_draft_04",
        {
            "dialect": "draft-2020-12",
            "schema": {
                "type": "object",
                "additionalProperties": {"const": "value"},
                "properties": {
                    "tuple": {
                        "type": "array",
                        "prefixItems": [{"type": "string"}],
                        "items": {"const": "rest"},
                    }
                },
            },
            "definitions": {},
        },
        {
            "dialect": "draft-04",
            "schema": {
                "type": "object",
                "additionalProperties": {"enum": ["value"]},
                "properties": {
                    "tuple": {
                        "type": "array",
                        "items": [{"type": "string"}],
                        "additionalItems": {"enum": ["rest"]},
                    }
                },
            },
            "definitions": {},
        },
    )


def test_todocumentdraft04_preserves_malformed_values_for_recognized():
    """toDocumentDraft04 / preserves malformed values for recognized keywords"""
    _check(
        "to_document_draft_04",
        {
            "dialect": "draft-2020-12",
            "schema": {"properties": "invalid", "not": [1], "allOf": "invalid"},
            "definitions": {},
        },
        {
            "dialect": "draft-04",
            "schema": {"properties": "invalid", "not": [1], "allOf": "invalid"},
            "definitions": {},
        },
    )


def test_todocumentdraft04_preserves_allof_not_and_null():
    """toDocumentDraft04 / preserves allOf, not, and null"""
    _check(
        "to_document_draft_04",
        {
            "dialect": "draft-2020-12",
            "schema": {"anyOf": [{"type": "null"}, {"allOf": [{"not": {"type": "string"}}]}]},
            "definitions": {},
        },
        {
            "dialect": "draft-04",
            "schema": {"anyOf": [{"type": "null"}, {"allOf": [{"not": {"type": "string"}}]}]},
            "definitions": {},
        },
    )


def test_todocumentdraft04_preserves_newer_annotations_as_draft_04_ex():
    """toDocumentDraft04 / preserves newer annotations as Draft-04 extensions"""
    _check(
        "to_document_draft_04",
        {
            "dialect": "draft-2020-12",
            "schema": {"type": "object", "examples": [{"value": 1}]},
            "definitions": {},
        },
        {
            "dialect": "draft-04",
            "schema": {"type": "object", "examples": [{"value": 1}]},
            "definitions": {},
        },
    )


def test_todocumentdraft04_preserves_constraints_next_to_refs():
    """toDocumentDraft04 / preserves constraints next to refs"""
    _check(
        "to_document_draft_04",
        {
            "dialect": "draft-2020-12",
            "schema": {"$ref": "#/$defs/S", "minLength": 3},
            "definitions": {"S": {"type": "string"}},
        },
        {
            "dialect": "draft-04",
            "schema": {"minLength": 3, "allOf": [{"$ref": "#/definitions/S"}]},
            "definitions": {"S": {"type": "string"}},
        },
    )


def test_todocumentdraft04_preserves_validation_semantics_for_convert():
    """toDocumentDraft04 / preserves validation semantics for converted constraints"""
    _check(
        "to_document_draft_04",
        {
            "dialect": "draft-2020-12",
            "schema": {
                "type": "object",
                "properties": {
                    "mode": {"const": "on"},
                    "value": {"type": "number", "exclusiveMinimum": 0, "exclusiveMaximum": 2},
                    "tuple": {"type": "array", "prefixItems": [{"type": "string"}], "items": False},
                },
                "required": ["mode", "value", "tuple"],
                "additionalProperties": False,
            },
            "definitions": {},
        },
        {
            "dialect": "draft-04",
            "schema": {
                "type": "object",
                "properties": {
                    "mode": {"enum": ["on"]},
                    "value": {
                        "type": "number",
                        "minimum": 0,
                        "exclusiveMinimum": True,
                        "maximum": 2,
                        "exclusiveMaximum": True,
                    },
                    "tuple": {
                        "type": "array",
                        "items": [{"type": "string"}],
                        "additionalItems": {"not": {}},
                    },
                },
                "required": ["mode", "value", "tuple"],
                "additionalProperties": {"not": {}},
            },
            "definitions": {},
        },
    )


def test_todocumentdraft04_converts_documents_generated_from_effect_s():
    """toDocumentDraft04 / converts documents generated from Effect schemas"""
    _check(
        "to_document_draft_04",
        {
            "dialect": "draft-2020-12",
            "schema": {
                "type": "object",
                "properties": {
                    "mode": {"type": "string", "enum": ["enabled"]},
                    "threshold": {"type": "number", "exclusiveMinimum": 0},
                    "tuple": {
                        "type": "array",
                        "prefixItems": [{"type": "string"}, {"type": "boolean"}],
                        "maxItems": 2,
                        "minItems": 2,
                    },
                    "left": {
                        "type": "object",
                        "properties": {"value": {"type": "string"}},
                        "required": ["value"],
                        "additionalProperties": True,
                    },
                    "right": {
                        "type": "object",
                        "properties": {"value": {"type": "string"}},
                        "required": ["value"],
                        "additionalProperties": True,
                    },
                },
                "required": ["mode", "threshold", "tuple", "left", "right"],
                "additionalProperties": True,
            },
            "definitions": {},
        },
        {
            "dialect": "draft-04",
            "schema": {
                "type": "object",
                "properties": {
                    "mode": {"type": "string", "enum": ["enabled"]},
                    "threshold": {"type": "number", "minimum": 0, "exclusiveMinimum": True},
                    "tuple": {
                        "type": "array",
                        "maxItems": 2,
                        "minItems": 2,
                        "items": [{"type": "string"}, {"type": "boolean"}],
                    },
                    "left": {
                        "type": "object",
                        "properties": {"value": {"type": "string"}},
                        "required": ["value"],
                        "additionalProperties": {},
                    },
                    "right": {
                        "type": "object",
                        "properties": {"value": {"type": "string"}},
                        "required": ["value"],
                        "additionalProperties": {},
                    },
                },
                "required": ["mode", "threshold", "tuple", "left", "right"],
                "additionalProperties": {},
            },
            "definitions": {},
        },
    )


def test_to_multi_document_components():
    """``toMultiDocumentComponents``: OpenAPI 3.1 components without its keyword checks,
    the error naming the target (Node's output)."""
    multi = json_schema.MultiDocument(
        "draft-2020-12",
        ({"$ref": "#/$defs/a%20b"}, {"example": 1}),
        {"a b": {"type": "string"}, "a_b": {"$ref": "#/$defs/a%20b/x"}},
    )
    out = json_schema.to_multi_document_components(multi, target="X")
    assert out.schemas == ({"$ref": "#/components/schemas/a_b_1"}, {"example": 1})
    assert out.definitions == {
        "a_b_1": {"type": "string"},
        "a_b": {"$ref": "#/components/schemas/a_b_1/x"},
    }
    resource = json_schema.MultiDocument(
        "draft-2020-12", ({"$id": "https://x/s", "$ref": "#/$defs/A"},), {"A": {}}
    )
    with pytest.raises(ValueError) as info:
        json_schema.to_multi_document_components(resource, target="Target 1")
    assert str(info.value) == (
        'Cannot convert JSON Schema keyword "$ref" to Target 1: '
        "a schema resource cannot reference the shared definitions pool"
    )


def test_to_document_draft_07_with_definitions_path():
    """``toDocumentDraft07WithDefinitionsPath``: references into the given path stay put
    (Node's output)."""
    document = json_schema.Document(
        "draft-2020-12",
        {"$ref": "#/components/schemas/A"},
        {
            "A": {"prefixItems": [{"type": "string"}], "$ref": "#/components/schemas/B"},
            "B": {"type": "string"},
        },
    )
    out = json_schema.to_document_draft_07_with_definitions_path(
        document, ["components", "schemas"]
    )
    assert out.dialect == "draft-07"
    assert out.schema == {"$ref": "#/components/schemas/A"}
    assert out.definitions == {
        "A": {"items": [{"type": "string"}], "allOf": [{"$ref": "#/components/schemas/B"}]},
        "B": {"type": "string"},
    }


def test_tomultidocumentopenapi3_1_rejects_opaque_keywords_that_opena():
    """toMultiDocumentOpenApi3_1 / rejects opaque keywords that OpenAPI 3.1 would activate"""
    _raises(
        "to_multi_document_open_api_3_1",
        {"dialect": "draft-2020-12", "schemas": [{"example": "value"}], "definitions": {}},
        'Cannot convert JSON Schema keyword "example" to OpenAPI 3.1: it is not active in Draft 2020-12 but would become active in the target',  # noqa: E501
    )
    _raises(
        "to_multi_document_open_api_3_1",
        {
            "dialect": "draft-2020-12",
            "schemas": [{"properties": {"value": {"discriminator": {}}}}],
            "definitions": {},
        },
        'Cannot convert JSON Schema keyword "discriminator" to OpenAPI 3.1: it is not active in Draft 2020-12 but would become active in the target',  # noqa: E501
    )
    _raises(
        "to_multi_document_open_api_3_1",
        {"dialect": "draft-2020-12", "schemas": [{}], "definitions": {"Value": {"xml": {}}}},
        'Cannot convert JSON Schema keyword "xml" to OpenAPI 3.1: it is not active in Draft 2020-12 but would become active in the target',  # noqa: E501
    )
    _raises(
        "to_multi_document_open_api_3_1",
        {"dialect": "draft-2020-12", "schemas": [{"externalDocs": {}}], "definitions": {}},
        'Cannot convert JSON Schema keyword "externalDocs" to OpenAPI 3.1: it is not active in Draft 2020-12 but would become active in the target',  # noqa: E501
    )


def test_tomultidocumentopenapi3_1_does_not_inspect_opaque_values_for():
    """toMultiDocumentOpenApi3_1 / does not inspect opaque values for OpenAPI 3.1 keyword collisions"""  # noqa: E501
    _check(
        "to_multi_document_open_api_3_1",
        {
            "dialect": "draft-2020-12",
            "schemas": [
                {"const": {"example": "value", "discriminator": {}, "xml": {}, "externalDocs": {}}}
            ],
            "definitions": {},
        },
        {
            "dialect": "openapi-3.1",
            "schemas": [
                {"const": {"example": "value", "discriminator": {}, "xml": {}, "externalDocs": {}}}
            ],
            "definitions": {},
        },
    )


def test_tomultidocumentopenapi3_1_rewrites_defs_references_to_compon():
    """toMultiDocumentOpenApi3_1 / rewrites `$defs` references to `components/schemas`"""
    _check(
        "to_multi_document_open_api_3_1",
        {
            "dialect": "draft-2020-12",
            "schemas": [
                {
                    "type": "object",
                    "properties": {"a": {"$ref": "#/$defs/A"}, "b": {"$ref": "#/$defs/B"}},
                }
            ],
            "definitions": {"A": {"type": "string", "$ref": "#/$defs/B"}, "B": {"type": "number"}},
        },
        {
            "dialect": "openapi-3.1",
            "schemas": [
                {
                    "type": "object",
                    "properties": {
                        "a": {"$ref": "#/components/schemas/A"},
                        "b": {"$ref": "#/components/schemas/B"},
                    },
                }
            ],
            "definitions": {
                "A": {"type": "string", "$ref": "#/components/schemas/B"},
                "B": {"type": "number"},
            },
        },
    )


def test_tomultidocumentopenapi3_1_rewrites_refs_only_in_schema_posit():
    """toMultiDocumentOpenApi3_1 / rewrites refs only in schema positions"""
    _check(
        "to_multi_document_open_api_3_1",
        {
            "dialect": "draft-2020-12",
            "schemas": [
                {
                    "properties": {"value": {"$ref": "#/$defs/Value"}},
                    "const": {"$ref": "#/$defs/Literal"},
                    "enum": [{"$ref": "#/$defs/Literal"}],
                    "default": {"$ref": "#/$defs/Literal"},
                    "examples": [{"$ref": "#/$defs/Literal"}],
                }
            ],
            "definitions": {"Value": {"type": "string"}},
        },
        {
            "dialect": "openapi-3.1",
            "schemas": [
                {
                    "properties": {"value": {"$ref": "#/components/schemas/Value"}},
                    "const": {"$ref": "#/$defs/Literal"},
                    "enum": [{"$ref": "#/$defs/Literal"}],
                    "default": {"$ref": "#/$defs/Literal"},
                    "examples": [{"$ref": "#/$defs/Literal"}],
                }
            ],
            "definitions": {"Value": {"type": "string"}},
        },
    )


def test_tomultidocumentopenapi3_1_sanitizes_component_schema_keys_an():
    """toMultiDocumentOpenApi3_1 / sanitizes component schema keys and rewritten refs together"""
    _check(
        "to_multi_document_open_api_3_1",
        {
            "dialect": "draft-2020-12",
            "schemas": [{"type": "object", "properties": {"A.B": {"$ref": "#/$defs/A$B"}}}],
            "definitions": {"A$B": {"$ref": "#/$defs/B$C"}, "B$C": {"type": "string"}},
        },
        {
            "dialect": "openapi-3.1",
            "schemas": [
                {"type": "object", "properties": {"A.B": {"$ref": "#/components/schemas/A_B"}}}
            ],
            "definitions": {"A_B": {"$ref": "#/components/schemas/B_C"}, "B_C": {"type": "string"}},
        },
    )


def test_tomultidocumentopenapi3_1_unescapes_a_definition_key_before():
    """toMultiDocumentOpenApi3_1 / unescapes a definition key before sanitizing its ref"""
    _check(
        "to_multi_document_open_api_3_1",
        {
            "dialect": "draft-2020-12",
            "schemas": [{"$ref": "#/$defs/A~1B"}],
            "definitions": {"A/B": {"type": "string"}},
        },
        {
            "dialect": "openapi-3.1",
            "schemas": [{"$ref": "#/components/schemas/A_B"}],
            "definitions": {"A_B": {"type": "string"}},
        },
    )


def test_tomultidocumentopenapi3_1_decodes_a_definition_key_before_sa():
    """toMultiDocumentOpenApi3_1 / decodes a definition key before sanitizing its ref"""
    _check(
        "to_multi_document_open_api_3_1",
        {
            "dialect": "draft-2020-12",
            "schemas": [{"allOf": [{"$ref": "#/$defs/A%20B"}, {"$dynamicRef": "#/$defs/A%20B"}]}],
            "definitions": {"A B": {"type": "string"}},
        },
        {
            "dialect": "openapi-3.1",
            "schemas": [
                {
                    "allOf": [
                        {"$ref": "#/components/schemas/A_B"},
                        {"$dynamicRef": "#/components/schemas/A_B"},
                    ]
                }
            ],
            "definitions": {"A_B": {"type": "string"}},
        },
    )


def test_tomultidocumentopenapi3_1_does_not_rewrite_local_refs_inside():
    """toMultiDocumentOpenApi3_1 / does not rewrite local refs inside embedded schema resources"""
    _check(
        "to_multi_document_open_api_3_1",
        {
            "dialect": "draft-2020-12",
            "schemas": [
                {
                    "allOf": [
                        {"$dynamicRef": "#/$defs/Embedded"},
                        {
                            "$id": "inline.json",
                            "$defs": {"Inner": {"type": "string"}},
                            "$dynamicRef": "#/$defs/Inner",
                        },
                    ]
                }
            ],
            "definitions": {
                "Embedded": {
                    "$id": "embedded.json",
                    "$defs": {"Inner": {"type": "number"}},
                    "allOf": [{"$ref": "#/$defs/Inner"}, {"$dynamicRef": "#/$defs/Inner"}],
                }
            },
        },
        {
            "dialect": "openapi-3.1",
            "schemas": [
                {
                    "allOf": [
                        {"$dynamicRef": "#/components/schemas/Embedded"},
                        {
                            "$id": "inline.json",
                            "$defs": {"Inner": {"type": "string"}},
                            "$dynamicRef": "#/$defs/Inner",
                        },
                    ]
                }
            ],
            "definitions": {
                "Embedded": {
                    "$id": "embedded.json",
                    "$defs": {"Inner": {"type": "number"}},
                    "allOf": [{"$ref": "#/$defs/Inner"}, {"$dynamicRef": "#/$defs/Inner"}],
                }
            },
        },
    )


def test_tomultidocumentopenapi3_1_does_not_rewrite_local_refs_inside_2():
    """toMultiDocumentOpenApi3_1 / does not rewrite local refs inside root schema resources"""
    _check(
        "to_multi_document_open_api_3_1",
        {
            "dialect": "draft-2020-12",
            "schemas": [
                {
                    "$id": "inline.json",
                    "$defs": {"Inner": {"type": "string"}},
                    "allOf": [{"$ref": "#/$defs/Inner"}, {"$dynamicRef": "#/$defs/Inner"}],
                }
            ],
            "definitions": {},
        },
        {
            "dialect": "openapi-3.1",
            "schemas": [
                {
                    "$id": "inline.json",
                    "$defs": {"Inner": {"type": "string"}},
                    "allOf": [{"$ref": "#/$defs/Inner"}, {"$dynamicRef": "#/$defs/Inner"}],
                }
            ],
            "definitions": {},
        },
    )


def test_tomultidocumentopenapi3_1_rejects_shared_definition_refs_fro():
    """toMultiDocumentOpenApi3_1 / rejects shared definition refs from root schema resources"""
    _raises(
        "to_multi_document_open_api_3_1",
        {
            "dialect": "draft-2020-12",
            "schemas": [{"$id": "inline.json", "$ref": "#/$defs/Value"}],
            "definitions": {"Value": {"type": "string"}},
        },
        'Cannot convert JSON Schema keyword "$ref" to OpenAPI 3.1: a schema resource cannot reference the shared definitions pool',  # noqa: E501
    )
    _raises(
        "to_multi_document_open_api_3_1",
        {
            "dialect": "draft-2020-12",
            "schemas": [{"$id": "inline.json", "$dynamicRef": "#/$defs/Value"}],
            "definitions": {"Value": {"type": "string"}},
        },
        'Cannot convert JSON Schema keyword "$dynamicRef" to OpenAPI 3.1: a schema resource cannot reference the shared definitions pool',  # noqa: E501
    )


def test_tomultidocumentopenapi3_1_suffixes_a_sanitized_key_that_coll():
    """toMultiDocumentOpenApi3_1 / suffixes a sanitized key that collides with a valid key"""
    _check(
        "to_multi_document_open_api_3_1",
        {
            "dialect": "draft-2020-12",
            "schemas": [{"allOf": [{"$ref": "#/$defs/A_B"}, {"$ref": "#/$defs/A~1B"}]}],
            "definitions": {"A_B": {"type": "string"}, "A/B": {"type": "number"}},
        },
        {
            "dialect": "openapi-3.1",
            "schemas": [
                {
                    "allOf": [
                        {"$ref": "#/components/schemas/A_B"},
                        {"$ref": "#/components/schemas/A_B_1"},
                    ]
                }
            ],
            "definitions": {"A_B": {"type": "string"}, "A_B_1": {"type": "number"}},
        },
    )


def test_tomultidocumentopenapi3_1_allocates_suffixes_deterministical():
    """toMultiDocumentOpenApi3_1 / allocates suffixes deterministically and skips occupied keys"""
    _check(
        "to_multi_document_open_api_3_1",
        {
            "dialect": "draft-2020-12",
            "schemas": [
                {
                    "allOf": [
                        {"$ref": "#/$defs/A_B"},
                        {"$ref": "#/$defs/A_B_1"},
                        {"$ref": "#/$defs/A~1B"},
                        {"$ref": "#/$defs/A?B"},
                    ]
                }
            ],
            "definitions": {
                "A?B": {"type": "null"},
                "A_B_1": {"type": "boolean"},
                "A/B": {"type": "number"},
                "A_B": {"type": "string"},
            },
        },
        {
            "dialect": "openapi-3.1",
            "schemas": [
                {
                    "allOf": [
                        {"$ref": "#/components/schemas/A_B"},
                        {"$ref": "#/components/schemas/A_B_1"},
                        {"$ref": "#/components/schemas/A_B_2"},
                        {"$ref": "#/components/schemas/A_B_3"},
                    ]
                }
            ],
            "definitions": {
                "A_B_3": {"type": "null"},
                "A_B_1": {"type": "boolean"},
                "A_B_2": {"type": "number"},
                "A_B": {"type": "string"},
            },
        },
    )
    _check(
        "to_multi_document_open_api_3_1",
        {
            "dialect": "draft-2020-12",
            "schemas": [
                {
                    "allOf": [
                        {"$ref": "#/$defs/A_B"},
                        {"$ref": "#/$defs/A_B_1"},
                        {"$ref": "#/$defs/A~1B"},
                        {"$ref": "#/$defs/A?B"},
                    ]
                }
            ],
            "definitions": {
                "A_B": {"type": "string"},
                "A/B": {"type": "number"},
                "A_B_1": {"type": "boolean"},
                "A?B": {"type": "null"},
            },
        },
        {
            "dialect": "openapi-3.1",
            "schemas": [
                {
                    "allOf": [
                        {"$ref": "#/components/schemas/A_B"},
                        {"$ref": "#/components/schemas/A_B_1"},
                        {"$ref": "#/components/schemas/A_B_2"},
                        {"$ref": "#/components/schemas/A_B_3"},
                    ]
                }
            ],
            "definitions": {
                "A_B": {"type": "string"},
                "A_B_2": {"type": "number"},
                "A_B_1": {"type": "boolean"},
                "A_B_3": {"type": "null"},
            },
        },
    )


def test_tomultidocumentopenapi3_1_reserves_sanitized_bases_before_al():
    """toMultiDocumentOpenApi3_1 / reserves sanitized bases before allocating suffixes"""
    _check(
        "to_multi_document_open_api_3_1",
        {
            "dialect": "draft-2020-12",
            "schemas": [
                {
                    "allOf": [
                        {"$ref": "#/$defs/A~1B"},
                        {"$ref": "#/$defs/A?B"},
                        {"$ref": "#/$defs/A?B?1"},
                    ]
                }
            ],
            "definitions": {
                "A/B": {"type": "number"},
                "A?B": {"type": "string"},
                "A?B?1": {"type": "boolean"},
            },
        },
        {
            "dialect": "openapi-3.1",
            "schemas": [
                {
                    "allOf": [
                        {"$ref": "#/components/schemas/A_B"},
                        {"$ref": "#/components/schemas/A_B_2"},
                        {"$ref": "#/components/schemas/A_B_1"},
                    ]
                }
            ],
            "definitions": {
                "A_B": {"type": "number"},
                "A_B_2": {"type": "string"},
                "A_B_1": {"type": "boolean"},
            },
        },
    )


def test_tomultidocumentopenapi3_1_rewrites_nested_definition_refs_wi():
    """toMultiDocumentOpenApi3_1 / rewrites nested definition refs without changing other refs"""
    _check(
        "to_multi_document_open_api_3_1",
        {
            "dialect": "draft-2020-12",
            "schemas": [
                {
                    "allOf": [
                        {"$ref": "#/$defs/A~1B/properties/value"},
                        {"$ref": "https://example.com/schema#/$defs/A~1B"},
                        {"$ref": "#/other/A~1B"},
                    ]
                }
            ],
            "definitions": {"A/B": {"type": "object", "properties": {"value": {"type": "string"}}}},
        },
        {
            "dialect": "openapi-3.1",
            "schemas": [
                {
                    "allOf": [
                        {"$ref": "#/components/schemas/A_B/properties/value"},
                        {"$ref": "https://example.com/schema#/$defs/A~1B"},
                        {"$ref": "#/other/A~1B"},
                    ]
                }
            ],
            "definitions": {"A_B": {"type": "object", "properties": {"value": {"type": "string"}}}},
        },
    )


def test_input_immutability_fromschemadraft07_does_not_mutate_its_inp():
    """input immutability / fromSchemaDraft07 does not mutate its input"""
    _check(
        "from_schema_draft_07",
        {
            "type": "array",
            "items": [{"type": "string"}],
            "additionalItems": False,
            "definitions": {"Value": {"type": "string"}},
        },
        {
            "dialect": "draft-2020-12",
            "schema": {"type": "array", "prefixItems": [{"type": "string"}], "items": False},
            "definitions": {"Value": {"type": "string"}},
        },
    )


def test_input_immutability_fromschemadraft2020_12_does_not_mutate_it():
    """input immutability / fromSchemaDraft2020_12 does not mutate its input"""
    _check(
        "from_schema_draft_2020_12",
        {
            "type": "object",
            "properties": {
                "value": {"type": "array", "prefixItems": [{"type": "string"}], "items": False}
            },
        },
        {
            "dialect": "draft-2020-12",
            "schema": {
                "type": "object",
                "properties": {
                    "value": {"type": "array", "prefixItems": [{"type": "string"}], "items": False}
                },
            },
            "definitions": {},
        },
    )


def test_input_immutability_fromschemaopenapi3_1_does_not_mutate_its():
    """input immutability / fromSchemaOpenApi3_1 does not mutate its input"""
    _check(
        "from_schema_open_api_3_1",
        {
            "type": "object",
            "properties": {
                "value": {"type": "array", "prefixItems": [{"type": "string"}], "items": False}
            },
        },
        {
            "dialect": "draft-2020-12",
            "schema": {
                "type": "object",
                "properties": {
                    "value": {"type": "array", "prefixItems": [{"type": "string"}], "items": False}
                },
            },
            "definitions": {},
        },
    )


def test_input_immutability_fromschemaopenapi3_0_does_not_mutate_its():
    """input immutability / fromSchemaOpenApi3_0 does not mutate its input"""
    _check(
        "from_schema_open_api_3_0",
        {"type": "array", "items": {"type": "string"}, "nullable": True},
        {
            "dialect": "draft-2020-12",
            "schema": {"type": ["array", "null"], "items": {"type": "string"}},
            "definitions": {},
        },
    )


def test_input_immutability_todocumentdraft07_does_not_mutate_its_inp():
    """input immutability / toDocumentDraft07 does not mutate its input"""
    _check(
        "to_document_draft_07",
        {
            "dialect": "draft-2020-12",
            "schema": {
                "type": "object",
                "properties": {
                    "value": {"type": "array", "prefixItems": [{"type": "string"}], "items": False}
                },
            },
            "definitions": {"Value": {"type": "string"}},
        },
        {
            "dialect": "draft-07",
            "schema": {
                "type": "object",
                "properties": {
                    "value": {
                        "type": "array",
                        "items": [{"type": "string"}],
                        "additionalItems": False,
                    }
                },
            },
            "definitions": {"Value": {"type": "string"}},
        },
    )


def test_input_immutability_todocumentdraft04_does_not_mutate_its_inp():
    """input immutability / toDocumentDraft04 does not mutate its input"""
    _check(
        "to_document_draft_04",
        {
            "dialect": "draft-2020-12",
            "schema": {
                "type": "object",
                "properties": {
                    "value": {"type": "array", "prefixItems": [{"type": "string"}], "items": False}
                },
            },
            "definitions": {"Value": {"type": "string"}},
        },
        {
            "dialect": "draft-04",
            "schema": {
                "type": "object",
                "properties": {
                    "value": {
                        "type": "array",
                        "items": [{"type": "string"}],
                        "additionalItems": {"not": {}},
                    }
                },
            },
            "definitions": {"Value": {"type": "string"}},
        },
    )


def test_input_immutability_tomultidocumentopenapi3_1_does_not_mutate():
    """input immutability / toMultiDocumentOpenApi3_1 does not mutate its input"""
    _check(
        "to_multi_document_open_api_3_1",
        {
            "dialect": "draft-2020-12",
            "schemas": [
                {
                    "type": "object",
                    "properties": {
                        "value": {
                            "type": "array",
                            "prefixItems": [{"type": "string"}],
                            "items": False,
                        }
                    },
                }
            ],
            "definitions": {"Value": {"type": "string"}},
        },
        {
            "dialect": "openapi-3.1",
            "schemas": [
                {
                    "type": "object",
                    "properties": {
                        "value": {
                            "type": "array",
                            "prefixItems": [{"type": "string"}],
                            "items": False,
                        }
                    },
                }
            ],
            "definitions": {"Value": {"type": "string"}},
        },
    )


def test_roundtrip_conversions_preserves_a_draft_07_schema_and_defini():
    """roundtrip conversions / preserves a Draft-07 schema and definitions through canonical form"""
    _check(
        "from_schema_draft_07",
        {
            "type": "object",
            "readOnly": True,
            "writeOnly": True,
            "not": {"required": ["forbidden"]},
            "properties": {
                "name": {"type": "string"},
                "items": {
                    "type": "array",
                    "items": [{"type": "string"}, {"type": "number"}],
                    "additionalItems": {"type": "boolean"},
                },
                "ref": {"$ref": "#/definitions/MyType"},
            },
            "definitions": {"MyType": {"type": "string"}},
        },
        {
            "dialect": "draft-2020-12",
            "schema": {
                "type": "object",
                "readOnly": True,
                "writeOnly": True,
                "not": {"required": ["forbidden"]},
                "properties": {
                    "name": {"type": "string"},
                    "items": {
                        "type": "array",
                        "prefixItems": [{"type": "string"}, {"type": "number"}],
                        "items": {"type": "boolean"},
                    },
                    "ref": {"$ref": "#/$defs/MyType"},
                },
            },
            "definitions": {"MyType": {"type": "string"}},
        },
    )
    _check(
        "to_document_draft_07",
        {
            "dialect": "draft-2020-12",
            "schema": {
                "type": "object",
                "readOnly": True,
                "writeOnly": True,
                "not": {"required": ["forbidden"]},
                "properties": {
                    "name": {"type": "string"},
                    "items": {
                        "type": "array",
                        "prefixItems": [{"type": "string"}, {"type": "number"}],
                        "items": {"type": "boolean"},
                    },
                    "ref": {"$ref": "#/$defs/MyType"},
                },
            },
            "definitions": {"MyType": {"type": "string"}},
        },
        {
            "dialect": "draft-07",
            "schema": {
                "type": "object",
                "readOnly": True,
                "writeOnly": True,
                "not": {"required": ["forbidden"]},
                "properties": {
                    "name": {"type": "string"},
                    "items": {
                        "type": "array",
                        "items": [{"type": "string"}, {"type": "number"}],
                        "additionalItems": {"type": "boolean"},
                    },
                    "ref": {"$ref": "#/definitions/MyType"},
                },
            },
            "definitions": {"MyType": {"type": "string"}},
        },
    )
