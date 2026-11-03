"""Ports of Effect's ``schema/representation/toJsonSchemaDocument.test.ts``.
Each test's docstring is the Effect test title, prefixed by its
``describe`` blocks. A check's JSON Schema callback is its
``to_json_schema`` annotation, given a ``S.CheckContext(type, schemas)``.

Omitted:
- No such nodes (§4: ``Schema.Undefined``, ``Void``, ``Symbol``): the
  "ObjectKeyword", "Void", "Undefined", "Symbol", "UniqueSymbol", "local
  UniqueSymbol" keyword titles, "arrays and objects / rejects a symbol
  object property".
- "local reference round trips / preserves the definition named ...": need
  ``fromJsonSchemaDocument``, not ported (see docs/PARITY.md).
- Annotation keys are pyfect's (``read_only``, not ``readOnly``), and the
  shared compiler's errors carry no document path ("reports an invalid
  index-signature parameter").
- "checks and callbacks / passes the type produced by isInt to following
  check callbacks": ported without ``maximum: MAX_SAFE_INTEGER`` (a Python
  int has no safe-integer bounds).
- "checks and callbacks / omits isPattern flags that JSON Schema cannot
  represent": pyfect leaves every ``re`` pattern out (see
  ``_jsonschema/_checks.py``), ported with a flagless pattern.
"""

import re
from collections.abc import Callable
from typing import Any

import pytest

from pyfect import schema as S
from pyfect.schema import representation as R


def _always(_: object) -> bool:
    return True


def _no_code(_: object) -> None:
    return None


def _const(out: Any) -> Callable[[S.CheckContext], Any]:
    def to_json_schema(_: S.CheckContext) -> Any:
        return out

    return to_json_schema


def _property_names(context: S.CheckContext) -> Any:
    return {"propertyNames": context.schemas[0]}


STRING = R.String()
NUMBER = R.Number()
BOOLEAN = R.Boolean()
NUMBER_SCHEMA = {
    "anyOf": [{"type": "number"}, {"type": "string", "enum": ["NaN", "Infinity", "-Infinity"]}]
}


def compile(representation: R.Representation) -> Any:
    document = R.Document(representation)
    return R.to_json_schema_document(document, on_excess_property="error").schema


def document_schema(document: R.Document) -> Any:
    return R.to_json_schema_document(document).schema


def fragment(out: Any, **annotations: object) -> R.Filter:
    return R.Filter(annotations={**annotations, "to_json_schema": _const(out)})


def raises(message: str) -> Any:
    return pytest.raises(R.RepresentationError, match=f"^{re.escape(message)}$")


# ----------------------------------------------------- representation nodes


def test_compiles_string_content_with_another_media_type():
    """representation nodes / compiles string content with another media type"""
    assert compile(R.String(content=R.Content("application/example", BOOLEAN))) == {
        "type": "string",
        "contentMediaType": "application/example",
        "contentSchema": {"type": "boolean"},
    }


@pytest.mark.parametrize(
    ("node", "expected"),
    [
        (R.Any(), {}),
        (R.Unknown(), {}),
        (R.BigInt(), {"type": "string", "allOf": [{"pattern": r"^-?\d+$"}]}),
        (R.Null(), {"type": "null"}),
        (R.Never(), {"not": {}}),
    ],
    ids=["Any", "Unknown", "BigInt", "Null", "Never"],
)
def test_keywords(node: R.Representation, expected: object):
    """representation nodes / Any, Unknown, BigInt, Null, Never"""
    assert compile(node) == expected


def test_compiles_suspend():
    """representation nodes / compiles Suspend"""
    assert compile(R.Suspend(STRING)) == {"type": "string"}


def test_compiles_a_bigint_literal():
    """representation nodes / compiles a bigint Literal"""
    # A Python int literal is a number: Effect's bigint literal has no match.
    assert compile(R.Literal(1)) == {"type": "number", "enum": [1]}


def test_compiles_a_string_literal():
    """representation nodes / compiles a string Literal"""
    assert compile(R.Literal("a")) == {"type": "string", "enum": ["a"]}


def test_compiles_an_empty_enum():
    """representation nodes / compiles an empty Enum"""
    assert compile(R.Enum(())) == {"not": {}}


