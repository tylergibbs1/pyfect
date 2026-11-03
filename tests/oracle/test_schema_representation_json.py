"""Ports of Effect's ``schema/representation/toJson.test.ts``,
``fromJson.test.ts``, ``toJsonMultiDocument.test.ts`` and
``fromJsonMultiDocument.test.ts``. Each test's docstring is the Effect
test title, prefixed by its file's ``describe``. The JSON form keeps
Effect's keys; see ``test_schema_representation_to.py`` for the model.

Omitted:
- No such nodes in pyfect (§4: ``Schema.Undefined``, ``Void``, ``Symbol``):
  "fromJson / decodes Undefined", "... Void", "... Symbol", "...
  ObjectKeyword", "... decodes global symbols", "... does not coerce
  strings resembling symbols" (ported without the symbol), "toJson /
  encodes global symbols", "... rejects local symbols", "... rejects local
  symbols used as property names".
- Invalid states the dataclasses cannot hold: "toJson / rejects checks on
  Suspend representations" (``R.Suspend`` has no checks).
- JavaScript object model: "toJson / preserves __proto__ annotations as
  data properties", "... omits a sparse-array annotation atomically", "...
  omits an annotation containing undefined atomically", "... encodes
  annotation accessors", "fromJson / does not invoke toJSON" (a Python
  mapping has none of these), "fromJson / rejects non-JSON roots" (ported
  with a function as the root).
- "toJson / preserves ambiguous property names": ported without the
  symbol names.
- "toJson / prunes nested representation annotations": a union's
  ``anyOf`` mode is the default and is not written (only ``oneOf`` is).
"""

import math
import re
from collections.abc import Callable
from typing import Any, TypedDict, TypeIs

import pytest

from pyfect import schema as S
from pyfect.schema import representation as R


def _always(_: object) -> bool:
    return True


def _is_str(value: object) -> TypeIs[str]:
    return isinstance(value, str)


def _no_code(_: object) -> None:
    return None


def _const(out: Any) -> Callable[[S.CheckContext], Any]:
    def to_json_schema(_: S.CheckContext) -> Any:
        return out

    return to_json_schema


def assert_to_json(representation: R.Representation, json: R.Json) -> None:
    assert R.to_json(R.Document(representation)) == {"representation": json, "references": {}}


def assert_roundtrip(representation: R.Representation, json: R.Json) -> None:
    assert_to_json(representation, json)
    assert R.from_json({"representation": json, "references": {}}) == R.Document(representation)


def string_property(name: Any) -> dict[str, Any]:
    return {
        "name": name,
        "type": {"_tag": "String", "checks": []},
        "isOptional": False,
        "isMutable": False,
    }


def raises(message: str) -> Any:
    return pytest.raises(R.RepresentationError, match=f"^{re.escape(message)}$")


# ------------------------------------------------------------------- toJson


def test_round_trips_a_string_s_content_schema_and_references():
    """SchemaRepresentation.toJson / round trips a string's content schema and references"""
    document = R.Document(
        R.String(content=R.Content("application/json", R.Reference("Content"))),
        {"Content": R.Boolean()},
    )
    json = R.to_json(document)
    assert json == {
        "representation": {
            "_tag": "String",
            "checks": [],
            "content": {
                "mediaType": "application/json",
                "schema": {"_tag": "Reference", "$ref": "Content"},
            },
        },
        "references": {"Content": {"_tag": "Boolean", "checks": []}},
    }
    assert R.from_json(json) == document


def test_round_trips_a_content_media_type_without_a_schema():
    """SchemaRepresentation.toJson / round trips a content media type without a schema"""
    assert_roundtrip(
        R.String(content=R.Content("text/plain")),
        {"_tag": "String", "checks": [], "content": {"mediaType": "text/plain"}},
    )


