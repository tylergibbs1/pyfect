"""Ports of Effect's ``standardSchemaAdapters.test.ts``: both adapters
(``to_standard_schema_v1`` and ``to_standard_json_schema_v1``) keep the
schema's members.

Python mappings: a static is a class attribute and a static method reading
``this`` a ``classmethod``; ``extend`` is subclassing the adapter. A JS static
accessor (``static get`` / ``static set``) needs a metaclass in Python;
the port uses a descriptor, which the adapter binds to itself on reads, and
a write to the adapter is local, as in Effect; the class's own accessor
setter (which a plain class attribute write would replace) is not
exercised."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, ClassVar, cast

import pytest

import pyfect.schema as S

_ADAPTERS: list[Callable[[Any], Any]] = [S.to_standard_schema_v1, S.to_standard_json_schema_v1]
_IDS = ["toStandardSchemaV1", "toStandardJSONSchemaV1"]
adapters = pytest.mark.parametrize("adapt", _ADAPTERS, ids=_IDS)


@adapters
def test_preserves_array_value(adapt: Callable[[Any], Any]):
    """%s preserves schema members / preserves Array.value"""
    schema = S.Array(S.String)
    assert adapt(schema).value is schema.value


@adapters
def test_preserves_record_key_and_record_value(adapt: Callable[[Any], Any]):
    """%s preserves schema members / preserves Record.key and Record.value"""
    schema = S.Record(S.String, S.Number)
    adapted = adapt(schema)
    assert adapted.key is schema.key
    assert adapted.value is schema.value


@adapters
def test_preserves_properties_of_class_and_function_valued_statics(adapt: Callable[[Any], Any]):
    """%s preserves schema members / preserves properties of class- and function-valued statics"""

    class _Item(S.Class):
        value: str
        custom: ClassVar[str] = "item"

    def _increment(value: int) -> int:
        return value + 1

    _increment.description = "increment"  # pyright: ignore[reportFunctionMemberAccess]

    class Parent(S.Class):
        a: str
        Item: ClassVar[type[Any]] = _Item
        increment: ClassVar[Callable[[int], int]] = staticmethod(_increment)

    adapted = adapt(Parent)
    assert adapted.Item.custom == "item"
    assert adapted.increment.description == "increment"
    assert adapted.increment(1) == 2


class _CurrentCount:
    """A class-level accessor reading ``count`` of the class it is read
    through (JavaScript's ``static get currentCount``)."""

    def __get__(self, instance: object, owner: Any) -> int:
        return owner.count


@adapters
def test_keeps_static_writes_accessors_and_method_reads_local_to_the_copy(
    adapt: Callable[[Any], Any],
):
    """%s preserves schema members / keeps static writes, accessors, and method reads local to the copy"""  # noqa: E501

    class Parent(S.Class):
        a: str
        count: ClassVar[int] = 0
        current_count: ClassVar[Any] = _CurrentCount()

        @classmethod
        def get_count(cls) -> int:
            return cls.count

    adapted = adapt(Parent)
    adapted.count = 1
    assert adapted.count == 1
    assert adapted.get_count() == 1
    assert Parent.count == 0
    assert adapted.current_count == 1
    assert Parent.current_count == 0

    adapted.current_count = 2
    assert adapted.current_count == 2
    assert Parent.current_count == 0


@adapters
def test_preserves_class_construction_and_decoding(adapt: Callable[[Any], Any]):
    """%s preserves schema members / preserves class construction and decoding"""

    class Parent(S.Class):
        a: str

    adapted = adapt(Parent)
    constructed = adapted(a="a")
    decoded = S.decode_unknown_sync(adapted)({"a": "a"})
    assert type(constructed) is Parent
    assert type(decoded) is Parent
    assert isinstance(constructed, adapted)
    assert isinstance(decoded, adapted)
    assert isinstance(Parent(a="a"), adapted)


@adapters
def test_supports_extending_an_adapted_class(adapt: Callable[[Any], Any]):
    """%s preserves schema members / supports extending an adapted class"""

    class Parent(S.Class):
        a: str

    adapted = adapt(Parent)

    class Child(adapted):
        b: float

    decoded = S.decode_unknown_sync(cast("Any", Child))({"a": "a", "b": 1})
    assert type(decoded) is Child
    assert decoded.b == 1
    assert isinstance(decoded, Parent)
