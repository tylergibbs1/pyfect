"""Port of Effect's ``schema/representation/fromJsonSchemaDocument.test.ts``, its
expected code strings unchanged (``_effect_code`` writes a schema as Effect does).
Each test's docstring is the Effect test title, prefixed by its ``describe`` blocks."""

# ruff: noqa: E501, RUF001, B023, PLC3002, PERF403, PLR1714
# pyright: reportUnknownLambdaType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportUnknownMemberType=false
import json
import math
from collections.abc import Callable
from typing import Any, cast

import pytest

from pyfect import json_schema as JS
from pyfect import schema as S
from pyfect.schema import ast
from pyfect.schema import representation as R
from pyfect.schema._schema import Bottom
from pyfect.testing import SchemaAsserts

from ._effect_code import effect_code

make_code = R.make_code


def from_schema(js: Any) -> Any:
    return JS.from_schema_draft_2020_12(js)


def document(dialect: Any, schema: Any, definitions: Any) -> Any:
    return JS.Document(dialect, schema, definitions)


def multi_document(dialect: Any, schemas: Any, definitions: Any) -> Any:
    return JS.MultiDocument(dialect, schemas, definitions)


def to_schema_from_json_schema_document(document: Any, options: Any = None) -> Any:
    resolved: Any = {"patterns": "apply", **(options or {})}
    return R.from_json_schema_document(document, **resolved)


def assert_code(schema: Any, expected: Any) -> None:
    assert effect_code(R.to_representations((schema,))) == {
        "codes": [expected["codes"]],
        "references": {
            "nonRecursives": expected.get("references", {}).get("nonRecursives", []),
            "recursives": expected.get("references", {}).get("recursives", {}),
        },
    }


def assert_from_json_schema(input: Any, expected: Any) -> None:
    document = JS.from_schema_draft_2020_12(input["schema"])
    assert_code(to_schema_from_json_schema_document(document, input.get("options")), expected)


def struct(fields: Any) -> Any:
    def node(value: Any) -> ast.AST:
        if isinstance(value, S.OptionalKey):
            return ast.replace_context(value.schema.__codec__().ast, optional_key=True)
        return value.__codec__().ast

    return Bottom(ast.struct({k: node(v) for k, v in fields.items()}))


def throws(thunk: Callable[[], object], expected: Any = None) -> None:
    with pytest.raises(Exception) as caught:
        thunk()
    if callable(expected):
        expected(caught.value)
    elif expected is not None:
        assert str(caught.value) == expected


def test_from_json_schema_document_round_trips_optional_never_properties_8137() -> None:
    "fromJsonSchemaDocument / round-trips optional Never properties (#8137)"
    original = struct({"value": S.optional_key(S.Never)})
    imported = R.from_json_schema_document(S.to_json_schema_document(original))
    assert_code(
        imported,
        {
            "codes": make_code(
                'Schema.StructWithRest(Schema.Struct({ "value": Schema.optionalKey(Schema.Never) }), [Schema.Record(Schema.String, Schema.Json.annotate({ "expected": "JSON value" }))])',
                '{ readonly "value"?: never } & { readonly [x: string]: Schema.Json }',
            )
        },
    )


def test_from_json_schema_document_imports_not_empty_schemas_at_the_root_and_through_references() -> (
    None
):
    "fromJsonSchemaDocument / imports not-empty schemas at the root and through references"
    assert_from_json_schema(
        {"schema": {"not": {}, "description": "impossible"}},
        {"codes": make_code('Schema.Never.annotate({ "description": "impossible" })', "never")},
    )
    assert_from_json_schema(
        {
            "schema": {
                "type": "object",
                "properties": {"value": {"$ref": "#/$defs/Impossible"}},
                "required": ["value"],
                "$defs": {"Impossible": {"type": "string", "not": {}}},
            }
        },
        {
            "codes": make_code(
                'Schema.StructWithRest(Schema.Struct({ "value": Impossible }), [Schema.Record(Schema.String, Schema.Json.annotate({ "expected": "JSON value" }))])',
                '{ readonly "value": Impossible } & { readonly [x: string]: Schema.Json }',
            ),
            "references": {
                "nonRecursives": [
                    {
                        "$ref": "Impossible",
                        "code": make_code(
                            'Schema.Never.annotate({ "identifier": "Impossible" })', "never"
                        ),
                    }
                ]
            },
        },
    )


def test_from_json_schema_document_preserves_never_in_array_items_and_union_members() -> None:
    "fromJsonSchemaDocument / preserves Never in array items and union members"
    assert_from_json_schema(
        {"schema": {"type": "array", "items": {"not": {}}}},
        {"codes": make_code("Schema.Array(Schema.Never)", "ReadonlyArray<never>")},
    )
    assert_from_json_schema(
        {"schema": {"type": "array", "prefixItems": [{"not": {}}]}},
        {
            "codes": make_code(
                'Schema.TupleWithRest(Schema.Tuple([Schema.optionalKey(Schema.Never)]), [Schema.Json.annotate({ "expected": "JSON value" })])',
                "readonly [(never)?, ...Array<Schema.Json>]",
            )
        },
    )
    assert_from_json_schema(
        {"schema": {"anyOf": [{"not": {}}, {"type": "string"}]}},
        {"codes": make_code("Schema.Union([Schema.Never, Schema.String])", "never | string")},
    )
    assert_from_json_schema(
        {"schema": {"oneOf": [{"not": {}}, {"type": "string"}]}},
        {
            "codes": make_code(
                'Schema.Union([Schema.Never, Schema.String], { mode: "oneOf" })', "never | string"
            )
        },
    )


def test_from_json_schema_document_imports_string_lengths_by_code_point_and_integers_as_safe_integers() -> (
    None
):
    "fromJsonSchemaDocument / imports string lengths by code point and integers as safe integers"
    for source, input, expected in [
        [{"type": "string", "minLength": 2}, "😀", False],
        [{"type": "string", "maxLength": 1}, "😀", True],
        [{"type": "string", "minLength": 1}, "😀", True],
        [{"type": "string", "minLength": 1}, "", False],
        [{"type": "string", "maxLength": 0}, "", True],
        [{"type": "string", "maxLength": 0}, "a", False],
        [{"type": "string", "minLength": 2}, "é", False],
        [{"type": "string", "maxLength": 1}, "é", True],
        [{"type": "string", "minLength": 2}, "e\u0301", True],
        [{"type": "string", "maxLength": 1}, "e\u0301", False],
        [{"type": "string", "minLength": 2}, "\ud800", False],
        [{"type": "string", "maxLength": 1}, "\ud800", True],
        [{"type": "integer"}, 1e20, False],
        [{"type": "string", "pattern": "^.$"}, "😀", True],
    ]:
        schema = to_schema_from_json_schema_document(from_schema(source))
        assert S.is_(schema)(input) == expected


def test_from_json_schema_document_uses_imported_string_semantics_while_intersecting_primitive_literals() -> (
    None
):
    "fromJsonSchemaDocument / uses imported string semantics while intersecting primitive literals"
    min_length = to_schema_from_json_schema_document(
        from_schema({"enum": ["😀", "e\u0301"], "minLength": 2})
    )
    assert not S.is_(min_length)("😀")
    assert S.is_(min_length)("e\u0301")
    pattern = to_schema_from_json_schema_document(from_schema({"const": "😀", "pattern": "^.$"}))
    assert S.is_(pattern)("😀")


def test_from_json_schema_document_reports_patterns_unsupported_in_ecma_script_unicode_mode() -> (
    None
):
    "fromJsonSchemaDocument / reports patterns unsupported in ECMAScript Unicode mode"
    throws(
        lambda: to_schema_from_json_schema_document(
            from_schema({"type": "string", "pattern": "\\a"})
        ),
        'Cannot import pattern using ECMAScript Unicode mode.\n  at ["schema"]["pattern"]',
    )


def test_from_json_schema_document_unconstrained_schema() -> None:
    "fromJsonSchemaDocument / unconstrained schema"
    assert_from_json_schema(
        {"schema": {}},
        {"codes": make_code('Schema.Json.annotate({ "expected": "JSON value" })', "Schema.Json")},
    )
    assert_from_json_schema(
        {
            "schema": {
                "title": "a",
                "description": "b",
                "default": "c",
                "examples": ["d"],
                "readOnly": True,
                "writeOnly": True,
            }
        },
        {
            "codes": make_code(
                'Schema.Json.annotate({ "expected": "JSON value", "title": "a", "description": "b", "default": "c", "examples": ["d"], "readOnly": true, "writeOnly": true })',
                "Schema.Json",
            )
        },
    )


def test_from_json_schema_document_keeps_annotation_only_schemas_unconstrained() -> None:
    "fromJsonSchemaDocument / keeps annotation-only schemas unconstrained"
    assert_from_json_schema(
        {"schema": {"format": "email"}},
        {
            "codes": make_code(
                'Schema.Json.annotate({ "expected": "JSON value", "format": "email" })',
                "Schema.Json",
            )
        },
    )


def test_from_json_schema_document_const_string_literal() -> None:
    "fromJsonSchemaDocument / const / string literal"
    assert_from_json_schema(
        {"schema": {"const": "a"}}, {"codes": make_code('Schema.Literal("a")', '"a"')}
    )
    assert_from_json_schema(
        {"schema": {"const": "a", "description": "a"}},
        {"codes": make_code('Schema.Literal("a").annotate({ "description": "a" })', '"a"')},
    )


def test_from_json_schema_document_const_const_literal_number() -> None:
    "fromJsonSchemaDocument / const / const: literal (number)"
    assert_from_json_schema(
        {"schema": {"const": 1}}, {"codes": make_code("Schema.Literal(1)", "1")}
    )


def test_from_json_schema_document_const_const_literal_boolean() -> None:
    "fromJsonSchemaDocument / const / const: literal (boolean)"
    assert_from_json_schema(
        {"schema": {"const": True}}, {"codes": make_code("Schema.Literal(true)", "true")}
    )


def test_from_json_schema_document_const_null_literal() -> None:
    "fromJsonSchemaDocument / const / null literal"
    assert_from_json_schema(
        {"schema": {"const": None}}, {"codes": make_code("Schema.Null", "null")}
    )
    assert_from_json_schema(
        {"schema": {"const": None, "description": "a"}},
        {"codes": make_code('Schema.Null.annotate({ "description": "a" })', "null")},
    )


def test_from_json_schema_document_const_rejects_structured_values() -> None:
    "fromJsonSchemaDocument / const / rejects structured values"
    for value in [{}, []]:
        throws(
            lambda: to_schema_from_json_schema_document(from_schema({"const": value})),
            'Only primitive values are supported in "const" and "enum".\n  at ["schema"]["const"]',
        )


def test_from_json_schema_document_enum_single_string_member() -> None:
    "fromJsonSchemaDocument / enum / single string member"
    assert_from_json_schema(
        {"schema": {"enum": ["a"]}}, {"codes": make_code('Schema.Literal("a")', '"a"')}
    )
    assert_from_json_schema(
        {"schema": {"enum": ["a"], "description": "a"}},
        {"codes": make_code('Schema.Literal("a").annotate({ "description": "a" })', '"a"')},
    )


def test_from_json_schema_document_enum_single_enum_number() -> None:
    "fromJsonSchemaDocument / enum / single enum (number)"
    assert_from_json_schema(
        {"schema": {"enum": [1]}}, {"codes": make_code("Schema.Literal(1)", "1")}
    )


def test_from_json_schema_document_enum_single_enum_boolean() -> None:
    "fromJsonSchemaDocument / enum / single enum (boolean)"
    assert_from_json_schema(
        {"schema": {"enum": [True]}}, {"codes": make_code("Schema.Literal(true)", "true")}
    )


def test_from_json_schema_document_enum_multiple_literal_members() -> None:
    "fromJsonSchemaDocument / enum / multiple literal members"
    assert_from_json_schema(
        {"schema": {"enum": ["a", 1]}}, {"codes": make_code('Schema.Literals(["a", 1])', '"a" | 1')}
    )
    assert_from_json_schema(
        {"schema": {"enum": ["a", 1], "description": "a"}},
        {
            "codes": make_code(
                'Schema.Literals(["a", 1]).annotate({ "description": "a" })', '"a" | 1'
            )
        },
    )


def test_from_json_schema_document_enum_enum_containing_null() -> None:
    "fromJsonSchemaDocument / enum / enum containing null"
    assert_from_json_schema(
        {"schema": {"enum": ["a", None]}},
        {"codes": make_code('Schema.Union([Schema.Literal("a"), Schema.Null])', '"a" | null')},
    )


def test_from_json_schema_document_any_of() -> None:
    "fromJsonSchemaDocument / anyOf"
    assert_from_json_schema(
        {"schema": {"anyOf": [{"const": "a"}, {"enum": [1, 2]}]}},
        {
            "codes": make_code(
                'Schema.Union([Schema.Literal("a"), Schema.Literals([1, 2])])', '"a" | 1 | 2'
            )
        },
    )


def test_from_json_schema_document_any_of_with_siblings() -> None:
    "fromJsonSchemaDocument / anyOf with siblings"
    assert_from_json_schema(
        {
            "schema": {
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
                "anyOf": [
                    {"properties": {"a": {"type": "string"}}, "required": ["a"]},
                    {"properties": {"b": {"type": "number"}}, "required": ["b"]},
                ],
            }
        },
        {
            "codes": make_code(
                'Schema.Union([Schema.StructWithRest(Schema.Struct({ "a": Schema.String, "id": Schema.String }), [Schema.Record(Schema.String, Schema.Json.annotate({ "expected": "JSON value" }))]), Schema.StructWithRest(Schema.Struct({ "b": Schema.Finite, "id": Schema.String }), [Schema.Record(Schema.String, Schema.Json.annotate({ "expected": "JSON value" }))])])',
                '{ readonly "a": string, readonly "id": string } & { readonly [x: string]: Schema.Json } | { readonly "b": number, readonly "id": string } & { readonly [x: string]: Schema.Json }',
            )
        },
    )


def test_from_json_schema_document_one_of() -> None:
    "fromJsonSchemaDocument / oneOf"
    assert_from_json_schema(
        {"schema": {"oneOf": [{"const": "a"}, {"enum": [1, 2]}]}},
        {
            "codes": make_code(
                'Schema.Union([Schema.Literal("a"), Schema.Literals([1, 2])], { mode: "oneOf" })',
                '"a" | 1 | 2',
            )
        },
    )


def test_from_json_schema_document_one_of_with_siblings() -> None:
    "fromJsonSchemaDocument / oneOf with siblings"
    assert_from_json_schema(
        {
            "schema": {
                "type": "object",
                "properties": {"id": {"type": "string"}},
                "required": ["id"],
                "oneOf": [
                    {"properties": {"a": {"type": "string"}}, "required": ["a"]},
                    {"properties": {"b": {"type": "number"}}, "required": ["b"]},
                ],
            }
        },
        {
            "codes": make_code(
                'Schema.Union([Schema.StructWithRest(Schema.Struct({ "a": Schema.String, "id": Schema.String }), [Schema.Record(Schema.String, Schema.Json.annotate({ "expected": "JSON value" }))]), Schema.StructWithRest(Schema.Struct({ "b": Schema.Finite, "id": Schema.String }), [Schema.Record(Schema.String, Schema.Json.annotate({ "expected": "JSON value" }))])], { mode: "oneOf" })',
                '{ readonly "a": string, readonly "id": string } & { readonly [x: string]: Schema.Json } | { readonly "b": number, readonly "id": string } & { readonly [x: string]: Schema.Json }',
            )
        },
    )


def test_from_json_schema_document_type_null_type_only() -> None:
    "fromJsonSchemaDocument / type: null / type only"
    assert_from_json_schema(
        {"schema": {"type": "null"}}, {"codes": make_code("Schema.Null", "null")}
    )


def test_from_json_schema_document_type_string_type_only() -> None:
    "fromJsonSchemaDocument / type: string / type only"
    assert_from_json_schema(
        {"schema": {"type": "string"}}, {"codes": make_code("Schema.String", "string")}
    )


def test_from_json_schema_document_type_string_checks_min_length() -> None:
    "fromJsonSchemaDocument / type: string / checks / minLength"
    assert_from_json_schema(
        {"schema": {"type": "string", "minLength": 1}},
        {
            "codes": make_code(
                'Schema.String.check(Schema.isMinLength(1).annotate({ "expected": "a value with a length of at least 1" }))',
                "string",
            )
        },
    )


def test_from_json_schema_document_type_string_checks_max_length() -> None:
    "fromJsonSchemaDocument / type: string / checks / maxLength"
    assert_from_json_schema(
        {"schema": {"type": "string", "maxLength": 1}},
        {
            "codes": make_code(
                'Schema.String.check(Schema.isMaxCodePoints(1).annotate({ "expected": "a string with at most 1 code points" }))',
                "string",
            )
        },
    )


def test_from_json_schema_document_type_string_checks_pattern_with_an_explicit_string_type() -> (
    None
):
    "fromJsonSchemaDocument / type: string / checks / pattern with an explicit string type"
    assert_from_json_schema(
        {"schema": {"type": "string", "pattern": "a*"}},
        {
            "codes": make_code(
                'Schema.String.check(Schema.isPattern(new globalThis.RegExp("a*", "u")).annotate({ "expected": "a string matching the RegExp a*" }))',
                "string",
            )
        },
    )