def test_compiles_an_enum():
    """representation nodes / compiles an Enum"""
    assert compile(R.Enum((("A", "a"), ("One", 1)))) == {
        "anyOf": [
            {"type": "string", "enum": ["a"], "title": "A"},
            {"type": "number", "enum": [1], "title": "One"},
        ]
    }


def test_compiles_a_template_literal():
    """representation nodes / compiles a TemplateLiteral"""
    assert compile(R.TemplateLiteral((R.Literal("prefix-"), STRING))) == {
        "type": "string",
        "pattern": r"^prefix-[\s\S]*?$",
    }


# ------------------------------------------------------ arrays and objects


def test_compiles_an_empty_objects_node_as_any_non_null_json_value():
    """arrays and objects / compiles an empty Objects node as any non-null JSON value"""
    assert compile(R.Objects()) == {"not": {"type": "null"}}


def test_compiles_optional_tuple_elements():
    """arrays and objects / compiles optional tuple elements"""
    assert compile(R.Arrays((R.Element(STRING), R.Element(NUMBER, is_optional=True)))) == {
        "type": "array",
        "prefixItems": [{"type": "string"}, NUMBER_SCHEMA],
        "maxItems": 2,
        "minItems": 1,
    }


def test_approximates_multiple_tuple_rest_elements():
    """arrays and objects / approximates multiple tuple rest elements"""
    assert compile(R.Arrays((), (STRING, NUMBER))) == {"type": "array", "minItems": 1}


def test_compiles_a_never_index_signature_value_as_false():
    """arrays and objects / compiles a Never index-signature value as false"""
    assert compile(R.Objects((), (R.IndexSignature(STRING, R.Never()),))) == {
        "type": "object",
        "additionalProperties": False,
    }


def test_removes_an_unconstrained_index_signature_value():
    """arrays and objects / removes an unconstrained index-signature value"""
    assert compile(R.Objects((), (R.IndexSignature(STRING, R.Unknown()),))) == {"type": "object"}


# ------------------------------------------------------------------ unions


def test_compacts_a_union_of_same_type_literals():
    """unions / compacts a union of same-type literals"""
    assert compile(R.Union((R.Literal("a"), R.Literal("b")))) == {
        "type": "string",
        "enum": ["a", "b"],
    }


def test_does_not_compact_a_union_of_mixed_type_literals():
    """unions / does not compact a union of mixed-type literals"""
    assert compile(R.Union((R.Literal("a"), R.Literal(1)))) == {
        "anyOf": [{"type": "string", "enum": ["a"]}, {"type": "number", "enum": [1]}]
    }


# ---------------------------------------------------- annotations and checks


def test_emits_every_supported_standard_annotation():
    """annotations and checks / emits every supported standard annotation"""
    annotations = {
        "title": "Title",
        "description": "Description",
        "default": "default",
        "examples": ["a", "b"],
        "read_only": True,
        "write_only": False,
    }
    assert compile(R.String(annotations=annotations)) == {
        "type": "string",
        "title": "Title",
        "description": "Description",
        "default": "default",
        "examples": ["a", "b"],
        "readOnly": True,
        "writeOnly": False,
    }


def test_uses_a_check_fragment_when_the_base_json_schema_is_empty():
    """annotations and checks / uses a check fragment when the base JSON Schema is empty"""
    assert compile(R.Unknown(checks=(fragment({"description": "checked"}),))) == {
        "description": "checked"
    }


def test_appends_a_check_to_an_existing_all_of():
    """annotations and checks / appends a check to an existing allOf"""
    assert compile(R.BigInt(checks=(fragment({"description": "checked"}),))) == {
        "type": "string",
        "allOf": [{"pattern": r"^-?\d+$"}, {"description": "checked"}],
    }


def test_lets_a_check_refine_number_to_integer():
    """annotations and checks / lets a check refine number to integer"""
    assert compile(R.Number(checks=(fragment({"type": "integer"}),))) == {"type": "integer"}


def test_compiles_a_callback_free_filter_group_without_ordinary_annotations():
    """annotations and checks / compiles a callback-free FilterGroup without ordinary annotations"""
    group = R.FilterGroup((fragment({"minLength": 1}),))
    assert compile(R.String(checks=(group,))) == {"type": "string", "allOf": [{"minLength": 1}]}


