"""Ports of Effect's ``schema/representation/fromRepresentation.test.ts``
and ``fromRepresentations.test.ts``. Each test's docstring is the Effect
test title. See ``test_schema_representation_to.py`` for the Python
mappings; a reviver error is a ``RepresentationError`` (a ``ValueError``)
whose message ends with the document path (snake_case field names).

Omitted:
- No such schemas in pyfect (§4: ``Schema.Undefined``, ``Void``, ``Symbol``):
  "revives Undefined", "revives Void", "revives Symbol", "revives
  ObjectKeyword", "revives UniqueSymbol".
- "revives Struct": ported without the ``mutableKey`` field (no mutable
  keys); "revives StructWithRest": with a string record (no symbol keys).
- "revives Literal without changing its type": ported for strings,
  numbers and booleans; a Python ``int`` is both Effect's number and
  bigint, so ``1n`` has no literal of its own.
"""

import enum
from collections.abc import Mapping, Sequence
from typing import Any, NewType, NotRequired, TypedDict, TypeIs, cast

import pytest

from pyfect import schema as S
from pyfect.brand import Brand
from pyfect.result import Err
from pyfect.schema import ast
from pyfect.schema import representation as R

_Int = NewType("_Int", float)
_Positive = NewType("_Positive", float)

FILTER_ID = "acme/schema/minLength"


def checks_of(node: ast.AST) -> Sequence[ast.Check[Any]]:
    return node.checks or ()


def codec(schema: object) -> S.Codec[Any, Any]:
    """A revived schema, typed for decoding (Effect's ``as Schema.Codec<unknown>``)."""
    return cast("S.Codec[Any, Any]", schema)


def min_length_check(minimum: int, **annotations: object) -> ast.Filter[str]:
    def long_enough(value: str) -> bool:
        return len(value) >= minimum

    representation = {"id": FILTER_ID, "payload": {"minimum": minimum}}
    return ast.filter_of(long_enough, {"representation": representation, **annotations}, False)


class _Minimum(TypedDict):
    minimum: float


min_length_reviver = R.make_reviver_filter(
    FILTER_ID,
    S.Struct(_Minimum),
    lambda input: min_length_check(int(input.payload["minimum"]), **(input.annotations or {})),
)


def revive(schema: S.Top, revivers: Sequence[R.AnyReviver] = ()) -> R.AnySchema:
    persisted = R.to_json(R.to_representation(schema))
    return R.from_representation(R.from_json(persisted), revivers=revivers)


def assert_roundtrip(schema: S.Top, revivers: Sequence[R.AnyReviver] = ()) -> R.AnySchema:
    expected = R.to_json(R.to_representation(schema))
    revived = R.from_representation(R.from_json(expected), revivers=revivers)
    assert R.to_json(R.to_representation(revived)) == expected
    return revived


def annotations_of(node: ast.AST | ast.Check[Any]) -> Mapping[str, object]:
    return node.annotations or {}


def is_(schema: S.Top, value: object) -> bool:
    return S.is_(codec(schema))(value)


def filter_json() -> R.Json:
    return R.to_json(R.to_representation(S.String.check(min_length_check(2))))


def test_revives_null():
    """revives Null"""
    assert_roundtrip(S.Null)


def test_revives_never():
    """revives Never"""
    assert_roundtrip(S.Never)


def test_revives_unknown():
    """revives Unknown"""
    assert_roundtrip(S.Unknown)


def test_revives_any():
    """revives Any"""
    assert_roundtrip(S.Any)


def test_revives_string():
    """revives String"""
    assert_roundtrip(S.String)


def test_revives_a_string_with_content_without_parsing_its_value():
    """revives a string with content without parsing its value"""
    schema = revive(S.from_json_string(S.Boolean))
    assert S.decode_unknown_sync(codec(schema))("not JSON") == "not JSON"
    assert not is_(schema, True)


def test_revives_number():
    """revives Number"""
    assert_roundtrip(S.Number)


def test_revives_boolean():
    """revives Boolean"""
    assert_roundtrip(S.Boolean)


def test_revives_big_int():
    """revives BigInt"""
    assert_roundtrip(S.BigInt)