def test_from_json_schema_document_type_string_checks_pattern_only_constrains_strings() -> None:
    "fromJsonSchemaDocument / type: string / checks / pattern only constrains strings"
    assert_from_json_schema(
        {"schema": {"pattern": "^a+$"}},
        {
            "codes": make_code(
                'Schema.Union([Schema.Null, Schema.String.check(Schema.isPattern(new globalThis.RegExp("^a+$", "u")).annotate({ "expected": "a string matching the RegExp ^a+$" })), Schema.Finite, Schema.Boolean, Schema.Record(Schema.String, Schema.Json.annotate({ "expected": "JSON value" })), Schema.Array(Schema.Json.annotate({ "expected": "JSON value" }))])',
                "null | string | number | boolean | { readonly [x: string]: Schema.Json } | ReadonlyArray<Schema.Json>",
            )
        },
    )


def test_from_json_schema_document_type_number_type_only() -> None:
    "fromJsonSchemaDocument / type: number / type only"
    assert_from_json_schema(
        {"schema": {"type": "number"}}, {"codes": make_code("Schema.Finite", "number")}
    )


def test_from_json_schema_document_type_number_checks_minimum() -> None:
    "fromJsonSchemaDocument / type: number / checks / minimum"
    assert_from_json_schema(
        {"schema": {"type": "number", "minimum": 1}},
        {
            "codes": make_code(
                'Schema.Finite.check(Schema.isGreaterThanOrEqualTo(1).annotate({ "expected": "a value greater than or equal to 1" }))',
                "number",
            )
        },
    )


def test_from_json_schema_document_type_number_checks_maximum() -> None:
    "fromJsonSchemaDocument / type: number / checks / maximum"
    assert_from_json_schema(
        {"schema": {"type": "number", "maximum": 1}},
        {
            "codes": make_code(
                'Schema.Finite.check(Schema.isLessThanOrEqualTo(1).annotate({ "expected": "a value less than or equal to 1" }))',
                "number",
            )
        },
    )


def test_from_json_schema_document_type_number_checks_exclusive_minimum() -> None:
    "fromJsonSchemaDocument / type: number / checks / exclusiveMinimum"
    assert_from_json_schema(
        {"schema": {"type": "number", "exclusiveMinimum": 1}},
        {
            "codes": make_code(
                'Schema.Finite.check(Schema.isGreaterThan(1).annotate({ "expected": "a value greater than 1" }))',
                "number",
            )
        },
    )


def test_from_json_schema_document_type_number_checks_exclusive_maximum() -> None:
    "fromJsonSchemaDocument / type: number / checks / exclusiveMaximum"
    assert_from_json_schema(
        {"schema": {"type": "number", "exclusiveMaximum": 1}},
        {
            "codes": make_code(
                'Schema.Finite.check(Schema.isLessThan(1).annotate({ "expected": "a value less than 1" }))',
                "number",
            )
        },
    )


def test_from_json_schema_document_type_number_checks_multiple_of() -> None:
    "fromJsonSchemaDocument / type: number / checks / multipleOf"
    assert_from_json_schema(
        {"schema": {"type": "number", "multipleOf": 1}},
        {
            "codes": make_code(
                'Schema.Finite.check(Schema.isMultipleOf(1).annotate({ "expected": "a value that is a multiple of 1" }))',
                "number",
            )
        },
    )


def test_from_json_schema_document_type_integer_type_only() -> None:
    "fromJsonSchemaDocument / type: integer / type only"
    assert_from_json_schema(
        {"schema": {"type": "integer"}}, {"codes": make_code("Schema.Int", "number")}
    )


def test_from_json_schema_document_type_integer_checks_minimum() -> None:
    "fromJsonSchemaDocument / type: integer / checks / minimum"
    assert_from_json_schema(
        {"schema": {"type": "integer", "minimum": 1}},
        {
            "codes": make_code(
                'Schema.Int.check(Schema.isGreaterThanOrEqualTo(1).annotate({ "expected": "a value greater than or equal to 1" }))',
                "number",
            )
        },
    )


def test_from_json_schema_document_type_integer_checks_maximum() -> None:
    "fromJsonSchemaDocument / type: integer / checks / maximum"
    assert_from_json_schema(
        {"schema": {"type": "integer", "maximum": 1}},
        {
            "codes": make_code(
                'Schema.Int.check(Schema.isLessThanOrEqualTo(1).annotate({ "expected": "a value less than or equal to 1" }))',
                "number",
            )
        },
    )


def test_from_json_schema_document_type_integer_checks_exclusive_minimum() -> None:
    "fromJsonSchemaDocument / type: integer / checks / exclusiveMinimum"
    assert_from_json_schema(
        {"schema": {"type": "integer", "exclusiveMinimum": 1}},
        {
            "codes": make_code(
                'Schema.Int.check(Schema.isGreaterThan(1).annotate({ "expected": "a value greater than 1" }))',
                "number",
            )
        },
    )


def test_from_json_schema_document_type_integer_checks_exclusive_maximum() -> None:
    "fromJsonSchemaDocument / type: integer / checks / exclusiveMaximum"
    assert_from_json_schema(
        {"schema": {"type": "integer", "exclusiveMaximum": 1}},
        {
            "codes": make_code(
                'Schema.Int.check(Schema.isLessThan(1).annotate({ "expected": "a value less than 1" }))',
                "number",
            )
        },
    )


def test_from_json_schema_document_type_integer_checks_multiple_of() -> None:
    "fromJsonSchemaDocument / type: integer / checks / multipleOf"
    assert_from_json_schema(
        {"schema": {"type": "integer", "multipleOf": 1}},
        {
            "codes": make_code(
                'Schema.Int.check(Schema.isMultipleOf(1).annotate({ "expected": "a value that is a multiple of 1" }))',
                "number",
            )
        },
    )


def test_from_json_schema_document_type_boolean_type_only() -> None:
    "fromJsonSchemaDocument / type: boolean / type only"
    assert_from_json_schema(
        {"schema": {"type": "boolean"}}, {"codes": make_code("Schema.Boolean", "boolean")}
    )


def test_from_json_schema_document_type_array_type_only() -> None:
    "fromJsonSchemaDocument / type: array / type only"
    assert_from_json_schema(
        {"schema": {"type": "array"}},
        {
            "codes": make_code(
                'Schema.Array(Schema.Json.annotate({ "expected": "JSON value" }))',
                "ReadonlyArray<Schema.Json>",
            )
        },
    )


def test_from_json_schema_document_type_array_items() -> None:
    "fromJsonSchemaDocument / type: array / items"
    assert_from_json_schema(
        {"schema": {"type": "array", "items": {"type": "string"}}},
        {"codes": make_code("Schema.Array(Schema.String)", "ReadonlyArray<string>")},
    )


def test_from_json_schema_document_type_array_prefix_items_preserves_max_items_below_the_prefix_length() -> (
    None
):
    "fromJsonSchemaDocument / type: array / prefixItems preserves maxItems below the prefix length"
    assert_from_json_schema(
        {
            "schema": {
                "type": "array",
                "prefixItems": [{"type": "string"}, {"type": "number"}],
                "maxItems": 1,
            }
        },
        {
            "codes": make_code(
                'Schema.TupleWithRest(Schema.Tuple([Schema.optionalKey(Schema.String), Schema.optionalKey(Schema.Finite)]), [Schema.Json.annotate({ "expected": "JSON value" })]).check(Schema.isMaxLength(1).annotate({ "expected": "a value with a length of at most 1" }))',
                "readonly [(string)?, (number)?, ...Array<Schema.Json>]",
            )
        },
    )


def test_from_json_schema_document_type_array_prefix_items_preserves_max_items_above_the_prefix_length() -> (
    None
):
    "fromJsonSchemaDocument / type: array / prefixItems preserves maxItems above the prefix length"
    assert_from_json_schema(
        {"schema": {"type": "array", "prefixItems": [{"type": "string"}], "maxItems": 2}},
        {
            "codes": make_code(
                'Schema.TupleWithRest(Schema.Tuple([Schema.optionalKey(Schema.String)]), [Schema.Json.annotate({ "expected": "JSON value" })]).check(Schema.isMaxLength(2).annotate({ "expected": "a value with a length of at most 2" }))',
                "readonly [(string)?, ...Array<Schema.Json>]",
            )
        },
    )


def test_from_json_schema_document_type_array_prefix_items_omits_max_items_redundant_with_items_false() -> (
    None
):
    "fromJsonSchemaDocument / type: array / prefixItems omits maxItems redundant with items: false"
    assert_from_json_schema(
        {
            "schema": {
                "type": "array",
                "prefixItems": [{"type": "string"}],
                "items": False,
                "maxItems": 2,
            }
        },
        {
            "codes": make_code(
                "Schema.Tuple([Schema.optionalKey(Schema.String)])", "readonly [(string)?]"
            )
        },
    )


def test_from_json_schema_document_type_array_prefix_items_closes_when_max_items_equals_the_prefix_length() -> (
    None
):
    "fromJsonSchemaDocument / type: array / prefixItems closes when maxItems equals the prefix length"
    assert_from_json_schema(
        {"schema": {"type": "array", "prefixItems": [{"type": "string"}], "maxItems": 1}},
        {
            "codes": make_code(
                "Schema.Tuple([Schema.optionalKey(Schema.String)])", "readonly [(string)?]"
            )
        },
    )


def test_from_json_schema_document_type_array_prefix_items_marks_elements_required_by_min_items() -> (
    None
):
    "fromJsonSchemaDocument / type: array / prefixItems marks elements required by minItems"
    assert_from_json_schema(
        {
            "schema": {
                "type": "array",
                "prefixItems": [{"type": "string"}],
                "minItems": 1,
                "maxItems": 1,
            }
        },
        {"codes": make_code("Schema.Tuple([Schema.String])", "readonly [string]")},
    )


def test_from_json_schema_document_type_array_prefix_items_min_items() -> None:
    "fromJsonSchemaDocument / type: array / prefixItems & minItems"
    assert_from_json_schema(
        {
            "schema": {
                "type": "array",
                "prefixItems": [{"type": "string"}],
                "minItems": 1,
                "items": {"type": "number"},
            }
        },
        {
            "codes": make_code(
                "Schema.TupleWithRest(Schema.Tuple([Schema.String]), [Schema.Finite])",
                "readonly [string, ...Array<number>]",
            )
        },
    )


def test_from_json_schema_document_type_array_checks_min_items() -> None:
    "fromJsonSchemaDocument / type: array / checks / minItems"
    assert_from_json_schema(
        {"schema": {"type": "array", "minItems": 1}},
        {
            "codes": make_code(
                'Schema.Array(Schema.Json.annotate({ "expected": "JSON value" })).check(Schema.isMinLength(1).annotate({ "expected": "a value with a length of at least 1" }))',
                "ReadonlyArray<Schema.Json>",
            )
        },
    )


def test_from_json_schema_document_type_array_checks_max_items() -> None:
    "fromJsonSchemaDocument / type: array / checks / maxItems"
    assert_from_json_schema(
        {"schema": {"type": "array", "maxItems": 1}},
        {
            "codes": make_code(
                'Schema.Array(Schema.Json.annotate({ "expected": "JSON value" })).check(Schema.isMaxLength(1).annotate({ "expected": "a value with a length of at most 1" }))',
                "ReadonlyArray<Schema.Json>",
            )
        },
    )


def test_from_json_schema_document_type_array_checks_unique_items() -> None:
    "fromJsonSchemaDocument / type: array / checks / uniqueItems"
    assert_from_json_schema(
        {"schema": {"type": "array", "uniqueItems": True}},
        {
            "codes": make_code(
                'Schema.Array(Schema.Json.annotate({ "expected": "JSON value" })).check(Schema.isUnique().annotate({ "expected": "an array with unique items" }))',
                "ReadonlyArray<Schema.Json>",
            )
        },
    )


def test_from_json_schema_document_type_array_checks_does_not_require_uniqueness_when_unique_items_is_false() -> (
    None
):
    "fromJsonSchemaDocument / type: array / checks / does not require uniqueness when uniqueItems is false"
    assert_from_json_schema(
        {"schema": {"type": "array", "uniqueItems": False}},
        {
            "codes": make_code(
                'Schema.Array(Schema.Json.annotate({ "expected": "JSON value" }))',
                "ReadonlyArray<Schema.Json>",
            )
        },
    )


def test_from_json_schema_document_type_object_delegates_excess_properties_of_closed_structs_to_parse_options() -> (
    None
):
    "fromJsonSchemaDocument / type: object / delegates excess properties of closed structs to ParseOptions"
    schema = to_schema_from_json_schema_document(
        from_schema(
            {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "additionalProperties": False,
            }
        )
    )
    asserts = SchemaAsserts(schema)
    decoding = asserts.decoding()
    strict_decoding = asserts.decoding(on_excess_property="error")
    input = {"extra": 1}
    decoding.succeed(input, {})
    assert input == {"extra": 1}
    strict_decoding.fail(input, 'Expected no excess property\n  at ["extra"]')
    strict_decoding.succeed({})
    for value in [None, False, 0, "", [], None]:
        decoding.fail(value, "Expected object")


def test_from_json_schema_document_type_object_preserves_json_valued_additional_properties_for_every_open_form() -> (
    None
):
    "fromJsonSchemaDocument / type: object / preserves JSON-valued additional properties for every open form"
    for additional_properties in [None, True, {}]:
        schema = to_schema_from_json_schema_document(
            from_schema(
                {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    **(
                        {}
                        if additional_properties is None
                        else {"additionalProperties": additional_properties}
                    ),
                }
            )
        )
        asserts = SchemaAsserts(schema)
        decoding = asserts.decoding()
        input = {"name": "Mario", "extra": {"values": [1, None, True]}}
        decoding.succeed(input)
        asserts.decoding(on_excess_property="error").succeed(input)
        for extra in [math.inf, object(), lambda: 1]:
            decoding.fail({"extra": extra}, 'Expected JSON value\n  at ["extra"]')


def test_from_json_schema_document_type_object_runs_property_checks_after_stripping_excess_properties() -> (
    None
):
    "fromJsonSchemaDocument / type: object / runs property checks after stripping excess properties"
    schema = to_schema_from_json_schema_document(
        from_schema(
            {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "additionalProperties": False,
                "maxProperties": 1,
                "propertyNames": {"enum": ["name"]},
            }
        )
    )
    asserts = SchemaAsserts(schema)
    asserts.decoding().succeed({"name": "Mario", "extra": 1}, {"name": "Mario"})
    asserts.decoding(on_excess_property="error").fail(
        {"name": "Mario", "extra": 1}, 'Expected no excess property\n  at ["extra"]'
    )


def test_from_json_schema_document_type_object_allows_additional_properties_by_default() -> None:
    "fromJsonSchemaDocument / type: object / allows additional properties by default"
    assert_from_json_schema(
        {"schema": {"type": "object"}},
        {
            "codes": make_code(
                'Schema.Record(Schema.String, Schema.Json.annotate({ "expected": "JSON value" }))',
                "{ readonly [x: string]: Schema.Json }",
            )
        },
    )


def test_from_json_schema_document_type_object_closes_an_object_when_additional_properties_is_false() -> (
    None
):
    "fromJsonSchemaDocument / type: object / closes an object when additionalProperties is false"
    assert_from_json_schema(
        {"schema": {"type": "object", "additionalProperties": False}},
        {
            "codes": make_code(
                "Schema.Record(Schema.String, Schema.Never)", "{ readonly [x: string]: never }"
            )
        },
    )


def test_from_json_schema_document_type_object_preserves_closed_empty_objects_through_representation_persistence_and_code_generation() -> (
    None
):
    "fromJsonSchemaDocument / type: object / preserves closed empty objects through representation persistence and code generation"
    schema = to_schema_from_json_schema_document(
        from_schema({"type": "object", "additionalProperties": False})
    )
    persisted = R.to_json(R.to_representation(schema))
    revived = R.from_representation(R.from_json(persisted), revivers=[])
    for current in [schema, revived]:
        asserts: Any = SchemaAsserts(current)
        for decoding in [asserts.decoding(), asserts.decoding(on_excess_property="error")]:
            decoding.succeed({})
            for value in [1, None]:
                decoding.fail({"extra": value}, 'Expected never\n  at ["extra"]')
            decoding.fail([], "Expected object")
    assert_code(
        revived,
        {
            "codes": make_code(
                "Schema.Record(Schema.String, Schema.Never)", "{ readonly [x: string]: never }"
            )
        },
    )


def test_from_json_schema_document_type_object_additional_properties() -> None:
    "fromJsonSchemaDocument / type: object / additionalProperties"
    assert_from_json_schema(
        {"schema": {"type": "object", "additionalProperties": {"type": "boolean"}}},
        {
            "codes": make_code(
                "Schema.Record(Schema.String, Schema.Boolean)", "{ readonly [x: string]: boolean }"
            )
        },
    )


def test_from_json_schema_document_type_object_properties() -> None:
    "fromJsonSchemaDocument / type: object / properties"
    assert_from_json_schema(
        {
            "schema": {
                "type": "object",
                "properties": {"a": {"type": "string"}, "b": {"type": "string"}},
                "required": ["a"],
                "additionalProperties": False,
            }
        },
        {
            "codes": make_code(
                'Schema.Struct({ "a": Schema.String, "b": Schema.optionalKey(Schema.String) })',
                '{ readonly "a": string, readonly "b"?: string }',
            )
        },
    )


def test_from_json_schema_document_type_object_properties_additional_properties() -> None:
    "fromJsonSchemaDocument / type: object / properties & additionalProperties"
    throws(
        lambda: to_schema_from_json_schema_document(
            from_schema(
                {
                    "type": "object",
                    "properties": {"a": {"type": "string"}},
                    "required": ["a"],
                    "additionalProperties": {"type": "boolean"},
                }
            )
        ),
        'Cannot combine typed "additionalProperties" with other property schemas: Effect index signatures also check excluded keys.\n  at ["schema"]',
    )


