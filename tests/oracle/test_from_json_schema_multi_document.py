"""Port of Effect's ``schema/representation/fromJsonSchemaMultiDocument.test.ts``,
its expected code strings unchanged (``_effect_code``). Each test's docstring is the
Effect test title, prefixed by its ``describe`` blocks."""

# ruff: noqa: E501
# pyright: reportUnknownLambdaType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportUnknownMemberType=false
from collections.abc import Callable
from typing import Any

import pytest

from pyfect import json_schema as JS
from pyfect.schema import representation as R
from pyfect.testing import SchemaAsserts

from ._effect_code import effect_code

make_code = R.make_code


def from_schema(js: Any) -> Any:
    return JS.from_schema_draft_2020_12(js)


def document(dialect: Any, schema: Any, definitions: Any) -> Any:
    return JS.Document(dialect, schema, definitions)


def multi_document(dialect: Any, schemas: Any, definitions: Any) -> Any:
    return JS.MultiDocument(dialect, schemas, definitions)


def assert_code(schemas: Any, expected: Any) -> None:
    assert effect_code(R.to_representations(tuple(schemas))) == {
        "codes": expected["codes"],
        "references": {
            "nonRecursives": expected.get("references", {}).get("nonRecursives", []),
            "recursives": expected.get("references", {}).get("recursives", {}),
        },
    }


def throws(thunk: Callable[[], object], expected: Any = None) -> None:
    with pytest.raises(Exception) as caught:
        thunk()
    if callable(expected):
        expected(caught.value)
    elif expected is not None:
        assert str(caught.value) == expected


def test_schema_representation_from_json_schema_multi_document_rejects_open_pattern_scopes_in_roots_and_shared_definitions() -> (
    None
):
    "SchemaRepresentation.fromJsonSchemaMultiDocument / rejects open pattern scopes in roots and shared definitions"
    open = {"type": "object", "patternProperties": {"^a": {"type": "number"}}}
    throws(
        lambda: R.from_json_schema_multi_document(
            multi_document(
                "draft-2020-12", tuple([{"type": "string"}, {"type": "array", "items": open}]), {}
            ),
            patterns="apply",
        ),
        'Cannot import open "patternProperties": unmatched keys cannot be typed correctly.\n  at ["schemas"][1]["items"]',
    )
    throws(
        lambda: R.from_json_schema_multi_document(
            multi_document(
                "draft-2020-12",
                tuple(
                    [
                        {"$ref": "#/$defs/Values"},
                        {"type": "array", "items": {"$ref": "#/$defs/Values"}},
                    ]
                ),
                {"Values": open},
            ),
            patterns="apply",
        ),
        'Cannot import open "patternProperties": unmatched keys cannot be typed correctly.\n  at ["definitions"]["Values"]',
    )


def test_schema_representation_from_json_schema_multi_document_imports_closed_patterned_records_through_shared_definitions() -> (
    None
):
    "SchemaRepresentation.fromJsonSchemaMultiDocument / imports closed patterned Records through shared definitions"
    schemas = R.from_json_schema_multi_document(
        multi_document(
            "draft-2020-12",
            tuple(
                [{"$ref": "#/$defs/Values"}, {"type": "array", "items": {"$ref": "#/$defs/Values"}}]
            ),
            {
                "Values": {
                    "type": "object",
                    "patternProperties": {"^a": {"type": "number"}},
                    "additionalProperties": False,
                }
            },
        ),
        patterns="apply",
    )
    asserts = SchemaAsserts(schemas[0])
    decoding = asserts.decoding()
    decoding.succeed({"a": 1, "z": True}, {"a": 1})
    decoding.fail({"a": "x"}, 'Expected number\n  at ["a"]')
    asserts.decoding(on_excess_property="error").fail(
        {"z": True}, 'Expected no excess property\n  at ["z"]'
    )
    array_decoding = SchemaAsserts(schemas[1]).decoding()
    array_decoding.succeed([{"a": 1}], ({"a": 1},))
    array_decoding.fail([{"a": "x"}], 'Expected number\n  at [0]["a"]')


