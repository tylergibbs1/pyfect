"""Ports of Effect's ``test/ai/AnthropicStructuredOutput.test.ts``. Each
test's docstring is the Effect test title, prefixed by its ``describe``
blocks below ``toCodecAnthropic``.

Python differs in one place, kept as the expected value: ``is_pattern``
takes a Python ``re`` pattern, which JSON Schema cannot carry, so it gives
no ``pattern`` (only its description).

Omitted:
- "Canonical JSON and mechanical invariants / encodes Undefined as null"
  and "... / encodes a bigint Literal as a string": Python has no
  ``undefined`` and no bigint literals (an ``int`` literal is a number).
- "Canonical JSON and mechanical invariants / Objects / non-string property
  signature name": a struct's keys are a TypedDict's, always strings.
"""

from __future__ import annotations

import re
from typing import Any, NotRequired, TypedDict

import pytest

from pyfect import schema as S
from pyfect.ai import tool as T
from pyfect.ai.anthropic_structured_output import to_codec_anthropic
from pyfect.json_schema import JsonSchema
from pyfect.testing import SchemaAsserts

_TUPLE = (
    "Tuple encoded as an object with numeric string keys ('0', '1', ...). "
    "If present, '__rest__' contains remaining elements"
)
_TUPLE_TAIL = f"{_TUPLE}. Post-rest elements use '__tail_0__', '__tail_1__', and so on"
_RECORD = (
    "Object encoded as array of [key, value] pairs. Apply object constraints to the decoded object"
)


def _check(schema: S.Top, expected: JsonSchema) -> None:
    assert to_codec_anthropic(schema).json_schema == expected


def _error(schema: S.Top, message: str) -> None:
    with pytest.raises(Exception, match=re.escape(message)):
        to_codec_anthropic(schema)


def _pair(key: JsonSchema, value: JsonSchema) -> JsonSchema:
    return {
        "type": "object",
        "description": _TUPLE,
        "properties": {"0": key, "1": value},
        "required": ["0", "1"],
        "additionalProperties": False,
    }


def _entries(description: str, key: JsonSchema, value: JsonSchema) -> JsonSchema:
    return {"type": "array", "description": description, "items": _pair(key, value)}


class _A(TypedDict):
    a: str


class _AB(TypedDict):
    a: str
    b: NotRequired[float]


_Recursive = TypedDict("_Recursive", {"a": str, "as": Any})


def test_post_rest_elements():
    """Canonical JSON and mechanical invariants / Arrays / encodes post-rest elements as object properties"""  # noqa: E501
    _check(
        S.TupleWithRest(S.Tuple(), S.String, S.String),
        {
            "type": "object",
            "properties": {
                "__rest__": {"type": "array", "items": {"type": "string"}},
                "__tail_0__": {"type": "string"},
            },
            "required": ["__rest__", "__tail_0__"],
            "additionalProperties": False,
            "description": _TUPLE_TAIL,
        },
    )


def test_non_recursive_suspend():
    """Canonical JSON and mechanical invariants / non-recursive Suspend"""
    _check(S.suspend(lambda: S.String), {"type": "string"})


def test_rejects_recursive_suspend():
    """Canonical JSON and mechanical invariants / rejects recursive Suspend"""

    def recursive() -> Any:
        return schema

    schema: Any = S.Struct(
        _Recursive,
        **{"a": S.String.check(S.is_starting_with("a")), "as": S.Array(S.suspend(recursive))},
    )
    _error(schema, "AnthropicStructuredOutput: Recursive schemas are not supported")


def test_null():
    """Null"""
    _check(S.Null, {"type": "null"})


def test_string():
    """String / String"""
    _check(S.String, {"type": "string"})
    _check(
        S.String.annotate(description="description"),
        {"type": "string", "description": "description"},
    )


def test_string_supported_format():
    """String / String + supported format"""
    _check(S.String.annotate(format="date-time"), {"type": "string", "format": "date-time"})


def test_string_unsupported_format():
    """String / String + unsupported format"""
    _check(
        S.String.annotate(format="int32"),
        {"type": "string", "description": "a value with a format of int32"},
    )


def test_string_min_length():
    """String / String + isMinLength"""
    _check(
        S.String.check(S.is_min_length(1)),
        {"type": "string", "description": "a value with a length of at least 1"},
    )