def test_revives_literal_without_changing_its_type():
    """revives Literal without changing its type"""
    for schema, literal, different in (
        (S.Literal("1"), "1", 1),
        (S.Literal("true"), "true", True),
        (S.Literal(1), 1, "1"),
        (S.Literal(True), True, "true"),
    ):
        revived = assert_roundtrip(schema)
        assert is_(revived, literal)
        assert not is_(revived, different)


def test_revives_enum():
    """revives Enum"""

    class E(enum.Enum):
        A = "a"
        One = 1

    schema = assert_roundtrip(S.Enum(E))
    # An enum decodes its values to members (Effect's ``is`` takes values).
    assert S.decode_unknown_sync(codec(schema))("a").name == "A"
    assert S.decode_unknown_sync(codec(schema))(1).name == "One"
    assert isinstance(S.decode_unknown_result(codec(schema))("other"), Err)


def test_rejects_non_finite_numeric_enum_values():
    """rejects non-finite numeric Enum values"""
    document = R.Document(R.Enum((("NumberNaN", float("nan")),)))
    with pytest.raises(ValueError, match="A numeric enum value must be finite, got NaN"):
        R.from_representation(document, revivers=())


def test_revives_template_literal():
    """revives TemplateLiteral"""
    schema = assert_roundtrip(S.TemplateLiteral("prefix-", S.String))
    assert is_(schema, "prefix-value")
    assert not is_(schema, "value")


def test_revives_a_reference_in_template_literal_as_a_concrete_part():
    """revives a reference in TemplateLiteral as a concrete part"""
    schema = assert_roundtrip(S.TemplateLiteral("prefix-", S.String.annotate(identifier="Part")))
    node = schema.ast
    assert isinstance(node, ast.TemplateLiteral)
    assert node.parts[1].tag == "String"
    assert is_(schema, "prefix-value")


def test_revives_nested_references_in_a_template_literal_union():
    """revives nested references in a TemplateLiteral union"""
    part = S.Union(
        S.Literal("a").annotate(identifier="A"), S.Literal("b").annotate(identifier="B")
    ).annotate(identifier="Part")
    schema = assert_roundtrip(S.TemplateLiteral("prefix-", part))
    assert is_(schema, "prefix-a")
    assert is_(schema, "prefix-b")
    assert not is_(schema, "prefix-c")


def test_revives_tuple():
    """revives Tuple"""
    assert_roundtrip(S.Tuple(S.String, S.optional_key(S.Number)))


def test_revives_array():
    """revives Array"""
    assert_roundtrip(S.Array(S.String))


def test_revives_tuple_with_rest():
    """revives TupleWithRest"""
    assert_roundtrip(S.TupleWithRest(S.Tuple(S.String), S.Number, S.Boolean))


def test_revives_struct():
    """revives Struct"""

    class Fields(TypedDict):
        required: str
        optional: NotRequired[float]

    assert_roundtrip(S.Struct(Fields))


def test_revives_record():
    """revives Record"""
    assert_roundtrip(S.Record(S.String, S.Number))


def test_revives_a_reference_used_as_a_record_key():
    """revives a reference used as a Record key"""
    schema = assert_roundtrip(S.Record(S.String.annotate(identifier="Key"), S.Number))
    node = schema.ast
    assert isinstance(node, ast.Objects)
    assert node.index_signatures[0].parameter.tag == "String"
    assert S.decode_unknown_sync(codec(schema))({"a": 1}) == {"a": 1}


def test_revives_struct_with_rest():
    """revives StructWithRest"""

    class Fields(TypedDict):
        value: float

    assert_roundtrip(S.StructWithRest(S.Struct(Fields), S.Record(S.String, S.Number)))


def test_revives_union():
    """revives Union"""
    schema = assert_roundtrip(S.Union(S.String, S.Number))
    assert is_(schema, "value")
    assert is_(schema, 1)
    assert not is_(schema, True)


def test_revives_union_options_through_live_and_json_representation_roundtrips():
    """revives Union options through live and JSON representation roundtrips"""
    document = R.Document(R.Union((R.String(), R.Number()), "one_of"))
    revived = R.from_representation(document, revivers=())
    assert isinstance(revived.ast, ast.Union)
    assert revived.ast.mode == "one_of"
    persisted = R.from_representation(R.from_json(R.to_json(document)), revivers=())
    assert isinstance(persisted.ast, ast.Union)
    assert persisted.ast.mode == "one_of"


