"""A struct or record reads any object's properties, as Effect's ``Objects`` does.

JavaScript has no split between a mapping and an object: ``typeof input === "object"`` and not
an array is the only check. So a class instance decodes and encodes through ``S.Struct``, and a
``Model``'s instance through ``User.json``. Numbers, strings, lists and functions stay refused.
Each outcome was printed by Effect's source under Node first.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal, TypedDict

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect.option import Some
from pyfect.result import Ok
from pyfect.schema import model as Model
from pyfect.schema.issue import Composite


class _Point(TypedDict):
    a: float
    b: float


class _Z(TypedDict):
    z: float


class _UserInsert(TypedDict):
    name: str
    password: str


class _UserUpdate(TypedDict):
    id: int
    name: str
    password: str


class _Instance:
    def __init__(self) -> None:
        self.a = 1
        self.extra = 9

    @property
    def b(self) -> int:
        return 2


@dataclass
class _Data:
    a: float
    b: float


def test_a_struct_decodes_a_class_instance_through_its_properties() -> None:
    assert S.decode_unknown_sync(S.Struct(_Point))(_Instance()) == {"a": 1, "b": 2}


def test_a_struct_encodes_a_class_instance_through_its_properties() -> None:
    assert S.encode_unknown_sync(S.Struct(_Point))(_Instance()) == {"a": 1, "b": 2}


def test_a_struct_reads_a_dataclass() -> None:
    assert S.decode_unknown_sync(S.Struct(_Point))(_Data(1, 2)) == {"a": 1, "b": 2}


def test_excess_properties_are_the_instances_own() -> None:
    exit = S.decode_unknown_exit(S.Struct(_Point), on_excess_property="error")(_Instance())
    assert isinstance(exit, fx.Failure)
    assert '["extra"]' in str(exit.cause)


def test_a_record_reads_the_instances_own_properties() -> None:
    record = S.Record(S.String, S.Number)
    assert S.decode_unknown_sync(record)(_Instance()) == {"a": 1, "extra": 9}


@pytest.mark.parametrize("value", [_Instance(), datetime(2020, 1, 1, tzinfo=UTC)])
def test_a_missing_property_is_a_missing_key(value: object) -> None:
    exit = S.decode_unknown_exit(S.Struct(_Z))(value)
    assert isinstance(exit, fx.Failure)
    assert "Missing key" in str(exit.cause)


@pytest.mark.parametrize("value", [1, "x", [], (1,), print, None, True])
def test_what_is_no_object_stays_refused(value: object) -> None:
    exit = S.decode_unknown_exit(S.Struct(_Z))(value)
    assert isinstance(exit, fx.Failure)
    assert "Missing key" not in str(exit.cause)


def test_a_model_instance_encodes_through_its_json_variant() -> None:
    """QA ai-workflow GQL-3: ``User.json`` reads a ``User`` instance, leaving out what it hides."""

    class User(Model.Class[_UserInsert, _UserUpdate]):
        id: int = Model.field(Model.field_except(["insert"])(S.Int))
        name: str
        password: str = Model.field(Model.Sensitive(S.String))

    user = User(id=1, name="ada", password="hunter2")
    assert S.encode_unknown_sync(User.json)(user) == {"id": 1, "name": "ada"}


class _Empty(TypedDict):
    pass


class _X(TypedDict):
    _tag: Literal["x"]
    a: float


class _Y(TypedDict):
    _tag: Literal["y"]
    b: float


class _TagY:
    _tag = "y"
    b = 2


class _TagZ:
    _tag = "z"


def test_a_union_selects_a_tagged_member_by_an_instances_attribute() -> None:
    """Node: ``Union([{ _tag: "x" }, { _tag: "y" }])`` decodes ``new Y()`` by its ``_tag``."""
    union = S.Union(S.Struct(_X), S.Struct(_Y))
    assert S.decode_unknown_sync(union)(_TagY()) == {"_tag": "y", "b": 2}
    assert isinstance(S.decode_unknown_exit(union)(_TagZ()), fx.Failure)


def test_an_issue_holds_the_instance_itself() -> None:
    value = _Instance()
    exit = S.decode_unknown_exit(S.Struct(_Z), report_input=True)(value)
    assert isinstance(exit, fx.Failure)
    error = exit.cause.find_error()
    assert isinstance(error, Ok)
    assert isinstance(error.value, S.SchemaError)
    issue = error.value.issue
    assert isinstance(issue, Composite)
    assert issue.input == Some(value)


class _Boom:
    @property
    def a(self) -> float:
        raise ValueError("boom")


def test_a_property_that_raises_is_a_defect() -> None:
    """Node: a getter that throws makes ``decodeUnknownExit`` a ``Die``."""
    exit = S.decode_unknown_exit(S.Struct(_Point))(_Boom())
    assert isinstance(exit, fx.Failure)
    assert isinstance(exit.cause.squash(), ValueError)


def test_a_union_reading_a_property_that_raises_is_a_defect() -> None:
    class Tagged:
        @property
        def _tag(self) -> str:
            raise ValueError("boom")

    exit = S.decode_unknown_exit(S.Union(S.Struct(_X), S.Struct(_Y)))(Tagged())
    assert isinstance(exit, fx.Failure)
    assert isinstance(exit.cause.squash(), ValueError)


@pytest.mark.parametrize("value", ["a", 1, True, [], (), print, _Instance(), {"a": 1}])
def test_an_empty_struct_takes_any_value_but_none_as_it_is(value: object) -> None:
    """``Schema.Struct({})`` is ``{}``: anything not nullish, returned as it came."""
    assert S.decode_unknown_sync(S.Struct(_Empty))(value) is value


def test_an_empty_struct_refuses_none_as_object_or_array() -> None:
    exit = S.decode_unknown_exit(S.Struct(_Empty))(None)
    assert isinstance(exit, fx.Failure)
    assert "Expected object | array" in str(exit.cause)


def test_struct_empty_preserves_its_semantics_in_a_union() -> None:
    """schema/Schema.test.ts / Union / Struct({}) preserves its semantics in a union"""
    decode = S.decode_unknown_sync(S.Union(S.Struct(_Empty), S.Null))
    values: tuple[object, ...] = ("a", 1, True, print, {}, [], None)
    for value in values:
        assert decode(value) == value