def test_schema_representation_from_json_schema_multi_document_imports_never_through_shared_definitions() -> (
    None
):
    "SchemaRepresentation.fromJsonSchemaMultiDocument / imports Never through shared definitions"
    schemas = R.from_json_schema_multi_document(
        multi_document(
            "draft-2020-12",
            tuple(
                [
                    {"type": "object", "properties": {"value": {"$ref": "#/$defs/Impossible"}}},
                    {"$ref": "#/$defs/Impossible"},
                ]
            ),
            {"Impossible": {"not": {}}},
        )
    )
    assert_code(
        schemas,
        {
            "codes": [
                make_code(
                    'Schema.StructWithRest(Schema.Struct({ "value": Schema.optionalKey(Impossible) }), [Schema.Record(Schema.String, Schema.Json.annotate({ "expected": "JSON value" }))])',
                    '{ readonly "value"?: Impossible } & { readonly [x: string]: Schema.Json }',
                ),
                make_code("Impossible", "Impossible"),
            ],
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


def test_schema_representation_from_json_schema_multi_document_keeps_resource_scope_separate_for_each_root() -> (
    None
):
    "SchemaRepresentation.fromJsonSchemaMultiDocument / keeps resource scope separate for each root"
    schemas = R.from_json_schema_multi_document(
        multi_document(
            "draft-2020-12",
            tuple(
                [
                    {"type": "object", "properties": {"child": {"$id": "child", "type": "number"}}},
                    {"$id": "https://example.com/root", "$ref": "#/$defs/X"},
                ]
            ),
            {"X": {"type": "string"}},
        )
    )
    assert_code(
        schemas,
        {
            "codes": [
                make_code(
                    'Schema.StructWithRest(Schema.Struct({ "child": Schema.optionalKey(Schema.Finite) }), [Schema.Record(Schema.String, Schema.Json.annotate({ "expected": "JSON value" }))])',
                    '{ readonly "child"?: number } & { readonly [x: string]: Schema.Json }',
                ),
                make_code("X", "X"),
            ],
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


def test_schema_representation_from_json_schema_multi_document_rejects_a_reference_in_a_nested_resource_with_its_multi_root_path() -> (
    None
):
    "SchemaRepresentation.fromJsonSchemaMultiDocument / rejects a reference in a nested resource with its multi-root path"
    throws(
        lambda: R.from_json_schema_multi_document(
            multi_document(
                "draft-2020-12",
                tuple(
                    [
                        {"type": "string"},
                        {"type": "array", "items": {"$id": "child", "$ref": "#/$defs/X"}},
                    ]
                ),
                {"X": {"type": "string"}},
            )
        ),
        'Cannot resolve $ref under a nested "$id". Resolve or flatten it first.\n  at ["schemas"][1]["items"]["$ref"]',
    )


def test_schema_representation_from_json_schema_multi_document_propagates_the_pattern_policy_through_reachable_definitions() -> (
    None
):
    "SchemaRepresentation.fromJsonSchemaMultiDocument / propagates the pattern policy through reachable definitions"
    document = multi_document(
        "draft-2020-12",
        tuple([{"$ref": "#/$defs/A"}]),
        {"A": {"type": "string", "pattern": "^a+$"}},
    )
    throws(
        lambda: R.from_json_schema_multi_document(document),
        'Patterns may block validation and are disabled. Use patterns: "apply" for trusted schemas or "ignore" to discard them.\n  at ["definitions"]["A"]["pattern"]',
    )
    schemas = R.from_json_schema_multi_document(document, patterns="apply")
    assert_code(
        schemas,
        {
            "codes": [make_code("A", "A")],
            "references": {
                "nonRecursives": [
                    {
                        "$ref": "A",
                        "code": make_code(
                            'Schema.String.check(Schema.isPattern(new globalThis.RegExp("^a+$", "u")).annotate({ "expected": "a string matching the RegExp ^a+$", "identifier": "A" }))',
                            "string",
                        ),
                    }
                ]
            },
        },
    )


def test_schema_representation_from_json_schema_multi_document_preserves_an_on_enter_exception_by_identity() -> (
    None
):
    "SchemaRepresentation.fromJsonSchemaMultiDocument / preserves an onEnter exception by identity"
    cause = Exception("boom")

    def _fn1(*_: Any) -> Any:
        raise cause

    def _fn2(error: Any) -> Any:
        assert error == cause
        return None

    throws(
        lambda: R.from_json_schema_multi_document(
            multi_document("draft-2020-12", tuple([{"type": "string"}]), {}), on_enter=_fn1
        ),
        _fn2,
    )


def test_schema_representation_from_json_schema_multi_document_preserves_content_schema_as_an_annotation_without_traversing_it() -> (
    None
):
    "SchemaRepresentation.fromJsonSchemaMultiDocument / preserves contentSchema as an annotation without traversing it"
    schemas = R.from_json_schema_multi_document(
        multi_document(
            "draft-2020-12",
            tuple(
                [
                    {
                        "type": "string",
                        "contentMediaType": "application/json",
                        "contentSchema": {"$ref": "#/$defs/Payload"},
                    }
                ]
            ),
            {
                "Payload": {
                    "type": "object",
                    "properties": {"value": {"type": "number"}},
                    "required": ["value"],
                    "additionalProperties": False,
                }
            },
        )
    )
    assert_code(
        schemas,
        {
            "codes": [
                make_code(
                    'Schema.String.annotate({ "contentMediaType": "application/json", "contentSchema": { "$ref": "#/$defs/Payload" } })',
                    "string",
                )
            ]
        },
    )


def test_schema_representation_from_json_schema_multi_document_does_not_import_unreachable_definitions() -> (
    None
):
    "SchemaRepresentation.fromJsonSchemaMultiDocument / does not import unreachable definitions"

    def _fn3(schema: Any) -> Any:
        if schema.get("description") == "unused":
            raise Exception("unreachable")
        return schema

    schemas = R.from_json_schema_multi_document(
        multi_document(
            "draft-2020-12",
            tuple([{"type": "string"}]),
            {"Unused": {"type": "number", "description": "unused"}},
        ),
        on_enter=_fn3,
    )
    assert_code(schemas, {"codes": [make_code("Schema.String", "string")]})


def test_schema_representation_from_json_schema_multi_document_preserves_root_order_and_shares_definitions() -> (
    None
):
    "SchemaRepresentation.fromJsonSchemaMultiDocument / preserves root order and shares definitions"
    schemas = R.from_json_schema_multi_document(
        multi_document(
            "draft-2020-12",
            tuple(
                [
                    {"$ref": "#/$defs/A"},
                    {"$ref": "#/$defs/A", "description": "second"},
                    {"type": "array", "items": {"$ref": "#/$defs/A"}},
                    {"$ref": "#/$defs/A", "description": "fourth"},
                ]
            ),
            {"A": {"type": "string", "minLength": 1}},
        )
    )
    assert_code(
        schemas,
        {
            "codes": [
                make_code("A", "A"),
                make_code(
                    'Schema.suspend((): Schema.Codec<A> => A).annotate({ "description": "second" })',
                    "A",
                ),
                make_code("Schema.Array(A)", "ReadonlyArray<A>"),
                make_code(
                    'Schema.suspend((): Schema.Codec<A> => A).annotate({ "description": "fourth" })',
                    "A",
                ),
            ],
            "references": {
                "nonRecursives": [
                    {
                        "$ref": "A",
                        "code": make_code(
                            'Schema.String.check(Schema.isMinLength(1).annotate({ "expected": "a value with a length of at least 1", "identifier": "A" }))',
                            "string",
                        ),
                    }
                ]
            },
        },
    )


def test_schema_representation_from_json_schema_multi_document_resolves_alias_chains_when_combining_a_reference() -> (
    None
):
    "SchemaRepresentation.fromJsonSchemaMultiDocument / resolves alias chains when combining a reference"
    schemas = R.from_json_schema_multi_document(
        multi_document(
            "draft-2020-12",
            tuple([{"$ref": "#/$defs/A", "description": "root"}]),
            {"A": {"$ref": "#/$defs/B"}, "B": {"$ref": "#/$defs/C"}, "C": {"type": "number"}},
        )
    )
    assert_code(
        schemas,
        {
            "codes": [
                make_code(
                    'Schema.suspend((): Schema.Codec<A> => A).annotate({ "description": "root" })',
                    "A",
                )
            ],
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


def test_schema_representation_from_json_schema_multi_document_tracks_recursive_definitions_independently() -> (
    None
):
    "SchemaRepresentation.fromJsonSchemaMultiDocument / tracks recursive definitions independently"
    schemas = R.from_json_schema_multi_document(
        multi_document(
            "draft-2020-12",
            tuple([{"$ref": "#/$defs/A"}, {"$ref": "#/$defs/B"}]),
            {"A": {"$ref": "#/$defs/A"}, "B": {"$ref": "#/$defs/B"}},
        )
    )
    assert_code(
        schemas,
        {
            "codes": [make_code("A", "A"), make_code("B", "B")],
            "references": {
                "recursives": {
                    "A": make_code(
                        'Schema.suspend((): Schema.Codec<A> => A).annotate({ "identifier": "A" })',
                        "A",
                    ),
                    "B": make_code(
                        'Schema.suspend((): Schema.Codec<B> => B).annotate({ "identifier": "B" })',
                        "B",
                    ),
                }
            },
        },
    )


def test_schema_representation_from_json_schema_multi_document_throws_when_a_reference_that_must_be_resolved_is_missing() -> (
    None
):
    "SchemaRepresentation.fromJsonSchemaMultiDocument / throws when a reference that must be resolved is missing"
    throws(
        lambda: R.from_json_schema_multi_document(
            multi_document(
                "draft-2020-12", tuple([{"$ref": "#/$defs/Missing", "description": "resolve"}]), {}
            )
        ),
        'Missing definition "Missing" for $ref "#/$defs/Missing".\n  at ["schemas"][0]["$ref"]',
    )


def test_schema_representation_from_json_schema_multi_document_throws_when_resolving_a_circular_alias_chain() -> (
    None
):
    "SchemaRepresentation.fromJsonSchemaMultiDocument / throws when resolving a circular alias chain"
    throws(
        lambda: R.from_json_schema_multi_document(
            multi_document(
                "draft-2020-12",
                tuple([{"$ref": "#/$defs/A", "description": "resolve"}]),
                {"A": {"$ref": "#/$defs/B"}, "B": {"$ref": "#/$defs/A"}},
            )
        ),
        'Definition "A" is a circular alias.\n  at ["schemas"][0]["$ref"]',
    )


def test_schema_representation_from_json_schema_multi_document_also_validates_circular_aliases_annotated_through_all_of() -> (
    None
):
    "SchemaRepresentation.fromJsonSchemaMultiDocument / also validates circular aliases annotated through allOf"
    throws(
        lambda: R.from_json_schema_multi_document(
            multi_document(
                "draft-2020-12",
                tuple([{"allOf": [{"$ref": "#/$defs/A"}, {"description": "resolve"}]}]),
                {"A": {"$ref": "#/$defs/B"}, "B": {"$ref": "#/$defs/A"}},
            )
        ),
        'Definition "A" is a circular alias.\n  at ["schemas"][0]["allOf"][0]["$ref"]',
    )
