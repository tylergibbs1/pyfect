"""Port of Effect's ``schema/jsonSchemaRoundTrip.test.ts``. ``_json_schema_validator``
stands in for Ajv. Each test's docstring is the Effect test title, prefixed by its
``describe`` blocks."""

# ruff: noqa: E501, E712
# pyright: reportUnknownLambdaType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportUnknownMemberType=false
from collections.abc import Callable
from typing import Any

from pyfect import json_schema as JS
from pyfect import schema as S
from pyfect.exit import Success
from pyfect.schema import ast
from pyfect.schema import representation as R
from pyfect.schema._schema import Bottom

from ._json_schema_validator import compile


def struct(fields: Any) -> Any:
    return Bottom(ast.struct({k: v.__codec__().ast for k, v in fields.items()}))


def is_success(exit: object) -> bool:
    return isinstance(exit, Success)


def assert_same_accepted_values(
    left: Callable[[Any], Any], right: Callable[[Any], Any], inputs: Any
) -> None:
    for input in inputs:
        assert (left(input) is True) == (right(input) is True), f"Validation differs for {input!r}"


def assert_json_schema_equivalent(left: Any, right: Any, inputs: Any) -> None:
    assert_same_accepted_values(compile(left), compile(right), inputs)


def assert_json_schema_import_round_trip(schema: JS.JsonSchema, inputs: Any) -> None:
    source = JS.from_schema_draft_2020_12(schema)
    imported = R.from_json_schema_document(source, patterns="apply")
    representation = R.to_representation(imported)
    emitted = R.to_json_schema_document(representation, on_excess_property="error")
    assert_json_schema_equivalent(source, emitted, inputs)
    decode = S.decode_unknown_exit(imported, on_excess_property="error")
    assert_same_accepted_values(lambda input: is_success(decode(input)), compile(source), inputs)


def assert_representation_round_trip(schema: Any, inputs: Any, options: Any = None) -> None:
    options = {"on_excess_property": "error"} if options is None else options
    emitted = S.to_json_schema_document(schema, **options)
    imported = R.from_json_schema_document(emitted, patterns="apply")
    decode_source = S.decode_unknown_exit(schema, on_excess_property="error")
    decode_imported = S.decode_unknown_exit(imported, on_excess_property="error")
    assert_same_accepted_values(
        lambda input: is_success(decode_imported(input)),
        lambda input: is_success(decode_source(input)),
        inputs,
    )
    assert_json_schema_equivalent(emitted, S.to_json_schema_document(imported, **options), inputs)


def assert_loose_representation_round_trip(schema: Any, inputs: Any, options: Any = None) -> Any:
    emitted = S.to_json_schema_document(schema, **(options or {}))
    imported = R.from_json_schema_document(emitted, patterns="apply")
    decode_source = S.decode_unknown_exit(schema, on_excess_property="error")
    decode_imported = S.decode_unknown_exit(imported, on_excess_property="error")
    for input in inputs:
        if is_success(decode_source(input)):
            assert is_success(decode_imported(input)), f"Import rejects {input!r}"
    assert_json_schema_equivalent(
        emitted, S.to_json_schema_document(imported, **(options or {})), inputs
    )
    return imported


def test_json_schema_round_trip_laws_to_json_schema_from_json_schema_a_applies_type_specific_keywords_only_to_matching_instances() -> (
    None
):
    "JSON Schema round-trip laws / toJsonSchema(fromJsonSchema(A)) / applies type-specific keywords only to matching instances"
    assert_json_schema_import_round_trip({"minLength": 2}, ["", "a", "ab", 0, True, None, [], {}])
    assert_json_schema_import_round_trip({"minimum": 1}, [0, 1, "a", True, None, [], {}])
    assert_json_schema_import_round_trip({"minItems": 1}, [[], [1], "a", 0, True, None, {}])
    assert_json_schema_import_round_trip(
        {"required": ["a"]}, [{}, {"a": 1}, [], "a", 0, True, None]
    )


def test_json_schema_round_trip_laws_to_json_schema_from_json_schema_a_preserves_unicode_string_lengths_and_patterns() -> (
    None
):
    "JSON Schema round-trip laws / toJsonSchema(fromJsonSchema(A)) / preserves Unicode string lengths and patterns"
    inputs = ["", "a", "é", "😀", "e\u0301", "😀a", "\ud800"]
    assert_json_schema_import_round_trip({"type": "string", "minLength": 2, "maxLength": 2}, inputs)
    assert_json_schema_import_round_trip({"type": "string", "pattern": "^.$"}, inputs)


