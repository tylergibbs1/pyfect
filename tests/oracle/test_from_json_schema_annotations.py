"""Port of Effect's ``schema/representation/fromJsonSchemaAnnotations.test.ts``.
Annotation keys are pyfect's (``read_only`` for ``readOnly``). Each test's docstring
is the Effect test title, prefixed by its ``describe`` blocks."""

# ruff: noqa: E501, E712
# pyright: reportUnknownLambdaType=false, reportUnknownArgumentType=false, reportUnknownVariableType=false, reportUnknownMemberType=false
import json
import math
from collections.abc import Callable
from typing import Any

import pytest

from pyfect import json_schema as JS
from pyfect import schema as S
from pyfect.schema import representation as R

options: dict[str, Any] = {"include_annotation_key": lambda key: key.startswith("x-")}


def from_schema(js: Any) -> Any:
    return JS.from_schema_draft_2020_12(js)


def document(dialect: Any, schema: Any, definitions: Any) -> Any:
    return JS.Document(dialect, schema, definitions)


def multi_document(dialect: Any, schemas: Any, definitions: Any) -> Any:
    return JS.MultiDocument(dialect, schemas, definitions)


def from_json_schema(schema: Any, options: Any = None) -> Any:
    return R.from_json_schema_document(document("draft-2020-12", schema, {}), **(options or {}))


def round_trip(schema: Any) -> Any:
    return S.to_json_schema_document(from_json_schema(schema, options), **options).schema


def throws(thunk: Callable[[], object], expected: Any = None) -> None:
    with pytest.raises(Exception) as caught:
        thunk()
    if callable(expected):
        expected(caught.value)
    elif expected is not None:
        assert str(caught.value) == expected


def test_json_schema_import_include_annotation_key_ignores_custom_annotations_by_default_and_leaves_standard_annotations_independent_of_selection() -> (
    None
):
    "JSON Schema import includeAnnotationKey / ignores custom annotations by default and leaves standard annotations independent of selection"
    input = {"type": "string", "title": "Name", "description": "A name", "x-sensitive": True}
    for options in [None, {"include_annotation_key": lambda *_: False}]:
        assert from_json_schema(input, options).ast.annotations == {
            "title": "Name",
            "description": "A name",
        }


def test_json_schema_import_include_annotation_key_retains_selected_json_values_and_skips_non_json_values() -> (
    None
):
    "JSON Schema import includeAnnotationKey / retains selected JSON values and skips non-JSON values"
    cyclic: dict[str, Any] = {}
    cyclic["self"] = cyclic
    metadata = {
        "x-string": "private",
        "x-boolean": False,
        "x-number": 0,
        "x-null": None,
        "x-array": [1, "a", False, None],
        "x-object": {"enabled": True},
    }
    input = {
        k: v
        for k, v in {
            "type": "string",
            **metadata,
            "markdownDescription": "**Private**",
            "x-function": lambda *_: True,
            "x-nan": math.nan,
            "x-infinity": math.inf,
            "x-cycle": cyclic,
        }.items()
        if k not in ("x-undefined",)
    }
    assert from_json_schema(input, options).ast.annotations == metadata
    assert round_trip(input) == {"type": "string", **metadata}
    assert from_json_schema(
        input, {"include_annotation_key": lambda key: key == "markdownDescription"}
    ).ast.annotations == {"markdownDescription": "**Private**"}