def test_rejects_invalid_documents():
    """SchemaRepresentation.toJson / rejects invalid documents"""
    with raises('Expected a value with a length of at least 1\n  at ["representation"]["$ref"]'):
        R.to_json(R.Document(R.Reference("")))


def test_requires_representation_when_persisting_a_filter():
    """SchemaRepresentation.toJson / requires representation when persisting a Filter"""
    with raises('Missing key\n  at ["representation"]["checks"][0]["representation"]'):
        R.to_json(R.Document(R.String(checks=(R.Filter(),))))


def test_removes_live_callbacks_and_preserves_json_annotations_from_a_custom_filter():
    """SchemaRepresentation.toJson / removes live callbacks and preserves JSON annotations from a custom filter"""  # noqa: E501
    check = S.make_filter(
        _always,
        description="custom",
        callback=lambda: "live",
        representation={
            "id": "acme/schema/custom",
            "payload": {"minimum": 1},
            "schemas": (S.Number.ast,),
        },
        to_code=_no_code,
        to_json_schema=_const({"minLength": 1}),
        arbitrary_constraint={"min_length": 1},
    ).abort()
    assert R.to_json(R.to_representation(S.String.check(check))) == {
        "representation": {
            "_tag": "String",
            "checks": [
                {
                    "_tag": "Filter",
                    "representation": {
                        "id": "acme/schema/custom",
                        "payload": {"minimum": 1},
                        "schemas": [{"_tag": "Number", "checks": []}],
                    },
                    "annotations": {
                        "description": "custom",
                        "arbitrary_constraint": {"min_length": 1},
                    },
                    "aborted": True,
                }
            ],
        },
        "references": {},
    }


def test_removes_live_callbacks_from_a_custom_declaration():
    """SchemaRepresentation.toJson / removes live callbacks from a custom declaration"""
    schema = S.declare(
        _is_str,
        description="custom",
        representation={"id": "acme/schema/custom", "payload": None},
        to_code=_no_code,
        to_json_schema=_const({"type": "string"}),
    )
    assert R.to_json(R.to_representation(schema)) == {
        "representation": {
            "_tag": "Declaration",
            "representation": {"id": "acme/schema/custom", "payload": None},
            "annotations": {"description": "custom"},
            "typeParameters": [],
            "checks": [],
        },
        "references": {},
    }


def test_preserves_json_annotations():
    """SchemaRepresentation.toJson / preserves JSON annotations"""
    document = R.to_representation(S.String.annotate(values=["1", "Symbol(a)", "NaN"]))
    assert R.to_json(document) == {
        "representation": {
            "_tag": "String",
            "annotations": {"values": ["1", "Symbol(a)", "NaN"]},
            "checks": [],
        },
        "references": {},
    }


def test_omits_annotations_containing_only_non_json_values():
    """SchemaRepresentation.toJson / omits annotations containing only non-JSON values"""
    assert_to_json(
        R.String(annotations={"callback": lambda: "live"}), {"_tag": "String", "checks": []}
    )


def test_omits_undefined_annotations():
    """SchemaRepresentation.toJson / omits undefined annotations"""
    assert_to_json(R.String(annotations=None), {"_tag": "String", "checks": []})


def test_prunes_nested_representation_annotations():
    """SchemaRepresentation.toJson / prunes nested representation annotations"""
    assert_to_json(
        R.Union((R.String(annotations={"title": "nested", "callback": lambda: "live"}),)),
        {
            "_tag": "Union",
            "types": [{"_tag": "String", "annotations": {"title": "nested"}, "checks": []}],
            "checks": [],
        },
    )


def test_prunes_annotations_in_check_schema_dependencies():
    """SchemaRepresentation.toJson / prunes annotations in check schema dependencies"""
    dependency = R.Number(annotations={"title": "dependency", "callback": lambda: "live"})
    assert_to_json(
        R.String(
            checks=(
                R.Filter(
                    R.CheckRepresentationAnnotation("acme/schema/custom", None, (dependency,))
                ),
            )
        ),
        {
            "_tag": "String",
            "checks": [
                {
                    "_tag": "Filter",
                    "representation": {
                        "id": "acme/schema/custom",
                        "payload": None,
                        "schemas": [
                            {
                                "_tag": "Number",
                                "annotations": {"title": "dependency"},
                                "checks": [],
                            }
                        ],
                    },
                    "aborted": False,
                }
            ],
        },
    )