def test_from_json_schema_document_type_object_explains_why_typed_additional_properties_cannot_exclude_patterned_keys() -> (
    None
):
    "fromJsonSchemaDocument / type: object / explains why typed additional properties cannot exclude patterned keys"
    throws(
        lambda: to_schema_from_json_schema_document(
            from_schema(
                {
                    "type": "object",
                    "patternProperties": {"^a": {"type": "string"}},
                    "additionalProperties": {"type": "number"},
                }
            )
        ),
        'Cannot combine typed "additionalProperties" with other property schemas: Effect index signatures also check excluded keys.\n  at ["schema"]',
    )


def test_from_json_schema_document_type_object_explains_the_supported_closed_pattern_form_when_properties_are_declared_or_required() -> (
    None
):
    "fromJsonSchemaDocument / type: object / explains the supported closed pattern form when properties are declared or required"
    for fields in [{"properties": {"a": {"type": "number"}}}, {"required": ["a"]}]:
        throws(
            lambda: to_schema_from_json_schema_document(
                from_schema(
                    {
                        "type": "object",
                        "patternProperties": {"^a": {"type": "number"}},
                        "additionalProperties": False,
                        **fields,
                    }
                )
            ),
            'Cannot import this closed patterned object: only one pattern without properties is supported.\n  at ["schema"]',
        )


def test_from_json_schema_document_type_object_round_trips_a_closed_record_with_a_patterned_key() -> (
    None
):
    "fromJsonSchemaDocument / type: object / round-trips a closed Record with a patterned key"
    original = S.Record(S.String.check(S.is_starting_with("a")), S.Finite)
    document = S.to_json_schema_document(original, on_excess_property="error")
    assert document.schema == {
        "type": "object",
        "patternProperties": {"^a": {"type": "number"}},
        "additionalProperties": False,
    }
    imported = to_schema_from_json_schema_document(document)
    asserts = SchemaAsserts(imported)
    decoding = asserts.decoding()
    strict_decoding = asserts.decoding(on_excess_property="error")
    for input in [{}, {"a": 1}, {"a": 1, "abc": 2}]:
        decoding.succeed(input)
        strict_decoding.succeed(input)
    input = {"a": 1, "z": "extra"}
    decoding.succeed(input, {"a": 1})
    assert input == {"a": 1, "z": "extra"}
    decoding.succeed({"z": 1}, {})
    strict_decoding.fail(input, 'Expected no excess property\n  at ["z"]')
    strict_decoding.fail({"z": 1}, 'Expected no excess property\n  at ["z"]')
    for value in ["x", None, None]:
        decoding.fail({"a": value}, 'Expected number\n  at ["a"]')
        strict_decoding.fail({"a": value}, 'Expected number\n  at ["a"]')
    decoding.fail({"a": math.inf}, 'Expected a finite number\n  at ["a"]')
    strict_decoding.fail({"a": math.inf}, 'Expected a finite number\n  at ["a"]')
    for value in [None, False, 0, "", [], None]:
        decoding.fail(value, "Expected object")
    assert S.to_json_schema_document(imported, on_excess_property="error") == document


def test_from_json_schema_document_type_object_imports_a_closed_patterned_record_through_references() -> (
    None
):
    "fromJsonSchemaDocument / type: object / imports a closed patterned Record through references"
    assert_from_json_schema(
        {
            "schema": {
                "type": "object",
                "properties": {"values": {"$ref": "#/$defs/Values"}},
                "required": ["values"],
                "additionalProperties": False,
                "$defs": {
                    "Values": {
                        "type": "object",
                        "patternProperties": {"a": {"$ref": "#/$defs/Value"}},
                        "additionalProperties": False,
                    },
                    "Value": {"type": "string", "minLength": 2},
                },
            }
        },
        {
            "codes": make_code(
                'Schema.Struct({ "values": Values })', '{ readonly "values": Values }'
            ),
            "references": {
                "nonRecursives": [
                    {
                        "$ref": "Value",
                        "code": make_code(
                            'Schema.String.check(Schema.isMinCodePoints(2).annotate({ "expected": "a string with at least 2 code points", "identifier": "Value" }))',
                            "string",
                        ),
                    },
                    {
                        "$ref": "Values",
                        "code": make_code(
                            'Schema.Record(Schema.String.check(Schema.isPattern(new globalThis.RegExp("a", "u")).annotate({ "expected": "a string matching the RegExp a" })), Value).annotate({ "identifier": "Values" })',
                            "{ readonly [x: string]: Value }",
                        ),
                    },
                ]
            },
        },
    )


def test_from_json_schema_document_type_object_keeps_a_closed_pattern_with_never_values_as_an_object_schema() -> (
    None
):
    "fromJsonSchemaDocument / type: object / keeps a closed pattern with Never values as an object schema"
    assert_from_json_schema(
        {
            "schema": {
                "type": "object",
                "patternProperties": {"^a": {"not": {}}},
                "additionalProperties": False,
            }
        },
        {
            "codes": make_code(
                'Schema.Record(Schema.String.check(Schema.isPattern(new globalThis.RegExp("^a", "u")).annotate({ "expected": "a string matching the RegExp ^a" })), Schema.Never)',
                "{ readonly [x: string]: never }",
            )
        },
    )


def test_from_json_schema_document_type_object_matches_finite_pattern_properties_keys_in_unicode_mode() -> (
    None
):
    "fromJsonSchemaDocument / type: object / matches finite patternProperties keys in Unicode mode"
    document = from_schema(
        {
            "allOf": [
                {"type": "object", "properties": {"😀": {}}, "additionalProperties": False},
                {"type": "object", "patternProperties": {"^.$": {"type": "string"}}},
            ]
        }
    )
    schema = to_schema_from_json_schema_document(document)
    assert S.is_(schema)({"😀": "value"})
    assert not S.is_(schema)({"😀": 1})
    assert_code(
        schema,
        {
            "codes": make_code(
                'Schema.Struct({ "😀": Schema.optionalKey(Schema.String) })',
                '{ readonly "😀"?: string }',
            )
        },
    )


def test_from_json_schema_document_type_object_rejects_closed_multiple_pattern_properties() -> None:
    "fromJsonSchemaDocument / type: object / rejects closed multiple pattern properties"
    throws(
        lambda: to_schema_from_json_schema_document(
            from_schema(
                {
                    "type": "object",
                    "patternProperties": {"a*": {"type": "string"}, "b*": {"type": "number"}},
                    "additionalProperties": False,
                }
            )
        ),
        'Cannot import this closed patterned object: only one pattern without properties is supported.\n  at ["schema"]',
    )


def test_from_json_schema_document_type_object_checks_min_properties() -> None:
    "fromJsonSchemaDocument / type: object / checks / minProperties"
    assert_from_json_schema(
        {"schema": {"type": "object", "minProperties": 1}},
        {
            "codes": make_code(
                'Schema.Record(Schema.String, Schema.Json.annotate({ "expected": "JSON value" })).check(Schema.isMinProperties(1).annotate({ "expected": "a value with at least 1 entry" }))',
                "{ readonly [x: string]: Schema.Json }",
            )
        },
    )


def test_from_json_schema_document_type_object_checks_max_properties() -> None:
    "fromJsonSchemaDocument / type: object / checks / maxProperties"
    assert_from_json_schema(
        {"schema": {"type": "object", "maxProperties": 1}},
        {
            "codes": make_code(
                'Schema.Record(Schema.String, Schema.Json.annotate({ "expected": "JSON value" })).check(Schema.isMaxProperties(1).annotate({ "expected": "a value with at most 1 entry" }))',
                "{ readonly [x: string]: Schema.Json }",
            )
        },
    )


def test_from_json_schema_document_type_object_property_names_pattern() -> None:
    "fromJsonSchemaDocument / type: object / propertyNames / pattern"
    assert_from_json_schema(
        {"schema": {"type": "object", "propertyNames": {"pattern": "^[A-Z]"}}},
        {
            "codes": make_code(
                'Schema.Record(Schema.String, Schema.Json.annotate({ "expected": "JSON value" })).check(Schema.isPropertyNames(Schema.String.check(Schema.isPattern(new globalThis.RegExp("^[A-Z]", "u")).annotate({ "expected": "a string matching the RegExp ^[A-Z]" }))).annotate({ "expected": "an object with property names matching the schema" }))',
                "{ readonly [x: string]: Schema.Json }",
            )
        },
    )


def test_from_json_schema_document_type_object_property_names_false() -> None:
    "fromJsonSchemaDocument / type: object / propertyNames / false"
    assert_from_json_schema(
        {"schema": {"type": "object", "propertyNames": False}},
        {
            "codes": make_code(
                'Schema.Record(Schema.String, Schema.Json.annotate({ "expected": "JSON value" })).check(Schema.isPropertyNames(Schema.Never).annotate({ "expected": "an object with property names matching the schema" }))',
                "{ readonly [x: string]: Schema.Json }",
            )
        },
    )


def test_from_json_schema_document_type_object_property_names_all_of_combines_checks() -> None:
    "fromJsonSchemaDocument / type: object / propertyNames / allOf combines checks"
    assert_from_json_schema(
        {
            "schema": {
                "allOf": [
                    {"type": "object", "propertyNames": {"pattern": "^[A-Z]"}},
                    {"type": "object", "propertyNames": {"minLength": 2}},
                ]
            }
        },
        {
            "codes": make_code(
                'Schema.Record(Schema.String, Schema.Json.annotate({ "expected": "JSON value" })).check(Schema.isPropertyNames(Schema.String.check(Schema.isPattern(new globalThis.RegExp("^[A-Z]", "u")).annotate({ "expected": "a string matching the RegExp ^[A-Z]" }))).annotate({ "expected": "an object with property names matching the schema" })).check(Schema.isPropertyNames(Schema.String.check(Schema.isMinCodePoints(2).annotate({ "expected": "a string with at least 2 code points" }))).annotate({ "expected": "an object with property names matching the schema" }))',
                "{ readonly [x: string]: Schema.Json }",
            )
        },
    )


def test_from_json_schema_document_array_of_types() -> None:
    "fromJsonSchemaDocument / array of types"
    assert_from_json_schema(
        {"schema": {"type": ["string", "null"]}},
        {"codes": make_code("Schema.Union([Schema.String, Schema.Null])", "string | null")},
    )
    assert_from_json_schema(
        {"schema": {"type": ["string", "null"], "description": "a"}},
        {
            "codes": make_code(
                'Schema.Union([Schema.String, Schema.Null]).annotate({ "description": "a" })',
                "string | null",
            )
        },
    )


def test_from_json_schema_document_ignores_true_schemas_in_all_of() -> None:
    "fromJsonSchemaDocument / ignores true schemas in allOf"
    assert_from_json_schema(
        {"schema": {"allOf": [True, {"type": "string"}]}},
        {"codes": make_code("Schema.String", "string")},
    )


def test_from_json_schema_document_rejects_structured_enum_members() -> None:
    "fromJsonSchemaDocument / rejects structured enum members"
    for value in [[], {}, {"not": "data"}]:
        throws(
            lambda: to_schema_from_json_schema_document(from_schema({"enum": ["a", value]})),
            'Only primitive values are supported in "const" and "enum".\n  at ["schema"]["enum"][1]',
        )
    throws(
        lambda: to_schema_from_json_schema_document(from_schema({"const": "a", "enum": [{}]})),
        'Only primitive values are supported in "const" and "enum".\n  at ["schema"]["enum"][0]',
    )


def test_from_json_schema_document_imports_built_in_json_schema_annotations() -> None:
    "fromJsonSchemaDocument / imports built-in JSON Schema annotations"
    assert_from_json_schema(
        {
            "schema": {
                "type": "string",
                "format": "email",
                "contentEncoding": "base64",
                "contentMediaType": "application/json",
                "contentSchema": {"type": "number"},
            }
        },
        {
            "codes": make_code(
                'Schema.String.annotate({ "format": "email", "contentEncoding": "base64", "contentMediaType": "application/json", "contentSchema": { "type": "number" } })',
                "string",
            )
        },
    )


def test_from_json_schema_document_ref_rejects_local_references_inside_nested_resources() -> None:
    "fromJsonSchemaDocument / $ref / rejects local references inside nested resources"
    reference = {"$ref": "#/$defs/X"}
    nested = {"$id": "child", "$defs": {"X": {"type": "number"}}}
    for body, suffix in [
        [reference, ""],
        [{"type": "object", "properties": {"value": reference}}, '["properties"]["value"]'],
        [{"properties": {"value": reference}}, '["properties"]["value"]'],
        [{"type": "array", "items": reference}, '["items"]'],
        [{"type": "array", "prefixItems": [reference]}, '["prefixItems"][0]'],
        [{"allOf": [reference]}, '["allOf"][0]'],
        [{"anyOf": [reference, {"type": "null"}]}, '["anyOf"][0]'],
        [{"oneOf": [reference, {"type": "null"}]}, '["oneOf"][0]'],
        [{"type": "object", "additionalProperties": reference}, '["additionalProperties"]'],
        [{"type": "object", "patternProperties": {"^a": reference}}, '["patternProperties"]["^a"]'],
        [{"type": "object", "propertyNames": reference}, '["propertyNames"]'],
    ]:
        throws(
            lambda: to_schema_from_json_schema_document(
                from_schema(
                    {
                        "$id": "https://example.com/root",
                        "type": "object",
                        "properties": {"child": {**nested, **cast("dict[str, Any]", body)}},
                        "$defs": {"X": {"type": "string"}},
                    }
                )
            ),
            'Cannot resolve $ref under a nested "$id". Resolve or flatten it first.\n  at ["schema"]["properties"]["child"]'
            + str(suffix)
            + '["$ref"]',
        )


def test_from_json_schema_document_ref_keeps_root_ids_and_nested_resources_without_references_supported() -> (
    None
):
    "fromJsonSchemaDocument / $ref / keeps root ids and nested resources without references supported"
    assert_from_json_schema(
        {
            "schema": {
                "$id": "https://example.com/root",
                "type": "object",
                "properties": {
                    "child": {
                        "$id": "child",
                        "type": "number",
                        "$defs": {"Unused": {"$ref": "#/$defs/X"}},
                    },
                    "value": {"$ref": "#/$defs/X"},
                },
                "$defs": {"X": {"type": "string"}},
            }
        },
        {
            "codes": make_code(
                'Schema.StructWithRest(Schema.Struct({ "child": Schema.optionalKey(Schema.Finite), "value": Schema.optionalKey(X) }), [Schema.Record(Schema.String, Schema.Json.annotate({ "expected": "JSON value" }))])',
                '{ readonly "child"?: number, readonly "value"?: X } & { readonly [x: string]: Schema.Json }',
            ),
            "references": {
                "nonRecursives": [
                    {
                        "$ref": "X",
                        "code": make_code(
                            'Schema.String.annotate({ "identifier": "X" })', "string"
                        ),
                    }
                ]
            },
        },
    )


def test_from_json_schema_document_ref_determines_resource_scope_from_on_enter_results() -> None:
    "fromJsonSchemaDocument / $ref / determines resource scope from onEnter results"
    document = from_schema(
        {
            "type": "object",
            "properties": {"child": {"$id": "child", "$ref": "#/$defs/X"}},
            "$defs": {"X": {"type": "string"}},
        }
    )
    schema = to_schema_from_json_schema_document(
        document,
        {"on_enter": lambda schema: {k: v for k, v in {**schema}.items() if k not in ("$id",)}},
    )
    assert_code(
        schema,
        {
            "codes": make_code(
                'Schema.StructWithRest(Schema.Struct({ "child": Schema.optionalKey(X) }), [Schema.Record(Schema.String, Schema.Json.annotate({ "expected": "JSON value" }))])',
                '{ readonly "child"?: X } & { readonly [x: string]: Schema.Json }',
            ),
            "references": {
                "nonRecursives": [
                    {
                        "$ref": "X",
                        "code": make_code(
                            'Schema.String.annotate({ "identifier": "X" })', "string"
                        ),
                    }
                ]
            },
        },
    )
    throws(
        lambda: to_schema_from_json_schema_document(
            from_schema(
                {
                    "type": "array",
                    "items": {"$ref": "#/$defs/X"},
                    "$defs": {"X": {"type": "string"}},
                }
            ),
            {
                "on_enter": lambda schema: (
                    schema if schema.get("$ref") is None else {**schema, "$id": "child"}
                )
            },
        ),
        'Cannot resolve $ref under a nested "$id". Resolve or flatten it first.\n  at ["schema"]["items"]["$ref"]',
    )


def test_from_json_schema_document_ref_rejects_references_in_a_reachable_definition_with_its_own_id() -> (
    None
):
    "fromJsonSchemaDocument / $ref / rejects references in a reachable definition with its own id"
    throws(
        lambda: to_schema_from_json_schema_document(
            from_schema(
                {
                    "$ref": "#/$defs/Child",
                    "$defs": {
                        "Child": {
                            "$id": "https://example.com/child",
                            "type": "object",
                            "properties": {"value": {"$ref": "#/$defs/X"}},
                        },
                        "X": {"type": "string"},
                    },
                }
            )
        ),
        'Cannot resolve $ref under a nested "$id". Resolve or flatten it first.\n  at ["definitions"]["Child"]["properties"]["value"]["$ref"]',
    )


