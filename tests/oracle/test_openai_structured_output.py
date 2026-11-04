"""Ports of Effect's ``test/ai/OpenAiStructuredOutput.test.ts``. Each test's
docstring is the Effect test title, prefixed by its ``describe`` blocks
below ``toCodecOpenAI``. ``_check`` is Effect's ``assertJsonSchema``: a
schema whose JSON Schema is not an object root is checked as the ``value``
property of a struct.

Python differs in one place, kept as the expected value: an ``int`` has no
safe-integer bounds, so ``Int`` is ``{"type": "integer"}`` without
``minimum`` / ``maximum``.

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
from pyfect.ai.openai_structured_output import to_codec_openai
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
_ROOT = 'OpenAiStructuredOutput: Root JSON Schema must have type "object" and must not use "anyOf"'


class _Value(TypedDict):
    value: Any


def _value(schema: S.Codec[Any, Any]) -> S.Codec[Any, Any]:
    return S.Struct(_Value, value=schema)


def _object(properties: dict[str, JsonSchema]) -> JsonSchema:
    return {
        "type": "object",
        "properties": properties,
        "required": list(properties),
        "additionalProperties": False,
    }


def _check(schema: S.Codec[Any, Any], expected: JsonSchema) -> None:
    if expected.get("type") == "object" and "anyOf" not in expected:
        assert to_codec_openai(schema).json_schema == expected
    else:
        assert to_codec_openai(_value(schema)).json_schema == _object({"value": expected})


def _error(schema: S.Top, message: str) -> None:
    with pytest.raises(Exception, match=re.escape(message)):
        to_codec_openai(schema)


def _pair(key: JsonSchema, value: JsonSchema) -> JsonSchema:
    return {**_object({"0": key, "1": value}), "description": _TUPLE}


def _entries(description: str, key: JsonSchema, value: JsonSchema) -> JsonSchema:
    return {"type": "array", "description": description, "items": _pair(key, value)}


class _A(TypedDict):
    a: str


class _B(TypedDict):
    b: str


class _AB(TypedDict):
    a: str
    b: NotRequired[float]


_Recursive = TypedDict("_Recursive", {"a": str, "as": Any})


def test_rejects_primitive_roots():
    """Canonical JSON and mechanical invariants / Root / rejects primitive roots"""
    _error(S.String, _ROOT)


def test_rejects_array_roots():
    """Canonical JSON and mechanical invariants / Root / rejects array roots"""
    _error(S.Array(S.String), _ROOT)


def test_rejects_any_of_roots():
    """Canonical JSON and mechanical invariants / Root / rejects anyOf roots"""
    _error(S.Union(S.Struct(_A), S.Struct(_B)), _ROOT)


def test_rejects_unconstrained_roots():
    """Canonical JSON and mechanical invariants / Root / rejects unconstrained roots"""
    _error(S.Any, _ROOT)
    _error(S.Unknown, _ROOT)
    _error(S.Never, _ROOT)


def test_post_rest_elements():
    """Canonical JSON and mechanical invariants / Arrays / encodes post-rest elements as object properties"""  # noqa: E501
    result = to_codec_openai(S.TupleWithRest(S.Tuple(), S.String, S.String))
    assert result.json_schema == {
        "type": "object",
        "properties": {
            "__rest__": {"type": "array", "items": {"type": "string"}},
            "__tail_0__": {"type": "string"},
        },
        "required": ["__rest__", "__tail_0__"],
        "additionalProperties": False,
        "description": _TUPLE_TAIL,
    }
    asserts = SchemaAsserts(result.codec)
    asserts.encoding().succeed(("a", "b"), {"__rest__": ["a"], "__tail_0__": "b"})
    asserts.decoding().succeed({"__rest__": ["a"], "__tail_0__": "b"}, ("a", "b"))


_STARTS_WITH_A: JsonSchema = {
    "type": "string",
    "description": 'a string starting with "a"',
    "pattern": "^a",
}


def test_no_transformation_recursive_schema():
    """Suspend / no-transformation recursive schema"""

    def recursive() -> Any:
        return schema

    schema: Any = S.Struct(
        _Recursive,
        **{"a": S.String.check(S.is_starting_with("a")), "as": S.Array(S.suspend(recursive))},
    )
    body = _object(
        {"a": _STARTS_WITH_A, "as": {"type": "array", "items": {"$ref": "#/$defs/Suspend_"}}}
    )
    _check(schema, {**body, "$defs": {"Suspend_": body}})


def test_transformation_recursive_schema():
    """Suspend / transformation recursive schema"""

    def recursive() -> Any:
        return schema

    schema: Any = S.Struct(
        _Recursive,
        **{"a": S.String.check(S.is_starting_with("a")), "as": S.Tuple(S.suspend(recursive))},
    )
    body = _object(
        {
            "a": _STARTS_WITH_A,
            "as": {
                **_object({"0": {"$ref": "#/$defs/Suspend_"}}),
                "description": _TUPLE,
            },
        }
    )
    _check(schema, {**body, "$defs": {"Suspend_": body}})


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
    _check(S.String.check(S.is_starting_with("a")), _STARTS_WITH_A)


def test_string_starts_with_ends_with():
    """String / String + startsWith + endsWith"""
    _check(
        S.String.check(S.is_starting_with("a"), S.is_ending_with("b")),
        {
            "type": "string",
            "description": 'a string starting with "a" and a string ending with "b"',
            "pattern": "^(?=[\\s\\S]*?(?:^a))(?=[\\s\\S]*?(?:b$))",
        },
    )


def test_string_pattern():
    """String / String + pattern

    pyfect gives no ``pattern``: a Python ``re`` pattern is not JSON
    Schema's."""
    _check(
        S.String.check(S.is_pattern(r"^a")),
        {"type": "string", "description": "a string matching the RegExp ^a"},
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
        {"type": "number", "description": "a value greater than 1", "exclusiveMinimum": 1},
    )


