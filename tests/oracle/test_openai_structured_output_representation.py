"""Ports of Effect's ``test/ai/OpenAiStructuredOutputRepresentation.test.ts``
(``describe("OpenAiStructuredOutput representation v2")``). Each test's
docstring is the Effect test title. A custom check's ``toJsonSchema`` is its
``to_json_schema`` annotation, given a ``CheckContext``."""

from __future__ import annotations

from typing import Any, TypedDict, TypeIs, cast

from pyfect import schema as S
from pyfect.ai.openai_structured_output import to_codec_openai
from pyfect.json_schema import JsonSchema
from pyfect.schema import CheckContext, ToJsonSchema
from pyfect.testing import SchemaAsserts


class _Value(TypedDict):
    value: Any


def _value_schema(schema: S.Top) -> JsonSchema:
    """Effect's ``toValueSchema``: the schema's JSON Schema as a property."""
    properties = to_codec_openai(S.Struct(_Value, value=schema)).json_schema["properties"]
    return cast("dict[str, JsonSchema]", properties)["value"]


def _fragment(schema: JsonSchema) -> ToJsonSchema:
    return lambda _: schema


def _representation(name: str, **rest: object) -> dict[str, object]:
    return {"id": f"test/ai/openai/{name}", "payload": None, **rest}


def test_projects_the_encoded_side():
    """projects the encoded side before JSON Schema generation"""
    assert _value_schema(S.FiniteFromString)["type"] == "string"


def test_keeps_supported_filters_with_a_description():
    """keeps supported custom JSON Schema filters with a description"""
    schema = S.String.check(
        S.make_filter(
            lambda value: value.startswith("a"),
            description="starts with a",
            representation=_representation("startsWithA"),
            to_json_schema=_fragment({"pattern": "^a"}),
        )
    )
    assert _value_schema(schema) == {
        "type": "string",
        "description": "starts with a",
        "pattern": "^a",
    }


def test_drops_unsupported_filters_with_a_description():
    """drops unsupported custom JSON Schema filters with a description"""
    schema = S.String.check(
        S.make_filter(
            lambda value: len(value) >= 2,
            description="at least two characters",
            representation=_representation("minTwoCharactersWithDescription"),
            to_json_schema=_fragment({"minLength": 2}),
        )
    )
    result = to_codec_openai(S.Struct(_Value, value=schema))
    properties = cast("dict[str, JsonSchema]", result.json_schema["properties"])
    assert properties["value"] == {"type": "string", "description": "at least two characters"}
    SchemaAsserts(result.codec).decoding().fail({"value": "a"}, 'Expected <filter>\n  at ["value"]')


def test_keeps_supported_filters_without_a_description():
    """keeps supported custom JSON Schema filters without a description"""
    schema = S.String.check(
        S.make_filter(
            lambda value: value.startswith("a"),
            representation=_representation("startsWithAWithoutDescription"),
            to_json_schema=_fragment({"pattern": "^a"}),
        )
    )
    assert _value_schema(schema) == {"type": "string", "pattern": "^a"}


def test_drops_unsupported_filters_without_a_description():
    """drops unsupported custom JSON Schema filters without a description"""
    schema = S.String.check(
        S.make_filter(
            lambda value: len(value) >= 2,
            representation=_representation("minTwoCharactersWithoutDescription"),
            to_json_schema=_fragment({"minLength": 2}),
        )
    )
    assert _value_schema(schema) == {"type": "string"}


def test_invokes_callbacks_only_with_compiler_inputs():
    """invokes custom JSON Schema callbacks only with compiler inputs"""
    contexts: list[CheckContext] = []

    def to_json_schema(context: CheckContext) -> dict[str, object]:
        contexts.append(context)
        return {"pattern": "^a"}

    schema = S.String.check(
        S.make_filter(
            lambda _: True,
            representation=_representation("compilerInputs", schemas=(S.Finite.ast,)),
            to_json_schema=to_json_schema,
        )
    )
    assert _value_schema(schema) == {"type": "string", "pattern": "^a"}
    assert len(contexts) == 1
    assert contexts[0].type == "string"
    assert [s.get("type") for s in contexts[0].schemas] == ["number"]