def test_revives_an_empty_union_as_never():
    """revives an empty Union as Never"""
    schema = R.from_representation(R.Document(R.Union(())), revivers=())
    assert not is_(schema, None)
    assert not is_(schema, 0)


class _Category(TypedDict):
    name: str
    children: Sequence["_Category"]


def test_revives_suspend():
    """revives Suspend"""
    category: S.Codec[Any, Any] = S.Struct(
        _Category, children=S.Array(S.suspend(lambda: category))
    ).annotate(identifier="Category")
    schema = revive(category)
    node = schema.ast
    assert isinstance(node, ast.Objects)
    children = next(p for p in node.properties if p.name == "children")
    assert isinstance(children.type, ast.Arrays)
    assert children.type.rest[0].tag == "Suspend"
    value: dict[str, object] = {"name": "root", "children": [{"name": "child", "children": []}]}
    decoded: dict[str, object] = {"name": "root", "children": ({"name": "child", "children": ()},)}
    assert S.decode_unknown_sync(codec(schema))(value) == decoded
    assert R.to_representation(schema).representation.tag == "Reference"


def test_restores_node_annotations():
    """restores node annotations"""
    schema = revive(S.String.annotate(title="Name"))
    assert (schema.ast.annotations or {})["title"] == "Name"


def test_restores_node_annotations_before_checks():
    """restores node annotations before checks"""
    schema = assert_roundtrip(
        S.String.annotate(title="node").check(min_length_check(2, description="check")),
        [min_length_reviver],
    )
    first = checks_of(schema.ast)[0]
    assert annotations_of(schema.ast)["title"] == "node"
    assert annotations_of(first)["description"] == "check"
    assert "title" not in annotations_of(first)


def test_restores_tuple_element_annotations():
    """restores tuple element annotations"""
    schema = revive(S.Tuple(S.String.annotate_key(description="element")))
    out = R.to_representation(schema).representation
    assert isinstance(out, R.Arrays)
    assert (out.elements[0].annotations or {})["description"] == "element"


def test_restores_property_annotations():
    """restores property annotations"""

    class Fields(TypedDict):
        value: str

    schema = revive(S.Struct(Fields, value=S.String.annotate_key(description="property")))
    out = R.to_representation(schema).representation
    assert isinstance(out, R.Objects)
    assert (out.property_signatures[0].annotations or {})["description"] == "property"


def test_restores_checks_added_by_from_brand():
    """restores checks added by fromBrand"""
    int_brand = Brand[float, _Int].check(S.is_int())
    positive = Brand[float, _Positive].check(S.is_greater_than(0))
    schema = S.Number.pipe(S.from_brand(int_brand)).pipe(S.from_brand(positive))
    restored = assert_roundtrip(schema, [R.is_int_reviver, R.is_greater_than_reviver])
    assert is_(restored, 1)
    assert not is_(restored, 1.2)
    assert not is_(restored, -1)


def test_restores_a_node_representation_annotation_without_schema_dependencies():
    """restores a node representation annotation without schema dependencies"""
    assert_roundtrip(
        S.String.annotate(representation={"id": "acme/schema/String", "payload": None})
    )


def test_restores_a_node_representation_annotation_with_schema_dependencies():
    """restores a node representation annotation with schema dependencies"""
    assert_roundtrip(
        S.String.annotate(
            representation={"id": "acme/schema/String", "payload": None, "schemas": (S.Number.ast,)}
        )
    )


def test_revives_a_filter():
    """revives a Filter"""
    schema = assert_roundtrip(
        S.String.check(min_length_check(2, description="at least two").abort()),
        [min_length_reviver],
    )
    assert isinstance(S.decode_unknown_result(codec(schema))("a"), Err)
    check = checks_of(schema.ast)[0]
    assert isinstance(check, ast.Filter)
    assert check.aborted
    assert annotations_of(check)["description"] == "at least two"


def test_revives_a_filter_group_without_an_identity_from_its_children():
    """revives a FilterGroup without an identity from its children"""
    group = S.make_filter_group(min_length_check(2), min_length_check(3), description="both")
    schema = assert_roundtrip(S.String.check(group), [min_length_reviver])
    assert isinstance(S.decode_unknown_result(codec(schema))("ab"), Err)
    assert annotations_of(checks_of(schema.ast)[0])["description"] == "both"


