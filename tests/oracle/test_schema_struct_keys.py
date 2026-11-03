"""Ports of Effect's ``Schema.test.ts`` "encodeKeys" and "extendTo" blocks,
and a pyfect test of ``Tree`` (Effect has none).

Omitted:
- "encodeKeys / supports symbol source keys" and "... symbol destination
  keys": a TypedDict's keys are strings.
- "encodeKeys / rejects canonical number and string destination key
  collisions": the mapping's encoded keys are strings (``{"a": 1}`` is a
  type error), so ``1`` and ``"1"`` cannot both be given.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal, TypedDict

import pytest

from pyfect import schema as S
from pyfect.option import Option, Some
from pyfect.testing import SchemaAsserts


class _AB(TypedDict):
    a: float
    b: float


def test_encode_keys_struct():
    """encodeKeys / Struct"""
    schema = S.Struct(_AB, a=S.FiniteFromString, b=S.FiniteFromString).pipe(
        S.encode_keys({"a": "c"})
    )
    asserts = SchemaAsserts(schema)
    asserts.decoding().succeed({"c": "1", "b": "2"}, {"a": 1, "b": 2})
    asserts.encoding().succeed({"a": 1, "b": 2}, {"c": "1", "b": "2"})


def test_encode_keys_class():
    """encodeKeys / Class"""

    class A(S.Class):
        a: float = S.field(S.FiniteFromString)
        b: str

    schema = A.pipe(S.encode_keys({"a": "c"}))
    asserts = SchemaAsserts(schema)
    asserts.decoding().succeed({"c": "1", "b": "b"}, A(a=1, b="b"))
    asserts.encoding().succeed(A(a=1, b="b"), {"c": "1", "b": "b"})


class _StringsAB(TypedDict):
    a: str
    b: str


def test_encode_keys_rejects_duplicate_destination_keys():
    """encodeKeys / rejects duplicate destination keys"""
    with pytest.raises(ValueError, match="Duplicate encoded keys"):
        S.Struct(_StringsAB).pipe(S.encode_keys({"a": "c", "b": "c"}))


def test_encode_keys_rejects_destination_keys_that_collide_with_unmapped_fields():
    """encodeKeys / rejects destination keys that collide with unmapped fields"""
    with pytest.raises(ValueError, match="Duplicate encoded keys"):
        S.Struct(_StringsAB).pipe(S.encode_keys({"a": "b"}))


class _Source(TypedDict):
    a: str
    b: float


class _Extended(_Source):
    c: str


def _c(value: _Source) -> Option[object]:
    return Some(f"{value['a']}c{value['b']:g}")


def test_extend_to_struct():
    """extendTo / Struct"""
    schema = S.Struct(_Source).pipe(S.extend_to(_Extended, {"c": _c}))
    asserts = SchemaAsserts(schema)
    asserts.decoding().succeed({"a": "1", "b": 2}, {"a": "1", "b": 2, "c": "1c2"})
    asserts.encoding().succeed({"a": "1", "b": 2, "c": "1c2"}, {"a": "1", "b": 2})


class _Circle(TypedDict):
    radius: float


class _Square(TypedDict):
    sideLength: float


class _KindCircle(_Circle):
    kind: Literal["circle"]


class _KindSquare(_Square):
    kind: Literal["square"]


def _circle(_: _Circle) -> Option[object]:
    return Some("circle")


def _square(_: _Square) -> Option[object]:
    return Some("square")


def test_extend_to_union():
    """extendTo / Union"""
    shape = S.Union(
        S.Struct(_Circle).pipe(S.extend_to(_KindCircle, {"kind": _circle}, kind=S.tag("circle"))),
        S.Struct(_Square).pipe(S.extend_to(_KindSquare, {"kind": _square}, kind=S.tag("square"))),
    )
    asserts = SchemaAsserts(shape)
    decoding = asserts.decoding()
    decoding.succeed({"radius": 1}, {"radius": 1, "kind": "circle"})
    decoding.succeed({"sideLength": 1}, {"sideLength": 1, "kind": "square"})
    encoding = asserts.encoding()
    encoding.succeed({"radius": 1, "kind": "circle"}, {"radius": 1})
    encoding.succeed({"sideLength": 1, "kind": "square"}, {"sideLength": 1})


def test_tree_decodes_nodes_arrays_and_records():
    """Tree accepts a node, an array of trees or a record of trees"""
    asserts = SchemaAsserts(S.Tree(S.FiniteFromString))
    decoding = asserts.decoding()
    decoding.succeed("1", 1)
    decoding.succeed(["1", {"a": ["2"]}], (1, {"a": (2,)}))
    decoding.fail({"a": True}, 'Expected string | array | object\n  at ["a"]')
    asserts.encoding().succeed({"a": (1,)}, {"a": ("1",)})


def test_encode_keys_rejects_keys_that_are_not_fields():
    """encode_keys rejects a mapping key that is not a field (Effect's type
    allows only the struct's keys); it would otherwise rename an encoded
    field away on decoding"""
    with pytest.raises(ValueError, match=r'Unknown keys in encode_keys mapping: \["x"\]'):
        S.Struct(_StringsAB).pipe(S.encode_keys({"x": "b"}))


def test_extend_to_rejects_derive_keys_other_than_the_new_keys():
    """extend_to needs one derive function per new key (Effect's type maps
    exactly the new fields); a missing or extra one is a ValueError"""
    with pytest.raises(ValueError, match=r'extend_to derives \["zz"\], new keys are \["c"\]'):
        S.Struct(_Source).pipe(S.extend_to(_Extended, {"zz": _c}))
    with pytest.raises(ValueError, match=r"extend_to derives \[\], new keys are \[\"c\"\]"):
        none: dict[str, Callable[[_Source], Option[object]]] = {}
        S.Struct(_Source).pipe(S.extend_to(_Extended, none))
