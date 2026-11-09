"""Ports of Effect's ``StructWithRest`` titles from ``schema/Schema.test.ts``,
``toFormatter.test.ts``, ``schema/toJsonSchemaDocument.test.ts`` and
``Arbitrary.test.ts``. Each test's docstring is the Effect test title,
prefixed by its ``describe`` blocks. ``TestSchema.Asserts`` is
``testing.SchemaAsserts``.

``Schema.StructWithRest(struct, [record, ...])`` is
``S.StructWithRest(struct, record, ...)``; its Type is the struct's
TypedDict, which is open (PEP 728's ``extra_items=`` types the other keys).
As in Effect, an index signature also checks the declared keys it takes.

Omitted:
- Symbols (no Python counterpart): "Record(Symbol, Number)", "indexed
  objects / selects matching pattern, template, numeric and symbol
  indexes". "Record(`a${string}`, Number)" and the toJsonSchemaDocument
  template titles are in ``test_schema_template_literal.py`` and
  ``test_to_json_schema_document.py``.
- Hypothesis runs, shrinks and replays (``test_arbitrary.py``): "indexed
  objects / does not generate omitted fixed property names from indexes",
  the shrink/replay half of "... / shrinks and replays fixed fields within
  the combined constraints", "... / validates residual index filters
  without constructive constraints", "... / rejects key shrinks that
  enter an incompatible index", and the size-zero and prototype halves of "... / combines fixed
  field constraints at size zero and starts progressive checks".
- "indexed objects / uses indexes when optional properties cannot satisfy
  the minimum": a TypedDict key cannot be ``optionalKey(Never)``.
- Ajv validation and surrogate pairs: "does not use approximate literal
  patterns as record selectors".
- toIso / toDifferJsonPatch titles: not ported derivations.
"""

from typing import Any, TypedDict

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis.errors import FailedHealthCheck, Unsatisfiable

from pyfect import schema as S
from pyfect.schema import transformation as T
from pyfect.testing import SchemaAsserts

GAVE_UP = (Unsatisfiable, FailedHealthCheck)
"""What Hypothesis raises where Effect reports a ``SampleError``."""


class _A(TypedDict):
    a: float


class _UpperA(TypedDict):
    A: str


class _StrA(TypedDict):
    a: str


class _Fixed(TypedDict):
    fixed: float


class _FixedStr(TypedDict):
    fixed: str


class _FixedInt(TypedDict):
    fixed: int


class _Empty(TypedDict):
    pass


def _sample(schema: S.Codec[Any, Any, Any, Any], count: int = 50) -> list[Any]:
    values: list[Any] = []

    @settings(
        max_examples=count,
        database=None,
        deadline=None,
        suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
    )
    @given(S.to_strategy(schema))
    def collect(value: Any) -> None:
        values.append(value)

    collect()
    return values


def _all_valid(schema: S.Codec[Any, Any, Any, Any]) -> None:
    is_ = S.is_(schema)
    assert all(is_(value) for value in _sample(schema))


# -------------------------------------------------------- schema/Schema.test.ts


def test_structwithrest_should_throw_an_error_if_there_are_duplicate_property_signatures():
    """StructWithRest / should throw an error if there are duplicate property signatures"""
    with pytest.raises(ValueError, match=r'^Duplicate identifier: "a"\. ts\(2300\)$'):
        S.StructWithRest(S.Struct(_A), S.Record(S.Literals("a", "b"), S.Number))


def test_structwithrest_should_throw_an_error_if_there_are_encodings():
    """StructWithRest / should throw an error if there are encodings"""
    # A struct node with an encoding of its own (Effect's ``encodeTo``).
    encoded = S.Record(S.String, S.Unknown).pipe(S.decode_to(S.Struct(_Empty)))
    with pytest.raises(ValueError, match=r"^StructWithRest does not support encodings$"):
        S.StructWithRest(encoded, S.Record(S.String, S.Number))  # pyright: ignore[reportArgumentType]


def test_structwithrest_record_string_number():
    """StructWithRest / Record(String, Number)"""
    schema = S.StructWithRest(S.Struct(_A), S.Record(S.String, S.Number))
    decoding = SchemaAsserts(schema).decoding()
    decoding.succeed({"a": 1})
    decoding.succeed({"a": 1, "b": 2})
    decoding.fail({"a": 1, "b": ""}, 'Expected number\n  at ["b"]')