def test_uses_an_identified_filter_group_reviver_instead_of_its_persisted_children():
    """uses an identified FilterGroup reviver instead of its persisted children"""
    group_id = "acme/schema/group"
    document = R.from_json(
        {
            "representation": {
                "_tag": "String",
                "checks": [
                    {
                        "_tag": "FilterGroup",
                        "representation": {"id": group_id, "payload": None},
                        "checks": [
                            {
                                "_tag": "Filter",
                                "representation": {"id": FILTER_ID, "payload": {"minimum": 1}},
                                "aborted": False,
                            }
                        ],
                    }
                ],
            },
            "references": {},
        }
    )
    reviver = R.make_reviver_filter_group(
        group_id, S.Null, lambda _: S.make_filter_group(S.make_filter(lambda v: v != "blocked"))
    )
    schema = R.from_representation(document, revivers=[reviver])
    assert S.decode_unknown_sync(codec(schema))("allowed") == "allowed"
    assert isinstance(S.decode_unknown_result(codec(schema))("blocked"), Err)


class _Label(TypedDict):
    label: str


def _is_box(value: object) -> TypeIs[Mapping[str, object]]:
    return isinstance(value, Mapping) and isinstance(
        cast("Mapping[str, object]", value).get("value"), str
    )


def test_revives_a_declaration():
    """revives a Declaration"""
    box_id = "acme/schema/Box"
    box = S.declare(_is_box, representation={"id": box_id, "payload": {"label": "Box"}})

    def revive_box(input: R.DeclarationInput[_Label]) -> S.Top:
        representation = {"id": box_id, "payload": dict(input.payload)}
        return S.declare(_is_box, **{**(input.annotations or {}), "representation": representation})

    reviver = R.make_reviver_declaration(box_id, S.Struct(_Label), revive_box)
    schema = assert_roundtrip(box, [reviver])
    assert S.decode_unknown_sync(codec(schema))({"value": "ok"}) == {"value": "ok"}


def test_reports_a_missing_reviver():
    """reports a missing reviver"""
    with pytest.raises(R.RepresentationError) as error:
        R.from_representation(R.from_json(filter_json()), revivers=[])
    assert str(error.value) == (
        f'Missing reviver for {FILTER_ID}\n  at ["representation"]["checks"][0]["representation"]'
    )


def test_rejects_duplicate_reviver_ids():
    """rejects duplicate reviver IDs"""
    with pytest.raises(R.RepresentationError) as error:
        R.from_representation(
            R.Document(R.String()), revivers=[min_length_reviver, min_length_reviver]
        )
    assert str(error.value) == f'Duplicate reviver for {FILTER_ID}\n  at ["revivers"][1]["id"]'


def test_rejects_an_invalid_reviver_payload():
    """rejects an invalid reviver payload"""
    persisted: Any = filter_json()
    persisted["representation"]["checks"][0]["representation"]["payload"] = {"minimum": "two"}
    with pytest.raises(R.RepresentationError) as error:
        R.from_representation(R.from_json(persisted), revivers=[min_length_reviver])
    assert str(error.value) == (
        f"Invalid representation payload for {FILTER_ID}\n"
        '  at ["representation"]["checks"][0]["representation"]["payload"]'
    )


def test_preserves_a_reviver_exception_by_identity():
    """preserves a reviver exception by identity"""
    cause = RuntimeError("boom")

    def boom(_: object) -> ast.Filter[Any]:
        raise cause

    reviver = R.make_reviver_filter(FILTER_ID, S.Struct(_Minimum), boom)
    with pytest.raises(RuntimeError) as error:
        R.from_representation(R.from_json(filter_json()), revivers=[reviver])
    assert error.value is cause


def test_requires_a_representation_identity_on_a_filter():
    """requires a representation identity on a Filter"""
    with pytest.raises(R.RepresentationError) as error:
        R.from_representation(R.Document(R.String(checks=(R.Filter(),))), revivers=[])
    assert str(error.value) == (
        'Missing representation annotation\n  at ["representation"]["checks"][0]["representation"]'
    )


