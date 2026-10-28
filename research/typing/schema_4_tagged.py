"""Q1: NewType over a TypedDict (Opaque)? Q2: match narrowing of TypedDict
unions on a literal _tag mapping pattern, with exhaustiveness."""

from typing import Literal, NewType, TypedDict, assert_never, assert_type


class A(TypedDict):
    _tag: Literal["A"]
    a: str


class B(TypedDict):
    _tag: Literal["B"]
    b: int


Opaque = NewType("Opaque", A)  # rejected: NewType of a TypedDict


def area(v: A | B) -> str:
    match v:
        case {"_tag": "A"}:
            assert_type(v, A)
            return v["a"]
        case {"_tag": "B"}:
            assert_type(v, B)
            return str(v["b"])
        case _:
            assert_never(v)


def partial(v: A | B) -> str:
    match v:
        case {"_tag": "A"}:
            return v["a"]
        case _:
            assert_never(v)  # rejected: the B case is missing


class Circle:
    radius: float = 1.0


class Square:
    side: float = 1.0


def classes(v: Circle | Square) -> float:
    match v:
        case Circle(radius=r):
            return r
        case Square():
            return v.side
        case _:
            assert_never(v)


def captured(v: A | B) -> str:
    match v:
        case {"_tag": "A", "a": a}:
            return a
        case {"_tag": "B"}:
            return ""
        case _:
            assert_never(v)  # rejected: a capture in a mapping pattern stops narrowing