def test_from_json_schema_document_ref_resolves_references_below_a_definition_to_the_pointed_subschema() -> (
    None
):
    "fromJsonSchemaDocument / $ref / resolves references below a definition to the pointed subschema"
    schema = to_schema_from_json_schema_document(
        from_schema(
            {
                "type": "object",
                "properties": {
                    "copy": {"$ref": "#/$defs/outer/properties/inner", "minLength": 2},
                    "item": {"$ref": "#/$defs/either/anyOf/1"},
                },
                "$defs": {
                    "inner": {"type": "number"},
                    "outer": {"type": "object", "properties": {"inner": {"type": "string"}}},
                    "either": {"anyOf": [{"type": "string"}, {"type": "number"}]},
                },
            }
        )
    )
    is_ = S.is_(schema)
    assert is_({"copy": "ab", "item": 1})
    assert not is_({"copy": 1})
    assert not is_({"copy": "a"})
    assert not is_({"item": "a"})


def test_from_json_schema_document_ref_reports_a_reference_below_a_definition_that_leads_nowhere() -> (
    None
):
    "fromJsonSchemaDocument / $ref / reports a reference below a definition that leads nowhere"
    throws(
        lambda: to_schema_from_json_schema_document(
            from_schema(
                {
                    "$ref": "#/$defs/outer/properties/missing",
                    "$defs": {
                        "outer": {"type": "object", "properties": {"name": {"type": "string"}}}
                    },
                }
            )
        ),
        'Unresolvable $ref "#/$defs/outer/properties/missing". Nothing exists at that location.\n  at ["schema"]["$ref"]',
    )


def test_from_json_schema_document_ref_resolves_a_recursive_reference_below_a_definition() -> None:
    "fromJsonSchemaDocument / $ref / resolves a recursive reference below a definition"
    schema = to_schema_from_json_schema_document(
        from_schema(
            {
                "$ref": "#/$defs/Tree/properties/node",
                "$defs": {
                    "Tree": {
                        "type": "object",
                        "properties": {
                            "node": {
                                "type": "object",
                                "properties": {"next": {"$ref": "#/$defs/Tree/properties/node"}},
                            }
                        },
                    }
                },
            }
        )
    )
    is_ = S.is_(schema)
    assert is_({"next": {"next": {}}})
    assert not is_({"next": {"next": 1}})


def test_from_json_schema_document_ref_rejects_a_pointer_that_refers_directly_to_itself() -> None:
    "fromJsonSchemaDocument / $ref / rejects a pointer that refers directly to itself"
    document = from_schema(
        {
            "$ref": "#/$defs/Container/properties/value",
            "$defs": {
                "Container": {
                    "properties": {"value": {"$ref": "#/$defs/Container/properties/value"}}
                }
            },
        }
    )
    throws(
        lambda: to_schema_from_json_schema_document(document),
        'Definition "Container/properties/value" is a circular alias.\n  at ["schema"]["$ref"]',
    )


def test_from_json_schema_document_ref_rejects_a_pointer_that_refers_back_to_itself_through_a_definition() -> (
    None
):
    "fromJsonSchemaDocument / $ref / rejects a pointer that refers back to itself through a definition"
    document = from_schema(
        {
            "$ref": "#/$defs/Container/properties/value",
            "$defs": {
                "Alias": {"$ref": "#/$defs/Container/properties/value"},
                "Container": {"properties": {"value": {"$ref": "#/$defs/Alias"}}},
            },
        }
    )
    throws(
        lambda: to_schema_from_json_schema_document(document),
        'Definition "Alias" is a circular alias.\n  at ["schema"]["$ref"]',
    )


def test_from_json_schema_document_ref_rejects_a_circular_pointer_alias_wrapped_in_any_of() -> None:
    "fromJsonSchemaDocument / $ref / rejects a circular pointer alias wrapped in anyOf"
    document = from_schema(
        {
            "$ref": "#/$defs/Container/properties/value",
            "$defs": {
                "Container": {
                    "properties": {
                        "value": {"anyOf": [{"$ref": "#/$defs/Container/properties/value"}]}
                    }
                }
            },
        }
    )
    throws(
        lambda: to_schema_from_json_schema_document(document),
        'Definition "Container/properties/value" is a circular alias.\n  at ["schema"]["$ref"]',
    )


def test_from_json_schema_document_ref_rejects_a_circular_pointer_alias_wrapped_in_one_of() -> None:
    "fromJsonSchemaDocument / $ref / rejects a circular pointer alias wrapped in oneOf"
    document = from_schema(
        {
            "$ref": "#/$defs/Container/properties/value",
            "$defs": {
                "Container": {
                    "properties": {
                        "value": {"oneOf": [{"$ref": "#/$defs/Container/properties/value"}]}
                    }
                }
            },
        }
    )
    throws(
        lambda: to_schema_from_json_schema_document(document),
        'Definition "Container/properties/value" is a circular alias.\n  at ["schema"]["$ref"]',
    )


def test_from_json_schema_document_ref_rejects_a_circular_alias_chain_through_singleton_unions() -> (
    None
):
    "fromJsonSchemaDocument / $ref / rejects a circular alias chain through singleton unions"
    document = from_schema(
        {
            "$ref": "#/$defs/Container/properties/value",
            "$defs": {
                "Alias": {"oneOf": [{"$ref": "#/$defs/Container/properties/value"}]},
                "Container": {"properties": {"value": {"anyOf": [{"$ref": "#/$defs/Alias"}]}}},
            },
        }
    )
    throws(
        lambda: to_schema_from_json_schema_document(document),
        'Definition "Alias" is a circular alias.\n  at ["schema"]["$ref"]',
    )


def test_from_json_schema_document_ref_rejects_a_circular_pointer_alias_alongside_another_any_of_branch() -> (
    None
):
    "fromJsonSchemaDocument / $ref / rejects a circular pointer alias alongside another anyOf branch"
    document = from_schema(
        {
            "$ref": "#/$defs/Container/properties/value",
            "$defs": {
                "Container": {
                    "properties": {
                        "value": {
                            "anyOf": [
                                {"$ref": "#/$defs/Container/properties/value"},
                                {"type": "string"},
                            ]
                        }
                    }
                }
            },
        }
    )
    throws(
        lambda: to_schema_from_json_schema_document(document),
        'Definition "Container/properties/value" is a circular alias.\n  at ["schema"]["$ref"]',
    )


def test_from_json_schema_document_ref_rejects_a_circular_pointer_alias_in_a_later_one_of_branch() -> (
    None
):
    "fromJsonSchemaDocument / $ref / rejects a circular pointer alias in a later oneOf branch"
    document = from_schema(
        {
            "$ref": "#/$defs/Container/properties/value",
            "$defs": {
                "Container": {
                    "properties": {
                        "value": {
                            "oneOf": [
                                {"type": "string"},
                                {"$ref": "#/$defs/Container/properties/value"},
                            ]
                        }
                    }
                }
            },
        }
    )
    throws(
        lambda: to_schema_from_json_schema_document(document),
        'Definition "Container/properties/value" is a circular alias.\n  at ["schema"]["$ref"]',
    )


def test_from_json_schema_document_ref_rejects_a_circular_alias_chain_through_unions_with_multiple_branches() -> (
    None
):
    "fromJsonSchemaDocument / $ref / rejects a circular alias chain through unions with multiple branches"
    document = from_schema(
        {
            "$ref": "#/$defs/Container/properties/value",
            "$defs": {
                "Alias": {
                    "oneOf": [{"type": "number"}, {"$ref": "#/$defs/Container/properties/value"}]
                },
                "Container": {
                    "properties": {
                        "value": {"anyOf": [{"type": "string"}, {"$ref": "#/$defs/Alias"}]}
                    }
                },
            },
        }
    )
    throws(
        lambda: to_schema_from_json_schema_document(document),
        'Definition "Alias" is a circular alias.\n  at ["schema"]["$ref"]',
    )


def test_from_json_schema_document_ref_allows_union_branches_to_share_the_same_alias() -> None:
    "fromJsonSchemaDocument / $ref / allows union branches to share the same alias"
    document = from_schema(
        {
            "$ref": "#/$defs/Container/properties/value",
            "$defs": {
                "Alias": {"$ref": "#/$defs/Text"},
                "Text": {"type": "string"},
                "Container": {
                    "properties": {
                        "value": {
                            "anyOf": [
                                {"$ref": "#/$defs/Alias"},
                                {"oneOf": [{"$ref": "#/$defs/Alias"}, {"type": "number"}]},
                            ]
                        }
                    }
                },
            },
        }
    )
    schema = to_schema_from_json_schema_document(document)
    is_ = S.is_(schema)
    assert is_("text")
    assert is_(123)
    assert not is_(False)


def test_from_json_schema_document_ref_imports_a_deeply_shared_union_graph() -> None:
    "fromJsonSchemaDocument / $ref / imports a deeply shared union graph"
    definitions: dict[str, Any] = {"Text": {"type": "string"}}
    level_count = 20
    for level in range(level_count - 1, -1, -1):
        next = "Text" if level == level_count - 1 else "Level" + str(level + 1) + ""
        definitions["Level" + str(level) + ""] = {
            "anyOf": [{"$ref": "#/$defs/" + str(next) + ""}, {"$ref": "#/$defs/" + str(next) + ""}]
        }
    definitions["Container"] = {"properties": {"value": {"$ref": "#/$defs/Level0"}}}
    document = from_schema({"$ref": "#/$defs/Container/properties/value", "$defs": definitions})
    schema = to_schema_from_json_schema_document(document)
    assert S.is_(schema)("text")


def test_from_json_schema_document_ref_rejects_a_circular_alias_after_validating_a_shared_branch() -> (
    None
):
    "fromJsonSchemaDocument / $ref / rejects a circular alias after validating a shared branch"
    document = from_schema(
        {
            "anyOf": [
                {"$ref": "#/$defs/Container/properties/shared"},
                {"$ref": "#/$defs/Container/properties/circular"},
            ],
            "$defs": {
                "Text": {"type": "string"},
                "Container": {
                    "properties": {
                        "shared": {"$ref": "#/$defs/Text"},
                        "circular": {
                            "anyOf": [
                                {"$ref": "#/$defs/Text"},
                                {"$ref": "#/$defs/Container/properties/circular"},
                            ]
                        },
                    }
                },
            },
        }
    )
    throws(
        lambda: to_schema_from_json_schema_document(document),
        'Definition "Container/properties/circular" is a circular alias.\n  at ["schema"]["anyOf"][1]["$ref"]',
    )


def test_from_json_schema_document_ref_allows_union_branches_to_recurse_through_object_properties_and_array_items() -> (
    None
):
    "fromJsonSchemaDocument / $ref / allows union branches to recurse through object properties and array items"
    document = from_schema(
        {
            "$ref": "#/$defs/Tree/properties/node",
            "$defs": {
                "Tree": {
                    "properties": {
                        "node": {
                            "anyOf": [
                                {
                                    "type": "object",
                                    "properties": {
                                        "next": {"$ref": "#/$defs/Tree/properties/node"}
                                    },
                                },
                                {
                                    "type": "array",
                                    "items": {"$ref": "#/$defs/Tree/properties/node"},
                                },
                                {"type": "null"},
                            ]
                        }
                    }
                }
            },
        }
    )
    schema = to_schema_from_json_schema_document(document)
    is_ = S.is_(schema)
    assert is_({"next": [{"next": None}]})
    assert is_([{"next": []}])
    assert not is_({"next": [123]})
    assert not is_([{"next": "invalid"}])


def test_from_json_schema_document_ref_allows_a_singleton_union_around_a_recursive_object() -> None:
    "fromJsonSchemaDocument / $ref / allows a singleton union around a recursive object"
    document = from_schema(
        {
            "$ref": "#/$defs/Tree/properties/node",
            "$defs": {
                "Tree": {
                    "properties": {
                        "node": {
                            "anyOf": [
                                {
                                    "type": "object",
                                    "properties": {
                                        "next": {"$ref": "#/$defs/Tree/properties/node"}
                                    },
                                }
                            ]
                        }
                    }
                }
            },
        }
    )
    schema = to_schema_from_json_schema_document(document)
    is_ = S.is_(schema)
    assert is_({"next": {"next": {}}})
    assert not is_({"next": {"next": 1}})


def test_from_json_schema_document_ref_allows_aliases_that_recurse_through_object_properties() -> (
    None
):
    "fromJsonSchemaDocument / $ref / allows aliases that recurse through object properties"
    document = from_schema(
        {
            "$ref": "#/$defs/Alias",
            "$defs": {
                "Alias": {"$ref": "#/$defs/Tree/properties/node"},
                "Tree": {
                    "properties": {
                        "node": {
                            "type": "object",
                            "properties": {"next": {"$ref": "#/$defs/Alias"}},
                        }
                    }
                },
            },
        }
    )
    schema = to_schema_from_json_schema_document(document)
    is_ = S.is_(schema)
    assert is_({"next": {"next": {}}})
    assert not is_({"next": {"next": 1}})


def test_from_json_schema_document_ref_exports_a_reference_below_a_definition_as_one_shared_definition() -> (
    None
):
    "fromJsonSchemaDocument / $ref / exports a reference below a definition as one shared definition"
    schema = to_schema_from_json_schema_document(
        from_schema(
            {
                "type": "object",
                "properties": {
                    "a": {"$ref": "#/$defs/O/properties/v"},
                    "b": {"$ref": "#/$defs/O/properties/v"},
                },
                "$defs": {"O": {"type": "object", "properties": {"v": {"type": "string"}}}},
            }
        )
    )
    hoisted = to_schema_from_json_schema_document(
        from_schema(
            {
                "type": "object",
                "properties": {
                    "a": {"$ref": "#/$defs/O~1properties~1v"},
                    "b": {"$ref": "#/$defs/O~1properties~1v"},
                },
                "$defs": {"O/properties/v": {"type": "string"}},
            }
        )
    )
    assert S.to_json_schema_document(schema) == S.to_json_schema_document(hoisted)


def test_from_json_schema_document_ref_rejects_a_reference_below_a_definition_whose_derived_key_is_already_a_definition() -> (
    None
):
    "fromJsonSchemaDocument / $ref / rejects a reference below a definition whose derived key is already a definition"
    throws(
        lambda: to_schema_from_json_schema_document(
            from_schema(
                {
                    "$ref": "#/$defs/O/properties/v",
                    "$defs": {
                        "O": {"type": "object", "properties": {"v": {"type": "string"}}},
                        "O/properties/v": {"type": "number"},
                    },
                }
            )
        ),
        'Pointer $ref "#/$defs/O/properties/v" conflicts with definition "O/properties/v".\n  at ["schema"]["$ref"]',
    )


def test_from_json_schema_document_ref_rejects_references_below_a_pointer_that_passes_through_a_definition_with_its_own_id() -> (
    None
):
    "fromJsonSchemaDocument / $ref / rejects references below a pointer that passes through a definition with its own id"
    throws(
        lambda: to_schema_from_json_schema_document(
            from_schema(
                {
                    "$ref": "#/$defs/Outer/properties/value",
                    "$defs": {
                        "X": {"type": "string"},
                        "Outer": {
                            "$id": "https://example.com/child",
                            "$defs": {"X": {"type": "number"}},
                            "type": "object",
                            "properties": {"value": {"$ref": "#/$defs/X"}},
                        },
                    },
                }
            )
        ),
        'Cannot resolve $ref under a nested "$id". Resolve or flatten it first.\n  at ["definitions"]["Outer"]["properties"]["value"]["$ref"]',
    )


def test_from_json_schema_document_ref_determines_the_resource_scope_of_a_pointer_below_a_definition_from_on_enter_results() -> (
    None
):
    "fromJsonSchemaDocument / $ref / determines the resource scope of a pointer below a definition from onEnter results"
    schema = to_schema_from_json_schema_document(
        from_schema(
            {
                "$ref": "#/$defs/Outer/properties/value",
                "$defs": {
                    "X": {"type": "string"},
                    "Outer": {
                        "$id": "https://example.com/child",
                        "type": "object",
                        "properties": {"value": {"$ref": "#/$defs/X"}},
                    },
                },
            }
        ),
        {"on_enter": lambda schema: {k: v for k, v in {**schema}.items() if k not in ("$id",)}},
    )
    is_ = S.is_(schema)
    assert is_("a")
    assert not is_(1)


def test_from_json_schema_document_ref_rejects_an_empty_reference() -> None:
    "fromJsonSchemaDocument / $ref / rejects an empty reference"
    throws(
        lambda: to_schema_from_json_schema_document(from_schema({"$ref": ""})),
        'Unsupported $ref "". Use "#/$defs/Name".\n  at ["schema"]["$ref"]',
    )


def test_from_json_schema_document_ref_rejects_an_external_reference_instead_of_aliasing_a_local_definition() -> (
    None
):
    "fromJsonSchemaDocument / $ref / rejects an external reference instead of aliasing a local definition"
    throws(
        lambda: to_schema_from_json_schema_document(
            from_schema(
                {"$ref": "https://example.com/schema#/$defs/A", "$defs": {"A": {"type": "string"}}}
            )
        ),
        'Unsupported $ref "https://example.com/schema#/$defs/A". Use "#/$defs/Name".\n  at ["schema"]["$ref"]',
    )


def test_from_json_schema_document_ref_reports_the_full_reference_when_a_direct_definition_is_missing() -> (
    None
):
    "fromJsonSchemaDocument / $ref / reports the full reference when a direct definition is missing"
    throws(
        lambda: to_schema_from_json_schema_document(from_schema({"$ref": "#/$defs/Missing"})),
        'Missing definition "Missing" for $ref "#/$defs/Missing".\n  at ["schema"]["$ref"]',
    )


def test_from_json_schema_document_ref_unescapes_a_direct_definition_reference() -> None:
    "fromJsonSchemaDocument / $ref / unescapes a direct definition reference"
    assert_from_json_schema(
        {"schema": {"$ref": "#/$defs/A~1B~0C", "$defs": {"A/B~C": {"type": "string"}}}},
        {
            "codes": make_code("A_B_C", "A_B_C"),
            "references": {
                "nonRecursives": [
                    {
                        "$ref": "A_B_C",
                        "code": make_code(
                            'Schema.String.annotate({ "identifier": "A/B~C" })', "string"
                        ),
                    }
                ]
            },
        },
    )