def test_requires_a_representation_identity_on_a_declaration():
    """requires a representation identity on a Declaration"""
    with pytest.raises(R.RepresentationError) as error:
        R.from_representation(R.Document(R.Declaration()), revivers=[])
    assert str(error.value) == (
        'Missing representation annotation\n  at ["representation"]["representation"]'
    )


def test_reports_an_invalid_reference():
    """reports an invalid reference"""
    with pytest.raises(R.RepresentationError) as error:
        R.from_representation(R.Document(R.Reference("Missing")), revivers=[])
    assert str(error.value) == 'Invalid reference Missing\n  at ["representation"]["$ref"]'


# ------------------------------------------------------- fromRepresentations


def test_preserves_root_order():
    """SchemaRepresentation.fromRepresentations / preserves root order"""
    roots = R.from_representations(
        R.MultiDocument((R.String(), R.Number(), R.Boolean())), revivers=[]
    )
    assert [r.ast.tag for r in roots] == ["String", "Number", "Boolean"]


def test_does_not_revive_unreachable_references():
    """SchemaRepresentation.fromRepresentations / does not revive unreachable references"""
    document = R.MultiDocument(
        (R.String(),),
        {"Unused": R.Declaration(representation=R.RepresentationAnnotation("missing", None))},
    )
    (root,) = R.from_representations(document, revivers=[])
    assert root.ast.tag == "String"


def test_normalizes_aliases_while_preserving_the_outer_reference():
    """SchemaRepresentation.fromRepresentations / normalizes aliases while preserving the outer reference"""  # noqa: E501
    document = R.MultiDocument(
        (R.Reference("Alias"),), {"Alias": R.Reference("Target"), "Target": R.String()}
    )
    (root,) = R.from_representations(document, revivers=[])
    assert root.ast.tag == "String"
    assert (root.ast.annotations or {})["identifier"] == "Alias"
    out = R.to_representation(root)
    assert out.representation == R.Reference("Alias")


def test_shares_a_resolved_reference_between_roots():
    """SchemaRepresentation.fromRepresentations / shares a resolved reference between roots"""
    document = R.MultiDocument(
        (R.Reference("Shared"), R.Reference("Shared")), {"Shared": R.String()}
    )
    first, second = R.from_representations(document, revivers=[])
    assert first.ast is second.ast


def test_resolves_a_reachable_proto_reference():
    """SchemaRepresentation.fromRepresentations / resolves a reachable __proto__ reference"""
    document = R.MultiDocument((R.Reference("__proto__"),), {"__proto__": R.String()})
    (root,) = R.from_representations(document, revivers=[])
    assert is_(root, "value")


def _list_node(ref: str) -> R.Objects:
    return R.Objects(
        (
            R.PropertySignature("value", R.Number()),
            R.PropertySignature("next", R.Reference(ref), is_optional=True),
        )
    )


def test_revives_recursive_definitions():
    """SchemaRepresentation.fromRepresentations / revives recursive definitions"""
    document = R.MultiDocument((R.Reference("Node"),), {"Node": _list_node("Node")})
    (root,) = R.from_representations(document, revivers=[])
    assert isinstance(root.ast, ast.Objects)
    assert root.ast.properties[1].type.tag == "Suspend"
    value = {"value": 1, "next": {"value": 2}}
    assert S.decode_unknown_sync(codec(root))(value) == value
    assert isinstance(
        S.decode_unknown_result(codec(root))({"value": 1, "next": {"value": "x"}}), Err
    )


def test_revives_mutually_recursive_definitions_with_concrete_roots():
    """SchemaRepresentation.fromRepresentations / revives mutually recursive definitions with concrete roots"""  # noqa: E501
    document = R.MultiDocument(
        (R.Reference("A"), R.Reference("B")),
        {
            "A": R.Objects((R.PropertySignature("b", R.Reference("B"), is_optional=True),)),
            "B": R.Objects((R.PropertySignature("a", R.Reference("A"), is_optional=True),)),
        },
    )
    a, b = R.from_representations(document, revivers=[])
    assert a.ast.tag == "Objects"
    assert b.ast.tag == "Objects"
    assert S.decode_unknown_sync(codec(a))({"b": {"a": {}}}) == {"b": {"a": {}}}
    assert S.decode_unknown_sync(codec(b))({"a": {"b": {}}}) == {"a": {"b": {}}}
