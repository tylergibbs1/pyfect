"""Ports of Effect's ``SchemaAST.test.ts``: ``mapOrSame``, the AST updates,
the ``toType`` / ``toEncoded`` projections, ``collectSentinels``,
``getIndexSignatureKeys``, ``record`` and ``IndexSignature``. Each test's
docstring is the Effect test title, prefixed by its ``describe`` block.

Python mappings:
- ``SchemaAST.Context`` is the node's key fields (``optional_key``,
  ``key_annotations``, ``constructor_default``): ``new Context(true, false)``
  is ``optional_key=True``, and ``replaceContext(ast, undefined)`` is
  ``replace_context(ast, optional_key=False)``. ``getContextOwner`` is
  ``ast.owner()``.
- A subclass's enumerable symbol property is a field of a dataclass
  subclass; ``Object.freeze`` is a frozen dataclass.
- ``Suspend.thunk()`` (Effect memoizes the thunk) is ``Suspend.target``.
- A ``TemplateLiteral``'s prepared ``encodedParts`` is its ``segments``.
- A sentinel ``{ key, literal }`` is the pair ``(key, literal)``; a
  declaration's ``"~sentinels"`` annotation holds such pairs.
- ``getIndexSignatureKeys`` reads a Python mapping's keys: a ``Number``
  parameter takes the number keys (an ``int`` or a ``float``), as the record
  parser does, where JavaScript's object keys are strings.
"""

import enum
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, NotRequired, TypedDict, TypeIs

import pytest

from pyfect import effect as fx
from pyfect import schema as S
from pyfect.exit import Failure, Success
from pyfect.schema import getter as G
from pyfect.schema import transformation as T

ast = S.ast


def _decode(node: S.ast.AST) -> Callable[[object], object]:
    schema: S.Bottom[object, object] = S.Bottom(node)
    return S.decode_unknown_sync(schema)


def _fails(schema: S.Codec[Any, Any], input: object) -> bool:
    return isinstance(S.decode_unknown_exit(schema)(input), Failure)


def _passthrough() -> S.ast.Encoding:
    transformation: T.Transformation[object, object] = T.passthrough()
    return (ast.Link(ast.unknown, transformation),)


def _long_a(value: Mapping[str, Any]) -> bool:
    return len(value["a"]) > 1


def _positive_a(value: Mapping[str, Any]) -> bool:
    return value["a"] > 0


# --- mapOrSame ---------------------------------------------------------------------------


def test_map_or_same_returns_the_original_array_when_no_element_changes():
    """mapOrSame / returns the original array when no element changes"""
    items = ({"value": 1}, {"value": 2})
    assert ast.map_or_same(items, lambda value: value) is items


def test_map_or_same_returns_all_mapped_elements_when_an_element_changes():
    """mapOrSame / returns all mapped elements when an element changes"""
    first, second, third = {"value": 1}, {"value": 2}, {"value": 3}
    replacement = {"value": 4}
    items = (first, second, third)
    calls: list[None] = []

    def f(value: dict[str, int]) -> dict[str, int]:
        calls.append(None)
        return replacement if value is second else value

    output = ast.map_or_same(items, f)
    assert output == (first, replacement, third)
    assert output is not items
    assert len(calls) == len(items)


# --- AST updates -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True, eq=False)
class _MarkedObjects(S.ast.Objects):
    marker: dict[str, str] = field(default_factory=lambda: {"value": "custom"}, kw_only=True)


class _A(TypedDict):
    a: str


def test_ast_updates_preserves_the_prototype_children_and_enumerable_symbols_when_updating_a_frozen_node():  # noqa: E501
    """AST updates / preserves the prototype, children and enumerable symbols when updating a frozen node"""  # noqa: E501
    node = _MarkedObjects((ast.PropertySignature("a", ast.string),))
    checks: S.ast.Checks = (S.is_min_properties(1),)
    updated = ast.replace_checks(node, checks)

    assert updated is not node
    assert isinstance(updated, _MarkedObjects)
    assert updated.marker is node.marker
    assert updated.properties is node.properties
    assert updated.index_signatures is node.index_signatures
    assert updated.checks is checks
    assert node.checks is None
    assert _decode(updated)({"a": "value"}) == {"a": "value"}


