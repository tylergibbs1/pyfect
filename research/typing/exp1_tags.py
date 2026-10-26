"""Exp 1: tag identity separate from shape; R tracks the TAG, value is the SHAPE."""
from __future__ import annotations
from collections.abc import Callable, Generator
from typing import Any, Never, Protocol, Self, TypeVar, Generic, overload, reveal_type

A = TypeVar("A", covariant=True)
E = TypeVar("E", covariant=True, default=Never)
R = TypeVar("R", covariant=True, default=Never)

class Effect(Generic[A, E, R]):
    def __iter__(self) -> Generator[Effect[object, E, R], object, A]: ...

class TagMeta(type):
    def __iter__[S](cls: type[Tag[S]]) -> Generator[Effect[object, Never, Any], object, S]: ...

class Tag[S](metaclass=TagMeta):
    @classmethod
    def use(cls) -> Effect[S, Never, Self]: ...

class DbShape(Protocol):
    def find(self, id: str) -> str | None: ...

class PrimaryDb(Tag[DbShape]): ...
class ReplicaDb(Tag[DbShape]): ...
class Clock(Tag[Callable[[], float]]): ...

reveal_type(PrimaryDb.use())   # want Effect[DbShape, Never, PrimaryDb]


class NotFound(Exception):
    def __iter__(self) -> Generator[Effect[Never, Self, Never], object, Never]: ...

def fail[EE](e: EE) -> Effect[Never, EE]: ...
def succeed[T](v: T) -> Effect[T]: ...

def prog(id: str):
    db = yield from PrimaryDb.use()
    rep = yield from ReplicaDb.use()
    now = yield from Clock.use()
    reveal_type(now)
    x = db.find(id) or rep.find(id)
    if x is None:
        return (yield from NotFound())
    return x

def gen[AA, EE = Never, RR = Never](f: Callable[[], Generator[Effect[object, EE, RR], object, AA]]) -> Effect[AA, EE, RR]: ...

reveal_type(gen(lambda: prog("x")))
reveal_type(prog)