# -------------------------------------------- collection and union edge cases


def test_compiles_tuple_element_annotations():
    """collection and union edge cases / compiles tuple element annotations"""
    element = R.Element(STRING, annotations={"description": "element"})
    assert compile(R.Arrays((element,))) == {
        "type": "array",
        "prefixItems": [{"type": "string", "allOf": [{"description": "element"}]}],
        "maxItems": 1,
        "minItems": 1,
    }


def test_omits_min_items_when_every_tuple_element_is_optional():
    """collection and union edge cases / omits minItems when every tuple element is optional"""
    assert compile(R.Arrays((R.Element(STRING, is_optional=True),))) == {
        "type": "array",
        "prefixItems": [{"type": "string"}],
        "maxItems": 1,
    }


def test_compiles_a_constrained_tuple_rest():
    """collection and union edge cases / compiles a constrained tuple rest"""
    assert compile(R.Arrays((), (STRING,))) == {"type": "array", "items": {"type": "string"}}


def test_compiles_property_annotations():
    """collection and union edge cases / compiles property annotations"""
    signature = R.PropertySignature(
        "value", STRING, is_optional=True, annotations={"description": "property"}
    )
    assert compile(R.Objects((signature,))) == {
        "type": "object",
        "properties": {"value": {"type": "string", "allOf": [{"description": "property"}]}},
        "additionalProperties": False,
    }


def test_compiles_a_single_member_union_without_compacting_it():
    """collection and union edge cases / compiles a single-member Union without compacting it"""
    assert compile(R.Union((STRING,))) == {"anyOf": [{"type": "string"}]}


def _approximate() -> R.String:
    return R.String(checks=(fragment(({"minLength": 1}, True)),))


def test_falls_back_from_one_of_to_any_of_when_a_branch_is_approximate():
    """collection and union edge cases / falls back from oneOf to anyOf when a branch is approximate"""  # noqa: E501
    union = R.Union(
        (_approximate(), BOOLEAN), "one_of", annotations={"description": "annotated union"}
    )
    assert compile(union) == {
        "anyOf": [{"type": "string", "minLength": 1}, {"type": "boolean"}],
        "description": "annotated union",
    }


def test_propagates_approximation_through_nested_representations():
    """collection and union edge cases / propagates approximation through nested representations"""
    approximate = R.String(checks=(R.Filter(),))
    union = R.Union((R.Arrays((), (approximate,)), NUMBER), "one_of")
    assert compile(union) == {
        "anyOf": [{"type": "array", "items": {"type": "string"}}, NUMBER_SCHEMA]
    }


def test_resolves_an_approximate_one_of_copied_by_contextual_annotations():
    """collection and union edge cases / resolves an approximate oneOf copied by contextual annotations"""  # noqa: E501
    element = R.Element(
        R.Union((_approximate(), BOOLEAN), "one_of"), annotations={"description": "element"}
    )
    assert compile(R.Arrays((element,))) == {
        "type": "array",
        "prefixItems": [
            {
                "anyOf": [{"type": "string", "minLength": 1}, {"type": "boolean"}],
                "allOf": [{"description": "element"}],
            }
        ],
        "minItems": 1,
        "maxItems": 1,
    }


def test_keeps_one_of_when_every_branch_is_exact():
    """collection and union edge cases / keeps oneOf when every branch is exact"""
    assert compile(R.Union((STRING, BOOLEAN), "one_of")) == {
        "oneOf": [{"type": "string"}, {"type": "boolean"}]
    }


def test_compiles_a_number_index_signature_parameter():
    """collection and union edge cases / compiles a Number index-signature parameter"""
    assert compile(R.Objects((), (R.IndexSignature(NUMBER, STRING),))) == {
        "type": "object",
        "patternProperties": {
            r"^(?:[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:[Ee][+-]?\d+)?|Infinity|-Infinity|NaN)$": {
                "type": "string"
            }
        },
        "additionalProperties": False,
    }


