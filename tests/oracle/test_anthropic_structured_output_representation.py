"""Ports of Effect's ``test/ai/AnthropicStructuredOutputRepresentation.test.ts``
(``describe("AnthropicStructuredOutput representation v2")``). Each test's
docstring is the Effect test title. A custom check's ``toJsonSchema`` is its
``to_json_schema`` annotation, given a ``CheckContext``."""

from __future__ import annotations

from typing import Any, TypedDict

from pyfect import schema as S
from pyfect.ai.anthropic_structured_output import to_codec_anthropic
from pyfect.json_schema import JsonSchema
from pyfect.schema import CheckContext, ToJsonSchema
from pyfect.testing import SchemaAsserts


def _fragment(schema: JsonSchema) -> ToJsonSchema:
    return lambda _: schema


def _representation(name: str, **rest: object) -> dict[str, object]:
    return {"id": f"test/ai/anthropic/{name}", "payload": None, **rest}


def test_projects_the_encoded_side():
    """projects the encoded side before JSON Schema generation"""
    assert to_codec_anthropic(S.FiniteFromString).json_schema["type"] == "string"


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
    assert to_codec_anthropic(schema).json_schema == {
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
    result = to_codec_anthropic(schema)
    assert result.json_schema == {"type": "string", "description": "at least two characters"}
    SchemaAsserts(result.codec).decoding().fail("a", "Expected <filter>")


def test_keeps_supported_filters_without_a_description():
    """keeps supported custom JSON Schema filters without a description"""
    schema = S.String.check(
        S.make_filter(
            lambda value: value.startswith("a"),
            representation=_representation("startsWithAWithoutDescription"),
            to_json_schema=_fragment({"pattern": "^a"}),
        )
    )
    assert to_codec_anthropic(schema).json_schema == {"type": "string", "pattern": "^a"}


def test_drops_unsupported_filters_without_a_description():
    """drops unsupported custom JSON Schema filters without a description"""
    schema = S.String.check(
        S.make_filter(
            lambda value: len(value) >= 2,
            representation=_representation("minTwoCharactersWithoutDescription"),
            to_json_schema=_fragment({"minLength": 2}),
        )
    )
    assert to_codec_anthropic(schema).json_schema == {"type": "string"}


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
    assert to_codec_anthropic(schema).json_schema == {"type": "string", "pattern": "^a"}
    assert len(contexts) == 1
    assert contexts[0].type == "string"
    assert [s.get("type") for s in contexts[0].schemas] == ["number"]


def test_compiles_callbacks_after_structural_transformations():
    """compiles custom callbacks after structural transformations"""
    types: list[str | None] = []

    def to_json_schema(context: CheckContext) -> dict[str, object]:
        types.append(context.type)
        return {"description": "compiled from the provider shape"}

    schema = S.Record(S.String, S.Finite).check(
        S.make_filter(
            lambda _: True,
            representation=_representation("structuralCompilerInput"),
            to_json_schema=to_json_schema,
        )
    )
    json_schema = to_codec_anthropic(schema).json_schema
    assert json_schema["type"] == "array"
    assert json_schema["description"] == (
        "Object encoded as array of [key, value] pairs. Apply object constraints to the "
        "decoded object and compiled from the provider shape"
    )
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
    assert to_codec_anthropic(S.Struct(_MinLength, minLength=unsupported)).json_schema == {
        "type": "object",
        "properties": {"minLength": {}},
        "required": ["minLength"],
        "additionalProperties": False,
    }


def test_keeps_the_original_codec_on_the_fast_path():
    """keeps the original codec on the unchanged fast path"""
    assert to_codec_anthropic(S.String).codec is S.String
