# pyright: strict
"""Exp 7: Layer.succeed(Tag, impl) checks impl against the tag's shape; zip/merge Never unions."""
from __future__ import annotations
from collections.abc import Callable, Generator
from typing import Any, Never, Protocol, Self, TypeVar, Generic, reveal_type

A = TypeVar("A", covariant=True)
E = TypeVar("E", covariant=True, default=Never)
R = TypeVar("R", covariant=True, default=Never)
ROut = TypeVar("ROut", contravariant=True)
RIn = TypeVar("RIn", covariant=True, default=Never)

class Effect(Generic[A, E, R]):
    def __iter__(self) -> Generator[Effect[Any, E, R], Any, A]:
        raise NotImplementedError

class Layer(Generic[ROut, E, RIn]): ...

class Tag[S]:
    def __new__(cls) -> Effect[S, Never, Self]:
        raise NotImplementedError

class TagLike[S, T](Protocol):
    def __call__(self) -> Effect[S, Never, T]: ...

def succeed[S, T](tag: TagLike[S, T], value: S) -> Layer[T]:
    raise NotImplementedError
def effect[S, T, E2 = Never, R2 = Never](tag: TagLike[S, T], make: Effect[S, E2, R2]) -> Layer[T, E2, R2]:
    raise NotImplementedError

class DbShape(Protocol):
    def find(self, k: str) -> str | None: ...
class GoodDb:
    def find(self, k: str) -> str | None: return None
class BadDb:
    def nope(self) -> None: ...
class Db(Tag[DbShape]): ...
class Replica(Tag[DbShape]): ...
class Port(Tag[int]): ...

reveal_type(succeed(Db, GoodDb()))     # Layer[Db]
reveal_type(succeed(Port, 8080))       # Layer[Port]
succeed(Db, BadDb())                   # ERROR expected
succeed(Port, "x")                     # ERROR expected
def mk() -> Effect[GoodDb, ValueError, Port]:
    raise NotImplementedError
reveal_type(effect(Replica, mk()))     # Layer[Replica, ValueError, Port]

def zip_[A1, A2, E1 = Never, E2 = Never, R1 = Never, R2 = Never](a: Effect[A1, E1, R1], b: Effect[A2, E2, R2]) -> Effect[tuple[A1, A2], E1 | E2, R1 | R2]:
    raise NotImplementedError
def merge[O1, O2, E1 = Never, E2 = Never, R1 = Never, R2 = Never](a: Layer[O1, E1, R1], b: Layer[O2, E2, R2]) -> Layer[O1 | O2, E1 | E2, R1 | R2]:
    raise NotImplementedError
def s[T](v: T) -> Effect[T]:
    raise NotImplementedError
def f() -> Effect[int, ValueError]:
    raise NotImplementedError
reveal_type(zip_(s(1), s("a")))
reveal_type(zip_(s(1), f()))
reveal_type(merge(succeed(Db, GoodDb()), succeed(Port, 1)))
reveal_type(merge(succeed(Db, GoodDb()), effect(Replica, mk())))