def test_string_min_max_length():
    """String / String + isMinLength + isMaxLength"""
    _check(
        S.String.check(S.is_min_length(1), S.is_max_length(2)),
        {
            "type": "string",
            "description": (
                "a value with a length of at least 1 and a value with a length of at most 2"
            ),
        },
    )


def test_string_starts_with():
    """String / String + startsWith"""
    _check(
        S.String.check(S.is_starting_with("a")),
        {"type": "string", "description": 'a string starting with "a"', "pattern": "^a"},
    )


def test_string_starts_with_ends_with():
    """String / String + startsWith + endsWith"""
    _check(
        S.String.check(S.is_starting_with("a"), S.is_ending_with("b")),
        {
            "type": "string",
            "description": 'a string starting with "a" and a string ending with "b"',
            "pattern": "^a",
            "allOf": [{"pattern": "b$"}],
        },
    )


def test_string_pattern():
    """String / String + pattern"""
    _check(
        S.String.check(S.is_pattern(r"^a")),
        {"type": "string", "description": "a string matching the RegExp ^a"},
    )


def test_string_pattern_description():
    """String / String + pattern + description"""
    _check(
        S.String.check(S.is_pattern(r"^a", description="description")),
        {"type": "string", "description": "description"},
    )


def test_number():
    """Number / Number"""
    _check(
        S.Number,
        {
            "anyOf": [
                {"type": "number"},
                {"type": "string", "enum": ["Infinity", "-Infinity", "NaN"]},
            ]
        },
    )


def test_finite():
    """Number / Finite / Finite"""
    _check(S.Finite, {"type": "number"})
    _check(
        S.Finite.annotate(description="description"),
        {"type": "number", "description": "description"},
    )


def test_finite_string_format():
    """Number / Finite / Finite + string format"""
    _check(
        S.Finite.annotate(format="duration"),
        {"type": "number", "description": "a value with a format of duration"},
    )


def test_finite_unsupported_format():
    """Number / Finite / Finite + unsupported format"""
    _check(
        S.Finite.annotate(format="int32"),
        {"type": "number", "description": "a value with a format of int32"},
    )


def test_finite_greater_than():
    """Number / Finite / Finite + isGreaterThan"""
    _check(
        S.Finite.check(S.is_greater_than(1)),
        {"type": "number", "description": "a value greater than 1"},
    )


def test_finite_greater_than_less_than():
    """Number / Finite / Finite + isGreaterThan + isLessThan"""
    _check(
        S.Finite.check(S.is_greater_than(1), S.is_less_than(2)),
        {"type": "number", "description": "a value greater than 1 and a value less than 2"},
    )


def test_int():
    """Number / Int / Int"""
    _check(S.Int, {"type": "integer"})
    _check(
        S.Int.annotate(description="description"),
        {"type": "integer", "description": "description"},
    )


def test_int_string_format():
    """Number / Int / Int + string format"""
    _check(
        S.Int.annotate(format="duration"),
        {"type": "integer", "description": "a value with a format of duration"},
    )


def test_int_unsupported_format():
    """Number / Int / Int + unsupported format"""
    _check(
        S.Int.annotate(format="int32"),
        {"type": "integer", "description": "a value with a format of int32"},
    )


def test_int_greater_than():
    """Number / Int / Int + isGreaterThan"""
    _check(
        S.Int.check(S.is_greater_than(1)),
        {"type": "integer", "description": "a value greater than 1"},
    )


def test_int_greater_than_less_than():
    """Number / Int / Int + isGreaterThan + isLessThan"""
    _check(
        S.Int.check(S.is_greater_than(1), S.is_less_than(2)),
        {"type": "integer", "description": "a value greater than 1 and a value less than 2"},
    )


def test_literal_string():
    """Literal / Literal(string)"""
    _check(S.Literal("a"), {"type": "string", "enum": ["a"]})


def test_literal_number():
    """Literal / Literal(number)"""
    _check(S.Literal(1), {"type": "number", "enum": [1]})


def test_literal_boolean():
    """Literal / Literal(boolean)"""
    _check(S.Literal(True), {"type": "boolean", "enum": [True]})


