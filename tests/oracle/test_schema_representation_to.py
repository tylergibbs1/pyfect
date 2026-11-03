"""Ports of Effect's ``schema/representation/toRepresentation.test.ts``.
Each test's docstring is the Effect test title, prefixed by its
``describe`` blocks.

Python mappings: ``SchemaRepresentation`` is ``pyfect.schema.representation``
(``R``); nodes are frozen dataclasses (``R.String()``), with snake_case
fields (``property_signatures``, ``is_optional``) and no ``isMutable``;
``toRepresentation(schema.ast)`` is ``R.to_representation(schema)`` and
``SchemaAST.toType(ast)`` is ``S.to_type(schema)``; annotations keep
pyfect's snake_case keys.

Omitted:
- No such schemas in pyfect (§4: ``Schema.Undefined``, ``Void``, ``Symbol``):
  "node conversion / Undefined", "... / Void", "... / Symbol",
  "... / ObjectKeyword", "node conversion / global unique symbol".
- "schema annotations and declarations / omits brands": ``S.from_brand``
  adds the brand's checks; a TypeScript-only brand has no runtime form.

Python differences: ``is_pattern``'s payload holds ``re`` flags (an
``int``), and its arbitrary constraint is a compiled pattern (not JSON).
"""

from typing import Any, NotRequired, TypedDict, TypeIs

from pyfect import schema as S
from pyfect.schema import ast
from pyfect.schema import representation as R


def _is_str(value: object) -> TypeIs[str]:
    return isinstance(value, str)


def _always(_: object) -> bool:
    return True


def doc(representation: R.Representation, references: dict[str, R.Representation] | None = None):
    return R.Document(representation, references or {})


# ------------------------------------------------------------ node conversion


def test_null():
    """node conversion / Null"""
    assert R.to_representation(S.Null) == doc(R.Null())


def test_never():
    """node conversion / Never"""
    assert R.to_representation(S.Never) == doc(R.Never())


def test_unknown():
    """node conversion / Unknown"""
    assert R.to_representation(S.Unknown) == doc(R.Unknown())


def test_any():
    """node conversion / Any"""
    assert R.to_representation(S.Any) == doc(R.Any())


def test_string():
    """node conversion / String"""
    assert R.to_representation(S.String) == doc(R.String())


def test_number():
    """node conversion / Number"""
    assert R.to_representation(S.Number) == doc(R.Number())


def test_boolean():
    """node conversion / Boolean"""
    assert R.to_representation(S.Boolean) == doc(R.Boolean())


def test_big_int():
    """node conversion / BigInt"""
    assert R.to_representation(S.BigInt) == doc(R.BigInt())


def test_literal():
    """node conversion / literal"""
    assert R.to_representation(S.Literal("value")) == doc(R.Literal("value"))


def test_enum():
    """node conversion / enum"""
    import enum

    class E(enum.Enum):
        A = "a"
        One = 1

    assert R.to_representation(S.Enum(E)) == doc(R.Enum((("A", "a"), ("One", 1))))


def test_template_literal():
    """node conversion / template literal"""
    schema = S.TemplateLiteral("prefix-", S.String, S.Number)
    assert R.to_representation(schema) == doc(
        R.TemplateLiteral((R.Literal("prefix-"), R.String(), R.Number()))
    )


def test_tuple_elements_and_rest():
    """node conversion / tuple elements and rest"""
    schema = S.TupleWithRest(S.Tuple(S.String, S.optional_key(S.Number)), S.Boolean)
    assert R.to_representation(schema) == doc(
        R.Arrays(
            (R.Element(R.String()), R.Element(R.Number(), is_optional=True)),
            (R.Boolean(),),
        )
    )


def test_object_properties_and_index_signatures():
    """node conversion / object properties and index signatures"""

    class Fields(TypedDict):
        required: str
        optional: NotRequired[float]

    schema = S.StructWithRest(S.Struct(Fields), S.Record(S.String, S.BigInt))
    assert R.to_representation(schema) == doc(
        R.Objects(
            (
                R.PropertySignature("required", R.String()),
                R.PropertySignature("optional", R.Number(), is_optional=True),
            ),
            (R.IndexSignature(R.String(), R.BigInt()),),
        )
    )


