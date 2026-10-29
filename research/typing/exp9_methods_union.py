# pyright: strict
"""Exp 9: flat_map-style methods: Never|Never unions via class vars vs shared self-rebinding."""

from __future__ import annotations
from collections.abc import Callable, Generator
from typing import Any, Never, TypeVar, Generic, reveal_type

A = TypeVar("A", covariant=True)
E = TypeVar("E", covariant=True, default=Never)
R = TypeVar("R", covariant=True, default=Never)


class Effect(Generic[A, E, R]):
    def __iter__(self) -> Generator[Effect[Any, E, R], Any, A]:
        raise NotImplementedError

    def fm_class[B, E2 = Never, R2 = Never](
        self, f: Callable[[A], Effect[B, E2, R2]]
    ) -> Effect[B, E | E2, R | R2]:
        raise NotImplementedError

    def fm_shared[AA, B, EE, RR](
        self: Effect[AA, EE, RR], f: Callable[[AA], Effect[B, EE, RR]]
    ) -> Effect[B, EE, RR]:
        raise NotImplementedError

    def catch_all[B, E2 = Never, R2 = Never](
        self, f: Callable[[E], Effect[B, E2, R2]]
    ) -> Effect[A | B, E2, R | R2]:
        raise NotImplementedError

    def catch_shared[AA, EE, B, E2, RR](
        self: Effect[AA, EE, RR], f: Callable[[EE], Effect[B, E2, RR]]
    ) -> Effect[AA | B, E2, RR]:
        raise NotImplementedError


def s[T](v: T) -> Effect[T]:
    raise NotImplementedError


def f() -> Effect[int, ValueError]:
    raise NotImplementedError


class Db: ...


def g(x: int) -> Effect[str, KeyError, Db]:
    raise NotImplementedError


reveal_type(s(1).fm_class(lambda n: s(str(n))))
reveal_type(s(1).fm_class(g))
reveal_type(f().fm_class(g))
reveal_type(s(1).fm_shared(lambda n: s(str(n))))
reveal_type(s(1).fm_shared(g))
reveal_type(f().fm_shared(g))
reveal_type(f().fm_shared(lambda n: s(n)))
reveal_type(f().catch_all(lambda e: s("x")))
reveal_type(f().catch_shared(lambda e: s("x")))
reveal_type(f().catch_shared(lambda e: g(1)))