def test_from_json_schema_document_ref_decodes_a_direct_definition_reference() -> None:
    "fromJsonSchemaDocument / $ref / decodes a direct definition reference"
    assert_from_json_schema(
        {"schema": {"$ref": "#/$defs/A%20B", "$defs": {"A B": {"type": "string"}}}},
        {
            "codes": make_code("A_B", "A_B"),
            "references": {
                "nonRecursives": [
                    {
                        "$ref": "A_B",
                        "code": make_code(
                            'Schema.String.annotate({ "identifier": "A B" })', "string"
                        ),
                    }
                ]
            },
        },
    )


def test_from_json_schema_document_ref_resolves_a_direct_reference_to_an_empty_definition_key() -> (
    None
):
    "fromJsonSchemaDocument / $ref / resolves a direct reference to an empty definition key"
    assert_from_json_schema(
        {"schema": {"$ref": "#/$defs/", "$defs": {"": {"type": "string"}}}},
        {
            "codes": make_code("_", "_"),
            "references": {
                "nonRecursives": [
                    {
                        "$ref": "_",
                        "code": make_code('Schema.String.annotate({ "identifier": "" })', "string"),
                    }
                ]
            },
        },
    )


def test_from_json_schema_document_ref_should_create_a_reference_and_a_definition() -> None:
    "fromJsonSchemaDocument / $ref / should create a Reference and a definition"
    assert_from_json_schema(
        {"schema": {"$ref": "#/$defs/A", "$defs": {"A": {"type": "string"}}}},
        {
            "codes": make_code("A", "A"),
            "references": {
                "nonRecursives": [
                    {
                        "$ref": "A",
                        "code": make_code(
                            'Schema.String.annotate({ "identifier": "A" })', "string"
                        ),
                    }
                ]
            },
        },
    )


def test_from_json_schema_document_ref_should_preserve_an_annotated_ref_as_a_stable_suspend() -> (
    None
):
    "fromJsonSchemaDocument / $ref / should preserve an annotated $ref as a stable suspend"
    assert_from_json_schema(
        {"schema": {"$ref": "#/$defs/A", "description": "a", "$defs": {"A": {"type": "string"}}}},
        {
            "codes": make_code(
                'Schema.suspend((): Schema.Codec<A> => A).annotate({ "description": "a" })', "A"
            ),
            "references": {
                "nonRecursives": [
                    {
                        "$ref": "A",
                        "code": make_code(
                            'Schema.String.annotate({ "identifier": "A" })', "string"
                        ),
                    }
                ]
            },
        },
    )


def test_from_json_schema_document_ref_does_not_combine_annotation_siblings_with_a_ref() -> None:
    "fromJsonSchemaDocument / $ref / does not combine annotation siblings with a $ref"
    assert_from_json_schema(
        {"schema": {"$ref": "#/$defs/A", "format": "custom", "$defs": {"A": {"type": "number"}}}},
        {
            "codes": make_code(
                'Schema.suspend((): Schema.Codec<A> => A).annotate({ "format": "custom" })', "A"
            ),
            "references": {
                "nonRecursives": [
                    {
                        "$ref": "A",
                        "code": make_code(
                            'Schema.Number.check(Schema.isFinite().annotate({ "expected": "a finite number", "identifier": "A" }))',
                            "number",
                        ),
                    }
                ]
            },
        },
    )


def test_from_json_schema_document_ref_should_preserve_a_ref_refined_only_by_annotations_as_a_stable_suspend() -> (
    None
):
    "fromJsonSchemaDocument / $ref / should preserve a $ref refined only by annotations as a stable suspend"
    assert_from_json_schema(
        {
            "schema": {
                "allOf": [{"$ref": "#/$defs/A"}, {"description": "a"}],
                "$defs": {"A": {"type": "string"}},
            }
        },
        {
            "codes": make_code(
                'Schema.suspend((): Schema.Codec<A> => A).annotate({ "description": "a" })', "A"
            ),
            "references": {
                "nonRecursives": [
                    {
                        "$ref": "A",
                        "code": make_code(
                            'Schema.String.annotate({ "identifier": "A" })', "string"
                        ),
                    }
                ]
            },
        },
    )


def test_from_json_schema_document_ref_recursive_schema() -> None:
    "fromJsonSchemaDocument / $ref / recursive schema"
    assert_from_json_schema(
        {
            "schema": {
                "$ref": "#/$defs/A",
                "$defs": {
                    "A": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "children": {"type": "array", "items": {"$ref": "#/$defs/A"}},
                        },
                        "required": ["name", "children"],
                        "additionalProperties": False,
                    }
                },
            }
        },
        {
            "codes": make_code("A", "A"),
            "references": {
                "recursives": {
                    "A": make_code(
                        'Schema.Struct({ "name": Schema.String, "children": Schema.Array(Schema.suspend((): Schema.Codec<A> => A)) }).annotate({ "identifier": "A" })',
                        '{ readonly "name": string, readonly "children": ReadonlyArray<A> }',
                    )
                }
            },
        },
    )


def test_from_json_schema_document_ref_preserves_annotations_on_a_recursive_ref() -> None:
    "fromJsonSchemaDocument / $ref / preserves annotations on a recursive $ref"
    assert_from_json_schema(
        {
            "schema": {
                "$ref": "#/$defs/Node",
                "$defs": {
                    "Node": {
                        "type": "object",
                        "properties": {
                            "child": {"$ref": "#/$defs/Node", "description": "recursive child"}
                        },
                        "required": ["child"],
                        "additionalProperties": False,
                    }
                },
            }
        },
        {
            "codes": make_code("Node", "Node"),
            "references": {
                "recursives": {
                    "Node": make_code(
                        'Schema.Struct({ "child": Schema.suspend((): Schema.Codec<Node> => Node).annotate({ "description": "recursive child" }) }).annotate({ "identifier": "Node" })',
                        '{ readonly "child": Node }',
                    )
                }
            },
        },
    )


def test_from_json_schema_document_ref_combines_assertion_siblings_with_a_ref() -> None:
    "fromJsonSchemaDocument / $ref / combines assertion siblings with a $ref"
    assert_from_json_schema(
        {
            "schema": {
                "$ref": "#/$defs/Name",
                "minLength": 2,
                "description": "name",
                "$defs": {"Name": {"type": "string"}},
            }
        },
        {
            "codes": make_code(
                'Schema.String.annotate({ "description": "name" }).check(Schema.isMinCodePoints(2).annotate({ "expected": "a string with at least 2 code points" }))',
                "string",
            )
        },
    )


def test_from_json_schema_document_ref_rejects_assertion_siblings_on_a_recursive_ref() -> None:
    "fromJsonSchemaDocument / $ref / rejects assertion siblings on a recursive $ref"
    throws(
        lambda: R.from_json_schema_document(
            from_schema(
                {
                    "$ref": "#/$defs/Node",
                    "$defs": {
                        "Node": {
                            "type": "object",
                            "properties": {"child": {"$ref": "#/$defs/Node", "minProperties": 1}},
                        }
                    },
                }
            )
        ),
        'Recursive $ref "Node" cannot have sibling constraints.\n  at ["definitions"]["Node"]["properties"]["child"]["$ref"]',
    )


@pytest.mark.parametrize(
    ("annotation_code", "annotations", "options"),
    [
        ('{ "description": "name" }', {"description": "name"}, {}),
        (
            '{ "x-sensitive": true }',
            {"x-sensitive": True},
            {"include_annotation_key": lambda key: key == "x-sensitive"},
        ),
    ],
)
def test_allof_intersects_union_members_containing_annotated_references(
    annotation_code: str, annotations: Any, options: Any
) -> None:
    "fromJsonSchemaDocument / allOf / intersects union members containing annotated references: $annotationCode"
    unconstrained = {"$ref": "#/$defs/Any", **annotations}
    name = {"$ref": "#/$defs/Name"}
    for all_of in [[unconstrained, name], [name, unconstrained]]:
        assert_from_json_schema(
            {
                "schema": {
                    "allOf": [
                        {"anyOf": [{"allOf": all_of}, {"type": "number"}]},
                        {"enum": ["a", "b"]},
                    ],
                    "$defs": {"Any": {}, "Name": {"type": "string"}},
                },
                "options": options,
            },
            {
                "codes": make_code(
                    f'Schema.Union([Schema.Literal("a").annotate({annotation_code}), Schema.Literal("b").annotate({annotation_code})])',
                    '"a" | "b"',
                )
            },
        )


def test_from_json_schema_document_all_of_prunes_disjoint_lanes_before_intersecting_unions() -> (
    None
):
    "fromJsonSchemaDocument / allOf / prunes disjoint lanes before intersecting unions"
    assert_from_json_schema(
        {
            "schema": {
                "allOf": [
                    {"anyOf": [{"type": "string"}, {"type": "number"}]},
                    {"anyOf": [{"type": "number"}, {"type": "boolean"}]},
                ]
            }
        },
        {"codes": make_code("Schema.Finite", "number")},
    )


def test_from_json_schema_document_all_of_rejects_intersections_requiring_a_cartesian_product() -> (
    None
):
    "fromJsonSchemaDocument / allOf / rejects intersections requiring a Cartesian product"
    throws(
        lambda: to_schema_from_json_schema_document(
            from_schema(
                {
                    "allOf": [
                        {
                            "anyOf": [
                                {"type": "string", "minLength": 2, "maxLength": 3},
                                {"type": "string", "minLength": 5, "maxLength": 6},
                            ]
                        },
                        {
                            "anyOf": [
                                {"type": "string", "pattern": "^a"},
                                {"type": "string", "pattern": "z$"},
                            ]
                        },
                    ]
                }
            )
        ),
        'Cannot intersect these "anyOf" or "oneOf" alternatives without expanding their branches.\n  at ["schema"]["allOf"][1]',
    )


def test_from_json_schema_document_all_of_rejects_distributions_that_duplicate_a_nested_choice() -> (
    None
):
    "fromJsonSchemaDocument / allOf / rejects distributions that duplicate a nested choice"
    throws(
        lambda: to_schema_from_json_schema_document(
            from_schema(
                {
                    "allOf": [
                        {
                            "anyOf": [
                                {"type": "object", "properties": {"tag": {"const": "a"}}},
                                {"type": "object", "properties": {"tag": {"const": "b"}}},
                            ]
                        },
                        {
                            "type": "object",
                            "properties": {
                                "value": {"anyOf": [{"type": "string"}, {"type": "number"}]}
                            },
                        },
                    ]
                }
            )
        ),
        'Cannot intersect these "anyOf" or "oneOf" alternatives without expanding their branches.\n  at ["schema"]["allOf"][1]',
    )


def test_from_json_schema_document_all_of_distributes_across_a_nested_reference_without_choices() -> (
    None
):
    "fromJsonSchemaDocument / allOf / distributes across a nested reference without choices"
    assert_from_json_schema(
        {
            "schema": {
                "allOf": [
                    {
                        "anyOf": [
                            {"type": "object", "required": ["a"]},
                            {"type": "object", "required": ["b"]},
                        ]
                    },
                    {
                        "type": "object",
                        "properties": {"value": {"$ref": "#/$defs/Value"}},
                        "required": ["value"],
                    },
                ],
                "$defs": {"Value": {"type": "string"}},
            }
        },
        {
            "codes": make_code(
                'Schema.Union([Schema.StructWithRest(Schema.Struct({ "a": Schema.Json.annotate({ "expected": "JSON value" }), "value": Value }), [Schema.Record(Schema.String, Schema.Json.annotate({ "expected": "JSON value" }))]), Schema.StructWithRest(Schema.Struct({ "b": Schema.Json.annotate({ "expected": "JSON value" }), "value": Value }), [Schema.Record(Schema.String, Schema.Json.annotate({ "expected": "JSON value" }))])])',
                '{ readonly "a": Schema.Json, readonly "value": Value } & { readonly [x: string]: Schema.Json } | { readonly "b": Schema.Json, readonly "value": Value } & { readonly [x: string]: Schema.Json }',
            ),
            "references": {
                "nonRecursives": [
                    {
                        "$ref": "Value",
                        "code": make_code(
                            'Schema.String.annotate({ "identifier": "Value" })', "string"
                        ),
                    }
                ]
            },
        },
    )


def test_from_json_schema_document_all_of_reports_unsupported_keywords_after_a_false_schema() -> (
    None
):
    "fromJsonSchemaDocument / allOf / reports unsupported keywords after a false schema"
    throws(
        lambda: to_schema_from_json_schema_document(
            from_schema({"allOf": [False, {"contains": {}}]})
        ),
        'Cannot import JSON Schema keyword "contains": Effect has no equivalent constraint.\n  at ["schema"]["allOf"][1]["contains"]',
    )


def test_from_json_schema_document_all_of_intersects_one_constraint_with_many_alternatives_linearly() -> (
    None
):
    "fromJsonSchemaDocument / allOf / intersects one constraint with many alternatives linearly"
    assert_from_json_schema(
        {
            "schema": {
                "pattern": "^value-",
                "anyOf": [
                    (lambda _, index: {"const": "value-" + str(index) + ""})(None, i)
                    for i in range(16)
                ],
            }
        },
        {
            "codes": make_code(
                'Schema.Literals(["value-0", "value-1", "value-2", "value-3", "value-4", "value-5", "value-6", "value-7", "value-8", "value-9", "value-10", "value-11", "value-12", "value-13", "value-14", "value-15"])',
                '"value-0" | "value-1" | "value-2" | "value-3" | "value-4" | "value-5" | "value-6" | "value-7" | "value-8" | "value-9" | "value-10" | "value-11" | "value-12" | "value-13" | "value-14" | "value-15"',
            )
        },
    )


def test_from_json_schema_document_all_of_resolves_a_root_reference_before_intersecting_all_of() -> (
    None
):
    "fromJsonSchemaDocument / allOf / resolves a root reference before intersecting allOf"
    definition = {"type": "string", "minLength": 1}
    assert_from_json_schema(
        {
            "schema": {
                "$ref": "#/$defs/A",
                "allOf": [{"type": "string", "maxLength": 2}],
                "$defs": {"A": definition},
            }
        },
        {
            "codes": make_code(
                'Schema.String.check(Schema.isMinLength(1).annotate({ "expected": "a value with a length of at least 1" })).check(Schema.isMaxCodePoints(2).annotate({ "expected": "a string with at most 2 code points" }))',
                "string",
            )
        },
    )


def test_from_json_schema_document_all_of_resolves_a_reference_declared_inside_all_of() -> None:
    "fromJsonSchemaDocument / allOf / resolves a reference declared inside allOf"
    definition = {"type": "string", "minLength": 1}
    assert_from_json_schema(
        {
            "schema": {
                "allOf": [{"$ref": "#/$defs/A"}, {"type": "string", "maxLength": 2}],
                "$defs": {"A": definition},
            }
        },
        {
            "codes": make_code(
                'Schema.String.check(Schema.isMinLength(1).annotate({ "expected": "a value with a length of at least 1" })).check(Schema.isMaxCodePoints(2).annotate({ "expected": "a string with at most 2 code points" }))',
                "string",
            )
        },
    )


def test_from_json_schema_document_all_of_preserves_annotations_on_array_intersections() -> None:
    "fromJsonSchemaDocument / allOf / preserves annotations on array intersections"
    assert_from_json_schema(
        {"schema": {"type": "array", "allOf": [{"description": "a"}]}},
        {
            "codes": make_code(
                'Schema.Array(Schema.Json.annotate({ "expected": "JSON value" })).annotate({ "description": "a" })',
                "ReadonlyArray<Schema.Json>",
            )
        },
    )


def test_from_json_schema_document_all_of_preserves_annotations_on_object_intersections() -> None:
    "fromJsonSchemaDocument / allOf / preserves annotations on object intersections"
    assert_from_json_schema(
        {
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "allOf": [{"description": "a"}],
            }
        },
        {
            "codes": make_code(
                'Schema.Record(Schema.String, Schema.Never).annotate({ "description": "a" })',
                "{ readonly [x: string]: never }",
            )
        },
    )


def test_from_json_schema_document_all_of_returns_never_when_a_union_has_no_compatible_member() -> (
    None
):
    "fromJsonSchemaDocument / allOf / returns Never when a union has no compatible member"
    assert_from_json_schema(
        {
            "schema": {
                "type": "string",
                "allOf": [{"anyOf": [{"type": "number"}, {"type": "boolean"}]}],
            }
        },
        {"codes": make_code("Schema.Never", "never")},
    )


def assert_literal_refinement(refinement: Any, valid: Any, invalid: Any) -> Any:
    for literal in [valid, invalid]:
        for all_of in [[refinement, {"const": literal}], [{"const": literal}, refinement]]:
            value = json.dumps(literal)
            assert_from_json_schema(
                {"schema": {"allOf": all_of}},
                {
                    "codes": (
                        make_code("Schema.Literal(" + str(value) + ")", value)
                        if literal == valid
                        else make_code("Schema.Never", "never")
                    )
                },
            )


def test_from_json_schema_document_all_of_literal_refinements_min_length() -> None:
    "fromJsonSchemaDocument / allOf / literal refinements / minLength"
    assert_literal_refinement({"type": "string", "minLength": 2}, "ab", "a")


def test_from_json_schema_document_all_of_literal_refinements_max_length() -> None:
    "fromJsonSchemaDocument / allOf / literal refinements / maxLength"
    assert_literal_refinement({"type": "string", "maxLength": 1}, "a", "ab")