def test_json_schema_import_include_annotation_key_excludes_schema_keywords_and_effect_capabilities_before_calling_the_predicate() -> (
    None
):
    "JSON Schema import includeAnnotationKey / excludes schema keywords and Effect capabilities before calling the predicate"
    keys = []

    def _fn1(key: Any) -> Any:
        keys.append(key)
        return True

    schema = from_json_schema(
        {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://example.com/name",
            "$anchor": "Name",
            "$dynamicAnchor": "Name",
            "$vocabulary": {},
            "$comment": "comment",
            "$defs": {},
            "type": "string",
            "minLength": 1,
            "maxLength": 10,
            "allOf": [{"type": "string"}],
            "else": {},
            "minContains": 1,
            "maxContains": 2,
            "definitions": {},
            "dependencies": {},
            "additionalItems": False,
            "description": "name",
            "identifier": "Untrusted",
            "expected": "untrusted",
            "message": "untrusted",
            "messageMissingKey": "untrusted",
            "messageUnexpectedKey": "untrusted",
            "representation": {"id": "untrusted", "payload": None},
            "arbitraryConstraint": {},
            "toJsonSchema": {},
            "toCode": {},
            "toEquivalence": {},
            "toFormatter": {},
            "toCodec": {},
            "toCodecJson": {},
            "toCodecStringTree": {},
            "toCodecIso": {},
            "toCodecArbitrary": {},
            "~identifier": "Untrusted",
            "~structural": True,
            "~sentinels": [],
            "~constructor": {},
            "x-sensitive": True,
        },
        {"include_annotation_key": _fn1},
    )
    assert keys == ["x-sensitive"]
    assert schema.ast.annotations == {"description": "name", "x-sensitive": True}
    is_ = S.is_(schema)
    assert is_("Alice")
    assert not is_("")
    assert not is_(1)


def test_json_schema_import_include_annotation_key_handles_own_proto_metadata_without_changing_prototypes_and_ignores_inherited_keys() -> (
    None
):
    "JSON Schema import includeAnnotationKey / handles own __proto__ metadata without changing prototypes and ignores inherited keys"
    input = {"type": "string", **json.loads('{"__proto__":{"sensitive":true}}')}
    schema = from_json_schema(input, {"include_annotation_key": lambda *_: True})
    assert schema.ast.annotations == json.loads('{"__proto__":{"sensitive":true}}')
    output = S.to_json_schema_document(schema, include_annotation_key=lambda *_: True).schema
    assert output == json.loads('{"type":"string","__proto__":{"sensitive":true}}')


def test_json_schema_import_include_annotation_key_selects_from_the_on_enter_result_and_treats_metadata_values_as_opaque() -> (
    None
):
    "JSON Schema import includeAnnotationKey / selects from the onEnter result and treats metadata values as opaque"
    visited = []
    metadata = {"type": "number", "$ref": "#/$defs/Missing", "x-nested": True}

    def _fn2(schema: Any) -> Any:
        visited.append(schema)
        return {"type": schema.get("type"), "x-after": metadata}

    schema = from_json_schema({"type": "string", "x-before": True}, {**options, "on_enter": _fn2})
    assert len(visited) == 1
    assert schema.ast.annotations == {"x-after": metadata}


def test_json_schema_import_include_annotation_key_propagates_predicate_exceptions_unchanged() -> (
    None
):
    "JSON Schema import includeAnnotationKey / propagates predicate exceptions unchanged"
    cause = Exception("annotation selection failed")

    def _fn3(*_: Any) -> Any:
        raise cause

    def _fn4(error: Any) -> Any:
        assert error == cause

    throws(
        lambda: from_json_schema(
            {"type": "string", "x-sensitive": True}, {"include_annotation_key": _fn3}
        ),
        _fn4,
    )


def test_json_schema_import_include_annotation_key_keeps_metadata_at_nested_property_item_and_union_member_locations() -> (
    None
):
    "JSON Schema import includeAnnotationKey / keeps metadata at nested property, item, and union member locations"
    input = {
        "type": "object",
        "properties": {
            "emails": {
                "type": "array",
                "items": {
                    "anyOf": [
                        {"type": "string", "x-sensitive": True},
                        {"type": "null", "x-empty": True},
                    ]
                },
                "x-collection": True,
            }
        },
        "required": ["emails"],
        "additionalProperties": False,
        "x-record": True,
    }
    assert round_trip(input) == {**input, "additionalProperties": True}