def test_preserves_shared_json_annotation_values():
    """SchemaRepresentation.toJson / preserves shared JSON annotation values"""
    shared = {"value": "shared"}
    document = R.to_representation(S.String.annotate(value={"left": shared, "right": shared}))
    assert R.to_json(document) == {
        "representation": {
            "_tag": "String",
            "annotations": {"value": {"left": {"value": "shared"}, "right": {"value": "shared"}}},
            "checks": [],
        },
        "references": {},
    }


def test_omits_a_cyclic_annotation_atomically():
    """SchemaRepresentation.toJson / omits a cyclic annotation atomically"""
    cyclic: dict[str, object] = {}
    cyclic["self"] = cyclic
    document = R.to_representation(S.String.annotate(cyclic=cyclic, title="kept"))
    assert R.to_json(document) == {
        "representation": {"_tag": "String", "annotations": {"title": "kept"}, "checks": []},
        "references": {},
    }


def test_omits_an_annotation_containing_bigint_atomically():
    """SchemaRepresentation.toJson / omits an annotation containing bigint atomically"""
    document = R.to_representation(S.String.annotate(invalid={"value": math.nan}, title="kept"))
    assert R.to_json(document) == {
        "representation": {"_tag": "String", "annotations": {"title": "kept"}, "checks": []},
        "references": {},
    }


def test_preserves_filter_groups_without_an_identity():
    """SchemaRepresentation.toJson / preserves filter groups without an identity"""
    first = S.make_filter(_always, representation={"id": "acme/schema/first", "payload": None})
    second = S.make_filter(
        _always, representation={"id": "acme/schema/second", "payload": None}
    ).abort()
    group = S.make_filter_group(first, second, description="both")
    assert R.to_json(R.to_representation(S.String.check(group))) == {
        "representation": {
            "_tag": "String",
            "checks": [
                {
                    "_tag": "FilterGroup",
                    "annotations": {"description": "both"},
                    "checks": [
                        {
                            "_tag": "Filter",
                            "representation": {"id": "acme/schema/first", "payload": None},
                            "aborted": False,
                        },
                        {
                            "_tag": "Filter",
                            "representation": {"id": "acme/schema/second", "payload": None},
                            "aborted": True,
                        },
                    ],
                }
            ],
        },
        "references": {},
    }


def test_preserves_tuple_element_annotations_independently():
    """SchemaRepresentation.toJson / preserves tuple element annotations independently"""
    schema = S.Tuple(S.String.annotate_key(description="element", callback=lambda: "live"))
    assert R.to_json(R.to_representation(schema)) == {
        "representation": {
            "_tag": "Arrays",
            "elements": [
                {
                    "type": {"_tag": "String", "checks": []},
                    "isOptional": False,
                    "annotations": {"description": "element"},
                }
            ],
            "rest": [],
            "checks": [],
        },
        "references": {},
    }


def test_preserves_property_annotations_independently():
    """SchemaRepresentation.toJson / preserves property annotations independently"""

    class Fields(TypedDict):
        value: str

    schema = S.Struct(
        Fields, value=S.String.annotate_key(description="property", callback=lambda: "live")
    )
    assert R.to_json(R.to_representation(schema)) == {
        "representation": {
            "_tag": "Objects",
            "propertySignatures": [
                {
                    "name": {"type": "string", "value": "value"},
                    "type": {"_tag": "String", "checks": []},
                    "isOptional": False,
                    "isMutable": False,
                    "annotations": {"description": "property"},
                }
            ],
            "indexSignatures": [],
            "checks": [],
        },
        "references": {},
    }


