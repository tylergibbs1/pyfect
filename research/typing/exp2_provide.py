"""Exp 2: partial provide via union subtraction; catch_tag subtraction; tag via __new__."""
from __future__ import annotations
from collections.abc import Callable, Generator
from typing import Any, Never, Self, TypeVar, Generic, overload, reveal_type

A = TypeVar("A", covariant=True)
E = TypeVar("E", covariant=True, default=Never)
R = TypeVar("R", covariant=True, default=Never)
ROut = TypeVar("ROut", contravariant=True)
RIn = TypeVar("RIn", covariant=True, default=Never)

class Effect(Generic[A, E, R]):
    def __iter__(self) -> Generator[Effect[object, E, R], object, A]: ...
    def pipe[B](self, f: Callable[[Self], B], /) -> B: ...

class Tag[S]:
    def __new__(cls) -> Effect[S, Never, Self]: ...  # type: ignore[misc]

class Layer(Generic[ROut, E, RIn]): ...

class A1(Tag[int]): ...
class B1(Tag[str]): ...
class C1(Tag[float]): ...
class D1(Tag[bytes]): ...

def gen[AA, EE = Never, RR = Never](f: Callable[[], Generator[Effect[object, EE, RR], object, AA]]) -> Effect[AA, EE, RR]: ...

def body():
    a = yield from A1()
    b = yield from B1()
    c = yield from C1()
    return (a, b, c)

eff = gen(body)
reveal_type(eff)

class _Provide[RO, E2, RI]:
    @overload
    def __call__[AA, EE = Never](self, eff: Effect[AA, EE, RO]) -> Effect[AA, EE | E2, RI]: ...
    @overload
    def __call__[AA, EE = Never, RR = Never](self, eff: Effect[AA, EE, RO | RR]) -> Effect[AA, EE | E2, RR | RI]: ...
    def __call__(self, eff: Any) -> Any: ...

def provide[RO, E2 = Never, RI = Never](layer: Layer[RO, E2, RI]) -> _Provide[RO, E2, RI]: ...

lay_a: Layer[A1] = Layer()
lay_ab: Layer[A1 | B1] = Layer()
lay_abc: Layer[A1 | B1 | C1, ValueError, D1] = Layer()
lay_d: Layer[D1] = Layer()

reveal_type(eff.pipe(provide(lay_a)))     # want R = B1 | C1
reveal_type(eff.pipe(provide(lay_ab)))    # want R = C1
reveal_type(eff.pipe(provide(lay_abc)))   # want E=ValueError R = D1
reveal_type(eff.pipe(provide(lay_d)))     # unrelated layer: want R unchanged (A1|B1|C1)
reveal_type(eff.pipe(provide(lay_abc)).pipe(provide(lay_d)))  # want R Never

# catch_tag
class NotFound(Exception): ...
class Timeout(Exception): ...
def two() -> Effect[int, NotFound | Timeout, A1]: ...
def one() -> Effect[int, NotFound, A1]: ...

class _Catch[EC, B, E2, R2]:
    @overload
    def __call__[AA, RR = Never](self, eff: Effect[AA, EC, RR]) -> Effect[AA | B, E2, RR | R2]: ...
    @overload
    def __call__[AA, RR = Never, ER = Never](self, eff: Effect[AA, EC | ER, RR]) -> Effect[AA | B, ER | E2, RR | R2]: ...
    def __call__(self, eff: Any) -> Any: ...

def catch_tag[EC, B, E2 = Never, R2 = Never](tag: type[EC], handler: Callable[[EC], Effect[B, E2, R2]]) -> _Catch[EC, B, E2, R2]: ...
def succeed[T](v: T) -> Effect[T]: ...

reveal_type(two().pipe(catch_tag(NotFound, lambda e: succeed("x"))))
reveal_type(one().pipe(catch_tag(NotFound, lambda e: succeed("x"))))
reveal_type(two().pipe(catch_tag(NotFound, lambda e: succeed(e))))

def run_sync[T](e: Effect[T, Never, Never]) -> T: ...
run_sync(eff)  # should error
run_sync(eff.pipe(provide(lay_abc)).pipe(provide(lay_d)))  # should error (ValueError)