def test_ast_updates_keeps_identity_for_unchanged_checks_encoding_and_context():
    """AST updates / keeps identity for unchanged checks, encoding and context"""
    node = S.NumberFromString.check(S.is_greater_than(0)).ast

    assert ast.replace_checks(node, node.checks) is node
    assert ast.replace_encoding(node, node.encoding) is node
    assert ast.replace_context(node) is node
    assert (
        ast.replace_context(
            node, key_annotations=node.key_annotations, optional_key=node.optional_key
        )
        is node
    )


def test_ast_updates_removes_encoding_without_changing_the_source_or_its_checks():
    """AST updates / removes encoding without changing the source or its checks"""
    node = S.NumberFromString.check(S.is_greater_than(0)).ast
    encoding = node.encoding
    updated = ast.replace_encoding(node, None)

    assert updated.encoding is None
    assert updated.checks is node.checks
    assert node.encoding is encoding
    assert encoding is not None
    assert _decode(updated)(1) == 1
    with pytest.raises(S.SchemaError):
        _decode(updated)(-1)


def test_ast_updates_restores_context_owners_without_losing_changes_made_to_a_contextual_node():
    """AST updates / restores context owners without losing changes made to a contextual node"""
    node = S.Struct(_A).ast
    contextual = ast.replace_context(node, optional_key=True)
    checks: S.ast.Checks = (S.is_min_properties(1),)
    checked = ast.replace_checks(contextual, checks)
    restored = ast.replace_context(checked, optional_key=False)

    assert contextual.owner() is node
    assert ast.replace_context(contextual, optional_key=False) is node
    assert checked.owner() is checked
    assert restored.checks is checks
    assert not restored.optional_key
    assert checked.optional_key
    assert not node.optional_key


def test_ast_updates_shares_prepared_template_data_when_merging_annotations():
    """AST updates / shares prepared template data when merging annotations"""
    node = S.TemplateLiteral("item-", S.String).ast
    assert isinstance(node, ast.TemplateLiteral)
    annotated = ast.annotate(node, {"title": "Item"})
    updated = ast.annotate(annotated, {"description": "An item identifier"})

    assert updated.parts is node.parts
    assert updated.segments is node.segments
    assert updated.literals is node.literals
    assert updated.suffix_lengths is node.suffix_lengths
    assert updated.annotations == {"title": "Item", "description": "An item identifier"}
    assert (annotated.annotations or {}).get("description") is None
    assert _decode(updated)("item-a") == "item-a"


class _Value(TypedDict):
    value: float


def test_ast_updates_restores_the_outer_context_without_restoring_an_earlier_encoding():
    """AST updates / restores the outer context without restoring an earlier encoding"""
    source = S.NumberFromString.ast
    optional = ast.optional_key(source)
    restored = ast.replace_context(optional, optional_key=source.optional_key)
    schema: S.Bottom[object, object] = S.Bottom(
        ast.Objects((ast.PropertySignature("value", restored),))
    )

    assert restored.encoding is optional.encoding
    assert not ast.is_optional(restored.to_type())
    assert ast.is_optional(ast.to_encoded(restored))
    assert S.decode_unknown_sync(schema)({"value": "1"}) == {"value": 1}
    assert _fails(schema, {})


def test_ast_updates_shares_the_memoized_suspended_thunk_when_copying_metadata():
    """AST updates / shares the memoized suspended thunk when copying metadata"""
    calls: list[None] = []

    def thunk() -> S.ast.AST:
        calls.append(None)
        return ast.string

    node = ast.Suspend(thunk)
    annotated = ast.annotate(node, {"title": "Suspended string"})

    assert calls == []
    assert annotated.thunk is node.thunk
    assert annotated.target is ast.string
    assert node.target is ast.string
    assert len(calls) == 1
    with pytest.raises(ValueError, match=r"^Cannot add checks to Suspend$"):
        ast.replace_checks(annotated, (S.is_min_length(1),))