def test_union_one_of():
    """Union / oneOf"""
    _check(
        S.Union(S.String, S.Finite, mode="one_of"),
        {"anyOf": [{"type": "string"}, {"type": "number"}]},
    )


def test_union_non_empty_string_int():
    """Union / Union(NonEmptyString, Int)"""
    _check(
        S.Union(S.NonEmptyString, S.Int),
        {
            "anyOf": [
                {"type": "string", "description": "a value with a length of at least 1"},
                {"type": "integer"},
            ]
        },
    )


def test_array_string():
    """Array / Array(String)"""
    _check(S.Array(S.String), {"type": "array", "items": {"type": "string"}})
    _check(
        S.Array(S.String).annotate(description="description"),
        {"type": "array", "items": {"type": "string"}, "description": "description"},
    )


def test_array_min_length():
    """Array / Array(String) + isMinLength"""
    _check(
        S.Array(S.String).check(S.is_min_length(1)),
        {
            "type": "array",
            "items": {"type": "string"},
            "description": "a value with a length of at least 1",
        },
    )


def test_array_min_max_length():
    """Array / Array(String) + isMinLength + isMaxLength"""
    _check(
        S.Array(S.String).check(S.is_min_length(1), S.is_max_length(2)),
        {
            "type": "array",
            "items": {"type": "string"},
            "description": (
                "a value with a length of at least 1 and a value with a length of at most 2"
            ),
        },
    )


def test_tuple_empty():
    """Tuple / Tuple([])"""
    _check(S.Tuple(), {"type": "array", "items": False})


def test_tuple_string_finite():
    """Tuple / Tuple([String, Finite])"""
    schema = S.Tuple(S.String, S.Finite)
    _check(schema, _pair({"type": "string"}, {"type": "number"}))
    asserts = SchemaAsserts(to_codec_anthropic(schema).codec)
    asserts.encoding().succeed(("a", 1), {"0": "a", "1": 1})
    asserts.decoding().succeed({"0": "a", "1": 1}, ("a", 1))


def test_tuple_description():
    """Tuple / Tuple([String, Finite]) + description"""
    _check(
        S.Tuple(S.String, S.Finite).annotate(description="description"),
        {
            **_pair({"type": "string"}, {"type": "number"}),
            "description": f"{_TUPLE}; description",
        },
    )


def test_tuple_optional_element():
    """Tuple / Tuple([String, Finite?])"""
    schema = S.Tuple(S.String, S.optional_key(S.Finite))
    _check(
        schema,
        _pair({"type": "string"}, {"anyOf": [{"type": "number"}, {"type": "null"}]}),
    )
    asserts = SchemaAsserts(to_codec_anthropic(schema).codec)
    encoding = asserts.encoding()
    encoding.succeed(("a", 1), {"0": "a", "1": 1})
    encoding.succeed(("a",), {"0": "a", "1": None})
    decoding = asserts.decoding()
    decoding.succeed({"0": "a", "1": 1}, ("a", 1))
    decoding.succeed({"0": "a", "1": None}, ("a",))


def test_tuple_with_rest():
    """TupleWithRest / TupleWithRest([String, Finite], Boolean)"""
    schema = S.TupleWithRest(S.Tuple(S.String, S.Finite), S.Boolean)
    _check(
        schema,
        {
            "type": "object",
            "description": _TUPLE,
            "properties": {
                "0": {"type": "string"},
                "1": {"type": "number"},
                "__rest__": {"type": "array", "items": {"type": "boolean"}},
            },
            "required": ["0", "1", "__rest__"],
            "additionalProperties": False,
        },
    )
    asserts = SchemaAsserts(to_codec_anthropic(schema).codec)
    encoding = asserts.encoding()
    encoding.succeed(("a", 1), {"0": "a", "1": 1, "__rest__": []})
    encoding.succeed(("a", 1, True), {"0": "a", "1": 1, "__rest__": [True]})
    encoding.succeed(("a", 1, True, False), {"0": "a", "1": 1, "__rest__": [True, False]})
    decoding = asserts.decoding()
    decoding.succeed({"0": "a", "1": 1, "__rest__": []}, ("a", 1))
    decoding.succeed({"0": "a", "1": 1, "__rest__": [True]}, ("a", 1, True))
    decoding.succeed({"0": "a", "1": 1, "__rest__": [True, False]}, ("a", 1, True, False))