def test_json_schema_import_include_annotation_key_retains_custom_metadata_when_constraints_simplify_to_literals_in_either_order() -> (
    None
):
    "JSON Schema import includeAnnotationKey / retains custom metadata when constraints simplify to literals in either order"
    constraint = {"type": "string", "minLength": 1, "x-sensitive": True}
    literal = {"const": "hello"}
    for all_of in [[constraint, literal], [literal, constraint]]:
        assert round_trip({"type": "string", "allOf": all_of}) == {
            "type": "string",
            "enum": ["hello"],
            "x-sensitive": True,
        }


def test_json_schema_import_include_annotation_key_keeps_custom_metadata_on_the_value_while_preserving_standard_check_annotations() -> (
    None
):
    "JSON Schema import includeAnnotationKey / keeps custom metadata on the value while preserving standard check annotations"
    schema = from_json_schema(
        {
            "type": "string",
            "x-source": "outer",
            "allOf": [
                {
                    "type": "string",
                    "minLength": 1,
                    "description": "nonempty",
                    "x-source": "inner",
                    "x-sensitive": True,
                }
            ],
        },
        options,
    )
    assert schema.ast.annotations == {"x-source": "inner", "x-sensitive": True}
    assert schema.ast.checks[0].annotations["description"] == "nonempty"
    assert schema.ast.checks[0].annotations.get("x-sensitive") is None


def test_json_schema_import_include_annotation_key_retains_metadata_through_deduplicated_checks_and_uses_the_existing_merge_precedence() -> (
    None
):
    "JSON Schema import includeAnnotationKey / retains metadata through deduplicated checks and uses the existing merge precedence"
    assert round_trip(
        {
            "type": "number",
            "allOf": [
                {"type": "integer", "minimum": 0, "x-source": "first", "x-first": True},
                {"type": "integer", "maximum": 10, "x-source": "second", "x-second": True},
                {"const": 3},
            ],
        }
    ) == {"type": "number", "enum": [3], "x-source": "second", "x-first": True, "x-second": True}


def test_json_schema_import_include_annotation_key_preserves_metadata_in_schema_dependencies_of_nested_check_groups() -> (
    None
):
    "JSON Schema import includeAnnotationKey / preserves metadata in schema dependencies of nested check groups"
    assert round_trip(
        {
            "type": "object",
            "allOf": [
                {
                    "minProperties": 1,
                    "propertyNames": {"minLength": 1, "x-sensitive": True},
                    "description": "Named object",
                    "allOf": [{"maxProperties": 2, "description": "Small object"}],
                }
            ],
        }
    ) == {
        "type": "object",
        "allOf": [
            {
                "allOf": [
                    {"minProperties": 1},
                    {"propertyNames": {"type": "string", "minLength": 1, "x-sensitive": True}},
                    {"maxProperties": 2, "description": "Small object"},
                ],
                "description": "Named object",
            }
        ],
    }


def test_json_schema_import_include_annotation_key_merges_metadata_on_duplicate_literal_alternatives_that_survive_an_intersection() -> (
    None
):
    "JSON Schema import includeAnnotationKey / merges metadata on duplicate literal alternatives that survive an intersection"
    assert round_trip(
        {
            "allOf": [
                {"enum": ["a", "b"]},
                {
                    "anyOf": [
                        {"const": "a", "x-first": True, "x-source": "first"},
                        {"const": "a", "x-second": True, "x-source": "second"},
                        {"const": "c", "x-discarded": True},
                    ]
                },
            ]
        }
    ) == {"type": "string", "enum": ["a"], "x-first": True, "x-second": True, "x-source": "second"}


def test_json_schema_import_include_annotation_key_discards_metadata_on_eliminated_alternatives_without_lifting_it_to_the_surviving_value() -> (
    None
):
    "JSON Schema import includeAnnotationKey / discards metadata on eliminated alternatives without lifting it to the surviving value"
    assert round_trip(
        {
            "type": "string",
            "anyOf": [{"type": "number", "x-discarded": True}, {"const": "a", "x-surviving": True}],
        }
    ) == {"type": "string", "enum": ["a"], "x-surviving": True}