def test_reports_an_invalid_index_signature_parameter():
    """collection and union edge cases / reports an invalid index-signature parameter"""
    # The shared compiler reports no document path.
    with pytest.raises(ValueError, match=r"^Invalid index signature parameter Boolean$"):
        compile(R.Objects((), (R.IndexSignature(BOOLEAN, STRING),)))


def test_compiles_an_empty_union_as_never():
    """collection and union edge cases / compiles an empty union as Never"""
    assert document_schema(R.Document(R.Union(()))) == {"not": {}}


def test_removes_items_when_an_empty_tuple_has_an_open_rest():
    """collection and union edge cases / removes items when an empty tuple has an open rest"""
    assert document_schema(R.Document(R.Arrays((), (R.Unknown(),)))) == {"type": "array"}


# ------------------------------------------------------ checks and callbacks


def test_passes_the_type_produced_by_is_int_to_following_check_callbacks():
    """checks and callbacks / passes the type produced by isInt to following check callbacks"""
    received: list[str | None] = []

    def to_json_schema(context: S.CheckContext) -> Any:
        received.append(context.type)
        return {"minimum": 0}

    dependent = S.make_filter(_always, to_json_schema=to_json_schema)
    document = R.to_representation(S.Number.check(S.is_int(), dependent))
    assert document_schema(document) == {"type": "integer", "minimum": 0}
    assert received == ["integer"]


def test_omits_is_pattern_flags_that_json_schema_cannot_represent():
    """checks and callbacks / omits isPattern flags that JSON Schema cannot represent"""
    document = R.to_representation(S.String.check(S.is_pattern(re.compile("^[a-z]+$", re.I))))
    out = R.to_json_schema_document(document)
    assert (out.dialect, out.schema, out.definitions) == ("draft-2020-12", {"type": "string"}, {})


def test_treats_an_empty_override_as_authoritative_and_ignores_a_leaf_without_a_callback():
    """checks and callbacks / treats an empty override as authoritative and ignores a leaf without a callback"""  # noqa: E501
    visits: list[None] = []

    def counted(_: S.CheckContext) -> Any:
        visits.append(None)
        return {"minLength": 1}

    group = R.FilterGroup(
        (R.Filter(annotations={"description": "ignored", "to_json_schema": counted}),),
        annotations={"to_json_schema": _const({})},
    )
    leaf = R.Filter(annotations={"description": "no callback"})
    assert document_schema(R.Document(R.String(checks=(group, leaf)))) == {"type": "string"}
    assert visits == []


def test_compiles_representation_schemas_before_invoking_a_callback():
    """checks and callbacks / compiles representation.schemas before invoking a callback"""
    check = R.Filter(
        R.CheckRepresentationAnnotation("acme/schema/propertyNames", None, (STRING,)),
        {"to_json_schema": _property_names},
    )
    assert document_schema(R.Document(R.Objects(checks=(check,)))) == {
        "not": {"type": "null"},
        "propertyNames": {"type": "string"},
    }


def test_propagates_approximation_from_representation_schemas():
    """checks and callbacks / propagates approximation from representation.schemas"""
    dependent = R.String(
        checks=(
            R.Filter(
                R.CheckRepresentationAnnotation("acme/schema/dependent", None, (_approximate(),)),
                {"to_json_schema": _const({})},
            ),
        )
    )
    assert compile(R.Union((dependent, BOOLEAN), "one_of")) == {
        "anyOf": [{"type": "string"}, {"type": "boolean"}]
    }


# --------------------------------------- declarations and pattern extraction


def test_approximates_declarations():
    """declarations and pattern extraction / approximates declarations"""
    declaration = R.Declaration(
        (STRING,), representation=R.RepresentationAnnotation("acme/schema/Box")
    )
    assert document_schema(R.Document(declaration)) == {}


def test_compiles_every_member_of_a_union_index_signature_parameter():
    """declarations and pattern extraction / compiles every member of a union index-signature parameter"""  # noqa: E501
    template = R.to_representation(S.TemplateLiteral("a", S.String)).representation
    pattern = R.String(checks=(fragment({"pattern": "^b"}),))
    objects = R.Objects((), (R.IndexSignature(R.Union((template, pattern)), STRING),))
    schema = document_schema(R.Document(objects))
    assert list(schema["patternProperties"]) == [r"^a[\s\S]*?$", "^b"]