def test_union_member_order():
    """node conversion / union member order"""
    assert R.to_representation(S.Union(S.String, S.BigInt)) == doc(
        R.Union((R.String(), R.BigInt()))
    )


def test_preserves_supplied_union_options_and_omits_absent_options():
    """node conversion / preserves supplied Union options and omits absent options"""
    one_of = R.to_representation(S.Union(S.String, S.Number, mode="one_of")).representation
    assert isinstance(one_of, R.Union)
    assert one_of.mode == "one_of"
    any_of = R.to_representation(S.Union(S.String, S.Number)).representation
    assert isinstance(any_of, R.Union)
    assert any_of.mode == "any_of"


# ------------------------------------------------- encoded and type projections


def test_preserves_json_content_despite_conflicting_annotations():
    """encoded and type projections / preserves JSON content despite conflicting annotations"""
    schema = S.from_json_string(S.Boolean).annotate_encoded(
        content_media_type="text/plain", content_schema={"type": "string"}
    )
    out = R.to_representation(schema).representation
    assert isinstance(out, R.String)
    assert out.content == R.Content("application/json", R.Boolean())
    assert out.annotations is not None
    assert out.annotations["content_media_type"] == "text/plain"
    assert out.annotations["content_schema"] == {"type": "string"}


def test_uses_the_encoded_side_of_a_transformation():
    """encoded and type projections / uses the encoded side of a transformation"""
    assert R.to_representation(S.NumberFromString) == doc(
        R.String(annotations={"expected": "a string that will be decoded as a number"})
    )


def test_uses_a_type_side_identifier_as_a_fallback_for_the_encoded_representation():
    """encoded and type projections / uses a type-side identifier as a fallback for the encoded representation"""  # noqa: E501
    schema = S.NumberFromString.annotate(identifier="Finite")
    assert R.to_representation(schema) == doc(
        R.Reference("FiniteEncoded"),
        {
            "FiniteEncoded": R.String(
                annotations={
                    "expected": "a string that will be decoded as a number",
                    "~identifier": "Finite",
                }
            )
        },
    )


def test_prefers_an_explicit_encoded_side_identifier_over_a_type_side_identifier():
    """encoded and type projections / prefers an explicit encoded-side identifier over a type-side identifier"""  # noqa: E501
    schema = S.NumberFromString.annotate_encoded(identifier="EncodedFinite").annotate(
        identifier="Finite"
    )
    assert R.to_representation(schema) == doc(
        R.Reference("EncodedFinite"),
        {
            "EncodedFinite": R.String(
                annotations={
                    "expected": "a string that will be decoded as a number",
                    "identifier": "EncodedFinite",
                }
            )
        },
    )


def test_overrides_an_encoded_side_fallback_with_the_type_side_identifier():
    """encoded and type projections / overrides an encoded-side fallback with the type-side identifier"""  # noqa: E501
    schema = S.NumberFromString.annotate_encoded(**{"~identifier": "Previous"}).annotate(
        identifier="Finite"
    )
    assert R.to_representation(schema) == doc(
        R.Reference("FiniteEncoded"),
        {
            "FiniteEncoded": R.String(
                annotations={
                    "expected": "a string that will be decoded as a number",
                    "~identifier": "Finite",
                }
            )
        },
    )


def test_uses_the_type_side_when_the_caller_projects_it():
    """encoded and type projections / uses the type side when the caller projects it"""
    assert R.to_representation(S.to_type(S.NumberFromString)) == doc(R.Number())


# -------------------------------------------- schema annotations and declarations


def test_preserves_declaration_code_callbacks():
    """schema annotations and declarations / preserves declaration code callbacks"""

    def to_code(_: object) -> R.Code:
        return R.make_code("Custom", "str")

    schema = S.declare(
        _is_str,
        representation={"id": "acme/schema/Custom", "payload": None},
        to_code=to_code,
    )
    assert R.to_representation(schema) == doc(
        R.Declaration(
            annotations={"to_code": to_code},
            representation=R.RepresentationAnnotation("acme/schema/Custom", None),
        )
    )