def test_stores_constructor_defaults_directly_in_the_context():
    """stores constructor defaults directly in the context"""
    default = fx.succeed("default")
    node = ast.with_constructor_default(ast.string, default)
    assert node.constructor_default is default


def test_union_options_preserves_the_complete_options_object_through_recur_and_flip():
    """Union options / preserves the complete options object through recur and flip"""
    union = ast.Union((S.NumberFromString.ast, S.String.ast), mode="one_of")
    encoded = ast.to_encoded(union)
    flipped = union.flip()
    assert isinstance(encoded, ast.Union)
    assert isinstance(flipped, ast.Union)
    assert encoded.mode == "one_of"
    assert flipped.mode == "one_of"


# --- toType ------------------------------------------------------------------------------


def test_to_type_preserves_different_key_optionality_on_the_decoded_and_encoded_sides():
    """toType / preserves different key optionality on the decoded and encoded sides"""
    value: S.DecodeToSchema[float, str] = S.NumberFromString.pipe(
        S.with_decoding_default_key(fx.succeed("1"))
    )
    schema = S.Struct(_Value, value=value)

    assert not ast.is_optional(value.ast.to_type())
    assert ast.is_optional(ast.to_encoded(value.ast))
    assert S.decode_unknown_sync(schema)({}) == {"value": 1}
    assert S.decode_unknown_sync(S.to_encoded(schema))({}) == {}
    assert _fails(S.to_type(schema), {})


def test_to_type_preserves_declaration_parsers_when_projecting_contextual_copies():
    """toType / preserves declaration parsers when projecting contextual copies"""

    def parser(value: str) -> S.ast.DeclarationRun:
        return lambda _: lambda input, node, options: Success(value)

    node = ast.Declaration((), parser("decoded"), encoding_run=parser("encoded"))
    contextual = ast.optional_key(node)
    decoded = contextual.to_type()
    encoded = ast.to_encoded(contextual)

    assert ast.is_optional(decoded)
    assert ast.is_optional(encoded)
    assert _decode(decoded)("input") == "decoded"
    assert _decode(encoded)("input") == "encoded"
    assert _decode(contextual.flip().to_type())("input") == "encoded"


def test_to_type_removes_outer_encoding_and_promotes_checks_when_children_are_unchanged():
    """toType / removes outer encoding and promotes checks when children are unchanged"""
    encoding = _passthrough()
    check = S.make_filter(_long_a)
    node = ast.Objects(
        (ast.PropertySignature("a", ast.string),),
        annotations={"title": "Object"},
        encoding=encoding,
        optional_key=True,
        encoding_checks=(check,),
    )
    projected = node.to_type()

    assert projected.encoding is None
    assert projected.encoding_checks is None
    assert projected.checks is not None
    assert projected.checks[0] is check
    assert isinstance(projected, ast.Objects)
    assert projected.properties is node.properties
    assert projected.annotations is node.annotations
    assert projected.optional_key
    assert node.encoding is encoding
    assert node.encoding_checks is not None
    assert node.encoding_checks[0] is check
    assert node.to_type() is projected
    assert projected.to_type() is projected
    assert _decode(projected)({"a": "ab"}) == {"a": "ab"}
    with pytest.raises(S.SchemaError):
        _decode(projected)({"a": "a"})