def test_structwithrest_applies_excess_property_options_after_fixed_and_index_signatures():
    """StructWithRest / applies excess-property options after fixed and index signatures"""
    schema = S.StructWithRest(
        S.Struct(_Fixed), S.Record(S.String.check(S.is_pattern("^a")), S.Number)
    )
    input = {"fixed": 0, "a": 1, "b": 2}
    expected = {"fixed": 0, "a": 1}
    assert S.decode_unknown_sync(schema)(input, on_excess_property="ignore") == expected
    assert S.encode_unknown_sync(schema)(input, on_excess_property="ignore") == expected
    with pytest.raises(S.SchemaError, match=r'^Expected no excess property\n  at \["b"\]$'):
        S.decode_unknown_sync(schema)(input, on_excess_property="error")
    with pytest.raises(S.SchemaError, match=r'^Expected no excess property\n  at \["b"\]$'):
        S.encode_unknown_sync(schema)(input, on_excess_property="error")


def test_structwithrest_should_preserve_both_checks():
    """StructWithRest / should preserve both checks"""
    schema = S.StructWithRest(
        S.Struct(_A).check(S.make_filter(lambda s: s["a"] > 0, expected="agt(0)")),
        S.Record(S.String, S.Number).check(
            S.make_filter(lambda s: s.get("b") is None or s["b"] > 1, expected="bgt(1)")
        ),
    )
    decoding = SchemaAsserts(schema).decoding()
    decoding.succeed({"a": 1})
    decoding.succeed({"a": 1, "b": 2})
    decoding.fail({"a": 0}, "Expected agt(0)")
    decoding.fail({"a": 1, "b": 1}, "Expected bgt(1)")


def test_structwithrest_index_signatures_should_not_re_parse_fixed_properties():
    """StructWithRest / index signatures should not re-parse fixed properties"""
    trimmed = S.String.pipe(S.decode_to(S.String, T.trim()))
    schema = S.StructWithRest(S.Struct(_StrA, a=trimmed), S.Record(S.String, S.String))
    asserts = SchemaAsserts(schema)
    asserts.decoding().succeed({"a": "  x  ", "b": "y"}, {"a": "x", "b": "y"})
    asserts.encoding().succeed({"a": "x", "b": "y"})


def test_structwithrest_index_signatures_should_not_overwrite_fixed_properties_after_key_decoding():
    """StructWithRest / index signatures should not overwrite fixed properties after key decoding"""
    uppercase_key = S.String.pipe(S.decode_to(S.String, T.to_upper_case()))
    schema = S.StructWithRest(S.Struct(_UpperA), S.Record(uppercase_key, S.String))
    SchemaAsserts(schema).decoding().succeed({"A": "fixed", "a": "rest"}, {"A": "fixed"})


# --------------------------------------------------- toFormatter.test.ts


def test_toformatter_structwithrest():
    """StructWithRest"""
    format = S.to_formatter(S.StructWithRest(S.Struct(_A), S.Record(S.String, S.Number)))
    value: Any = {"a": 1, "b": 2}
    assert format(value) == '{ "a": 1, "b": 2 }'


# ------------------------------------------ toJsonSchemaDocument.test.ts


def _json_schema(schema: S.Top) -> object:
    return S.to_json_schema_document(schema, on_excess_property="error").schema


def test_structwithrest_property_and_string_index():
    """StructWithRest / property and string index"""
    schema = S.StructWithRest(S.Struct(_StrA), S.Record(S.String, S.Union(S.Finite, S.String)))
    assert _json_schema(schema) == {
        "type": "object",
        "properties": {"a": {"type": "string"}},
        "allOf": [
            {
                "type": "object",
                "additionalProperties": {"anyOf": [{"type": "number"}, {"type": "string"}]},
            }
        ],
        "required": ["a"],
    }