def test_encodes_bigint_structural_values():
    """SchemaRepresentation.toJson / encodes bigint structural values"""
    # A Python int literal is a number; a bigint one decodes to an int.
    assert R.to_json(R.to_representation(S.Literal(1))) == {
        "representation": {
            "_tag": "Literal",
            "literal": {"type": "number", "value": 1},
            "checks": [],
        },
        "references": {},
    }


def test_preserves_ambiguous_enum_values():
    """SchemaRepresentation.toJson / preserves ambiguous Enum values"""
    representation = R.Enum(
        (
            ("StringNaN", "NaN"),
            ("NumberInfinity", math.inf),
            ("StringInfinity", "Infinity"),
        )
    )
    assert_roundtrip(
        representation,
        {
            "_tag": "Enum",
            "enums": [
                ["StringNaN", {"type": "string", "value": "NaN"}],
                ["NumberInfinity", {"type": "number", "value": "Infinity"}],
                ["StringInfinity", {"type": "string", "value": "Infinity"}],
            ],
            "checks": [],
        },
    )
    decoded = R.from_json(
        {
            "representation": {
                "_tag": "Enum",
                "enums": [["NumberNaN", {"type": "number", "value": "NaN"}]],
                "checks": [],
            },
            "references": {},
        }
    ).representation
    assert isinstance(decoded, R.Enum)
    value = decoded.enums[0][1]
    assert isinstance(value, float)
    assert math.isnan(value)


def test_preserves_ambiguous_property_names():
    """SchemaRepresentation.toJson / preserves ambiguous property names"""
    assert_roundtrip(
        R.Objects((R.PropertySignature("1", R.String()), R.PropertySignature(1, R.String()))),
        {
            "_tag": "Objects",
            "propertySignatures": [
                string_property({"type": "string", "value": "1"}),
                string_property({"type": "number", "value": 1}),
            ],
            "indexSignatures": [],
            "checks": [],
        },
    )


def test_preserves_string_literals_resembling_non_finite_numbers():
    """SchemaRepresentation.toJson / preserves string literals resembling non-finite numbers"""
    for literal in ("NaN", "Infinity", "-Infinity"):
        assert R.to_json(R.to_representation(S.Literal(literal))) == {
            "representation": {
                "_tag": "Literal",
                "literal": {"type": "string", "value": literal},
                "checks": [],
            },
            "references": {},
        }


def test_encodes_recursive_references():
    """SchemaRepresentation.toJson / encodes recursive references"""
    schema: S.Codec[Any, Any] = S.suspend(lambda: schema)
    assert R.to_json(R.to_representation(schema)) == {
        "representation": {"_tag": "Reference", "$ref": "Suspend_"},
        "references": {
            "Suspend_": {
                "_tag": "Suspend",
                "thunk": {"_tag": "Reference", "$ref": "Suspend_"},
                "checks": [],
            }
        },
    }


def test_encodes_from_json_string_annotations():
    """SchemaRepresentation.toJson / encodes fromJsonString annotations"""

    class Fields(TypedDict):
        value: float

    schema = S.to_encoded(S.from_json_string(S.Struct(Fields)))
    assert R.to_json(R.to_representation(schema)) == {
        "representation": {
            "_tag": "String",
            "annotations": {"expected": "a string that will be decoded as JSON"},
            "checks": [],
        },
        "references": {},
    }


# ----------------------------------------------------------------- fromJson


def _decodes(json: dict[str, Any], expected: R.Representation) -> None:
    document = {"representation": json, "references": {}}
    assert R.from_json(document) == R.Document(expected)


def test_decodes_a_document():
    """SchemaRepresentation.fromJson / decodes a document"""
    _decodes(
        {"_tag": "String", "annotations": {"description": "value"}, "checks": []},
        R.String(annotations={"description": "value"}),
    )