def test_finite_greater_than_or_equal_to():
    """Number / Finite / Finite + isGreaterThanOrEqualTo"""
    _check(
        S.Finite.check(S.is_greater_than_or_equal_to(1)),
        {"type": "number", "description": "a value greater than or equal to 1", "minimum": 1},
    )


def test_finite_less_than():
    """Number / Finite / Finite + isLessThan"""
    _check(
        S.Finite.check(S.is_less_than(2)),
        {"type": "number", "description": "a value less than 2", "exclusiveMaximum": 2},
    )


def test_finite_less_than_or_equal_to():
    """Number / Finite / Finite + isLessThanOrEqualTo"""
    _check(
        S.Finite.check(S.is_less_than_or_equal_to(2)),
        {"type": "number", "description": "a value less than or equal to 2", "maximum": 2},
    )


def test_finite_between():
    """Number / Finite / Finite + isBetween"""
    _check(
        S.Finite.check(S.is_between(minimum=1, maximum=2)),
        {"type": "number", "description": "a value between 1 and 2", "minimum": 1, "maximum": 2},
    )


def test_finite_multiple_of():
    """Number / Finite / Finite + isMultipleOf"""
    _check(
        S.Finite.check(S.is_multiple_of(2)),
        {"type": "number", "description": "a value that is a multiple of 2", "multipleOf": 2},
    )


def test_finite_greater_than_less_than():
    """Number / Finite / Finite + isGreaterThan + isLessThan"""
    _check(
        S.Finite.check(S.is_greater_than(1), S.is_less_than(2)),
        {
            "type": "number",
            "description": "a value greater than 1 and a value less than 2",
            "exclusiveMinimum": 1,
            "exclusiveMaximum": 2,
        },
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
        {"type": "integer", "description": "a value greater than 1", "exclusiveMinimum": 1},
    )


def test_int_greater_than_less_than():
    """Number / Int / Int + isGreaterThan + isLessThan"""
    _check(
        S.Int.check(S.is_greater_than(1), S.is_less_than(2)),
        {
            "type": "integer",
            "description": "a value greater than 1 and a value less than 2",
            "exclusiveMinimum": 1,
            "exclusiveMaximum": 2,
        },
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
            "minItems": 1,
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
            "minItems": 1,
            "maxItems": 2,
        },
    )


def test_tuple_empty():
    """Tuple / Tuple([])"""
    _check(S.Tuple(), {"type": "array", "items": False})