def test_json_schema_round_trip_laws_to_json_schema_from_json_schema_a_conjoins_enum_with_its_sibling_constraints() -> (
    None
):
    "JSON Schema round-trip laws / toJsonSchema(fromJsonSchema(A)) / conjoins enum with its sibling constraints"
    assert_json_schema_import_round_trip(
        {"enum": ["a", "ab", 1], "minLength": 2}, ["a", "ab", 1, True]
    )


def test_json_schema_round_trip_laws_to_json_schema_from_json_schema_a_conjoins_const_with_its_sibling_constraints() -> (
    None
):
    "JSON Schema round-trip laws / toJsonSchema(fromJsonSchema(A)) / conjoins const with its sibling constraints"
    assert_json_schema_import_round_trip({"const": "a", "minLength": 2}, ["a", "aa", 1, None])


def test_json_schema_round_trip_laws_to_json_schema_from_json_schema_a_intersects_finite_enums_as_sets() -> (
    None
):
    "JSON Schema round-trip laws / toJsonSchema(fromJsonSchema(A)) / intersects finite enums as sets"
    assert_json_schema_import_round_trip(
        {"allOf": [{"enum": ["a", "b", 1]}, {"enum": ["b", 1, True]}]}, ["a", "b", 1, True, None]
    )


def test_json_schema_round_trip_laws_to_json_schema_from_json_schema_a_preserves_one_of_branch_multiplicity() -> (
    None
):
    "JSON Schema round-trip laws / toJsonSchema(fromJsonSchema(A)) / preserves oneOf branch multiplicity"
    assert_json_schema_import_round_trip({"oneOf": [{"const": "a"}, {"const": "a"}]}, ["a", "b", 1])


def test_json_schema_round_trip_laws_to_json_schema_from_json_schema_a_preserves_min_items_after_prefix_items() -> (
    None
):
    "JSON Schema round-trip laws / toJsonSchema(fromJsonSchema(A)) / preserves minItems after prefixItems"
    assert_json_schema_import_round_trip(
        {
            "type": "array",
            "prefixItems": [{"type": "string"}],
            "items": {"type": "number"},
            "minItems": 2,
        },
        [[], ["a"], ["a", 1], ["a", 1, 2], ["a", "b"]],
    )


def test_json_schema_round_trip_laws_to_json_schema_from_json_schema_a_intersects_one_constraint_with_multiple_alternatives_linearly() -> (
    None
):
    "JSON Schema round-trip laws / toJsonSchema(fromJsonSchema(A)) / intersects one constraint with multiple alternatives linearly"
    assert_json_schema_import_round_trip(
        {
            "allOf": [
                {
                    "anyOf": [
                        {"type": "string", "minLength": 2, "maxLength": 3},
                        {"type": "string", "minLength": 5, "maxLength": 6},
                    ]
                },
                {"type": "string", "pattern": "^a"},
            ]
        },
        ["a", "aa", "bb", "aaaa", "aaaaa", "bbbbb", 1],
    )


def test_json_schema_round_trip_laws_to_json_schema_from_json_schema_a_preserves_empty_closed_objects() -> (
    None
):
    "JSON Schema round-trip laws / toJsonSchema(fromJsonSchema(A)) / preserves empty closed objects"
    assert_json_schema_import_round_trip(
        {"type": "object", "additionalProperties": False}, [{}, {"a": 1}, [], [1], None, 1]
    )


def test_json_schema_round_trip_laws_to_json_schema_from_json_schema_a_applies_additional_properties_to_required_only_names() -> (
    None
):
    "JSON Schema round-trip laws / toJsonSchema(fromJsonSchema(A)) / applies additionalProperties to required-only names"
    assert_json_schema_import_round_trip(
        {"type": "object", "required": ["a"], "additionalProperties": False},
        [{}, {"a": 1}, {"a": "a"}, {"b": 1}, []],
    )


def test_json_schema_round_trip_laws_to_json_schema_from_json_schema_a_applies_an_additional_properties_schema_to_required_only_names() -> (
    None
):
    "JSON Schema round-trip laws / toJsonSchema(fromJsonSchema(A)) / applies an additionalProperties schema to required-only names"
    assert_json_schema_import_round_trip(
        {"type": "object", "required": ["a"], "additionalProperties": {"type": "string"}},
        [{}, {"a": 1}, {"a": "a"}, {"a": "a", "b": "b"}, {"a": "a", "b": 1}, []],
    )