@pytest.mark.parametrize(
    ("tag", "node"),
    [
        ("Null", R.Null()),
        ("Never", R.Never()),
        ("Unknown", R.Unknown()),
        ("Any", R.Any()),
        ("Number", R.Number()),
        ("Boolean", R.Boolean()),
        ("BigInt", R.BigInt()),
    ],
)
def test_decodes_keyword(tag: str, node: R.Representation):
    """SchemaRepresentation.fromJson / decodes Null (and Never, Unknown, Any, Number, Boolean, BigInt)"""  # noqa: E501
    _decodes({"_tag": tag, "checks": []}, node)


def test_decodes_enum():
    """SchemaRepresentation.fromJson / decodes Enum"""
    _decodes(
        {
            "_tag": "Enum",
            "enums": [
                ["A", {"type": "string", "value": "a"}],
                ["One", {"type": "number", "value": 1}],
            ],
            "checks": [],
        },
        R.Enum((("A", "a"), ("One", 1))),
    )


def test_decodes_template_literal():
    """SchemaRepresentation.fromJson / decodes TemplateLiteral"""
    _decodes(
        {
            "_tag": "TemplateLiteral",
            "parts": [
                {
                    "_tag": "Literal",
                    "literal": {"type": "string", "value": "prefix-"},
                    "checks": [],
                },
                {"_tag": "String", "checks": []},
            ],
            "checks": [],
        },
        R.TemplateLiteral((R.Literal("prefix-"), R.String())),
    )


def test_decodes_arrays():
    """SchemaRepresentation.fromJson / decodes Arrays"""
    _decodes(
        {
            "_tag": "Arrays",
            "elements": [{"type": {"_tag": "String", "checks": []}, "isOptional": False}],
            "rest": [{"_tag": "Number", "checks": []}],
            "checks": [],
        },
        R.Arrays((R.Element(R.String()),), (R.Number(),)),
    )


def test_decodes_objects():
    """SchemaRepresentation.fromJson / decodes Objects"""
    _decodes(
        {
            "_tag": "Objects",
            "propertySignatures": [
                {
                    "name": {"type": "string", "value": "value"},
                    "type": {"_tag": "String", "checks": []},
                    "isOptional": False,
                    "isMutable": True,
                }
            ],
            "indexSignatures": [
                {
                    "parameter": {"_tag": "String", "checks": []},
                    "type": {"_tag": "Number", "checks": []},
                }
            ],
            "checks": [],
        },
        R.Objects(
            (R.PropertySignature("value", R.String()),),
            (R.IndexSignature(R.String(), R.Number()),),
        ),
    )


def test_decodes_union():
    """SchemaRepresentation.fromJson / decodes Union"""
    _decodes(
        {
            "_tag": "Union",
            "types": [{"_tag": "String", "checks": []}, {"_tag": "Number", "checks": []}],
            "options": {"mode": "oneOf"},
            "checks": [],
        },
        R.Union((R.String(), R.Number()), "one_of"),
    )


def test_decodes_reference():
    """SchemaRepresentation.fromJson / decodes Reference"""
    document: dict[str, Any] = {
        "representation": {"_tag": "Reference", "$ref": "Value"},
        "references": {"Value": {"_tag": "String", "checks": []}},
    }
    assert R.from_json(document) == R.Document(R.Reference("Value"), {"Value": R.String()})


def test_decodes_suspend():
    """SchemaRepresentation.fromJson / decodes Suspend"""
    document: dict[str, Any] = {
        "representation": {
            "_tag": "Suspend",
            "thunk": {"_tag": "Reference", "$ref": "Value"},
            "checks": [],
        },
        "references": {"Value": {"_tag": "String", "checks": []}},
    }
    assert R.from_json(document) == R.Document(
        R.Suspend(R.Reference("Value")), {"Value": R.String()}
    )


