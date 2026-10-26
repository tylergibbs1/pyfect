"""Exp 3: can subtraction combinators be METHODS (overloaded self-types)?"""
from __future__ import annotations
from collections.abc import Callable, Generator
from typing import Any, Never, Self, TypeVar, Generic, overload, reveal_type

A = TypeVar("A", covariant=True)
E = TypeVar("E", covariant=True, default=Never)
R = TypeVar("R", covariant=True, default=Never)
ROut = TypeVar("ROut", contravariant=True)
RIn = TypeVar("RIn", covariant=True, default=Never)

class Layer(Generic[ROut, E, RIn]): ...

class Effect(Generic[A, E, R]):
    def __iter__(self) -> Generator[Effect[object, E, R], object, A]: ...

    @overload
    def catch_tag[AA, EC, RR, B, E2 = Never, R2 = Never](
        self: Effect[AA, EC, RR], tag: type[EC], handler: Callable[[EC], Effect[B, E2, R2]]
    ) -> Effect[AA | B, E2, RR | R2]: ...
    @overload
    def catch_tag[AA, EC, ER, RR, B, E2 = Never, R2 = Never](
        self: Effect[AA, EC | ER, RR], tag: type[EC], handler: Callable[[EC], Effect[B, E2, R2]]
    ) -> Effect[AA | B, ER | E2, RR | R2]: ...
    def catch_tag(self, tag: Any, handler: Any) -> Any: ...

    @overload
    def provide[AA, EE, RO, E2 = Never, RI = Never](
        self: Effect[AA, EE, RO], layer: Layer[RO, E2, RI]
    ) -> Effect[AA, EE | E2, RI]: ...
    @overload
    def provide[AA, EE, RO, RR, E2 = Never, RI = Never](
        self: Effect[AA, EE, RO | RR], layer: Layer[RO, E2, RI]
    ) -> Effect[AA, EE | E2, RR | RI]: ...
    def provide(self, layer: Any) -> Any: ...

    def map[AA, EE, RR, B](self: Effect[AA, EE, RR], f: Callable[[AA], B]) -> Effect[B, EE, RR]: ...

class A1: ...
class B1: ...
class C1: ...
class NotFound(Exception): ...
class Timeout(Exception): ...
class Other(Exception): ...
def succeed[T](v: T) -> Effect[T]: ...

def two() -> Effect[int, NotFound | Timeout | Other, A1 | B1 | C1]: ...
def one() -> Effect[int, NotFound, A1]: ...
lay_ab: Layer[A1 | B1, ValueError] = Layer()
lay_a: Layer[A1] = Layer()
lay_x: Layer[C1 | A1 | B1] = Layer()

reveal_type(two().catch_tag(NotFound, lambda e: succeed("x")))
reveal_type(two().catch_tag(NotFound, lambda e: succeed("x")).catch_tag(Timeout, lambda e: succeed(1.0)))
reveal_type(one().catch_tag(NotFound, lambda e: succeed("x")))
reveal_type(two().provide(lay_ab))
reveal_type(two().provide(lay_ab).provide(lay_x))
reveal_type(one().provide(lay_a))
reveal_type(one().provide(lay_ab))
reveal_type(two().map(lambda n: n + 1).catch_tag(Other, lambda e: succeed(str(e))).provide(lay_x))
# catching tag NOT in E: should be an error ideally
reveal_type(one().catch_tag(Timeout, lambda e: succeed("x")))