def test_to_type_keeps_only_structural_encoding_checks_when_outer_encoding_and_child_encoding_are_removed():  # noqa: E501
    """toType / keeps only structural encoding checks when outer encoding and child encoding are removed"""  # noqa: E501
    structural = S.is_min_properties(1)
    encoded = S.make_filter(_long_a)
    decoded = S.make_filter(_positive_a)
    encoding = _passthrough()
    node = ast.Objects(
        (ast.PropertySignature("a", S.NumberFromString.ast),),
        checks=(decoded,),
        encoding=encoding,
        encoding_checks=(encoded.and_(structural),),
    )
    projected = node.to_type()

    assert isinstance(projected, ast.Objects)
    assert projected.encoding is None
    assert projected.encoding_checks is None
    assert projected.checks is not None
    assert len(projected.checks) == 2
    assert projected.checks[0] is decoded
    assert projected.checks[1] is structural
    assert projected.properties[0].type is S.NumberFromString.ast.to_type()
    assert node.encoding is encoding
    assert node.properties[0].type is S.NumberFromString.ast
    assert projected.to_type() is projected
    assert _decode(projected)({"a": 1}) == {"a": 1}
    with pytest.raises(S.SchemaError):
        _decode(projected)({"a": -1})
    with pytest.raises(S.SchemaError):
        _decode(projected)({"a": "1"})


def test_to_type_preserves_lazy_recursive_references_when_removing_a_suspended_nodes_encoding():
    """toType / preserves lazy recursive references when removing a suspended node's encoding"""
    calls: list[None] = []
    encoding = _passthrough()

    def thunk() -> S.ast.AST:
        calls.append(None)
        return ast.Objects(
            (
                ast.PropertySignature("value", S.NumberFromString.ast),
                ast.PropertySignature("next", ast.Union((ast.null, node))),
            )
        )

    node = ast.Suspend(thunk, encoding=encoding)
    projected = node.to_type()

    assert calls == []
    assert projected.encoding is None
    assert node.encoding is encoding
    assert node.to_type() is projected
    assert projected.to_type() is projected
    assert isinstance(projected, ast.Suspend)
    body = projected.target
    assert len(calls) == 1
    assert projected.target is body
    assert isinstance(body, ast.Objects)
    next = body.properties[1].type
    assert isinstance(next, ast.Union)
    assert next.types[1] is projected
    input = {"value": 1, "next": {"value": 2, "next": None}}
    assert _decode(projected)(input) == input
    assert len(calls) == 1


class _ANumber(TypedDict):
    a: float


def test_to_type_is_idempotent_for_suspended_schemas():
    """toType / is idempotent for suspended schemas"""
    schema = S.suspend(lambda: S.Struct(_ANumber, a=S.NumberFromString))
    node = schema.ast.to_type()

    assert node.to_type() is node


def test_to_type_to_encoded_is_idempotent_for_suspended_schemas():
    """toType / toEncoded is idempotent for suspended schemas"""
    schema = S.suspend(lambda: S.Struct(_ANumber, a=S.NumberFromString))
    node = ast.to_encoded(schema.ast)

    assert ast.to_encoded(node) is node


def test_to_type_promotes_encoding_checks_when_contained_type_shape_is_preserved():
    """toType / promotes encodingChecks when contained type shape is preserved"""
    schema = S.flip(S.flip(S.Struct(_A).__codec__()).check(S.make_filter(_long_a)))
    node = schema.__codec__().ast.to_type()

    assert isinstance(node, ast.Objects)
    assert node.checks is not None
    assert len(node.checks) == 1
    assert node.encoding_checks is None


class _Xs(TypedDict):
    xs: tuple[str, ...]


def test_to_type_to_encoded_preserves_parent_checks_when_projecting_checked_children_without_transformations():  # noqa: E501
    """toType / toEncoded preserves parent checks when projecting checked children without transformations"""  # noqa: E501
    schema = S.Struct(_Xs, xs=S.Array(S.String).check(S.is_min_length(1))).check(
        S.make_filter(lambda o: o["xs"][0] == "ok")
    )
    encoded = S.to_encoded(schema)

    assert _fails(schema, {"xs": ["bad"]})
    assert _fails(encoded, {"xs": ["bad"]})
    assert S.decode_unknown_sync(encoded)({"xs": ["ok"]}) == {"xs": ("ok",)}