def test_from_json_schema_document_all_of_literal_refinements_pattern() -> None:
    "fromJsonSchemaDocument / allOf / literal refinements / pattern"
    assert_literal_refinement({"type": "string", "pattern": "^a+$"}, "aa", "ab")


def test_from_json_schema_document_all_of_literal_refinements_integer() -> None:
    "fromJsonSchemaDocument / allOf / literal refinements / integer"
    assert_literal_refinement({"type": "integer"}, 1, 1.5)


def test_from_json_schema_document_all_of_literal_refinements_multiple_of() -> None:
    "fromJsonSchemaDocument / allOf / literal refinements / multipleOf"
    assert_literal_refinement({"type": "number", "multipleOf": 0.1}, 0.3, 0.31)


def test_from_json_schema_document_all_of_literal_refinements_multiple_of_beyond_the_to_fixed_precision_limit() -> (
    None
):
    "fromJsonSchemaDocument / allOf / literal refinements / multipleOf beyond the toFixed precision limit"
    assert_literal_refinement({"type": "number", "multipleOf": float("1e-101")}, 0, float("5e-102"))


def test_from_json_schema_document_all_of_literal_refinements_multiple_of_with_a_large_scientific_operand() -> (
    None
):
    "fromJsonSchemaDocument / allOf / literal refinements / multipleOf with a large scientific operand"
    assert_literal_refinement({"type": "number", "multipleOf": 2}, float("1e21"), 1)


def test_from_json_schema_document_all_of_literal_refinements_multiple_of_with_a_nonzero_subnormal_remainder() -> (
    None
):
    "fromJsonSchemaDocument / allOf / literal refinements / multipleOf with a nonzero subnormal remainder"
    assert_literal_refinement(
        {"type": "number", "multipleOf": float("1e-323")}, 0, float("1.042e-321")
    )


def test_from_json_schema_document_all_of_literal_refinements_minimum() -> None:
    "fromJsonSchemaDocument / allOf / literal refinements / minimum"
    assert_literal_refinement({"type": "number", "minimum": 1}, 1, 0)


def test_from_json_schema_document_all_of_literal_refinements_maximum() -> None:
    "fromJsonSchemaDocument / allOf / literal refinements / maximum"
    assert_literal_refinement({"type": "number", "maximum": 1}, 1, 2)


def test_from_json_schema_document_all_of_literal_refinements_exclusive_minimum() -> None:
    "fromJsonSchemaDocument / allOf / literal refinements / exclusiveMinimum"
    assert_literal_refinement({"type": "number", "exclusiveMinimum": 1}, 2, 1)


def test_from_json_schema_document_all_of_literal_refinements_exclusive_maximum() -> None:
    "fromJsonSchemaDocument / allOf / literal refinements / exclusiveMaximum"
    assert_literal_refinement({"type": "number", "exclusiveMaximum": 1}, 0, 1)


def test_from_json_schema_document_all_of_literal_refinements_filter_group() -> None:
    "fromJsonSchemaDocument / allOf / literal refinements / filter group"
    assert_literal_refinement(
        {"type": "number", "allOf": [{"minimum": 1, "maximum": 2, "description": "range"}]}, 2, 0
    )


def test_from_json_schema_document_all_of_literal_refinements_filters_enum_members_when_the_refinement_precedes_the_enum() -> (
    None
):
    "fromJsonSchemaDocument / allOf / literal refinements / filters enum members when the refinement precedes the enum"
    assert_from_json_schema(
        {"schema": {"type": "string", "minLength": 2, "allOf": [{"enum": ["a", "ab"]}]}},
        {"codes": make_code('Schema.Literal("ab")', '"ab"')},
    )


def test_from_json_schema_document_all_of_literal_refinements_filters_enum_members_when_the_enum_precedes_the_refinement() -> (
    None
):
    "fromJsonSchemaDocument / allOf / literal refinements / filters enum members when the enum precedes the refinement"
    assert_from_json_schema(
        {"schema": {"enum": ["a", "ab"], "allOf": [{"type": "string", "minLength": 2}]}},
        {"codes": make_code('Schema.Literal("ab")', '"ab"')},
    )


def test_from_json_schema_document_all_of_no_type() -> None:
    "fromJsonSchemaDocument / allOf / no type"
    assert_from_json_schema(
        {"schema": {"allOf": [{"type": "string"}]}}, {"codes": make_code("Schema.String", "string")}
    )


def test_from_json_schema_document_all_of_type_string_min_length() -> None:
    "fromJsonSchemaDocument / allOf / type: string / & minLength"
    assert_from_json_schema(
        {"schema": {"type": "string", "allOf": [{"minLength": 1}]}},
        {
            "codes": make_code(
                'Schema.String.check(Schema.isMinLength(1).annotate({ "expected": "a value with a length of at least 1" }))',
                "string",
            )
        },
    )


def test_from_json_schema_document_all_of_type_string_min_length_description() -> None:
    "fromJsonSchemaDocument / allOf / type: string / & minLength + description"
    assert_from_json_schema(
        {"schema": {"type": "string", "allOf": [{"minLength": 1, "description": "b"}]}},
        {
            "codes": make_code(
                'Schema.String.check(Schema.isMinLength(1).annotate({ "expected": "a value with a length of at least 1", "description": "b" }))',
                "string",
            )
        },
    )


def test_from_json_schema_document_all_of_type_string_description_min_length() -> None:
    "fromJsonSchemaDocument / allOf / type: string / description & minLength"
    assert_from_json_schema(
        {"schema": {"type": "string", "description": "a", "allOf": [{"minLength": 1}]}},
        {
            "codes": make_code(
                'Schema.String.annotate({ "description": "a" }).check(Schema.isMinLength(1).annotate({ "expected": "a value with a length of at least 1" }))',
                "string",
            )
        },
    )


def test_from_json_schema_document_all_of_type_string_description_description() -> None:
    "fromJsonSchemaDocument / allOf / type: string / description & description"
    assert_from_json_schema(
        {"schema": {"type": "string", "description": "a", "allOf": [{"description": "b"}]}},
        {"codes": make_code('Schema.String.annotate({ "description": "b" })', "string")},
    )


def test_from_json_schema_document_all_of_type_string_description_min_length_description() -> None:
    "fromJsonSchemaDocument / allOf / type: string / description & minLength + description"
    assert_from_json_schema(
        {
            "schema": {
                "type": "string",
                "description": "a",
                "allOf": [{"minLength": 1, "description": "b"}],
            }
        },
        {
            "codes": make_code(
                'Schema.String.annotate({ "description": "a" }).check(Schema.isMinLength(1).annotate({ "expected": "a value with a length of at least 1", "description": "b" }))',
                "string",
            )
        },
    )


def test_from_json_schema_document_all_of_type_string_max_length_min_length() -> None:
    "fromJsonSchemaDocument / allOf / type: string / maxLength & minLength"
    assert_from_json_schema(
        {"schema": {"type": "string", "maxLength": 2, "allOf": [{"minLength": 1}]}},
        {
            "codes": make_code(
                'Schema.String.check(Schema.isMaxCodePoints(2).annotate({ "expected": "a string with at most 2 code points" })).check(Schema.isMinLength(1).annotate({ "expected": "a value with a length of at least 1" }))',
                "string",
            )
        },
    )


def test_from_json_schema_document_all_of_type_string_description_max_length_min_length() -> None:
    "fromJsonSchemaDocument / allOf / type: string / description + maxLength & minLength"
    assert_from_json_schema(
        {
            "schema": {
                "type": "string",
                "description": "a",
                "maxLength": 2,
                "allOf": [{"minLength": 1}],
            }
        },
        {
            "codes": make_code(
                'Schema.String.annotate({ "description": "a" }).check(Schema.isMaxCodePoints(2).annotate({ "expected": "a string with at most 2 code points" })).check(Schema.isMinLength(1).annotate({ "expected": "a value with a length of at least 1" }))',
                "string",
            )
        },
    )


def test_from_json_schema_document_all_of_type_string_description_max_length_min_length_description() -> (
    None
):
    "fromJsonSchemaDocument / allOf / type: string / description + maxLength & minLength + description"
    assert_from_json_schema(
        {
            "schema": {
                "type": "string",
                "description": "a",
                "maxLength": 2,
                "allOf": [{"minLength": 1, "description": "b"}],
            }
        },
        {
            "codes": make_code(
                'Schema.String.annotate({ "description": "a" }).check(Schema.isMaxCodePoints(2).annotate({ "expected": "a string with at most 2 code points" })).check(Schema.isMinLength(1).annotate({ "expected": "a value with a length of at least 1", "description": "b" }))',
                "string",
            )
        },
    )


def test_from_json_schema_document_all_of_type_string_min_length_max_length() -> None:
    "fromJsonSchemaDocument / allOf / type: string / & minLength + maxLength"
    assert_from_json_schema(
        {"schema": {"type": "string", "allOf": [{"minLength": 1, "maxLength": 2}]}},
        {
            "codes": make_code(
                'Schema.String.check(Schema.isMinLength(1).annotate({ "expected": "a value with a length of at least 1" })).check(Schema.isMaxCodePoints(2).annotate({ "expected": "a string with at most 2 code points" }))',
                "string",
            )
        },
    )


def test_from_json_schema_document_all_of_type_string_min_length_max_length_description() -> None:
    "fromJsonSchemaDocument / allOf / type: string / & minLength + maxLength + description"
    assert_from_json_schema(
        {
            "schema": {
                "type": "string",
                "allOf": [{"minLength": 1, "maxLength": 2, "description": "b"}],
            }
        },
        {
            "codes": make_code(
                'Schema.String.check(Schema.makeFilterGroup([Schema.isMinLength(1).annotate({ "expected": "a value with a length of at least 1" }), Schema.isMaxCodePoints(2).annotate({ "expected": "a string with at most 2 code points" })]).annotate({ "description": "b" }))',
                "string",
            )
        },
    )


def test_from_json_schema_document_all_of_type_string_min_length_max_length_description_2() -> None:
    "fromJsonSchemaDocument / allOf / type: string / & (minLength & maxLength + description)"
    assert_from_json_schema(
        {
            "schema": {
                "type": "string",
                "allOf": [{"minLength": 1, "allOf": [{"maxLength": 2, "description": "c"}]}],
            }
        },
        {
            "codes": make_code(
                'Schema.String.check(Schema.isMinLength(1).annotate({ "expected": "a value with a length of at least 1" })).check(Schema.isMaxCodePoints(2).annotate({ "expected": "a string with at most 2 code points", "description": "c" }))',
                "string",
            )
        },
    )


def test_from_json_schema_document_all_of_type_string_min_length_description_max_length_description() -> (
    None
):
    "fromJsonSchemaDocument / allOf / type: string / & (minLength + description & maxLength + description)"
    assert_from_json_schema(
        {
            "schema": {
                "type": "string",
                "allOf": [
                    {
                        "minLength": 1,
                        "description": "b",
                        "allOf": [{"maxLength": 2, "description": "c"}],
                    }
                ],
            }
        },
        {
            "codes": make_code(
                'Schema.String.check(Schema.makeFilterGroup([Schema.isMinLength(1).annotate({ "expected": "a value with a length of at least 1" }), Schema.isMaxCodePoints(2).annotate({ "expected": "a string with at most 2 code points", "description": "c" })]).annotate({ "description": "b" }))',
                "string",
            )
        },
    )


def test_from_json_schema_document_all_of_type_string_intersects_with_a_single_member_string_enum() -> (
    None
):
    "fromJsonSchemaDocument / allOf / type: string / intersects with a single-member string enum"
    assert_from_json_schema(
        {"schema": {"type": "string", "allOf": [{"enum": ["a"]}]}},
        {"codes": make_code('Schema.Literal("a")', '"a"')},
    )
    assert_from_json_schema(
        {
            "schema": {
                "type": "string",
                "description": "a",
                "allOf": [{"enum": ["a"], "description": "b"}],
            }
        },
        {"codes": make_code('Schema.Literal("a").annotate({ "description": "b" })', '"a"')},
    )


def test_from_json_schema_document_all_of_type_string_intersects_with_a_multi_member_string_enum() -> (
    None
):
    "fromJsonSchemaDocument / allOf / type: string / intersects with a multi-member string enum"
    assert_from_json_schema(
        {"schema": {"type": "string", "allOf": [{"enum": ["a", "b"]}]}},
        {"codes": make_code('Schema.Literals(["a", "b"])', '"a" | "b"')},
    )


def test_from_json_schema_document_all_of_type_string_mixed_enum() -> None:
    "fromJsonSchemaDocument / allOf / type: string / & mixed enum"
    assert_from_json_schema(
        {"schema": {"type": "string", "allOf": [{"enum": ["a", 1]}]}},
        {"codes": make_code('Schema.Literal("a")', '"a"')},
    )


def test_from_json_schema_document_all_of_type_number_number_number_preserves_annotations_after_removing_duplicate_checks() -> (
    None
):
    "fromJsonSchemaDocument / allOf / type: number / number & number preserves annotations after removing duplicate checks"
    assert_from_json_schema(
        {"schema": {"type": "number", "allOf": [{"type": "number", "description": "b"}]}},
        {
            "codes": make_code(
                'Schema.Number.annotate({ "description": "b" }).check(Schema.isFinite().annotate({ "expected": "a finite number" }))',
                "number",
            )
        },
    )


def test_from_json_schema_document_all_of_type_number_number_integer() -> None:
    "fromJsonSchemaDocument / allOf / type: number / number & integer"
    assert_from_json_schema(
        {"schema": {"type": "number", "allOf": [{"type": "integer"}]}},
        {
            "codes": make_code(
                'Schema.Finite.check(Schema.isInt().annotate({ "expected": "an integer" }))',
                "number",
            )
        },
    )


def test_from_json_schema_document_all_of_type_number_number_integer_integer() -> None:
    "fromJsonSchemaDocument / allOf / type: number / number & integer & integer"
    assert_from_json_schema(
        {
            "schema": {
                "type": "number",
                "allOf": [{"type": "integer", "minimum": 2}, {"type": "integer", "maximum": 2}],
            }
        },
        {
            "codes": make_code(
                'Schema.Finite.check(Schema.isInt().annotate({ "expected": "an integer" })).check(Schema.isGreaterThanOrEqualTo(2).annotate({ "expected": "a value greater than or equal to 2" })).check(Schema.isLessThanOrEqualTo(2).annotate({ "expected": "a value less than or equal to 2" }))',
                "number",
            )
        },
    )


def test_from_json_schema_document_all_of_type_number_integer_number() -> None:
    "fromJsonSchemaDocument / allOf / type: number / integer & number"
    assert_from_json_schema(
        {"schema": {"type": "integer", "allOf": [{"type": "number"}]}},
        {
            "codes": make_code(
                'Schema.Int.check(Schema.isFinite().annotate({ "expected": "a finite number" }))',
                "number",
            )
        },
    )


def test_from_json_schema_document_all_of_type_number_minimum_description_maximum_description() -> (
    None
):
    "fromJsonSchemaDocument / allOf / type: number / & (minimum + description & maximum + description)"
    assert_from_json_schema(
        {
            "schema": {
                "type": "number",
                "allOf": [
                    {
                        "minimum": 1,
                        "description": "b",
                        "allOf": [{"maximum": 2, "description": "c"}],
                    }
                ],
            }
        },
        {
            "codes": make_code(
                'Schema.Finite.check(Schema.makeFilterGroup([Schema.isGreaterThanOrEqualTo(1).annotate({ "expected": "a value greater than or equal to 1" }), Schema.isLessThanOrEqualTo(2).annotate({ "expected": "a value less than or equal to 2", "description": "c" })]).annotate({ "description": "b" }))',
                "number",
            )
        },
    )


def test_from_json_schema_document_all_of_type_number_continues_intersecting_after_an_annotated_filter_group() -> (
    None
):
    "fromJsonSchemaDocument / allOf / type: number / continues intersecting after an annotated filter group"
    assert_from_json_schema(
        {
            "schema": {
                "type": "number",
                "allOf": [
                    {"minimum": 1, "maximum": 2, "description": "range"},
                    {"type": "integer"},
                ],
            }
        },
        {
            "codes": make_code(
                'Schema.Finite.check(Schema.makeFilterGroup([Schema.isGreaterThanOrEqualTo(1).annotate({ "expected": "a value greater than or equal to 1" }), Schema.isLessThanOrEqualTo(2).annotate({ "expected": "a value less than or equal to 2" })]).annotate({ "description": "range" })).check(Schema.isInt().annotate({ "expected": "an integer" }))',
                "number",
            )
        },
    )


def test_from_json_schema_document_all_of_type_number_intersects_with_a_single_member_number_enum() -> (
    None
):
    "fromJsonSchemaDocument / allOf / type: number / intersects with a single-member number enum"
    assert_from_json_schema(
        {"schema": {"type": "number", "allOf": [{"enum": [1]}]}},
        {"codes": make_code("Schema.Literal(1)", "1")},
    )
    assert_from_json_schema(
        {
            "schema": {
                "type": "number",
                "description": "a",
                "allOf": [{"enum": [1], "description": "b"}],
            }
        },
        {"codes": make_code('Schema.Literal(1).annotate({ "description": "b" })', "1")},
    )


def test_from_json_schema_document_all_of_type_number_intersects_with_a_multi_member_number_enum() -> (
    None
):
    "fromJsonSchemaDocument / allOf / type: number / intersects with a multi-member number enum"
    assert_from_json_schema(
        {"schema": {"type": "number", "allOf": [{"enum": [1, 2]}]}},
        {"codes": make_code("Schema.Literals([1, 2])", "1 | 2")},
    )