def test_tuple_string_finite():
    """Tuple / Tuple([String, Finite])"""
    schema = S.Tuple(S.String, S.Finite)
    _check(schema, _pair({"type": "string"}, {"type": "number"}))
    asserts = SchemaAsserts(to_codec_openai(schema).codec)
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
    asserts = SchemaAsserts(to_codec_openai(schema).codec)
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
            **_object(
                {
                    "0": {"type": "string"},
                    "1": {"type": "number"},
                    "__rest__": {"type": "array", "items": {"type": "boolean"}},
                }
            ),
            "description": _TUPLE,
        },
    )
    asserts = SchemaAsserts(to_codec_openai(schema).codec)
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
    _check(S.Struct(_A), _object({"a": {"type": "string"}}))


def test_struct_optional_properties():
    """Struct / optional properties"""
    schema = S.Struct(_AB, b=S.Finite)
    _check(
        schema,
        _object({"a": {"type": "string"}, "b": {"anyOf": [{"type": "number"}, {"type": "null"}]}}),
    )
    asserts = SchemaAsserts(to_codec_openai(schema).codec)
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

    body = _object({"name": {"type": "string"}})
    _check(Person, {**body, "$defs": {"PersonEncoded": body}})


def test_record_empty_params():
    """Record / EmptyParams"""
    empty: JsonSchema = {"type": "object", "properties": {}, "additionalProperties": False}
    _check(T.EMPTY_PARAMS, empty)
    _check(S.Record(S.String, S.Never), empty)


def test_record_string_finite():
    """Record / Record(String, Finite)"""
    schema = S.Record(S.String, S.Finite)
    _check(schema, _entries(_RECORD, {"type": "string"}, {"type": "number"}))
    asserts = SchemaAsserts(to_codec_openai(_value(schema)).codec)
    asserts.encoding().succeed(
        {"value": {"a": 1, "b": 2}}, {"value": [{"0": "a", "1": 1}, {"0": "b", "1": 2}]}
    )
    asserts.decoding().succeed(
        {"value": [{"0": "a", "1": 1}, {"0": "b", "1": 2}]}, {"value": {"a": 1, "b": 2}}
    )


def test_record_properties_and_index_signature():
    """Record / Record with properties and an index signature"""
    schema = S.Record(S.Union(S.Literal("fixed"), S.String), S.String)
    _check(
        schema,
        _entries(
            _RECORD,
            {"anyOf": [{"type": "string", "enum": ["fixed"]}, {"type": "string"}]},
            {"type": "string"},
        ),
    )
    result = to_codec_openai(_value(schema))
    asserts = SchemaAsserts(result.codec)
    asserts.encoding().succeed(
        {"value": {"fixed": "required", "dynamic": "value"}},
        {"value": [{"0": "fixed", "1": "required"}, {"0": "dynamic", "1": "value"}]},
    )
    asserts.decoding().succeed(
        {"value": [{"0": "fixed", "1": "required"}, {"0": "dynamic", "1": "value"}]},
        {"value": {"fixed": "required", "dynamic": "value"}},
    )
    decode = S.decode_unknown_option(result.codec)
    assert decode({"value": [{"0": "dynamic", "1": "value"}]}) is None


def test_record_description():
    """Record / Record(String, Finite) + description"""
    _check(
        S.Record(S.String, S.Finite).annotate(description="description"),
        _entries(f"{_RECORD}; description", {"type": "string"}, {"type": "number"}),
    )


def test_record_min_properties():
    """Record / Record(String, Finite) + isMinProperties"""
    schema = S.Record(S.String, S.Finite).check(S.is_min_properties(2))
    _check(
        schema,
        {
            **_entries(
                f"{_RECORD}; a value with at least 2 entries",
                {"type": "string"},
                {"type": "number"},
            ),
            "minItems": 2,
        },
    )
    result = to_codec_openai(_value(schema))
    SchemaAsserts(result.codec).decoding().fail(
        {"value": [{"0": "a", "1": 1}, {"0": "a", "1": 2}]},
        'Expected a value with at least 2 entries\n  at ["value"]',
    )


def test_record_min_properties_description():
    """Record / Record(String, Finite) + isMinProperties + description"""
    _check(
        S.Record(S.String, S.Finite).check(S.is_min_properties(2, description="description")),
        {
            **_entries(f"{_RECORD}; description", {"type": "string"}, {"type": "number"}),
            "minItems": 2,
        },
    )