def test_to_type_to_encoded_preserves_union_checks_when_projecting_checked_members_without_transformations():  # noqa: E501
    """toType / toEncoded preserves union checks when projecting checked members without transformations"""  # noqa: E501
    schema = S.Union(S.Array(S.String).check(S.is_min_length(1)), S.String).check(
        S.make_filter(lambda value: isinstance(value, str) or value[0] == "ok")
    )
    encoded = S.to_encoded(schema)

    assert _fails(encoded, ["bad"])
    assert S.decode_unknown_sync(encoded)(["ok"]) == ("ok",)
    assert S.decode_unknown_sync(encoded)("ok") == "ok"


class _ANumberOrBool(TypedDict):
    a: float | bool


def test_to_type_to_encoded_drops_parent_checks_when_a_union_member_has_a_transformation():
    """toType / toEncoded drops parent checks when a union member has a transformation"""
    schema = S.Struct(_ANumberOrBool, a=S.Union(S.NumberFromString, S.Boolean)).check(
        S.make_filter(lambda o: isinstance(o["a"], bool) or o["a"] > 0)
    )
    encoded = S.to_encoded(schema)

    assert _fails(schema, {"a": "-1"})
    assert S.decode_unknown_sync(encoded)({"a": "-1"}) == {"a": "-1"}


class _OptionalA(TypedDict):
    a: NotRequired[str]


@pytest.mark.parametrize("evaluated", [False, True])
def test_to_type_treats_suspended_children_as_opaque(evaluated: bool):
    """toType / treats suspended children as opaque (already evaluated: %s)"""
    calls: list[None] = []

    def make() -> S.Codec[str, str]:
        calls.append(None)
        return S.String

    suspended = S.suspend(make)
    if evaluated:
        S.decode_unknown_sync(suspended)("ok")
    schema = S.Struct(_OptionalA, a=suspended).check(
        S.make_filter(lambda o: o.get("a") != "bad"), S.is_min_properties(1)
    )
    encoded = S.to_encoded(schema)

    assert len(calls) == (1 if evaluated else 0)
    assert _fails(encoded, {})
    assert S.decode_unknown_sync(encoded)({"a": "bad"}) == {"a": "bad"}


def test_to_type_drops_encoding_checks_when_contained_type_shape_changes():
    """toType / drops encodingChecks when contained type shape changes"""
    schema = S.flip(
        S.flip(S.Struct(_ANumber, a=S.FiniteFromString).__codec__()).check(S.make_filter(_long_a))
    )
    node = schema.__codec__().ast.to_type()

    assert isinstance(node, ast.Objects)
    assert node.checks is None
    assert node.encoding_checks is None


def test_to_type_preserves_structural_checks_when_contained_type_shape_changes():
    """toType / preserves structural checks when contained type shape changes"""
    check = S.is_min_properties(1)
    schema = S.Struct(_ANumber, a=S.NumberFromString).check(check)
    node = ast.to_encoded(schema.ast)

    assert isinstance(node, ast.Objects)
    assert node.checks is not None
    assert node.checks[0] is check


def test_to_type_preserves_structural_checks_when_contained_element_shape_changes():
    """toType / preserves structural checks when contained element shape changes"""
    check = S.is_min_length(1)
    schema = S.Array(S.NumberFromString).check(check)
    node = ast.to_encoded(schema.ast)

    assert isinstance(node, ast.Arrays)
    assert node.checks is not None
    assert node.checks[0] is check


def test_to_type_preserves_structural_checks_when_a_declaration_type_parameter_shape_changes():
    """toType / preserves structural checks when a declaration type parameter shape changes"""
    check = S.is_min_size(1)
    schema = S.FrozenSet(S.NumberFromString).check(check)
    node = ast.to_encoded(schema.ast)

    assert isinstance(node, ast.Declaration)
    assert node.checks is not None
    assert node.checks[0] is check