def test_does_not_extract_a_partial_pattern_from_boolean_applicator_members():
    """declarations and pattern extraction / does not extract a partial pattern from boolean applicator members"""  # noqa: E501
    key = R.String(checks=(fragment({"allOf": [False, {"pattern": "^a"}]}),))
    objects = R.Objects((), (R.IndexSignature(key, STRING),))
    assert document_schema(R.Document(objects)) == {
        "type": "object",
        "additionalProperties": True,
    }


def test_does_not_use_an_approximate_pattern_as_an_index_selector():
    """declarations and pattern extraction / does not use an approximate pattern as an index selector"""  # noqa: E501
    key = R.String(checks=(fragment(({"pattern": "^a"}, True)),))
    objects = R.Objects((), (R.IndexSignature(key, NUMBER),))
    expected = {
        "type": "object",
        "propertyNames": {"type": "string", "pattern": "^a"},
        "additionalProperties": NUMBER_SCHEMA,
    }
    assert compile(objects) == expected
    assert compile(R.Union((objects, BOOLEAN), "one_of")) == {
        "anyOf": [expected, {"type": "boolean"}]
    }


def test_keeps_an_exact_key_selector_when_its_value_is_approximate():
    """declarations and pattern extraction / keeps an exact key selector when its value is approximate"""  # noqa: E501
    key = R.String(checks=(fragment({"pattern": "^a"}),))
    objects = R.Objects((), (R.IndexSignature(key, _approximate()),))
    assert compile(R.Union((objects, BOOLEAN), "one_of")) == {
        "anyOf": [
            {
                "type": "object",
                "patternProperties": {"^a": {"type": "string", "minLength": 1}},
                "additionalProperties": False,
            },
            {"type": "boolean"},
        ]
    }


FINITE = r"[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:[Ee][+-]?\d+)?"


def test_compiles_all_supported_template_literal_parts_and_rejects_other_nodes():
    """declarations and pattern extraction / compiles all supported template-literal parts and rejects other nodes"""  # noqa: E501
    template = R.TemplateLiteral(
        (
            R.Literal("p"),
            NUMBER,
            R.TemplateLiteral((R.Literal("x"), STRING)),
            R.Union((R.Literal("a"), R.Literal("b"))),
        )
    )
    assert document_schema(R.Document(template)) == {
        "type": "string",
        "pattern": rf"^p{FINITE}x[\s\S]*?(?:a|b)$",
    }
    with pytest.raises(ValueError, match="Invalid TemplateLiteral part Boolean"):
        document_schema(R.Document(R.TemplateLiteral((BOOLEAN,))))


@pytest.mark.parametrize("ref", ["Missing", "toString"])
def test_rejects_missing_template_literal_references(ref: str):
    """declarations and pattern extraction / rejects missing template-literal references: %s"""
    with pytest.raises(R.RepresentationError, match=f"^Invalid reference {ref}"):
        document_schema(R.Document(R.TemplateLiteral((R.Reference(ref),))))


def test_rejects_recursive_template_literal_references():
    """declarations and pattern extraction / rejects recursive template-literal references"""
    template = R.TemplateLiteral((R.Reference("Segment"),))
    with pytest.raises(ValueError, match="Invalid recursive TemplateLiteral part Segment"):
        document_schema(R.Document(template, {"Segment": template}))


# ------------------------------------- normalization / conservative compaction


def check(out: Any, **annotations: object) -> R.Filter:
    return fragment(out, **annotations)


def compile_checks(*fragments: Any) -> Any:
    return compile(R.Any(checks=tuple(check(f) for f in fragments)))


def test_tightens_colliding_bounds_in_place():
    """normalization / conservative check compaction / tightens colliding bounds in place"""
    checks = (
        check({"minLength": 1}),
        check({"minLength": 2}),
        check({"maxLength": 5}),
        check({"maxLength": 9}),
    )
    assert compile(R.String(checks=checks)) == {"type": "string", "minLength": 2, "maxLength": 5}