def test_decodes_declaration():
    """SchemaRepresentation.fromJson / decodes Declaration"""
    _decodes(
        {
            "_tag": "Declaration",
            "representation": {"id": "acme/schema/Value", "payload": None},
            "annotations": {},
            "typeParameters": [{"_tag": "String", "checks": []}],
            "checks": [],
        },
        R.Declaration(
            (R.String(),),
            annotations={},
            representation=R.RepresentationAnnotation("acme/schema/Value", None),
        ),
    )


def test_decodes_filter():
    """SchemaRepresentation.fromJson / decodes Filter"""
    _decodes(
        {
            "_tag": "String",
            "checks": [
                {
                    "_tag": "Filter",
                    "representation": {"id": "acme/schema/filter", "payload": None},
                    "annotations": {},
                    "aborted": True,
                }
            ],
        },
        R.String(
            checks=(R.Filter(R.CheckRepresentationAnnotation("acme/schema/filter"), {}, True),)
        ),
    )


def test_decodes_filter_group():
    """SchemaRepresentation.fromJson / decodes FilterGroup"""
    _decodes(
        {
            "_tag": "String",
            "checks": [
                {
                    "_tag": "FilterGroup",
                    "checks": [
                        {
                            "_tag": "Filter",
                            "representation": {"id": "acme/schema/filter", "payload": None},
                            "annotations": {},
                            "aborted": False,
                        }
                    ],
                }
            ],
        },
        R.String(
            checks=(
                R.FilterGroup(
                    (R.Filter(R.CheckRepresentationAnnotation("acme/schema/filter"), {}),)
                ),
            )
        ),
    )


def test_decodes_bigint_structural_values():
    """SchemaRepresentation.fromJson / decodes bigint structural values"""
    _decodes(
        {"_tag": "Literal", "literal": {"type": "bigint", "value": "1"}, "checks": []},
        R.Literal(1),
    )


@pytest.mark.parametrize(
    "literal",
    [
        {"type": "bigint", "value": "not-an-integer"},
        {"type": "boolean", "value": "true"},
        {"type": "string", "value": 1},
    ],
)
def test_rejects_mismatched_literal_types(literal: dict[str, object]):
    """SchemaRepresentation.fromJson / rejects mismatched literal types"""
    with pytest.raises(R.RepresentationError):
        R.from_json(
            {
                "representation": {"_tag": "Literal", "literal": literal, "checks": []},
                "references": {},
            }
        )


def test_rejects_mismatched_enum_value_types():
    """SchemaRepresentation.fromJson / rejects mismatched Enum value types"""
    with pytest.raises(R.RepresentationError):
        R.from_json(
            {
                "representation": {
                    "_tag": "Enum",
                    "enums": [["One", {"type": "number", "value": "1"}]],
                    "checks": [],
                },
                "references": {},
            }
        )


def test_rejects_mismatched_property_name_types():
    """SchemaRepresentation.fromJson / rejects mismatched property name types"""
    with pytest.raises(R.RepresentationError):
        R.from_json(
            {
                "representation": {
                    "_tag": "Objects",
                    "propertySignatures": [{**string_property({"type": "number", "value": "1"})}],
                    "indexSignatures": [],
                    "checks": [],
                },
                "references": {},
            }
        )


def test_from_json_preserves_string_literals_resembling_non_finite_numbers():
    """SchemaRepresentation.fromJson / preserves string literals resembling non-finite numbers"""
    for literal in ("NaN", "Infinity", "-Infinity", "Symbol(a)"):
        _decodes(
            {"_tag": "Literal", "literal": {"type": "string", "value": literal}, "checks": []},
            R.Literal(literal),
        )


def test_requires_representation_on_persisted_filters():
    """SchemaRepresentation.fromJson / requires representation on persisted Filters"""
    with raises('Missing key\n  at ["representation"]["checks"][0]["representation"]'):
        R.from_json(
            {
                "representation": {
                    "_tag": "String",
                    "checks": [{"_tag": "Filter", "aborted": False}],
                },
                "references": {},
            }
        )