def test_to_type_preserves_only_the_structural_members_of_a_mixed_filter_group():
    """toType / preserves only the structural members of a mixed filter group"""
    structural = S.is_min_properties(1)
    group = structural.and_(S.make_filter(lambda _: True))
    schema = S.Struct(_ANumber, a=S.NumberFromString).check(group)
    node = ast.to_encoded(schema.ast)

    assert isinstance(node, ast.Objects)
    assert node.checks is not None
    assert len(node.checks) == 1
    assert node.checks[0] is structural


# --- collectSentinels --------------------------------------------------------------------


class _TagA(TypedDict):
    _tag: Literal["a"]
    a: str


class _OptionalTagA(TypedDict):
    _tag: NotRequired[Literal["a"]]
    a: str


class _Marked:
    _tag = "A"


def test_collect_sentinels_declaration_sentinels():
    """collectSentinels / Declaration / ~sentinels"""
    schema = S.instance_of(_Marked, **{"~sentinels": (("_tag", "A"),)})
    assert ast.collect_sentinels(schema.ast) == (("_tag", "A"),)


def test_collect_sentinels_struct_required_tag():
    """collectSentinels / Struct / required tag"""
    assert ast.collect_sentinels(S.Struct(_TagA).ast) == (("_tag", "a"),)


def test_collect_sentinels_struct_optional_tag():
    """collectSentinels / Struct / optional tag"""
    assert ast.collect_sentinels(S.Struct(_OptionalTagA).ast) == ()


def test_collect_sentinels_tuple_required_element():
    """collectSentinels / Tuple / required element"""
    schema = S.Tuple(S.Literal("a"), S.Number)
    assert ast.collect_sentinels(schema.ast) == ((0, "a"),)


def test_collect_sentinels_tuple_optional_element():
    """collectSentinels / Tuple / optional element"""
    schema = S.Tuple(S.Number, S.optional_key(S.Literal("a")))
    assert ast.collect_sentinels(schema.ast) == ()


def test_collect_sentinels_declaration():
    """collectSentinels / Declaration"""
    schema = S.instance_of(_Marked, **{"~sentinels": (("_tag", "A"),)})
    assert ast.collect_sentinels(schema.ast) == (("_tag", "A"),)


def test_collect_sentinels_class():
    """collectSentinels / Class"""

    class A(S.Class):
        type: Literal["A"]
        a: str

    assert ast.collect_sentinels(A.__codec__().ast) == (("type", "A"),)


def test_collect_sentinels_tagged_class():
    """collectSentinels / TaggedClass"""

    class A(S.TaggedClass, tag="A"):
        a: str

    assert ast.collect_sentinels(A.__codec__().ast) == (("_tag", "A"),)


def test_collect_sentinels_error():
    """collectSentinels / Error"""

    class E(S.Error):
        type: Literal["E"]
        e: str

    assert ast.collect_sentinels(E.__codec__().ast) == (("type", "E"),)


def test_collect_sentinels_tagged_error():
    """collectSentinels / TaggedError"""

    class E(S.TaggedError, tag="E"):
        e: str

    assert ast.collect_sentinels(E.__codec__().ast) == (("_tag", "E"),)


class _KindVariantX(TypedDict):
    kind: Literal["a"]
    variant: Literal["x"]


class _KindVariantY(TypedDict):
    kind: Literal["a"]
    variant: Literal["y"]


class _KindA(TypedDict):
    kind: Literal["a"]


class _KindB(TypedDict):
    kind: Literal["b"]


def test_collect_sentinels_union_the_sentinels_common_to_every_member():
    """collectSentinels / Union: the sentinels common to every member"""
    shared = S.Union(S.Struct(_KindVariantX), S.Struct(_KindVariantY))
    assert ast.collect_sentinels(shared.ast) == (("kind", "a"),)

    disjoint = S.Union(S.Struct(_KindA), S.Struct(_KindB))
    assert ast.collect_sentinels(disjoint.ast) == ()

    # A suspended member stays opaque, so the intersection is conservative.
    with_suspend = S.Union(S.Struct(_KindA), S.suspend(lambda: S.Struct(_KindA)))
    assert ast.collect_sentinels(with_suspend.ast) == ()