def test_keeps_other_colliding_keywords_in_separate_schema_objects():
    """normalization / conservative check compaction / keeps other colliding keywords in separate schema objects"""  # noqa: E501
    checks = (check({"pattern": "a"}), check({"pattern": "b"}))
    assert compile(R.String(checks=checks)) == {
        "type": "string",
        "pattern": "a",
        "allOf": [{"pattern": "b"}],
    }


def test_inlines_pure_annotations_on_a_check():
    """normalization / conservative check compaction / inlines pure annotations on a check"""
    annotated = check(
        {"minLength": 1},
        title="title",
        description="description",
        default="default",
        examples=["example"],
        read_only=True,
        write_only=False,
    )
    assert compile(R.String(checks=(annotated,))) == {
        "type": "string",
        "minLength": 1,
        "title": "title",
        "description": "description",
        "default": "default",
        "examples": ["example"],
        "readOnly": True,
        "writeOnly": False,
    }


def test_inlines_callback_metadata_with_pure_check_annotations():
    """normalization / conservative check compaction / inlines callback metadata with pure check annotations"""  # noqa: E501
    annotated = check({"minLength": 1, "title": "callback"}, description="annotation")
    assert compile(R.String(checks=(annotated,))) == {
        "type": "string",
        "minLength": 1,
        "title": "callback",
        "description": "annotation",
    }


def test_keeps_colliding_annotations_in_a_separate_schema_object():
    """normalization / conservative check compaction / keeps colliding annotations in a separate schema object"""  # noqa: E501
    node = R.String(
        annotations={"description": "string"},
        checks=(check({"minLength": 1}, description="check"),),
    )
    assert compile(node) == {
        "type": "string",
        "description": "string",
        "allOf": [{"minLength": 1, "description": "check"}],
    }


def test_keeps_format_annotations_in_a_separate_schema_object():
    """normalization / conservative check compaction / keeps format annotations in a separate schema object"""  # noqa: E501
    node = R.String(checks=(check({"minLength": 1}, format="annotated-check"),))
    assert compile(node) == {
        "type": "string",
        "allOf": [{"minLength": 1, "format": "annotated-check"}],
    }


def test_inlines_property_names_without_a_collision():
    """normalization / conservative check compaction / inlines propertyNames without a collision"""
    node = R.Objects(checks=(check({"propertyNames": {"minLength": 1}}),))
    assert compile(node) == {"not": {"type": "null"}, "propertyNames": {"minLength": 1}}


def test_keeps_colliding_property_names_in_separate_schema_objects():
    """normalization / conservative check compaction / keeps colliding propertyNames in separate schema objects"""  # noqa: E501
    node = R.Objects(
        checks=(
            check({"propertyNames": {"minLength": 1}}),
            check({"propertyNames": {"maxLength": 2}}),
        )
    )
    assert compile(node) == {
        "not": {"type": "null"},
        "propertyNames": {"minLength": 1},
        "allOf": [{"propertyNames": {"maxLength": 2}}],
    }


def test_keeps_a_reference_separate_from_contextual_annotations():
    """normalization / conservative check compaction / keeps a reference separate from contextual annotations"""  # noqa: E501
    signature = R.PropertySignature(
        "value", R.Reference("Value"), annotations={"description": "contextual"}
    )
    document = R.to_json_schema_document(R.Document(R.Objects((signature,)), {"Value": STRING}))
    assert document.schema == {
        "type": "object",
        "properties": {
            "value": {"allOf": [{"$ref": "#/$defs/Value"}, {"description": "contextual"}]}
        },
        "required": ["value"],
        "additionalProperties": True,
    }


@pytest.mark.parametrize(
    ("first", "second"),
    [
        ({"contains": {"const": "a"}}, {"minContains": 2}),
        ({"properties": {"a": True}}, {"additionalProperties": False}),
        ({"prefixItems": [True]}, {"items": False}),
        ({"if": {"required": ["a"]}}, {"else": {"required": ["b"]}}),
    ],
    ids=[
        "contains and minContains",
        "properties and additionalProperties",
        "prefixItems and items",
        "if and else",
    ],
)
def test_keeps_coupled_keywords_in_separate_schema_objects(first: Any, second: Any):
    """normalization / conservative check compaction / keeps ${name} in separate schema objects"""
    for left, right in ((first, second), (second, first)):
        assert compile_checks(left, right) == {**left, "allOf": [right]}