def test_json_schema_round_trip_laws_to_json_schema_from_json_schema_a_preserves_closed_object_scopes() -> (
    None
):
    "JSON Schema round-trip laws / toJsonSchema(fromJsonSchema(A)) / preserves closed object scopes"
    assert_json_schema_import_round_trip(
        {
            "type": "object",
            "additionalProperties": False,
            "allOf": [{"properties": {"a": {"type": "string"}}}],
        },
        [{}, {"a": "a"}, {"a": 1}, {"b": 1}, {"a": "a", "b": 1}, []],
    )


def test_json_schema_round_trip_laws_to_json_schema_from_json_schema_a_preserves_sibling_additional_properties_schemas() -> (
    None
):
    "JSON Schema round-trip laws / toJsonSchema(fromJsonSchema(A)) / preserves sibling additionalProperties schemas"
    assert_json_schema_import_round_trip(
        {
            "type": "object",
            "properties": {"a": {"type": "string"}},
            "allOf": [{"additionalProperties": {"type": "boolean"}}],
        },
        [{}, {"a": "a"}, {"b": True}, {"b": "b"}, {"a": "a", "b": True}, []],
    )


def test_json_schema_round_trip_laws_to_json_schema_from_json_schema_a_preserves_closed_pattern_properties() -> (
    None
):
    "JSON Schema round-trip laws / toJsonSchema(fromJsonSchema(A)) / preserves closed patternProperties"
    assert_json_schema_import_round_trip(
        {
            "type": "object",
            "patternProperties": {"^a": {"type": "string"}},
            "additionalProperties": False,
        },
        [{}, {"a": "a"}, {"a": 1}, {"ab": "a", "b": 1}, {"b": 1}, []],
    )


def test_json_schema_round_trip_laws_from_json_schema_to_json_schema_x_preserves_structs() -> None:
    "JSON Schema round-trip laws / fromJsonSchema(toJsonSchema(X)) / preserves structs"
    assert_representation_round_trip(
        struct({"a": S.String}), [{}, {"a": "a"}, {"a": 1}, {"a": "a", "b": 1}, []]
    )


def test_json_schema_round_trip_laws_from_json_schema_to_json_schema_x_preserves_string_indexes() -> (
    None
):
    "JSON Schema round-trip laws / fromJsonSchema(toJsonSchema(X)) / preserves string indexes"
    assert_representation_round_trip(
        S.Record(S.String, S.Union([S.Finite, S.String])),
        [{}, {"a": "a"}, {"a": 1}, {"a": True}, []],
    )


def test_json_schema_round_trip_laws_from_json_schema_to_json_schema_x_imports_the_loose_default_export_of_approximate_pattern_records() -> (
    None
):
    "JSON Schema round-trip laws / fromJsonSchema(toJsonSchema(X)) / imports the loose default export of approximate pattern records"
    schema = S.Record(S.String.check(S.is_uppercased()), S.Finite)
    inputs = [{}, {"A": 1}, {"A": "a"}, {"a": 1}, {"a": "a"}, []]
    assert_representation_round_trip(schema, inputs)
    emitted = S.to_json_schema_document(schema)
    assert emitted.schema == {"type": "object", "additionalProperties": True}
    imported = assert_loose_representation_round_trip(schema, inputs)
    assert not S.is_(schema)({"A": "a"})
    assert S.is_(imported)({"A": "a"})


def test_json_schema_round_trip_laws_from_json_schema_to_json_schema_x_handles_conjunctive_key_patterns_permissively() -> (
    None
):
    "JSON Schema round-trip laws / fromJsonSchema(toJsonSchema(X)) / handles conjunctive key patterns permissively"
    schema = S.Record(S.String.check(S.is_starting_with("ab"), S.is_ending_with("z")), S.Finite)
    document = S.to_json_schema_document(schema)
    assert document.schema == {"type": "object", "additionalProperties": True}
    validate = compile(document)
    assert validate({"abc": "not a number"}) == True
    assert S.decode_unknown_sync(schema)({"abc": "not a number"}) == {}
    assert validate({"abz": "not a number"}) == True
    assert not is_success(S.decode_unknown_exit(schema)({"abz": "not a number"}))
    assert validate({"abz": 1}) == True
    assert S.decode_unknown_sync(schema)({"abz": 1}) == {"abz": 1}
    strict_document = S.to_json_schema_document(schema, on_excess_property="error")
    assert strict_document.schema == {
        "type": "object",
        "propertyNames": {"type": "string", "pattern": "^ab", "allOf": [{"pattern": "z$"}]},
        "additionalProperties": {"type": "number"},
    }
    validate_strict = compile(strict_document)
    assert validate_strict({"abc": "not a number"}) == False
    assert not is_success(
        S.decode_unknown_exit(schema, on_excess_property="error")({"abc": "not a number"})
    )
    assert validate_strict({"abz": "not a number"}) == False
    assert validate_strict({"abz": 1}) == True