def test_structwithrest_pattern_and_string_indexes():
    """StructWithRest / pattern and string indexes"""
    schema = S.StructWithRest(
        S.Struct(_Empty),
        S.Record(S.String.check(S.is_uppercased()), S.Finite),
        S.Record(S.String, S.Boolean),
    )
    assert _json_schema(schema) == {
        "type": "object",
        "propertyNames": {
            "anyOf": [{"type": "string", "pattern": "^[^a-z]*$"}, {"type": "string"}]
        },
        "additionalProperties": {"anyOf": [{"type": "number"}, {"type": "boolean"}]},
        "allOf": [{"type": "object", "additionalProperties": {"type": "boolean"}}],
    }


def test_structwithrest_property_and_compound_pattern_index():
    """StructWithRest / property and compound pattern index"""
    schema = S.StructWithRest(
        S.Struct(_StrA),
        S.Record(S.String.check(S.is_starting_with("x"), S.is_ending_with("z")), S.Finite),
    )
    assert _json_schema(schema) == {
        "type": "object",
        "properties": {"a": {"type": "string"}},
        "required": ["a"],
        "propertyNames": {
            "anyOf": [
                {"enum": ["a"]},
                {"type": "string", "pattern": "^x", "allOf": [{"pattern": "z$"}]},
            ]
        },
        "additionalProperties": {"type": "number"},
    }


# ------------------------------------------------------ Arbitrary.test.ts


def test_indexed_objects_combines_fixed_field_constraints_at_size_zero():
    """indexed objects / combines fixed field constraints at size zero and starts progressive checks"""  # noqa: E501
    schema = S.StructWithRest(S.Struct(_FixedStr), S.Record(S.String, S.NonEmptyString))
    values = _sample(schema, 128)
    assert all(S.is_(schema)(value) for value in values)
    assert all(len(value["fixed"]) >= 1 for value in values)


def test_indexed_objects_combines_numeric_and_bigint_bounds_with_fixed_field_constraints():
    """indexed objects / combines numeric and bigint bounds with fixed field constraints"""

    class _Big(TypedDict):
        fixed: int

    _all_valid(
        S.StructWithRest(
            S.Struct(_Fixed),
            S.Record(S.String, S.Int.check(S.is_between(minimum=10, maximum=20))),
        )
    )
    _all_valid(
        S.StructWithRest(
            S.Struct(_Big, fixed=S.BigInt.check(S.is_less_than_or_equal_to_big_int(15))),
            S.Record(S.String, S.BigInt.check(S.is_greater_than_or_equal_to_big_int(10))),
        )
    )


def test_indexed_objects_combines_overlapping_index_constraints_after_generating_the_key():
    """indexed objects / combines overlapping index constraints after generating the key"""
    _all_valid(
        S.StructWithRest(
            S.Struct(_Empty), S.Record(S.String, S.String), S.Record(S.String, S.NonEmptyString)
        ).check(S.is_min_properties(1))
    )


def test_indexed_objects_discards_empty_scalar_intersections_without_failing_compilation():
    """indexed objects / discards empty scalar intersections without failing compilation"""
    schemas: list[S.Top] = [
        S.StructWithRest(
            S.Struct(_FixedStr, fixed=S.String.check(S.is_max_length(0))),
            S.Record(S.String, S.NonEmptyString),
        ),
        S.StructWithRest(
            S.Struct(_FixedInt),
            S.Record(S.String, S.Number.check(S.is_between(minimum=0.2, maximum=0.8))),
        ),
        S.StructWithRest(
            S.Struct(_FixedInt, fixed=S.BigInt.check(S.is_less_than_or_equal_to_big_int(1))),
            S.Record(S.String, S.BigInt.check(S.is_greater_than_big_int(1))),
        ),
    ]
    for schema in schemas:
        with pytest.raises(GAVE_UP):
            _sample(schema, 1)


def test_indexed_objects_shrinks_and_replays_fixed_fields_within_the_combined_constraints():
    """indexed objects / shrinks and replays fixed fields within the combined constraints

    The drawing half: a fixed field is drawn within the index's constraints,
    not filtered into them (Hypothesis's filter health check stays on)."""
    schema = S.StructWithRest(
        S.Struct(_FixedStr), S.Record(S.String, S.String.check(S.is_min_length(30)))
    )
    is_ = S.is_(schema)

    @settings(max_examples=50, database=None, deadline=None)
    @given(S.to_strategy(schema))
    def check(value: Any) -> None:
        assert is_(value)
        assert len(value["fixed"]) >= 30

    check()
