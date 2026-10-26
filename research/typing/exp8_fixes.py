# pyright: strict
"""Exp 8: invariant tag marker; Never-union fixes."""
from __future__ import annotations
from collections.abc import Generator
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

S_inv = TypeVar("S_inv")
T_co = TypeVar("T_co", covariant=True)
class ServiceEffect(Effect[S_inv, Never, T_co], Generic[S_inv, T_co]):
    """Invariant in S so the shape can't widen when matching a value."""

class Tag[S]:
    def __new__(cls) -> ServiceEffect[S, Self]:
        raise NotImplementedError

class TagLike[S, T](Protocol):
    def __call__(self) -> ServiceEffect[S, T]: ...

def succeed[S, T](tag: TagLike[S, T], value: S) -> Layer[T]:
    raise NotImplementedError

class DbShape(Protocol):
    def find(self, k: str) -> str | None: ...
class GoodDb:
    def find(self, k: str) -> str | None: return None
class BadDb:
    def nope(self) -> None: ...
class Db(Tag[DbShape]): ...
class Port(Tag[int]): ...

reveal_type(succeed(Db, GoodDb()))
reveal_type(succeed(Port, 8080))
succeed(Db, BadDb())     # want error
succeed(Port, "x")       # want error

def gen_():
    d = yield from Db()
    return d
reveal_type(gen_)

def s[T](v: T) -> Effect[T]:
    raise NotImplementedError
def f() -> Effect[int, ValueError]:
    raise NotImplementedError

# Variant 1: no defaults
def zip1[A1, A2, E1, E2, R1, R2](a: Effect[A1, E1, R1], b: Effect[A2, E2, R2]) -> Effect[tuple[A1, A2], E1 | E2, R1 | R2]:
    raise NotImplementedError
reveal_type(zip1(s(1), s("a")))
reveal_type(zip1(s(1), f()))
# Variant 2: single variadic-ish union param via one TypeVar shared
def zip2[A1, A2, EE = Never, RR = Never](a: Effect[A1, EE, RR], b: Effect[A2, EE, RR]) -> Effect[tuple[A1, A2], EE, RR]:
    raise NotImplementedError
reveal_type(zip2(s(1), s("a")))
reveal_type(zip2(s(1), f()))
def g() -> Effect[int, KeyError, Db]:
    raise NotImplementedError
reveal_type(zip2(f(), g()))
reveal_type(zip2(g(), s(1)))
