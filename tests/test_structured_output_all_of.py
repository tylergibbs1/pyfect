"""How the providers' structured-output rewriters fold ``allOf`` members,
on edges Effect's tests leave out. Each expected value was printed by
Effect's ``toCodecOpenAI`` / ``toCodecAnthropic`` under Node."""

from __future__ import annotations

from typing import TypedDict, cast

from pyfect import schema as S
from pyfect.ai.anthropic_structured_output import to_codec_anthropic
from pyfect.ai.openai_structured_output import to_codec_openai
from pyfect.json_schema import JsonSchema
from pyfect.schema.ast import Filter, make_filter


class _A(TypedDict):
    a: object


def _fragment(fragment: JsonSchema) -> Filter[object]:
    def to_json_schema(_: object) -> JsonSchema:
        return fragment

    return make_filter(lambda _: True, to_json_schema=to_json_schema)


def _openai_property(schema: S.Top) -> JsonSchema:
    properties = to_codec_openai(S.Struct(_A, a=schema)).json_schema["properties"]
    return cast("dict[str, JsonSchema]", properties)["a"]


def test_a_member_keyword_is_kept_only_when_every_member_has_the_same_value():
    """Effect compares with ``!==``: equal strings agree, two equal
    ``enum`` arrays do not (they are different arrays)."""
    assert _openai_property(
        S.String.check(_fragment({"title": "x"}), _fragment({"title": "x"}))
    ) == {"type": "string", "title": "x"}
    assert _openai_property(
        S.String.check(
            _fragment({"title": "x"}), _fragment({"title": "y"}), _fragment({"title": "x"})
        )
    ) == {"type": "string"}
    assert _openai_property(
        S.String.check(_fragment({"enum": ["a"]}), _fragment({"enum": ["a"]}))
    ) == {"type": "string"}


def test_a_member_with_both_bounds_keeps_the_exclusive_one():
    assert _openai_property(
        S.Finite.check(_fragment({"minimum": 1, "exclusiveMinimum": 1}), _fragment({"minimum": 0}))
    ) == {"type": "number", "exclusiveMinimum": 1}
    assert _openai_property(
        S.Finite.check(_fragment({"maximum": 1, "exclusiveMaximum": 1}), _fragment({"maximum": 2}))
    ) == {"type": "number", "exclusiveMaximum": 1}


def test_repeated_member_descriptions_are_joined_once():
    assert _openai_property(S.String.check(S.is_min_length(1), S.is_min_length(1))) == {
        "type": "string",
        "description": "a value with a length of at least 1",
    }
    assert to_codec_anthropic(
        S.String.check(S.is_min_length(1), S.is_min_length(1))
    ).json_schema == {"type": "string", "description": "a value with a length of at least 1"}


def test_anthropic_drops_member_patterns_of_a_type_that_is_not_a_string():
    schema = S.Finite.check(
        _fragment({"pattern": "x", "description": "d1"}),
        _fragment({"pattern": "y", "description": "d2"}),
    )
    assert to_codec_anthropic(schema).json_schema == {"type": "number", "description": "d1 and d2"}
