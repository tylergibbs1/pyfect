"""A union of mutually recursive TypedDicts decodes in time linear in the
input's depth. Each TypedDict met again while its own fields are derived is a
suspended union member; once made, its discriminator picks it like any
other member's, where every suspended member used to be tried on every
value (2**depth parses under ``errors="all"``)."""

from __future__ import annotations

import time
from typing import Literal, TypedDict

from _growth import Work, assert_near_linear
from _guards import guards

import pyfect as fx
from pyfect import schema as S


class And(TypedDict):
    op: Literal["and"]
    left: And | Or | Eq
    right: And | Or | Eq


class Or(TypedDict):
    op: Literal["or"]
    left: And | Or | Eq
    right: And | Or | Eq


class Eq(TypedDict):
    op: Literal["eq"]
    field: str


class Late(TypedDict):
    # The discriminator after the recursive field.
    next: Late | End
    kind: Literal["late"]


class End(TypedDict):
    kind: Literal["end"]


class LateA(TypedDict):
    # Two members whose discriminators follow the recursive field.
    next: LateA | LateB | End
    kind: Literal["a"]


class LateB(TypedDict):
    next: LateA | LateB | End
    kind: Literal["b"]


def _filter(depth: int) -> object:
    value: object = {"op": "eq", "field": "x"}
    for _ in range(depth):
        value = {"op": "or", "left": {"op": "eq", "field": "y"}, "right": value}
    return value


def _late(depth: int, kind: str = "late") -> object:
    value: object = {"kind": "end"}
    for _ in range(depth):
        value = {"next": value, "kind": kind}
    return value


_GUARD = guards("2dfb157a", "recursive-union-tries-every-member")


@_GUARD
def test_mutually_recursive_typed_dicts_decode_in_linear_time() -> None:
    decode = S.decode_unknown_exit(S.Union(S.Struct(And), S.Struct(Or), S.Struct(Eq)), errors="all")

    def sized(depth: int) -> Work:
        value = _filter(depth)
        return lambda: decode(value)

    assert isinstance(sized(30)(), fx.Success)
    assert_near_linear(sized, 6, 6 * 4, factor=4, bound=8, clock=time.process_time)


@_GUARD
def test_members_whose_discriminator_follows_the_recursive_field_decode_in_linear_time() -> None:
    """Stopping at the first error does not help when the discriminator comes after the
    recursive field: trying the wrong member first would decode the rest of the value
    before its ``kind`` fails, at every level."""
    decode = S.decode_unknown_exit(
        S.Union(S.Struct(LateA), S.Struct(LateB), S.Struct(End)), errors="first"
    )

    def sized(depth: int) -> Work:
        value = _late(depth, "b")
        return lambda: decode(value)

    assert isinstance(sized(30)(), fx.Success)
    assert_near_linear(sized, 6, 6 * 4, factor=4, bound=8, clock=time.process_time)


def test_a_discriminator_after_the_recursive_field_still_picks_the_member() -> None:
    decode = S.decode_unknown_exit(S.Union(S.Struct(Late), S.Struct(End)))

    def sized(depth: int) -> Work:
        value = _late(depth)
        return lambda: decode(value)

    assert isinstance(sized(40)(), fx.Success)
    assert_near_linear(sized, 8, 8 * 4, factor=4, bound=8, clock=time.process_time)


@_GUARD
def test_issues_name_the_members_a_discriminator_picks() -> None:
    decode = S.decode_unknown_exit(S.Union(S.Struct(And), S.Struct(Or), S.Struct(Eq)), errors="all")
    bad = {
        "op": "or",
        "left": {"op": "and", "left": {"op": "eq", "field": "a"}, "right": {"op": "x"}},
        "right": 5,
    }
    exit = decode(bad)
    assert isinstance(exit, fx.Failure)
    text = str(exit.cause)
    assert 'at ["left"]["right"]' in text
    assert 'at ["right"]' in text
    assert '{ readonly "op": "and", ... }' in text