def test_json_schema_round_trip_laws_from_json_schema_to_json_schema_x_uses_permissive_value_alternatives_with_strict_conjunctive_indexes() -> (
    None
):
    "JSON Schema round-trip laws / fromJsonSchema(toJsonSchema(X)) / uses permissive value alternatives with strict conjunctive indexes"
    schema = S.StructWithRest(
        struct({}),
        *[
            S.Record(S.String.check(S.is_starting_with("a"), S.is_ending_with("z")), S.Finite),
            S.Record(S.String.check(S.is_starting_with("b"), S.is_ending_with("z")), S.Boolean),
        ],
    )
    document = S.to_json_schema_document(schema, on_excess_property="error")
    assert document.schema == {
        "type": "object",
        "propertyNames": {
            "anyOf": [
                {"type": "string", "pattern": "^a", "allOf": [{"pattern": "z$"}]},
                {"type": "string", "pattern": "^b", "allOf": [{"pattern": "z$"}]},
            ]
        },
        "additionalProperties": {"anyOf": [{"type": "number"}, {"type": "boolean"}]},
    }
    validate = compile(document)
    assert validate({"az": 1}) == True
    assert S.decode_unknown_sync(schema, on_excess_property="error")({"az": 1}) == {"az": 1}
    assert validate({"bz": True}) == True
    assert S.decode_unknown_sync(schema, on_excess_property="error")({"bz": True}) == {"bz": True}
    assert validate({"az": True}) == True
    assert not is_success(S.decode_unknown_exit(schema, on_excess_property="error")({"az": True}))
    assert validate({"cz": 1}) == False
    assert not is_success(S.decode_unknown_exit(schema, on_excess_property="error")({"cz": 1}))


def test_json_schema_round_trip_laws_from_json_schema_to_json_schema_x_imports_the_loose_export_of_approximate_pattern_and_string_indexes() -> (
    None
):
    "JSON Schema round-trip laws / fromJsonSchema(toJsonSchema(X)) / imports the loose export of approximate pattern and string indexes"
    schema = S.StructWithRest(
        struct({}),
        *[S.Record(S.String.check(S.is_uppercased()), S.Finite), S.Record(S.String, S.Boolean)],
    )
    inputs = [{}, {"A": True}, {"A": 1}, {"a": True}, {"a": 1}, []]
    imported = assert_loose_representation_round_trip(
        schema, inputs, {"on_excess_property": "error"}
    )
    assert not S.is_(schema)({"A": True})
    assert S.is_(imported)({"A": True})


def test_json_schema_round_trip_laws_from_json_schema_to_json_schema_x_preserves_multiple_string_indexes() -> (
    None
):
    "JSON Schema round-trip laws / fromJsonSchema(toJsonSchema(X)) / preserves multiple string indexes"
    assert_representation_round_trip(
        S.StructWithRest(
            struct({}),
            *[
                S.Record(S.String, S.Union([S.Boolean, S.String])),
                S.Record(S.String, S.Union([S.Boolean, S.Finite])),
            ],
        ),
        [{}, {"a": True}, {"a": False}, {"a": 1}, {"a": "a"}, []],
    )


def test_json_schema_round_trip_laws_from_json_schema_to_json_schema_x_applies_string_indexes_to_explicit_properties() -> (
    None
):
    "JSON Schema round-trip laws / fromJsonSchema(toJsonSchema(X)) / applies string indexes to explicit properties"
    assert_representation_round_trip(
        S.StructWithRest(
            struct({"a": S.Union([S.String, S.Boolean])}), *[S.Record(S.String, S.Boolean)]
        ),
        [{}, {"a": True}, {"a": False}, {"a": "a"}, {"a": 1}, {"a": True, "b": False}, []],
    )