def test_requires_representation_on_persisted_declarations():
    """SchemaRepresentation.fromJson / requires representation on persisted Declarations"""
    with raises('Missing key\n  at ["representation"]["representation"]'):
        R.from_json(
            {
                "representation": {"_tag": "Declaration", "typeParameters": [], "checks": []},
                "references": {},
            }
        )


def test_rejects_empty_references():
    """SchemaRepresentation.fromJson / rejects empty references"""
    with raises('Expected a value with a length of at least 1\n  at ["representation"]["$ref"]'):
        R.from_json({"representation": {"_tag": "Reference", "$ref": ""}, "references": {}})


def test_rejects_non_json_annotations():
    """SchemaRepresentation.fromJson / rejects non-JSON annotations"""
    with raises('Expected JSON value\n  at ["representation"]["annotations"]["invalid"]'):
        R.from_json(
            {
                "representation": {
                    "_tag": "String",
                    "annotations": {"invalid": math.inf},
                    "checks": [],
                },
                "references": {},
            }
        )


def test_rejects_non_json_roots():
    """SchemaRepresentation.fromJson / rejects non-JSON roots"""
    with raises("Expected object"):
        R.from_json(lambda: None)


# ------------------------------------------------------- multi-documents


def test_encodes_every_root_in_order():
    """SchemaRepresentation.toJsonMultiDocument / encodes every root in order"""
    document = R.to_representations((S.String, S.Number, S.Literal(1)))
    assert R.to_json_multi_document(document) == {
        "representations": [
            {"_tag": "String", "checks": []},
            {"_tag": "Number", "checks": []},
            {"_tag": "Literal", "literal": {"type": "number", "value": 1}, "checks": []},
        ],
        "references": {},
    }


def test_encodes_shared_references_once():
    """SchemaRepresentation.toJsonMultiDocument / encodes shared references once"""
    shared = S.String.annotate(identifier="Shared", callback=lambda: "live")
    document = R.to_representations((shared, shared))
    assert R.to_json_multi_document(document) == {
        "representations": [
            {"_tag": "Reference", "$ref": "Shared"},
            {"_tag": "Reference", "$ref": "Shared"},
        ],
        "references": {
            "Shared": {"_tag": "String", "annotations": {"identifier": "Shared"}, "checks": []}
        },
    }


def test_decodes_every_root_in_order():
    """SchemaRepresentation.fromJsonMultiDocument / decodes every root in order"""
    document: dict[str, Any] = {
        "representations": [
            {"_tag": "String", "checks": []},
            {"_tag": "Number", "checks": []},
            {"_tag": "Literal", "literal": {"type": "string", "value": "1"}, "checks": []},
            {"_tag": "Literal", "literal": {"type": "bigint", "value": "1"}, "checks": []},
        ],
        "references": {},
    }
    assert R.from_json_multi_document(document) == R.MultiDocument(
        (R.String(), R.Number(), R.Literal("1"), R.Literal(1))
    )


def test_decodes_shared_references():
    """SchemaRepresentation.fromJsonMultiDocument / decodes shared references"""
    document: dict[str, Any] = {
        "representations": [
            {"_tag": "Reference", "$ref": "Shared"},
            {"_tag": "Reference", "$ref": "Shared"},
        ],
        "references": {"Shared": {"_tag": "String", "checks": []}},
    }
    decoded = R.from_json_multi_document(document)
    assert decoded == R.MultiDocument(
        (R.Reference("Shared"), R.Reference("Shared")), {"Shared": R.String()}
    )
    assert R.to_json_multi_document(decoded) == document


def test_rejects_an_empty_roots_array():
    """SchemaRepresentation.fromJsonMultiDocument / rejects an empty roots array"""
    with raises('Missing key\n  at ["representations"][0]'):
        R.from_json_multi_document({"representations": [], "references": {}})
