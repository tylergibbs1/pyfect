"""Ports of Effect's ``toStandardJSONSchemaV1.test.ts``.

``schema["~standard"].jsonSchema`` is ``adapted.__standard__.json_schema``;
``extend`` is subclassing the adapter."""

from __future__ import annotations

from typing import Any, cast

import pyfect.schema as S

_2020 = "https://json-schema.org/draft/2020-12/schema"
_07 = "http://json-schema.org/draft-07/schema#"


def _input(schema: Any, target: Any = "draft-2020-12") -> Any:
    return schema.__standard__.json_schema.input(target=target)


def _output(schema: Any, target: Any = "draft-2020-12") -> Any:
    return schema.__standard__.json_schema.output(target=target)


def test_describes_subclass_fields_when_the_parent_already_has_a_standard_json_schema_adapter():
    """describes subclass fields when the parent already has a Standard JSON Schema adapter"""

    class Parent(S.Class):
        a: str

    parent: Any = S.to_standard_schema_v1(S.to_standard_json_schema_v1(Parent))

    class Child(parent):
        b: float = S.field(S.FiniteFromString)

    child = S.to_standard_json_schema_v1(cast("Any", Child))
    assert child.__standard__.validate is None

    def document(b: str) -> object:
        return {
            "$schema": _2020,
            "$ref": "#/$defs/Child",
            "$defs": {
                "Child": {
                    "type": "object",
                    "properties": {"a": {"type": "string"}, "b": {"type": b}},
                    "required": ["a", "b"],
                    "additionalProperties": True,
                }
            },
        }

    assert _input(child) == document("string")
    assert _output(child) == document("number")


def test_should_return_a_schema_with_standard_json_schema_metadata():
    """should return a schema with Standard JSON Schema metadata"""
    assert S.is_schema(S.to_standard_json_schema_v1(S.FiniteFromString))


def test_should_support_both_standards():
    """should support both standards"""
    both = S.to_standard_schema_v1(S.to_standard_json_schema_v1(S.String))
    assert _input(both) == {"$schema": _2020, "type": "string"}


def test_draft_2020_12_should_return_the_input_json_schema():
    """draft-2020-12 / should return the input JSON Schema"""
    standard = S.to_standard_json_schema_v1(S.Tuple(S.FiniteFromString))
    assert _input(standard) == {
        "$schema": _2020,
        "type": "array",
        "prefixItems": [{"type": "string"}],
        "minItems": 1,
        "maxItems": 1,
    }


def test_draft_2020_12_should_return_the_output_json_schema():
    """draft-2020-12 / should return the output JSON Schema"""
    standard = S.to_standard_json_schema_v1(S.Tuple(S.FiniteFromString))
    assert _output(standard) == {
        "$schema": _2020,
        "type": "array",
        "prefixItems": [{"type": "number"}],
        "minItems": 1,
        "maxItems": 1,
    }


def test_draft_2020_12_a_schema_with_identifier():
    """draft-2020-12 / a schema with identifier"""
    s = S.String.annotate(identifier="id")
    standard = S.to_standard_json_schema_v1(S.Tuple(s, s))
    assert _input(standard) == {
        "$schema": _2020,
        "type": "array",
        "prefixItems": [{"$ref": "#/$defs/id"}, {"$ref": "#/$defs/id"}],
        "minItems": 2,
        "maxItems": 2,
        "$defs": {"id": {"type": "string"}},
    }


def test_draft_07_should_return_the_input_json_schema():
    """draft-07 / should return the input JSON Schema"""
    standard = S.to_standard_json_schema_v1(S.Tuple(S.FiniteFromString))
    assert _input(standard, "draft-07") == {
        "$schema": _07,
        "type": "array",
        "items": [{"type": "string"}],
        "minItems": 1,
        "maxItems": 1,
    }


def test_draft_07_should_return_the_output_json_schema():
    """draft-07 / should return the output JSON Schema"""
    standard = S.to_standard_json_schema_v1(S.Tuple(S.FiniteFromString))
    assert _output(standard, "draft-07") == {
        "$schema": _07,
        "type": "array",
        "items": [{"type": "number"}],
        "minItems": 1,
        "maxItems": 1,
    }


def test_draft_07_a_schema_with_identifier():
    """draft-07 / a schema with identifier"""
    s = S.String.annotate(identifier="id")
    standard = S.to_standard_json_schema_v1(S.Tuple(s, s))
    assert _input(standard, "draft-07") == {
        "$schema": _07,
        "type": "array",
        "items": [{"$ref": "#/definitions/id"}, {"$ref": "#/definitions/id"}],
        "minItems": 2,
        "maxItems": 2,
        "definitions": {"id": {"type": "string"}},
    }