def test_struct_required_properties():
    """Struct / required properties"""
    _check(
        S.Struct(_A),
        {
            "type": "object",
            "properties": {"a": {"type": "string"}},
            "required": ["a"],
            "additionalProperties": False,
        },
    )


def test_struct_optional_properties():
    """Struct / optional properties"""
    schema = S.Struct(_AB, b=S.Finite)
    _check(
        schema,
        {
            "type": "object",
            "properties": {
                "a": {"type": "string"},
                "b": {"anyOf": [{"type": "number"}, {"type": "null"}]},
            },
            "required": ["a", "b"],
            "additionalProperties": False,
        },
    )
    asserts = SchemaAsserts(to_codec_anthropic(schema).codec)
    encoding = asserts.encoding()
    encoding.succeed({"a": "a", "b": 1})
    encoding.succeed({"a": "a"}, {"a": "a", "b": None})
    decoding = asserts.decoding()
    decoding.succeed({"a": "a", "b": 1})
    decoding.succeed({"a": "a", "b": None}, {"a": "a"})


def test_class():
    """Class"""

    class Person(S.Class, identifier="Person"):
        name: str

    _check(
        Person,
        {
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
            "additionalProperties": False,
            "$defs": {
                "PersonEncoded": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                    "additionalProperties": False,
                }
            },
        },
    )


def test_record_empty_params():
    """Record / EmptyParams"""
    _check(T.EMPTY_PARAMS, {"type": "object", "additionalProperties": False})
    _check(S.Record(S.String, S.Never), {"type": "object", "additionalProperties": False})


def test_record_string_finite():
    """Record / Record(String, Finite)"""
    schema = S.Record(S.String, S.Finite)
    _check(schema, _entries(_RECORD, {"type": "string"}, {"type": "number"}))
    asserts = SchemaAsserts(to_codec_anthropic(schema).codec)
    asserts.encoding().succeed({"a": 1, "b": 2}, [{"0": "a", "1": 1}, {"0": "b", "1": 2}])
    asserts.decoding().succeed([{"0": "a", "1": 1}, {"0": "b", "1": 2}], {"a": 1, "b": 2})


def test_record_properties_and_index_signature():
    """Record / Record with properties and an index signature"""
    schema = S.Record(S.Union(S.Literal("fixed"), S.String), S.String)
    result = to_codec_anthropic(schema)
    assert result.json_schema == _entries(
        _RECORD,
        {"anyOf": [{"type": "string", "enum": ["fixed"]}, {"type": "string"}]},
        {"type": "string"},
    )
    asserts = SchemaAsserts(result.codec)
    asserts.encoding().succeed(
        {"fixed": "required", "dynamic": "value"},
        [{"0": "fixed", "1": "required"}, {"0": "dynamic", "1": "value"}],
    )
    asserts.decoding().succeed(
        [{"0": "fixed", "1": "required"}, {"0": "dynamic", "1": "value"}],
        {"fixed": "required", "dynamic": "value"},
    )
    assert S.decode_unknown_option(result.codec)([{"0": "dynamic", "1": "value"}]) is None


def test_record_description():
    """Record / Record(String, Finite) + description"""
    _check(
        S.Record(S.String, S.Finite).annotate(description="description"),
        _entries(f"{_RECORD}; description", {"type": "string"}, {"type": "number"}),
    )


def test_record_min_properties():
    """Record / Record(String, Finite) + isMinProperties"""
    schema = S.Record(S.String, S.Finite).check(S.is_min_properties(2))
    result = to_codec_anthropic(schema)
    assert result.json_schema == _entries(
        f"{_RECORD}; a value with at least 2 entries", {"type": "string"}, {"type": "number"}
    )
    SchemaAsserts(result.codec).decoding().fail(
        [{"0": "a", "1": 1}, {"0": "a", "1": 2}], "Expected a value with at least 2 entries"
    )


def test_record_min_properties_description():
    """Record / Record(String, Finite) + isMinProperties + description"""
    _check(
        S.Record(S.String, S.Finite).check(S.is_min_properties(2, description="description")),
        _entries(f"{_RECORD}; description", {"type": "string"}, {"type": "number"}),
    )