def test_json_schema_import_include_annotation_key_discards_metadata_on_unreachable_tuple_elements() -> (
    None
):
    "JSON Schema import includeAnnotationKey / discards metadata on unreachable tuple elements"
    assert round_trip(
        {
            "allOf": [
                {
                    "type": "array",
                    "prefixItems": [{"type": "string", "x-discarded": True}],
                    "items": False,
                },
                {"type": "array", "items": False, "x-array": True},
            ]
        }
    ) == {"type": "array", "items": False, "x-array": True}


def test_json_schema_import_include_annotation_key_skips_annotated_references_on_discarded_tuple_elements() -> (
    None
):
    "JSON Schema import includeAnnotationKey / skips annotated references on discarded tuple elements"
    array = {
        "type": "array",
        "prefixItems": [{"$ref": "#/$defs/Unused", "x-sensitive": True}],
        "items": False,
    }
    empty = {"type": "array", "items": False}
    for all_of in [[array, empty], [empty, array]]:
        for import_options in [None, options]:
            schema = R.from_json_schema_document(
                document(
                    "draft-2020-12", {"allOf": all_of}, {"Unused": {"not": {"type": "string"}}}
                ),
                **(import_options or {}),
            )
            assert S.to_json_schema_document(schema, **(options or {})) == document(
                "draft-2020-12", empty, {}
            )


def test_json_schema_import_include_annotation_key_does_not_validate_discarded_annotations_through_another_use_of_the_same_reference() -> (
    None
):
    "JSON Schema import includeAnnotationKey / does not validate discarded annotations through another use of the same reference"
    schemas = R.from_json_schema_multi_document(
        multi_document(
            "draft-2020-12",
            tuple(
                [
                    {
                        "allOf": [
                            {
                                "type": "array",
                                "prefixItems": [{"$ref": "#/$defs/A", "x-sensitive": True}],
                                "items": False,
                            },
                            {"type": "array", "items": False},
                        ]
                    },
                    {"$ref": "#/$defs/A"},
                ]
            ),
            {"A": {"$ref": "#/$defs/A"}},
        ),
        **(options or {}),
    )
    assert S.to_json_schema_document(schemas[0], **(options or {})).schema == {
        "type": "array",
        "items": False,
    }
    assert schemas[1].ast.tag == "Suspend"


def test_json_schema_import_include_annotation_key_preserves_shared_definition_metadata_and_keeps_reference_local_annotations_isolated() -> (
    None
):
    "JSON Schema import includeAnnotationKey / preserves shared definition metadata and keeps reference-local annotations isolated"

    def _fn5(key: Any) -> Any:
        assert key != "x-unused"
        return options["include_annotation_key"](key)

    schemas = R.from_json_schema_multi_document(
        multi_document(
            "draft-2020-12",
            tuple(
                [
                    {"$ref": "#/$defs/Name", "x-local": True},
                    {"$ref": "#/$defs/Name"},
                    {"type": "array", "items": {"$ref": "#/$defs/Name"}, "x-array": True},
                ]
            ),
            {
                "Name": {"type": "string", "x-definition": True},
                "Unused": {"type": "number", "x-unused": True},
            },
        ),
        include_annotation_key=_fn5,
    )
    assert schemas[0].ast.annotations == {"x-local": True}
    assert (
        S.to_json_schema_document(schemas[0], **(options or {})).definitions["Name"]["x-definition"]
        == True
    )
    assert schemas[1].ast.annotations == {"identifier": "Name", "x-definition": True}
    assert schemas[2].ast.annotations == {"x-array": True}
    assert (
        S.to_json_schema_document(schemas[2], **(options or {})).definitions["Name"]["x-definition"]
        == True
    )