def test_from_json_schema_document_all_of_type_boolean_boolean_boolean() -> None:
    "fromJsonSchemaDocument / allOf / type: boolean / boolean & boolean"
    assert_from_json_schema(
        {"schema": {"type": "boolean", "allOf": [{"type": "boolean"}]}},
        {"codes": make_code("Schema.Boolean", "boolean")},
    )


def test_from_json_schema_document_all_of_type_boolean_boolean_non_boolean_literal() -> None:
    "fromJsonSchemaDocument / allOf / type: boolean / boolean & non-boolean literal"
    assert_from_json_schema(
        {"schema": {"type": "boolean", "allOf": [{"const": 1}]}},
        {"codes": make_code("Schema.Never", "never")},
    )


def test_from_json_schema_document_all_of_type_boolean_intersects_with_a_single_member_boolean_enum() -> (
    None
):
    "fromJsonSchemaDocument / allOf / type: boolean / intersects with a single-member boolean enum"
    assert_from_json_schema(
        {"schema": {"type": "boolean", "allOf": [{"enum": [True]}]}},
        {"codes": make_code("Schema.Literal(true)", "true")},
    )
    assert_from_json_schema(
        {
            "schema": {
                "type": "boolean",
                "description": "a",
                "allOf": [{"enum": [True], "description": "b"}],
            }
        },
        {"codes": make_code('Schema.Literal(true).annotate({ "description": "b" })', "true")},
    )


def assert_array_all_of(a: Any, b: Any, expected: Any) -> Any:
    for schema, member in [[a, b], [b, a]]:
        assert_from_json_schema({"schema": {**schema, "allOf": [member]}}, expected)


def test_from_json_schema_document_all_of_type_array_unique_items_unique_items() -> None:
    "fromJsonSchemaDocument / allOf / type: array / uniqueItems & uniqueItems"
    assert_from_json_schema(
        {"schema": {"type": "array", "uniqueItems": True, "allOf": [{"uniqueItems": True}]}},
        {
            "codes": make_code(
                'Schema.Array(Schema.Json.annotate({ "expected": "JSON value" })).check(Schema.isUnique().annotate({ "expected": "an array with unique items" }))',
                "ReadonlyArray<Schema.Json>",
            )
        },
    )


def test_from_json_schema_document_all_of_type_array_combines_unequal_open_prefixes() -> None:
    "fromJsonSchemaDocument / allOf / type: array / combines unequal open prefixes"
    assert_array_all_of(
        {
            "type": "array",
            "prefixItems": [{"type": "string"}],
            "minItems": 1,
            "items": {"type": "string"},
        },
        {
            "type": "array",
            "prefixItems": [{"type": "string"}, {"const": "tail"}],
            "minItems": 2,
            "items": {"type": "string"},
        },
        {
            "codes": make_code(
                'Schema.TupleWithRest(Schema.Tuple([Schema.String, Schema.Literal("tail")]), [Schema.String])',
                'readonly [string, "tail", ...Array<string>]',
            )
        },
    )


def test_from_json_schema_document_all_of_type_array_truncates_optional_elements_forbidden_by_a_closed_tuple() -> (
    None
):
    "fromJsonSchemaDocument / allOf / type: array / truncates optional elements forbidden by a closed tuple"
    assert_array_all_of(
        {"type": "array", "prefixItems": [{"type": "string"}], "minItems": 1, "maxItems": 1},
        {
            "type": "array",
            "prefixItems": [{"type": "string"}, {"type": "number"}],
            "minItems": 1,
            "maxItems": 2,
        },
        {"codes": make_code("Schema.Tuple([Schema.String])", "readonly [string]")},
    )


def test_from_json_schema_document_all_of_type_array_returns_never_when_a_closed_tuple_forbids_a_required_element() -> (
    None
):
    "fromJsonSchemaDocument / allOf / type: array / returns Never when a closed tuple forbids a required element"
    assert_array_all_of(
        {"type": "array", "prefixItems": [{"type": "string"}], "minItems": 1, "maxItems": 1},
        {
            "type": "array",
            "prefixItems": [{"type": "string"}, {"type": "number"}],
            "minItems": 2,
            "maxItems": 2,
        },
        {"codes": make_code("Schema.Never", "never")},
    )


def test_from_json_schema_document_all_of_type_array_combines_an_open_rest_with_a_closed_rest() -> (
    None
):
    "fromJsonSchemaDocument / allOf / type: array / combines an open rest with a closed rest"
    assert_array_all_of(
        {
            "type": "array",
            "prefixItems": [{"type": "string"}],
            "minItems": 1,
            "items": {"type": "number"},
        },
        {"type": "array", "prefixItems": [{"type": "string"}], "minItems": 1, "maxItems": 1},
        {"codes": make_code("Schema.Tuple([Schema.String])", "readonly [string]")},
    )


def test_from_json_schema_document_all_of_type_array_closes_the_tuple_when_the_rest_intersection_is_never() -> (
    None
):
    "fromJsonSchemaDocument / allOf / type: array / closes the tuple when the rest intersection is Never"
    assert_array_all_of(
        {
            "type": "array",
            "prefixItems": [{"type": "string"}],
            "minItems": 1,
            "items": {"type": "string"},
        },
        {
            "type": "array",
            "prefixItems": [{"type": "string"}],
            "minItems": 1,
            "items": {"type": "number"},
        },
        {"codes": make_code("Schema.Tuple([Schema.String])", "readonly [string]")},
    )


def test_from_json_schema_document_all_of_type_array_rejects_a_required_literal_that_fails_rest_refinements() -> (
    None
):
    "fromJsonSchemaDocument / allOf / type: array / rejects a required literal that fails rest refinements"
    assert_array_all_of(
        {"type": "array", "minItems": 1, "items": {"const": 0}},
        {
            "type": "array",
            "prefixItems": [{"type": "number", "minimum": 1}],
            "minItems": 1,
            "maxItems": 1,
        },
        {"codes": make_code("Schema.Never", "never")},
    )


def test_from_json_schema_document_all_of_type_array_truncates_an_optional_literal_that_fails_rest_refinements() -> (
    None
):
    "fromJsonSchemaDocument / allOf / type: array / truncates an optional literal that fails rest refinements"
    assert_array_all_of(
        {"type": "array", "items": {"const": 0}},
        {"type": "array", "prefixItems": [{"type": "number", "minimum": 1}], "maxItems": 1},
        {"codes": make_code("Schema.Tuple([])", "readonly []")},
    )


def test_from_json_schema_document_all_of_type_array_preserves_a_literal_that_satisfies_rest_refinements() -> (
    None
):
    "fromJsonSchemaDocument / allOf / type: array / preserves a literal that satisfies rest refinements"
    assert_array_all_of(
        {"type": "array", "minItems": 1, "items": {"const": 2}},
        {
            "type": "array",
            "prefixItems": [{"type": "number", "minimum": 1}],
            "minItems": 1,
            "maxItems": 1,
        },
        {
            "codes": make_code(
                'Schema.Tuple([Schema.Literal(2)]).check(Schema.isMinLength(1).annotate({ "expected": "a value with a length of at least 1" }))',
                "readonly [2]",
            )
        },
    )


def test_from_json_schema_document_all_of_short_circuits_false_intersections_to_never() -> None:
    "fromJsonSchemaDocument / allOf / short-circuits false intersections to Never"
    assert_from_json_schema(
        {"schema": {"allOf": [False, {"type": "string"}]}},
        {"codes": make_code("Schema.Never", "never")},
    )


def test_from_json_schema_document_all_of_returns_never_when_intersecting_array_and_string() -> (
    None
):
    "fromJsonSchemaDocument / allOf / returns Never when intersecting array and string"
    assert_from_json_schema(
        {"schema": {"allOf": [{"type": "array"}, {"type": "string"}]}},
        {"codes": make_code("Schema.Never", "never")},
    )


def test_from_json_schema_document_all_of_returns_never_when_intersecting_object_and_string() -> (
    None
):
    "fromJsonSchemaDocument / allOf / returns Never when intersecting object and string"
    assert_from_json_schema(
        {"schema": {"allOf": [{"type": "object"}, {"type": "string"}]}},
        {"codes": make_code("Schema.Never", "never")},
    )


def test_from_json_schema_document_all_of_returns_never_when_intersecting_null_and_string() -> None:
    "fromJsonSchemaDocument / allOf / returns Never when intersecting null and string"
    assert_from_json_schema(
        {"schema": {"allOf": [{"type": "null"}, {"type": "string"}]}},
        {"codes": make_code("Schema.Never", "never")},
    )


def test_from_json_schema_document_all_of_returns_never_when_intersecting_distinct_literals() -> (
    None
):
    "fromJsonSchemaDocument / allOf / returns Never when intersecting distinct literals"
    assert_from_json_schema(
        {"schema": {"allOf": [{"const": 1}, {"const": 2}]}},
        {"codes": make_code("Schema.Never", "never")},
    )


def test_from_json_schema_document_all_of_preserves_null_when_intersecting_null_types() -> None:
    "fromJsonSchemaDocument / allOf / preserves null when intersecting null types"
    assert_from_json_schema(
        {"schema": {"allOf": [{"type": "null"}, {"type": "null"}]}},
        {"codes": make_code("Schema.Null", "null")},
    )


def test_from_json_schema_document_all_of_preserves_a_literal_when_intersecting_identical_literals() -> (
    None
):
    "fromJsonSchemaDocument / allOf / preserves a literal when intersecting identical literals"
    assert_from_json_schema(
        {"schema": {"allOf": [{"const": 1}, {"const": 1}]}},
        {"codes": make_code("Schema.Literal(1)", "1")},
    )


def test_from_json_schema_document_all_of_preserves_a_matching_literal_after_a_boolean_type() -> (
    None
):
    "fromJsonSchemaDocument / allOf / preserves a matching literal after a boolean type"
    assert_from_json_schema(
        {"schema": {"allOf": [{"type": "boolean"}, {"const": True}]}},
        {"codes": make_code("Schema.Literal(true)", "true")},
    )


def test_from_json_schema_document_all_of_preserves_a_matching_literal_before_a_boolean_type() -> (
    None
):
    "fromJsonSchemaDocument / allOf / preserves a matching literal before a boolean type"
    assert_from_json_schema(
        {"schema": {"allOf": [{"const": True}, {"type": "boolean"}]}},
        {"codes": make_code("Schema.Literal(true)", "true")},
    )


def test_from_json_schema_document_all_of_combines_a_string_with_a_reference() -> None:
    "fromJsonSchemaDocument / allOf / combines a string with a reference"
    definition = {"type": "string", "minLength": 1}
    assert_from_json_schema(
        {
            "schema": {
                "type": "string",
                "allOf": [{"$ref": "#/$defs/A"}],
                "$defs": {"A": definition},
            }
        },
        {
            "codes": make_code(
                'Schema.String.check(Schema.isMinLength(1).annotate({ "expected": "a value with a length of at least 1" }))',
                "string",
            )
        },
    )


def test_from_json_schema_document_all_of_preserves_annotations_on_a_reference_inside_all_of() -> (
    None
):
    "fromJsonSchemaDocument / allOf / preserves annotations on a reference inside allOf"
    definition = {"type": "string", "minLength": 1}
    assert_from_json_schema(
        {
            "schema": {
                "type": "string",
                "allOf": [{"$ref": "#/$defs/A", "description": "annotated"}],
                "$defs": {"A": definition},
            }
        },
        {
            "codes": make_code(
                'Schema.String.annotate({ "description": "annotated" }).check(Schema.isMinLength(1).annotate({ "expected": "a value with a length of at least 1" }))',
                "string",
            )
        },
    )


def test_from_json_schema_document_all_of_preserves_annotations_on_a_root_reference_intersected_with_all_of() -> (
    None
):
    "fromJsonSchemaDocument / allOf / preserves annotations on a root reference intersected with allOf"
    definition = {"type": "string", "minLength": 1}
    assert_from_json_schema(
        {
            "schema": {
                "$ref": "#/$defs/A",
                "description": "annotated",
                "allOf": [{"type": "string"}],
                "$defs": {"A": definition},
            }
        },
        {
            "codes": make_code(
                'Schema.String.annotate({ "description": "annotated" }).check(Schema.isMinLength(1).annotate({ "expected": "a value with a length of at least 1" }))',
                "string",
            )
        },
    )


def test_from_json_schema_document_all_of_preserves_annotations_through_reference_aliases() -> None:
    "fromJsonSchemaDocument / allOf / preserves annotations through reference aliases"
    assert_from_json_schema(
        {
            "schema": {
                "type": "string",
                "allOf": [{"$ref": "#/$defs/A"}],
                "$defs": {
                    "A": {"$ref": "#/$defs/B", "description": "alias"},
                    "B": {"type": "string"},
                },
            }
        },
        {"codes": make_code('Schema.String.annotate({ "description": "alias" })', "string")},
    )


def test_from_json_schema_document_all_of_merges_annotations_on_string_intersections() -> None:
    "fromJsonSchemaDocument / allOf / merges annotations on string intersections"
    assert_from_json_schema(
        {
            "schema": {
                "allOf": [
                    {"type": "string", "contentMediaType": "application/json"},
                    {"type": "string", "contentSchema": {"type": "number"}},
                ]
            }
        },
        {
            "codes": make_code(
                'Schema.String.annotate({ "contentMediaType": "application/json", "contentSchema": { "type": "number" } })',
                "string",
            )
        },
    )


def test_from_json_schema_document_all_of_merges_constraints_on_overlapping_required_properties() -> (
    None
):
    "fromJsonSchemaDocument / allOf / merges constraints on overlapping required properties"
    assert_from_json_schema(
        {
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"a": {"type": "string"}},
                "required": ["a"],
                "allOf": [
                    {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {"a": {"type": "string", "minLength": 2}},
                        "required": ["a"],
                    }
                ],
            }
        },
        {
            "codes": make_code(
                'Schema.Struct({ "a": Schema.String.check(Schema.isMinCodePoints(2).annotate({ "expected": "a string with at least 2 code points" })) })',
                '{ readonly "a": string }',
            )
        },
    )


def test_from_json_schema_document_all_of_preserves_optional_properties_when_intersecting_object_fields() -> (
    None
):
    "fromJsonSchemaDocument / allOf / preserves optional properties when intersecting object fields"
    assert_from_json_schema(
        {
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "properties": {"a": {"type": "string"}},
                "allOf": [
                    {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {"a": {"minLength": 1}},
                    }
                ],
            }
        },
        {
            "codes": make_code(
                'Schema.Struct({ "a": Schema.optionalKey(Schema.String.check(Schema.isMinLength(1).annotate({ "expected": "a value with a length of at least 1" }))) })',
                '{ readonly "a"?: string }',
            )
        },
    )


def test_from_json_schema_document_all_of_keeps_additional_properties_scopes_separate() -> None:
    "fromJsonSchemaDocument / allOf / keeps additionalProperties scopes separate"
    for schema in [
        {
            "type": "object",
            "additionalProperties": False,
            "allOf": [{"properties": {"a": {"type": "string"}}}],
        },
        {
            "type": "object",
            "properties": {"a": {"type": "string"}},
            "allOf": [{"additionalProperties": False}],
        },
    ]:
        assert_from_json_schema(
            {"schema": schema},
            {
                "codes": make_code(
                    'Schema.Struct({ "a": Schema.optionalKey(Schema.Never) })',
                    '{ readonly "a"?: never }',
                )
            },
        )


def test_from_json_schema_document_all_of_does_not_move_sibling_properties_into_a_closed_scope() -> (
    None
):
    "fromJsonSchemaDocument / allOf / does not move sibling properties into a closed scope"
    assert_from_json_schema(
        {
            "schema": {
                "type": "object",
                "properties": {"a": {"type": "string"}},
                "additionalProperties": False,
                "allOf": [{"properties": {"b": {"type": "number"}}}],
            }
        },
        {
            "codes": make_code(
                'Schema.Struct({ "a": Schema.optionalKey(Schema.String), "b": Schema.optionalKey(Schema.Never) })',
                '{ readonly "a"?: string, readonly "b"?: never }',
            )
        },
    )


def test_from_json_schema_document_all_of_rejects_an_object_when_a_required_sibling_property_is_outside_a_closed_scope() -> (
    None
):
    "fromJsonSchemaDocument / allOf / rejects an object when a required sibling property is outside a closed scope"
    assert_from_json_schema(
        {
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "allOf": [{"properties": {"a": {"type": "string"}}, "required": ["a"]}],
            }
        },
        {"codes": make_code("Schema.Never", "never")},
    )


def test_from_json_schema_document_all_of_keeps_object_keyword_scopes_through_references() -> None:
    "fromJsonSchemaDocument / allOf / keeps object keyword scopes through references"
    assert_from_json_schema(
        {
            "schema": {
                "$ref": "#/$defs/Closed",
                "allOf": [{"properties": {"a": {"type": "string"}}}],
                "$defs": {"Closed": {"type": "object", "additionalProperties": False}},
            }
        },
        {
            "codes": make_code(
                'Schema.Struct({ "a": Schema.optionalKey(Schema.Never) })',
                '{ readonly "a"?: never }',
            )
        },
    )


def test_from_json_schema_document_all_of_applies_a_sibling_additional_properties_schema_to_fixed_properties() -> (
    None
):
    "fromJsonSchemaDocument / allOf / applies a sibling additionalProperties schema to fixed properties"
    schema = to_schema_from_json_schema_document(
        from_schema(
            {
                "type": "object",
                "properties": {"a": {"type": "string"}},
                "allOf": [{"additionalProperties": {"type": "boolean"}}],
            }
        )
    )
    assert_code(
        schema,
        {
            "codes": make_code(
                'Schema.StructWithRest(Schema.Struct({ "a": Schema.optionalKey(Schema.Never) }), [Schema.Record(Schema.String, Schema.Boolean)])',
                '{ readonly "a"?: never } & { readonly [x: string]: boolean }',
            )
        },
    )
    assert S.to_json_schema_document(schema).schema == {
        "type": "object",
        "properties": {"a": {"not": {}}},
        "allOf": [{"type": "object", "additionalProperties": {"type": "boolean"}}],
    }