def test_converts_declaration_type_parameters():
    """schema annotations and declarations / converts declaration type parameters"""
    out = R.to_representation(S.Option(S.Number)).representation
    assert isinstance(out, R.Declaration)
    assert out.type_parameters == (R.Number(),)


# --------------------------------------------------------------------- checks


def test_preserves_custom_filter_callbacks_dependencies_and_aborted_state():
    """checks / preserves custom filter callbacks, dependencies and aborted state"""

    def to_code(_: object) -> object:
        return {"runtime": "Custom"}

    def to_json_schema(_: object) -> object:
        return {"minLength": 1}

    def marker() -> str:
        return "marker"

    check = S.make_filter(
        _always,
        representation={
            "id": "acme/schema/Custom",
            "payload": {"minimum": 1},
            "schemas": (S.Number.ast,),
        },
        to_code=to_code,
        to_json_schema=to_json_schema,
        marker=marker,
    ).abort()
    assert R.to_representation(S.String.check(check)) == doc(
        R.String(
            checks=(
                R.Filter(
                    R.CheckRepresentationAnnotation(
                        "acme/schema/Custom", {"minimum": 1}, (R.Number(),)
                    ),
                    {"to_code": to_code, "to_json_schema": to_json_schema, "marker": marker},
                    aborted=True,
                ),
            )
        )
    )


def test_preserves_filters_without_persistence_metadata():
    """checks / preserves filters without persistence metadata"""
    check = S.make_filter(_always, expected="custom")
    assert R.to_representation(S.String.check(check)) == doc(
        R.String(checks=(R.Filter(annotations={"expected": "custom"}),))
    )


def test_preserves_a_filter_without_annotations():
    """checks / preserves a filter without annotations"""
    check = S.make_filter(_always)
    assert R.to_representation(S.String.check(check)) == doc(R.String(checks=(R.Filter(),)))


def test_preserves_filter_groups():
    """checks / preserves filter groups"""
    first = S.make_filter(_always, expected="first")
    second = S.make_filter(_always, expected="second")
    group = S.make_filter_group(first, second, description="group")
    assert R.to_representation(S.String.check(group)) == doc(
        R.String(
            checks=(
                R.FilterGroup(
                    (
                        R.Filter(annotations={"expected": "first"}),
                        R.Filter(annotations={"expected": "second"}),
                    ),
                    annotations={"description": "group"},
                ),
            )
        )
    )


def test_converts_representation_dependencies_of_built_in_filters():
    """checks / converts representation dependencies of built-in filters"""
    schema = S.Record(S.String, S.Number).check(
        S.is_property_names(S.String.check(S.is_pattern("^[A-Z]")))
    )
    out = R.to_representation(schema).representation
    assert isinstance(out, R.Objects)
    check = out.checks[0]
    assert isinstance(check, R.Filter)
    assert check.representation is not None
    assert check.representation.schemas is not None
    dependency = check.representation.schemas[0]
    assert R.to_json(doc(dependency)) == {
        "representation": {
            "_tag": "String",
            "checks": [
                {
                    "_tag": "Filter",
                    "representation": {
                        "id": "effect/schema/isPattern",
                        "payload": {"source": "^[A-Z]", "flags": 32},
                    },
                    "annotations": {"expected": "a string matching the RegExp ^[A-Z]"},
                    "aborted": False,
                }
            ],
        },
        "references": {},
    }


def test_extracts_shared_representation_dependencies_of_filters():
    """checks / extracts shared representation dependencies of filters"""

    class Shared(TypedDict):
        value: str

    shared = S.Struct(Shared)
    check = S.make_filter(
        _always,
        representation={
            "id": "acme/schema/Custom",
            "payload": None,
            "schemas": (shared.ast, shared.ast),
        },
    )

    def policy(candidate: R.ReferenceCandidate) -> str | None:
        return f"{candidate.ast.tag}_" if candidate.occurrences > 1 else None

    document = R.to_representation(S.String.check(check), reference_policy=policy)
    out = document.representation
    assert isinstance(out, R.String)
    identity = out.checks[0].representation
    assert identity is not None
    assert identity.schemas == (R.Reference("Objects_"), R.Reference("Objects_"))
    assert list(document.references) == ["Objects_"]


