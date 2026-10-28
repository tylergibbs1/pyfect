"""Struct, Record and schema classes: the Python-specific edges (derivation
from annotations, defaults, frozen errors, union dispatch by tag)."""

import copy
import pickle
from typing import Literal, Never, NotRequired, TypedDict

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect.testing import SchemaAsserts


class _Missing(S.TaggedError):
    id: int
    cause: object = None


class _Tree(TypedDict):
    value: int
    children: dict[str, "_Tree"]


def test_a_struct_derives_its_fields_from_the_typed_dict():
    class User(TypedDict):
        id: int
        nick: NotRequired[str]

    decoding = SchemaAsserts(S.Struct(User)).decoding()
    decoding.succeed({"id": 1})
    decoding.succeed({"id": 1, "nick": "a"})
    decoding.fail({"id": "1"}, 'Expected number\n  at ["id"]')


def test_an_override_for_a_key_the_typed_dict_lacks_raises():
    class User(TypedDict):
        id: int

    with pytest.raises(TypeError, match="nick"):
        S.Struct(User, nick=S.String)


def test_an_annotation_without_a_schema_raises():
    class Odd(TypedDict):
        when: complex

    with pytest.raises(TypeError):
        S.Struct(Odd)


def test_a_recursive_typed_dict_decodes_nested_values():
    decoding = SchemaAsserts(S.Struct(_Tree)).decoding()
    decoding.succeed({"value": 1, "children": {"a": {"value": 2, "children": {}}}})
    decoding.fail(
        {"value": 1, "children": {"a": {"value": "x", "children": {}}}},
        'Expected number\n  at ["children"]["a"]["value"]',
    )


def test_a_missing_key_with_a_default_decodes_to_the_default():
    class Point(S.Class):
        x: int
        y: int = 0

    assert S.decode_unknown_sync(Point)({"x": 1}) == Point(x=1, y=0)


def test_construction_validates_the_fields():
    class Point(S.Class):
        x: int

    with pytest.raises(S.SchemaError):
        Point(x="1")  # pyright: ignore[reportArgumentType]


def test_a_tagged_union_of_classes_dispatches_on_the_tag():
    class Circle(S.TaggedClass):
        radius: float

    class Square(S.TaggedClass):
        side: float

    shape = S.Union(Circle, Square)
    assert S.decode_unknown_sync(shape)({"_tag": "Square", "side": 2}) == Square(side=2)
    SchemaAsserts(shape).decoding().fail({"_tag": "Circle"}, 'Missing key\n  at ["radius"]')


def test_a_union_tries_only_the_members_whose_tag_the_input_holds():
    class A(TypedDict):
        kind: Literal["a"]
        value: str

    class B(TypedDict):
        kind: Literal["b"]
        value: int

    schema = S.Union(S.Struct(A), S.Struct(B))
    SchemaAsserts(schema).decoding().fail(
        {"kind": "b", "value": "x"}, 'Expected number\n  at ["value"]'
    )


def test_a_schema_error_is_frozen_but_takes_notes():
    class NotFound(S.TaggedError):
        id: int

    error = NotFound(id=1)
    with pytest.raises(AttributeError):
        error.id = 2  # pyright: ignore[reportAttributeAccessIssue]
    error.add_note("looked in the cache")
    assert error.__notes__ == ["looked in the cache"]


def test_catch_tag_recovers_a_schema_tagged_error():
    class NotFound(S.TaggedError):
        id: int

    program = fx.fail(NotFound(id=7)).pipe(fx.catch_tag(NotFound, lambda e: fx.succeed(e.id)))
    assert fx.run_sync(program) == 7


def test_schema_errors_compare_by_their_fields():
    class NotFound(S.TaggedError):
        id: int

    assert NotFound(id=1) == NotFound(id=1)
    assert NotFound(id=1) != NotFound(id=2)


def test_a_schema_error_survives_copy_and_pickle_with_its_notes():
    error = _Missing(id=1)
    error.add_note("looked in the cache")
    for clone in (copy.copy(error), pickle.loads(pickle.dumps(error))):
        assert clone == error
        assert clone.__notes__ == ["looked in the cache"]


def test_a_decoded_schema_error_links_its_cause():
    cause = ValueError("down")
    error = S.decode_unknown_sync(_Missing)({"_tag": "_Missing", "id": 1, "cause": cause})
    assert error.__cause__ is cause


def test_a_defaulted_literal_field_does_not_discriminate_a_union():
    """The encoded side of a defaulted key is optional (Effect's
    ``withDecodingDefault``), so it is no sentinel: checked under Node."""

    class A(S.Class):
        kind: Literal["a"] = "a"
        x: int

    class B(S.Class):
        kind: Literal["b"]
        y: int

    decoding = SchemaAsserts(S.Union(A, B)).decoding()
    decoding.succeed({"x": 1}, A(x=1))
    decoding.fail({"z": 1}, 'Missing key\n  at ["x"]')


class _Range(S.Class):
    low: int
    high: int

    @S.class_check(message="low above high")
    def ordered(self) -> bool:
        return self.low <= self.high


def test_a_subclass_replaces_or_drops_an_overridden_class_check():
    class Narrow(_Range):
        @S.class_check(message="wider than 10")
        def ordered(self) -> bool:
            return self.high - self.low <= 10

    class Loose(_Range):
        def ordered(self) -> bool:
            return True

    with pytest.raises(S.SchemaError, match="wider than 10"):
        Narrow(low=0, high=20)
    assert Narrow(low=2, high=1).low == 2
    assert Loose(low=2, high=1).low == 2


def test_disable_checks_skips_the_class_checks_when_decoding():
    decoded = S.decode_unknown_sync(_Range)({"low": 2, "high": 1}, disable_checks=True)
    assert (decoded.low, decoded.high) == (2, 1)
    SchemaAsserts(_Range).decoding().fail({"low": 2, "high": 1}, "low above high")


class _Chain(TypedDict):
    value: int
    next: "_Chain | None"


def test_the_decoded_side_of_a_recursive_schema_refers_back_to_itself():
    # Each use of a suspend's decoded side is the same node, so walking the
    # decoded side of a recursive schema ends (``to_strategy`` walks it).
    chain: S.StructSchema[_Chain, Never, Never] = S.Struct(
        _Chain, next=S.NullOr(S.suspend(lambda: chain))
    )
    typed = S.to_type(chain).ast
    assert isinstance(typed, S.ast.Objects)
    nullable = typed.properties[1].type
    assert isinstance(nullable, S.ast.Union)
    suspend = nullable.types[0]
    assert isinstance(suspend, S.ast.Suspend)
    assert suspend.to_type() is suspend
    again = suspend.target
    assert isinstance(again, S.ast.Objects)
    inner = again.properties[1].type
    assert isinstance(inner, S.ast.Union)
    assert inner.types[0] is suspend