def test_from_json_schema_document_all_of_lowers_open_patterns_over_a_finite_object_domain() -> (
    None
):
    "fromJsonSchemaDocument / allOf / lowers open patterns over a finite object domain"
    assert_from_json_schema(
        {
            "schema": {
                "type": "object",
                "properties": {"a": {"type": "string"}},
                "additionalProperties": False,
                "allOf": [{"patternProperties": {"^a$": {"minLength": 2}}}],
            }
        },
        {
            "codes": make_code(
                'Schema.Struct({ "a": Schema.optionalKey(Schema.String.check(Schema.isMinCodePoints(2).annotate({ "expected": "a string with at least 2 code points" }))) })',
                '{ readonly "a"?: string }',
            )
        },
    )


def test_from_json_schema_document_all_of_rejects_open_pattern_scopes() -> None:
    "fromJsonSchemaDocument / allOf / rejects open pattern scopes"
    for additional in [{}, {"additionalProperties": True}, {"additionalProperties": {}}]:
        schema = {"type": "object", "patternProperties": {"^a": {"type": "number"}}, **additional}
        throws(
            lambda: to_schema_from_json_schema_document(from_schema(schema)),
            'Cannot import open "patternProperties": unmatched keys cannot be typed correctly.\n  at ["schema"]',
        )
        assert_from_json_schema(
            {"schema": schema, "options": {"patterns": "ignore"}},
            {
                "codes": make_code(
                    'Schema.Record(Schema.String, Schema.Json.annotate({ "expected": "JSON value" }))',
                    "{ readonly [x: string]: Schema.Json }",
                )
            },
        )


def test_from_json_schema_document_all_of_rejects_open_patterns_with_fixed_properties() -> None:
    "fromJsonSchemaDocument / allOf / rejects open patterns with fixed properties"
    throws(
        lambda: to_schema_from_json_schema_document(
            from_schema(
                {
                    "type": "object",
                    "properties": {"a": {"type": "string"}},
                    "patternProperties": {"^a$": {"minLength": 2}},
                }
            )
        ),
        'Cannot import open "patternProperties": unmatched keys cannot be typed correctly.\n  at ["schema"]',
    )


def test_from_json_schema_document_all_of_rejects_nested_open_pattern_scopes_with_their_source_paths() -> (
    None
):
    "fromJsonSchemaDocument / allOf / rejects nested open pattern scopes with their source paths"
    open = {"type": "object", "patternProperties": {"^a": {"type": "number"}}}
    cases = [
        [{"type": "array", "items": open}, '["schema"]["items"]'],
        [{"type": "object", "properties": {"values": open}}, '["schema"]["properties"]["values"]'],
        [{"anyOf": [{"type": "string"}, open]}, '["schema"]["anyOf"][1]'],
        [{"$ref": "#/$defs/Values", "$defs": {"Values": open}}, '["definitions"]["Values"]'],
    ]
    for schema, path in cases:
        throws(
            lambda: to_schema_from_json_schema_document(from_schema(schema)),
            'Cannot import open "patternProperties": unmatched keys cannot be typed correctly.\n  at '
            + str(path)
            + "",
        )


def test_from_json_schema_document_all_of_lowers_an_initially_open_pattern_over_a_finite_object_domain() -> (
    None
):
    "fromJsonSchemaDocument / allOf / lowers an initially open pattern over a finite object domain"
    assert_from_json_schema(
        {
            "schema": {
                "type": "object",
                "patternProperties": {"^a$": {"minLength": 2}},
                "allOf": [{"properties": {"a": {"type": "string"}}, "additionalProperties": False}],
            }
        },
        {
            "codes": make_code(
                'Schema.Struct({ "a": Schema.optionalKey(Schema.String.check(Schema.isMinCodePoints(2).annotate({ "expected": "a string with at least 2 code points" }))) })',
                '{ readonly "a"?: string }',
            )
        },
    )


def test_from_json_schema_document_all_of_lowers_a_referenced_open_pattern_over_a_finite_object_domain() -> (
    None
):
    "fromJsonSchemaDocument / allOf / lowers a referenced open pattern over a finite object domain"
    assert_from_json_schema(
        {
            "schema": {
                "type": "object",
                "properties": {"a": {"type": "string"}},
                "additionalProperties": False,
                "allOf": [{"$ref": "#/$defs/Pattern"}],
                "$defs": {
                    "Pattern": {"type": "object", "patternProperties": {"^a$": {"minLength": 2}}}
                },
            }
        },
        {
            "codes": make_code(
                'Schema.Struct({ "a": Schema.optionalKey(Schema.String.check(Schema.isMinCodePoints(2).annotate({ "expected": "a string with at least 2 code points" }))) })',
                '{ readonly "a"?: string }',
            )
        },
    )


def test_from_json_schema_document_all_of_rejects_object_scopes_that_require_pattern_complements() -> (
    None
):
    "fromJsonSchemaDocument / allOf / rejects object scopes that require pattern complements"
    throws(
        lambda: to_schema_from_json_schema_document(
            from_schema(
                {
                    "type": "object",
                    "additionalProperties": False,
                    "patternProperties": {"^a": {"type": "string"}},
                    "allOf": [
                        {
                            "type": "object",
                            "additionalProperties": False,
                            "patternProperties": {"^b": {"type": "number"}},
                        }
                    ],
                }
            )
        ),
        'Cannot import this closed patterned object: only one pattern without properties is supported.\n  at ["schema"]["allOf"][0]',
    )


def test_from_json_schema_document_all_of_preserves_a_closed_pattern_scope_when_intersecting_a_finite_object_domain() -> (
    None
):
    "fromJsonSchemaDocument / allOf / preserves a closed pattern scope when intersecting a finite object domain"
    assert_from_json_schema(
        {
            "schema": {
                "type": "object",
                "properties": {"a": {"type": "number"}, "b": {"type": "number"}},
                "additionalProperties": False,
                "allOf": [
                    {
                        "type": "object",
                        "patternProperties": {"^a": {"type": "number"}},
                        "additionalProperties": False,
                    }
                ],
            }
        },
        {
            "codes": make_code(
                'Schema.Struct({ "a": Schema.optionalKey(Schema.Finite), "b": Schema.optionalKey(Schema.Never) })',
                '{ readonly "a"?: number, readonly "b"?: never }',
            )
        },
    )


def test_from_json_schema_document_all_of_type_object_add_properties() -> None:
    "fromJsonSchemaDocument / allOf / type: object / add properties"
    assert_from_json_schema(
        {
            "schema": {
                "type": "object",
                "additionalProperties": False,
                "allOf": [{"properties": {"a": {"type": "string"}}}],
            }
        },
        {
            "codes": make_code(
                'Schema.Struct({ "a": Schema.optionalKey(Schema.Never) })',
                '{ readonly "a"?: never }',
            )
        },
    )


def test_from_json_schema_document_all_of_type_object_add_additional_properties() -> None:
    "fromJsonSchemaDocument / allOf / type: object / add additionalProperties"
    assert_from_json_schema(
        {"schema": {"type": "object", "allOf": [{"additionalProperties": {"type": "boolean"}}]}},
        {
            "codes": make_code(
                "Schema.Record(Schema.String, Schema.Boolean)", "{ readonly [x: string]: boolean }"
            )
        },
    )


def test_from_json_schema_document_unsupported_validation_keywords_not() -> None:
    "fromJsonSchemaDocument / unsupported validation keywords / not"
    throws(
        lambda: to_schema_from_json_schema_document(
            JS.from_schema_draft_07(
                {"type": "object", "properties": {"value": {"not": {"type": "string"}}}}
            )
        ),
        'Cannot import JSON Schema keyword "not": Effect has no equivalent constraint.\n  at ["schema"]["properties"]["value"]["not"]',
    )


@pytest.mark.parametrize(
    ("keyword", "value"),
    [
        ("$dynamicRef", "#node"),
        ("contains", {"type": "string"}),
        ("dependentRequired", {"a": ["b"]}),
        ("dependentSchemas", {"a": {"required": ["b"]}}),
        ("unevaluatedItems", False),
        ("unevaluatedProperties", False),
    ],
)
def test_unsupported_validation_keywords(keyword: str, value: Any) -> None:
    "fromJsonSchemaDocument / unsupported validation keywords / $dynamicRef, contains, dependentRequired, dependentSchemas, unevaluatedItems, unevaluatedProperties"
    throws(
        lambda: to_schema_from_json_schema_document(JS.from_schema_draft_2020_12({keyword: value})),
        f'Cannot import JSON Schema keyword "{keyword}": Effect has no equivalent constraint.\n  at ["schema"]["{keyword}"]',
    )


@pytest.mark.parametrize("branch", ["then", "else"])
def test_unsupported_validation_keywords_if_branch(branch: str) -> None:
    "fromJsonSchemaDocument / unsupported validation keywords / if/then, if/else"
    throws(
        lambda: to_schema_from_json_schema_document(
            JS.from_schema_draft_2020_12({"if": {"type": "string"}, branch: False})
        ),
        'Cannot import JSON Schema keyword "if": Effect has no equivalent constraint.\n  at ["schema"]["if"]',
    )


def test_from_json_schema_document_unsupported_validation_keywords_ignores_inactive_conditional_and_contains_cardinality_keywords() -> (
    None
):
    "fromJsonSchemaDocument / unsupported validation keywords / ignores inactive conditional and contains cardinality keywords"
    for keyword, value in [
        ["if", False],
        ["then", False],
        ["else", False],
        ["minContains", 1],
        ["maxContains", 2],
    ]:
        assert_from_json_schema(
            {"schema": {keyword: value}},
            {
                "codes": make_code(
                    'Schema.Json.annotate({ "expected": "JSON value" })', "Schema.Json"
                )
            },
        )


def test_from_json_schema_document_unsupported_validation_keywords_ignores_custom_keywords() -> (
    None
):
    "fromJsonSchemaDocument / unsupported validation keywords / ignores custom keywords"
    assert_from_json_schema(
        {"schema": {"custom": False}},
        {"codes": make_code('Schema.Json.annotate({ "expected": "JSON value" })', "Schema.Json")},
    )


def test_from_json_schema_document_options_patterns_can_reject_previously_exclusive_branches_when_patterns_are_ignored() -> (
    None
):
    "fromJsonSchemaDocument / options / patterns / can reject previously exclusive branches when patterns are ignored"
    document = from_schema(
        {"oneOf": [{"type": "string", "pattern": "^a$"}, {"type": "string", "pattern": "^b$"}]}
    )
    applied = to_schema_from_json_schema_document(document, {"patterns": "apply"})
    ignored = to_schema_from_json_schema_document(document, {"patterns": "ignore"})
    for input in ["a", "b"]:
        assert S.is_(applied)(input)
        assert not S.is_(ignored)(input)


def test_from_json_schema_document_options_patterns_rejects_patterns_by_default() -> None:
    "fromJsonSchemaDocument / options / patterns / rejects patterns by default"
    for schema, path in [
        [{"type": "string", "pattern": "^a+$"}, '["schema"]["pattern"]'],
        [
            {"type": "object", "patternProperties": {"^a+$": {"type": "string"}}},
            '["schema"]["patternProperties"]["^a+$"]',
        ],
        [
            {"type": "object", "propertyNames": {"pattern": "^a+$"}},
            '["schema"]["propertyNames"]["pattern"]',
        ],
    ]:
        throws(
            lambda: R.from_json_schema_document(from_schema(schema)),
            'Patterns may block validation and are disabled. Use patterns: "apply" for trusted schemas or "ignore" to discard them.\n  at '
            + str(path)
            + "",
        )


def test_from_json_schema_document_options_patterns_applies_patterns_explicitly() -> None:
    "fromJsonSchemaDocument / options / patterns / applies patterns explicitly"
    assert_from_json_schema(
        {"schema": {"type": "string", "pattern": "^a+$"}, "options": {"patterns": "apply"}},
        {
            "codes": make_code(
                'Schema.String.check(Schema.isPattern(new globalThis.RegExp("^a+$", "u")).annotate({ "expected": "a string matching the RegExp ^a+$" }))',
                "string",
            )
        },
    )


def test_from_json_schema_document_options_patterns_applies_patterns_whose_source_is_canonicalized_by_reg_exp() -> (
    None
):
    "fromJsonSchemaDocument / options / patterns / applies patterns whose source is canonicalized by RegExp"
    for pattern, source, matching, non_matching in [
        ["a/b", "a\\/b", "a/b", "ab"],
        ["", "(?:)", "anything", None],
        ["\n", "\\n", "a\nb", "ab"],
        ["\r", "\\r", "a\rb", "ab"],
        [" ", "\\u2028", "a b", "ab"],
        [" ", "\\u2029", "a b", "ab"],
    ]:
        schema = to_schema_from_json_schema_document(
            from_schema({"type": "string", "pattern": pattern})
        )
        representation: Any = R.to_representation(schema).representation
        assert representation.tag == "String"
        if representation.tag == "String":
            assert representation.checks[0].representation.payload == {
                "source": source,
                "flags": "u",
            }
        assert S.is_(schema)(matching)
        if non_matching is not None:
            assert not S.is_(schema)(non_matching)
        assert not S.is_(schema)(123)


def test_from_json_schema_document_options_patterns_ignores_patterns_explicitly() -> None:
    "fromJsonSchemaDocument / options / patterns / ignores patterns explicitly"
    assert_from_json_schema(
        {"schema": {"type": "string", "pattern": "^a+$"}, "options": {"patterns": "ignore"}},
        {"codes": make_code("Schema.String", "string")},
    )
    assert_from_json_schema(
        {"schema": {"type": "string", "pattern": "["}, "options": {"patterns": "ignore"}},
        {"codes": make_code("Schema.String", "string")},
    )


def test_from_json_schema_document_options_patterns_ignores_pattern_property_value_constraints_explicitly() -> (
    None
):
    "fromJsonSchemaDocument / options / patterns / ignores pattern property value constraints explicitly"
    assert_from_json_schema(
        {
            "schema": {
                "type": "object",
                "patternProperties": {"^a+$": {"type": "string"}, "^b+$": {"type": "number"}},
                "additionalProperties": False,
            },
            "options": {"patterns": "ignore"},
        },
        {
            "codes": make_code(
                'Schema.Record(Schema.String, Schema.Json.annotate({ "expected": "JSON value" }))',
                "{ readonly [x: string]: Schema.Json }",
            )
        },
    )
    assert_from_json_schema(
        {
            "schema": {
                "type": "object",
                "patternProperties": {"^a+$": {"type": "string"}},
                "additionalProperties": {"type": "boolean"},
            },
            "options": {"patterns": "ignore"},
        },
        {
            "codes": make_code(
                'Schema.Record(Schema.String, Schema.Json.annotate({ "expected": "JSON value" }))',
                "{ readonly [x: string]: Schema.Json }",
            )
        },
    )


def test_from_json_schema_document_options_on_enter_additional_properties_false_via_on_enter() -> (
    None
):
    "fromJsonSchemaDocument / options / onEnter / additionalProperties false via onEnter"

    def _fn1(js: Any) -> Any:
        if js.get("type") == "object" and js.get("additionalProperties") is None:
            return {**js, "additionalProperties": False}
        return js

    assert_from_json_schema(
        {
            "schema": {
                "type": "object",
                "properties": {"a": {"type": "string"}},
                "required": ["a"],
            },
            "options": {"on_enter": _fn1},
        },
        {"codes": make_code('Schema.Struct({ "a": Schema.String })', '{ readonly "a": string }')},
    )


def test_from_json_schema_document_options_on_enter_strips_annotation_keys_via_on_enter() -> None:
    "fromJsonSchemaDocument / options / onEnter / strips annotation keys via onEnter"

    def _fn2(js: Any) -> Any:
        out = {**js}
        out.pop("examples", None)
        return out

    assert_from_json_schema(
        {
            "schema": {"title": "a", "description": "b", "examples": ["d"]},
            "options": {"on_enter": _fn2},
        },
        {
            "codes": make_code(
                'Schema.Json.annotate({ "expected": "JSON value", "title": "a", "description": "b" })',
                "Schema.Json",
            )
        },
    )


def test_from_json_schema_document_options_on_enter_filters_annotations_by_predicate_via_on_enter() -> (
    None
):
    "fromJsonSchemaDocument / options / onEnter / filters annotations by predicate via onEnter"

    def _fn3(js: Any) -> Any:
        out = {}
        for k, v in js.items():
            if (k == "title" or k == "default") or k == "type":
                out[k] = v
        return out

    assert_from_json_schema(
        {
            "schema": {"title": "a", "description": "b", "examples": ["d"], "default": "c"},
            "options": {"on_enter": _fn3},
        },
        {
            "codes": make_code(
                'Schema.Json.annotate({ "expected": "JSON value", "title": "a", "default": "c" })',
                "Schema.Json",
            )
        },
    )


def test_from_json_schema_document_options_on_enter_default_preserves_all_annotations() -> None:
    "fromJsonSchemaDocument / options / onEnter / default preserves all annotations"
    assert_from_json_schema(
        {"schema": {"title": "a", "description": "b", "default": "c", "examples": ["d"]}},
        {
            "codes": make_code(
                'Schema.Json.annotate({ "expected": "JSON value", "title": "a", "description": "b", "default": "c", "examples": ["d"] })',
                "Schema.Json",
            )
        },
    )