def test_compiles_callbacks_after_structural_transformations():
    """compiles custom callbacks after structural transformations"""
    types: list[str | None] = []

    def to_json_schema(context: CheckContext) -> dict[str, object]:
        types.append(context.type)
        return {"minItems": 1}

    schema = S.Record(S.String, S.Finite).check(
        S.make_filter(
            lambda _: True,
            representation=_representation("structuralCompilerInput"),
            to_json_schema=to_json_schema,
        )
    )
    json_schema = _value_schema(schema)
    assert json_schema["type"] == "array"
    assert json_schema["minItems"] == 1
    assert types == ["array"]


class _MinLength(TypedDict):
    minLength: Any


def test_keeps_property_names_matching_unsupported_keywords():
    """keeps property names that match unsupported keywords"""
    unsupported = S.Any.check(
        S.make_filter(
            lambda _: True,
            representation=_representation("unsupportedPropertySchema"),
            to_json_schema=_fragment({"minLength": 2}),
        )
    )
    assert to_codec_openai(S.Struct(_MinLength, minLength=unsupported)).json_schema == {
        "type": "object",
        "properties": {"minLength": {}},
        "required": ["minLength"],
        "additionalProperties": False,
    }


def test_keeps_the_original_codec_on_the_fast_path():
    """keeps the original codec on the unchanged fast path"""
    schema = S.Struct(_Value, value=S.String)
    assert to_codec_openai(schema).codec is schema


class _Fixed(TypedDict):
    fixed: str


_FIXED: JsonSchema = {
    "type": "object",
    "properties": {"fixed": {"type": "string"}},
    "required": ["fixed"],
    "additionalProperties": False,
}


def test_drops_pattern_properties_from_callbacks():
    """drops patternProperties returned by custom callbacks"""
    schema = S.Struct(_Fixed).check(
        S.make_filter(
            lambda _: True,
            representation=_representation("patternProperties"),
            to_json_schema=_fragment({"patternProperties": {"^x": {"type": "string"}}}),
        )
    )
    assert to_codec_openai(schema).json_schema == _FIXED


def test_does_not_merge_structural_constraints_from_all_of():
    """does not merge structural constraints from allOf"""
    schema = S.Struct(_Fixed).check(
        S.make_filter(
            lambda _: True,
            representation=_representation("structuralAllOf"),
            to_json_schema=_fragment(
                {"properties": {"extra": {"type": "string"}}, "required": ["extra"]}
            ),
        )
    )
    assert to_codec_openai(schema).json_schema == _FIXED


class _Opaque:
    tag = "Opaque"


def _is_opaque(value: object) -> TypeIs[_Opaque]:
    return isinstance(value, _Opaque)


def test_keeps_declaration_fallback_validation():
    """keeps declaration fallback validation in the codec"""
    result = to_codec_openai(S.Struct(_Value, value=S.declare(_is_opaque, expected="Opaque")))
    properties = cast("dict[str, JsonSchema]", result.json_schema["properties"])
    assert properties["value"]
    assert S.decode_unknown_option(result.codec)({"value": {}}) is None


def test_merges_repeated_lower_bounds():
    """merges repeated lower bounds conservatively"""
    schema = S.Finite.check(
        S.is_greater_than(1), S.is_greater_than_or_equal_to(2), S.is_greater_than(2)
    )
    assert _value_schema(schema) == {
        "type": "number",
        "description": (
            "a value greater than 1 and a value greater than or equal to 2 "
            "and a value greater than 2"
        ),
        "exclusiveMinimum": 2,
    }


def test_merges_repeated_array_bounds():
    """merges repeated array bounds conservatively"""
    json_schema = _value_schema(
        S.Array(S.String).check(
            S.is_min_length(1), S.is_min_length(2), S.is_max_length(5), S.is_max_length(4)
        )
    )
    assert json_schema["minItems"] == 2
    assert json_schema["maxItems"] == 4


def test_transports_only_sound_record_size_bounds():
    """transports only sound record size bounds to entry arrays"""
    maximum = _value_schema(S.Record(S.String, S.Finite).check(S.is_max_properties(3)))
    assert "maxItems" not in maximum
    between = _value_schema(S.Record(S.String, S.Finite).check(S.is_between_properties(1, 3)))
    assert between["minItems"] == 1
    assert "maxItems" not in between