# --- getCandidateIndex -------------------------------------------------------------------


def test_get_candidate_index_should_deduplicate_repeated_declaration_sentinels_in_one_of_mode():
    """getCandidateIndex / should deduplicate repeated declaration sentinels in "oneOf" mode"""

    def is_mapping(input: object) -> TypeIs[dict[str, object]]:
        return isinstance(input, dict)

    member = S.declare(is_mapping, **{"~sentinels": (("kind", "a"), ("kind", "a"))})
    schema = S.Union(member, mode="one_of")
    input = {"kind": "a"}
    assert S.decode_unknown_sync(schema)(input) is input


def test_get_candidate_index_should_handle_function_valued_declarations_with_sentinels():
    """getCandidateIndex / should handle function-valued declarations with sentinels"""
    a = S.declare(callable, **{"~sentinels": (("kind", "a"),)})
    b = S.declare(callable, **{"~sentinels": (("kind", "b"),)})
    union = S.Union(a, b).ast
    assert isinstance(union, ast.Union)

    def input() -> None:
        pass

    input.kind = "a"  # type: ignore[attr-defined]
    assert union.candidates(input) == [0]


def test_get_candidate_index_should_protect_cached_common_sentinel_candidates_from_external_mutation():  # noqa: E501
    """getCandidateIndex / should protect cached common sentinel candidates from external mutation"""  # noqa: E501
    union = S.Union(S.Struct(_KindA), S.Struct(_KindB)).ast
    assert isinstance(union, ast.Union)
    input = {"kind": "a"}
    candidates = union.candidates(input)
    candidates.append(1)
    assert union.candidates(input) == [0]


# --- getIndexSignatureKeys ---------------------------------------------------------------


def test_get_index_signature_keys_string():
    """getIndexSignatureKeys / String"""
    keys = ast.get_index_signature_keys({"a": 1, "b": 2, 3: 3}, S.String.ast)
    assert keys == ["a", "b"]


def test_get_index_signature_keys_string_with_checks():
    """getIndexSignatureKeys / String with checks"""
    parameter = S.String.check(S.is_pattern(r"^a")).ast
    assert ast.get_index_signature_keys({"a": 1, "ab": 2, "b": 3}, parameter) == ["a", "ab"]


def test_get_index_signature_keys_transformed_string_with_decoded_checks():
    """getIndexSignatureKeys / transformed String with decoded checks"""
    schema = S.String.pipe(S.decode(T.snake_to_camel())).check(S.is_pattern(r"^aB$"))
    keys = ast.get_index_signature_keys({"a_b": 1, "x_y": 2}, schema.ast)
    assert keys == ["a_b", "x_y"]


def test_get_index_signature_keys_template_literal():
    """getIndexSignatureKeys / TemplateLiteral"""
    schema = S.TemplateLiteral("a")
    assert ast.get_index_signature_keys({"a": 1, "ab": 2, "b": 3}, schema.ast) == ["a"]


def test_get_index_signature_keys_template_literal_with_checked_parts():
    """getIndexSignatureKeys / TemplateLiteral with checked parts"""
    schema = S.TemplateLiteral("a", S.NonEmptyString)
    assert ast.get_index_signature_keys({"a": 1, "ab": 2, "b": 3}, schema.ast) == ["ab"]


_NUMBER_KEYS = {1: 1, 1.5: 2, -2: 3, "a": 4, float("nan"): 5, "x1": 6, "1x": 7}


def test_get_index_signature_keys_number():
    """getIndexSignatureKeys / Number"""
    keys = ast.get_index_signature_keys(_NUMBER_KEYS, S.Number.ast)
    assert keys[:3] == [1, 1.5, -2]
    assert len(keys) == 4
    nan = keys[3]
    assert isinstance(nan, float)
    assert math.isnan(nan)


