# pyright: strict
"""Exp 6: strict-mode noise for unannotated effect generators; Tag via __new__."""

from __future__ import annotations
from collections.abc import Callable, Generator
from typing import Any, Never, Self, TypeVar, Generic, reveal_type

A = TypeVar("A", covariant=True)
E = TypeVar("E", covariant=True, default=Never)
R = TypeVar("R", covariant=True, default=Never)


class Effect(Generic[A, E, R]):
    def __iter__(self) -> Generator[Effect[Any, E, R], Any, A]:
        raise NotImplementedError


class Tag[S]:
    def __new__(cls) -> Effect[S, Never, Self]:
        raise NotImplementedError


class Db(Tag[dict[str, str]]): ...


def succeed[T](v: T) -> Effect[T]:
    raise NotImplementedError


def fn[**P, AA, EE = Never, RR = Never](
    f: Callable[P, Generator[Effect[Any, EE, RR], Any, AA]],
) -> Callable[P, Effect[AA, EE, RR]]:
    raise NotImplementedError


class NotFound(Exception):
    def __iter__(self) -> Generator[Effect[Never, Self, Never], Any, Never]:
        raise NotImplementedError


@fn
def find(key: str):
    db = yield from Db()
    n = yield from succeed(1)
    v = db.get(key)
    if v is None:
        return (yield from NotFound())
    return v * n


reveal_type(find)
reveal_type(find("a"))