def test_converts_checks_on_arrays():
    """checks / converts checks on arrays"""
    out = R.to_representation(S.Array(S.String).check(S.is_min_length(1))).representation
    assert isinstance(out, R.Arrays)
    assert len(out.checks) == 1
    assert out.checks[0].representation == R.CheckRepresentationAnnotation(
        "effect/schema/isMinLength", {"minLength": 1}
    )


def test_converts_checks_on_objects():
    """checks / converts checks on objects"""
    schema = S.Record(S.String, S.Number).check(S.is_min_properties(1))
    out = R.to_representation(schema).representation
    assert isinstance(out, R.Objects)
    assert len(out.checks) == 1
    assert out.checks[0].representation == R.CheckRepresentationAnnotation(
        "effect/schema/isMinProperties", {"minProperties": 1}
    )


# --------------------------------------------------------- contextual annotations


class _Value(TypedDict):
    value: float


def test_preserves_from_json_string_annotations():
    """contextual annotations / preserves fromJsonString annotations"""
    schema = S.to_encoded(S.from_json_string(S.Struct(_Value)))
    assert R.to_representation(schema) == doc(
        R.String(annotations={"expected": "a string that will be decoded as JSON"})
    )


def test_preserves_tuple_element_annotations():
    """contextual annotations / preserves tuple element annotations"""

    def marker() -> str:
        return "element"

    schema = S.Tuple(S.String.annotate_key(description="element", marker=marker))
    assert R.to_representation(schema) == doc(
        R.Arrays((R.Element(R.String(), annotations={"description": "element", "marker": marker}),))
    )


def test_preserves_property_annotations():
    """contextual annotations / preserves property annotations"""

    def marker() -> str:
        return "property"

    class Fields(TypedDict):
        value: str

    schema = S.Struct(Fields, value=S.String.annotate_key(description="property", marker=marker))
    assert R.to_representation(schema) == doc(
        R.Objects(
            (
                R.PropertySignature(
                    "value", R.String(), annotations={"description": "property", "marker": marker}
                ),
            )
        )
    )


# ------------------------------------------------------------ reference policies


class _Named(TypedDict):
    value: str


def test_extracts_only_candidates_with_identifiers_by_default():
    """reference policies / extracts only candidates with identifiers by default"""
    anonymous = S.Struct(_Named)
    identified = S.Struct(_Named).annotate(identifier="Identified")
    document = R.to_representation(S.Tuple(anonymous, identified))
    assert list(document.references) == ["Identified"]
    out = document.representation
    assert isinstance(out, R.Arrays)
    assert [e.type.tag for e in out.elements] == ["Objects", "Reference"]


def test_allows_a_policy_to_inline_an_explicitly_identified_schema():
    """reference policies / allows a policy to inline an explicitly identified schema"""
    schema = S.String.annotate(identifier="Value")
    assert R.to_representation(schema, reference_policy=lambda _: None) == doc(
        R.String(annotations={"identifier": "Value"})
    )


class _Node(TypedDict):
    next: NotRequired["_Node"]


def _recursive_node(identifier: str) -> S.Codec[Any, Any]:
    node: S.Codec[Any, Any] = S.Struct(_Node, next=S.suspend(lambda: node)).annotate(
        identifier=identifier
    )
    return node


def test_forces_a_synthetic_reference_when_a_policy_inlines_a_recursive_schema():
    """reference policies / forces a synthetic reference when a policy inlines a recursive schema"""
    document = R.to_representation(_recursive_node("Node"), reference_policy=lambda _: None)
    assert document.representation == R.Reference("Objects_")
    assert list(document.references) == ["Objects_"]


# --------------------------------------------------- reference allocation and recursion


def test_extracts_a_named_schema_into_references():
    """reference allocation and recursion / extracts a named schema into references"""
    schema = S.String.annotate(identifier="Value", description="value")
    assert R.to_representation(schema) == doc(
        R.Reference("Value"),
        {"Value": R.String(annotations={"identifier": "Value", "description": "value"})},
    )