def test_get_index_signature_keys_number_with_checks():
    """getIndexSignatureKeys / Number with checks"""
    assert ast.get_index_signature_keys(_NUMBER_KEYS, S.Int.ast) == [1, -2]


def test_get_index_signature_keys_union():
    """getIndexSignatureKeys / Union"""
    schema = S.Union(S.Number, S.TemplateLiteral("b"))
    keys = ast.get_index_signature_keys({"b": 1, 1: 2, "c": 3}, schema.ast)
    assert keys == [1, "b"]


# --- record ------------------------------------------------------------------------------


def test_record_treats_never_parameters_as_no_keys():
    """record / treats Never parameters as no keys"""
    node = ast.record(S.Never.ast, S.Number.ast)
    assert node.properties == ()
    assert node.index_signatures == ()


def test_record_ignores_never_arms_in_union_parameters():
    """record / ignores Never arms in union parameters"""
    node = ast.record(S.Union(S.String, S.Never).ast, S.Number.ast)
    index_signature = node.index_signatures[0]

    assert node.properties == ()
    assert len(node.index_signatures) == 1
    assert index_signature.parameter is S.String.ast
    assert index_signature.type is S.Number.ast


# --- IndexSignature ----------------------------------------------------------------------


def test_index_signature_accepts_valid_parameters_on_both_type_and_encoded_side():
    """IndexSignature / accepts valid parameters on both type and encoded side"""
    ast.IndexSignature(S.String.ast, S.Number.ast)
    ast.IndexSignature(S.NumberFromString.ast, S.Number.ast)
    ast.IndexSignature(S.Union(S.String, S.NumberFromString).ast, S.Number.ast)


def test_index_signature_rejects_invalid_type_side_parameters():
    """IndexSignature / rejects invalid type side parameters"""
    with pytest.raises(ValueError, match=r"^Invalid index signature parameter Literal$"):
        ast.IndexSignature(S.Literal("a").ast, S.Number.ast)


def test_index_signature_rejects_invalid_encoded_side_parameters():
    """IndexSignature / rejects invalid encoded side parameters"""
    string_from_boolean = S.Boolean.pipe(
        S.decode_to(
            S.String,
            T.Transformation(G.transform(str), G.transform(lambda s: s == "True")),
        )
    )
    with pytest.raises(ValueError, match=r"^Invalid index signature parameter String$"):
        ast.IndexSignature(string_from_boolean.ast, S.Number.ast)
    with pytest.raises(ValueError, match=r"^Invalid index signature parameter Union$"):
        ast.IndexSignature(S.Union(S.String, string_from_boolean).ast, S.Number.ast)

    union_from_boolean = S.Boolean.pipe(
        S.decode_to(
            S.Union(S.String, S.Number),
            T.Transformation(
                G.transform(lambda b: "true" if b else 0), G.transform(lambda _: True)
            ),
        )
    )
    with pytest.raises(ValueError, match=r"^Invalid index signature parameter Union$"):
        ast.IndexSignature(union_from_boolean.ast, S.Number.ast)


# --- pyfect's own transforming nodes -----------------------------------------------------


class _Color(enum.Enum):
    RED = "red"
    BLUE = "blue"


class _ColorField(TypedDict):
    a: _Color


def _is_red(value: Mapping[str, object]) -> bool:
    return value["a"] is _Color.RED


def test_to_encoded_drops_parent_checks_when_an_enum_part_decodes_to_members():
    """A Python ``Enum`` decodes its values to members, a transformation
    Effect's enums do not have: a check of the members does not hold on
    the values."""
    schema = S.Struct(_ColorField, a=S.Enum(_Color)).check(S.make_filter(_is_red))
    encoded = S.to_encoded(schema)

    assert _fails(schema, {"a": "blue"})
    assert S.decode_unknown_sync(encoded)({"a": "red"}) == {"a": "red"}
    assert S.decode_unknown_sync(encoded)({"a": "blue"}) == {"a": "blue"}
