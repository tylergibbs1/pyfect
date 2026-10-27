# pyright: strict
"""Schema exp 1: how ``Codec[T, E, RD, RE]`` is spelled, and what pyright infers for
decoders, Literal, Union, transformations and brands.

Run: uv run pyright -p research/typing research/typing/schema_1_codec.py
Every line below passes; the comments say what was measured on the way.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Generic, Literal, LiteralString, Never, NewType, TypeVar, assert_type

T = TypeVar("T", covariant=True)
E = TypeVar("E", covariant=True, default=T)
RD = TypeVar("RD", covariant=True, default=Never)
RE = TypeVar("RE", covariant=True, default=Never)


class Effect(Generic[T, E, RD]): ...


class Codec(Generic[T, E, RD, RE]):
    """Effect's ``Codec<out T, out E = T, out RD = never, out RE = never>``. Covariant
    in all four, as in Effect; old-style TypeVars because PEP 695 cannot spell
    ``E = T`` together with explicit variance."""

    def pipe[B](self, f: Callable[[Codec[T, E, RD, RE]], B]) -> B:
        return f(self)


# Q1: E defaults to T, RD / RE to Never.
def string() -> Codec[str]: ...


assert_type(string(), Codec[str, str, Never, Never])


# Q2: decoders solve every parameter; Encoded-typed input is checked, and a
# synchronous decoder rejects a schema that needs services.
def decode_unknown_sync[A](schema: Codec[A, object, Never, object]) -> Callable[[object], A]: ...
def decode_sync[A, I](schema: Codec[A, I, Never, object]) -> Callable[[I], A]: ...
def decode_unknown_effect[A, R](
    schema: Codec[A, object, R, object],
) -> Callable[[object], Effect[A, Exception, R]]: ...


class Db: ...


def needs_db() -> Codec[int, str, Db]: ...


assert_type(decode_unknown_sync(string())(1), str)
assert_type(decode_unknown_effect(needs_db())(1), Effect[int, Exception, Db])
decode_sync(needs_db())  # pyright: ignore[reportArgumentType]
decode_sync(string())(1)  # pyright: ignore[reportArgumentType]


# Q3: Literal inference. A bound of ``str | int | bool`` strips literals
# (measured: Codec[str]); a bound containing ``LiteralString`` keeps string
# literals and mixed ones, but still widens all-int / all-bool calls to int /
# bool. Those need the expected type.
def literals[L: LiteralString | int | bool | None](*values: L) -> Codec[L]: ...


assert_type(literals("a", "b"), Codec[Literal["a", "b"], Literal["a", "b"]])
assert_type(literals(1, "a"), Codec[Literal[1, "a"], Literal[1, "a"]])
# (``Codec[Literal["a"]]`` written out widens its E default to str: spell both.)
assert_type(literals(1, 2), Codec[int])
ints: Codec[Literal[1, 2]] = literals(1, 2)


# Q4: Union over one shared TypeVar set joins each parameter.
def number() -> Codec[float]: ...
def number_from_string() -> Codec[float, str]: ...
def union[A, I, R1, R2](*members: Codec[A, I, R1, R2]) -> Codec[A, I, R1, R2]: ...


assert_type(union(string(), number()), Codec[str | float, str | float])
assert_type(union(string(), number_from_string()), Codec[str | float, str])
assert_type(union(string(), needs_db()), Codec[str | int, str, Db])


# Q5: transformations. A curried function returning a *generic* Callable is NOT
# checked by ``.pipe`` (measured: ``string().pipe(compose(number()))`` passes
# and gives Codec[float, str]). A class whose ``__call__`` has the free
# TypeVar is checked.
def compose_unchecked[B, M, I](to: Codec[B, M]) -> Callable[[Codec[M, I]], Codec[B, I]]: ...


assert_type(string().pipe(compose_unchecked(number())), Codec[float, str])  # unsound


class Compose[B, M]:
    def __call__[I](self, source: Codec[M, I], /) -> Codec[B, I]: ...


def compose[B, M](to: Codec[B, M]) -> Compose[B, M]: ...


assert_type(string().pipe(compose(number_from_string())), Codec[float, str])
string().pipe(compose(number()))  # pyright: ignore[reportArgumentType]

# Q6: brands. Pyright turns a NewType into a callable returning Any when it is
# matched against ``Callable[[A], B]`` (also ``Callable[..., B]`` and protocol
# ``__call__``; ``type[B]`` is rejected as a function), so ``brand(UserId)``
# cannot learn the brand. Both types must be named: pyfect.brand's
# ``Brand[str, UserId]`` already does that.
UserId = NewType("UserId", str)


def brand_from_callable[A, B](make: Callable[[A], B]) -> Callable[[A], B]: ...


assert_type(brand_from_callable(UserId), Callable[[Any], Any])


class Brand[A, B]: ...


class FromBrand[A, B]:
    def __call__[I, R1, R2](self, schema: Codec[A, I, R1, R2], /) -> Codec[B, I, R1, R2]: ...


def from_brand[A, B](brand: Brand[A, B]) -> FromBrand[A, B]: ...


assert_type(string().pipe(from_brand(Brand[str, UserId]())), Codec[UserId, str])
number().pipe(from_brand(Brand[str, UserId]()))  # pyright: ignore[reportArgumentType]