def test_keeps_a_fragment_containing_a_custom_keyword_intact():
    """normalization / conservative check compaction / keeps a fragment containing a custom keyword intact"""  # noqa: E501
    node = R.String(checks=(check({"minLength": 1, "x-check": True}),))
    assert compile(node) == {"type": "string", "allOf": [{"minLength": 1, "x-check": True}]}


def test_keeps_format_scoped_after_absorbing_a_number_type():
    """normalization / conservative check compaction / keeps format scoped after absorbing a number type"""  # noqa: E501
    node = R.Number(checks=(check({"type": "number"}, format="finite"),))
    assert compile(node) == {"type": "number", "allOf": [{"format": "finite"}]}


def test_inlines_callback_metadata_after_absorbing_a_number_type():
    """normalization / conservative check compaction / inlines callback metadata after absorbing a number type"""  # noqa: E501
    node = R.Number(checks=(check({"type": "integer", "description": "integer"}),))
    assert compile(node) == {"type": "integer", "description": "integer"}


def test_does_not_overwrite_an_annotation_after_absorbing_a_number_type():
    """normalization / conservative check compaction / does not overwrite an annotation after absorbing a number type"""  # noqa: E501
    node = R.Number(
        annotations={"description": "number"},
        checks=(check({"type": "integer"}, description="integer"),),
    )
    assert compile(node) == {
        "type": "integer",
        "description": "number",
        "allOf": [{"description": "integer"}],
    }


def test_extracts_nested_number_types_without_losing_other_all_of_members():
    """normalization / extracts nested number types without losing other allOf members"""
    nested = {
        "allOf": [
            {"description": "nested", "allOf": [{"type": "number"}, {"minimum": 1}]},
            {"type": "integer", "maximum": 10},
            {"title": "kept"},
        ]
    }
    assert document_schema(R.Document(R.Number(checks=(fragment(nested),)))) == {
        "type": "integer",
        "allOf": [
            {"description": "nested", "allOf": [{"minimum": 1}]},
            {"maximum": 10},
            {"title": "kept"},
        ],
    }
    twice = {"allOf": [{"type": "number"}, {"type": "number"}]}
    assert document_schema(R.Document(R.Number(checks=(fragment(twice),)))) == {"type": "number"}


# --------------------------------------------------------- safety and errors


def test_never_exposes_compiler_capabilities_as_extension_annotations():
    """safety and errors / never exposes compiler capabilities as extension annotations"""
    node = R.String(
        annotations={
            "description": "text",
            "identifier": "id",
            "representation": {"id": "acme/schema/String", "payload": None},
            "to_code": _no_code,
            "to_json_schema": _const({"title": "ignored"}),
            "x-custom": {"enabled": True},
            "x-invalid": lambda: "ignored",
        }
    )
    out = R.to_json_schema_document(R.Document(node), include_annotation_key=_always)
    assert out.schema == {
        "type": "string",
        "description": "text",
        "identifier": "id",
        "x-custom": {"enabled": True},
    }


def test_captures_exceptions_from_json_schema_callbacks():
    """safety and errors / captures exceptions from JSON Schema callbacks"""
    cause = RuntimeError("json schema callback")

    def boom(_: S.CheckContext) -> Any:
        raise cause

    node = R.String(checks=(R.Filter(annotations={"to_json_schema": boom}),))
    with pytest.raises(RuntimeError) as error:
        R.to_json_schema_document(R.Document(node))
    assert error.value is cause


def test_supports_proto_as_a_reference():
    """safety and errors / supports __proto__ as a reference"""
    document = R.to_json_schema_document(
        R.to_representation(S.String.annotate(identifier="__proto__"))
    )
    assert document.schema == {"$ref": "#/$defs/__proto__"}
    assert document.definitions == {"__proto__": {"type": "string"}}


def test_reports_missing_references_with_their_document_path():
    """safety and errors / reports missing references with their document path"""
    with raises('Invalid reference Missing\n  at ["representation"]["$ref"]'):
        R.to_json_schema_document(R.Document(R.Reference("Missing")))