def test_supports_proto_as_an_identifier():
    """reference allocation and recursion / supports __proto__ as an identifier"""
    document = R.to_representation(S.String.annotate(identifier="__proto__"))
    assert document.representation == R.Reference("__proto__")
    assert list(document.references) == ["__proto__"]
    assert document.references["__proto__"].tag == "String"


def test_converts_a_non_recursive_suspend():
    """reference allocation and recursion / converts a non-recursive suspend"""
    assert R.to_representation(S.suspend(lambda: S.String)) == doc(R.Suspend(R.String()))


def _node_body(ref: str, identifier: str) -> R.Objects:
    return R.Objects(
        (R.PropertySignature("next", R.Suspend(R.Reference(ref)), is_optional=True),),
        annotations={"identifier": identifier},
    )


def test_uses_an_outer_identifier_for_a_recursive_schema():
    """reference allocation and recursion / uses an outer identifier for a recursive schema"""
    assert R.to_representation(_recursive_node("Node")) == doc(
        R.Reference("Node"), {"Node": _node_body("Node", "Node")}
    )


def test_suffixes_duplicate_identifiers_on_recursive_schemas():
    """reference allocation and recursion / suffixes duplicate identifiers on recursive schemas"""
    schema = S.Tuple(_recursive_node("Node"), _recursive_node("Node"))
    assert R.to_representation(schema) == doc(
        R.Arrays((R.Element(R.Reference("Node")), R.Element(R.Reference("Node_1")))),
        {"Node": _node_body("Node", "Node"), "Node_1": _node_body("Node_1", "Node_1")},
    )


def test_does_not_resolve_an_identifier_below_a_check():
    """reference allocation and recursion / does not resolve an identifier below a check"""
    schema = S.String.annotate(identifier="Text").check(S.is_min_length(1))
    document = R.to_representation(schema)
    out = document.representation
    assert isinstance(out, R.String)
    assert document.references == {}
    assert out.annotations == {"identifier": "Text"}
    assert len(out.checks) == 1
    identity = out.checks[0].representation
    assert identity is not None
    assert identity.id == "effect/schema/isMinLength"


def test_uses_a_fallback_identifier_for_encoded_representations():
    """reference allocation and recursion / uses a fallback identifier for encoded representations"""  # noqa: E501
    schema = S.String.annotate(**{"~identifier": "Person"})
    assert R.to_representation(schema) == doc(
        R.Reference("PersonEncoded"),
        {"PersonEncoded": R.String(annotations={"~identifier": "Person"})},
    )


def test_prefers_an_identifier_over_a_fallback_identifier():
    """reference allocation and recursion / prefers an identifier over a fallback identifier"""
    schema = S.String.annotate(identifier="EncodedPerson", **{"~identifier": "Person"})
    document = R.to_representation(schema)
    assert document.representation == R.Reference("EncodedPerson")
    assert list(document.references) == ["EncodedPerson"]


def test_reuses_a_class_identifier_across_repeated_type_side_occurrences():
    """reference allocation and recursion / reuses a Class identifier across repeated type-side occurrences"""  # noqa: E501

    class User(S.Class):
        name: str

    document = R.to_representation(S.to_type(S.Tuple(User, User)))
    assert document.representation == R.Arrays(
        (R.Element(R.Reference("User")), R.Element(R.Reference("User")))
    )
    assert list(document.references) == ["User"]


def test_extracts_anonymous_recursion_into_references():
    """reference allocation and recursion / extracts anonymous recursion into references"""
    schema: S.Codec[Any, Any] = S.suspend(lambda: schema)
    assert R.to_representation(schema) == doc(
        R.Reference("Suspend_"), {"Suspend_": R.Suspend(R.Reference("Suspend_"))}
    )


def test_ast_union_options_kept():
    """node conversion / preserves supplied Union options and omits absent options (AST)"""
    union = ast.Union((ast.string, ast.number), "one_of")
    out = R.to_representation(S.Bottom(union)).representation
    assert isinstance(out, R.Union)
    assert out.mode == "one_of"
