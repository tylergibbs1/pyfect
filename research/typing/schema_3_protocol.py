# pyright: strict
"""Schema exp 3: one parameter type for "a schema": codec values and Class types.

Effect's ``Schema.decodeUnknownSync(User)`` takes a Class like any codec. Here a
``Codec`` protocol with one member, ``__codec__``, is matched by ``Bottom`` (the
concrete schema object, returning itself) and by Class subclasses (a classmethod
returning a ``Bottom[Self, Mapping[str, object]]``). Combinators and decoders
take ``Codec``; the services parameters still solve and ``Never`` still rejects
a schema that needs services.

Run: uv run pyright -p research/typing research/typing/schema_3_protocol.py
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Generic, Literal, LiteralString, Never, Protocol, Self, TypeVar, assert_type

T = TypeVar("T", covariant=True)
E = TypeVar("E", covariant=True, default=T)
RD = TypeVar("RD", covariant=True, default=Never)
RE = TypeVar("RE", covariant=True, default=Never)


class Bottom(Generic[T, E, RD, RE]):
    def __codec__(self) -> Bottom[T, E, RD, RE]:
        return self

    def pipe[B](self, f: Callable[[Self], B], /) -> B:
        return f(self)


class Codec(Protocol[T, E, RD, RE]):
    def __codec__(self) -> Bottom[T, E, RD, RE]: ...


type Schema[A] = Codec[A, object, object, object]


class Class:
    @classmethod
    def __codec__(cls) -> Bottom[Self, Mapping[str, object]]: ...


class User(Class): ...


class Db: ...


String: Bottom[str] = Bottom()
Number: Bottom[float] = Bottom()
NumberFromString: Bottom[float, str] = Bottom()
NeedsDb: Bottom[int, str, Db] = Bottom()


def decode_unknown_sync[A](schema: Codec[A, object, Never, object]) -> Callable[[object], A]: ...
def decode_sync[A, I](schema: Codec[A, I, Never, object]) -> Callable[[I], A]: ...
def decode_unknown_effect[A, R](
    schema: Codec[A, object, R, object],
) -> Callable[[object], tuple[A, R]]: ...
def encode_sync[A, I](schema: Codec[A, I, object, Never]) -> Callable[[A], I]: ...


assert_type(decode_unknown_sync(String)(1), str)
assert_type(decode_unknown_sync(User)(1), User)
assert_type(decode_sync(NumberFromString), Callable[[str], float])
assert_type(decode_sync(User), Callable[[Mapping[str, object]], User])
assert_type(decode_unknown_effect(NeedsDb)(1), tuple[int, Db])
assert_type(encode_sync(NumberFromString), Callable[[float], str])
decode_unknown_sync(NeedsDb)  # pyright: ignore[reportArgumentType]
decode_sync(String)(1)  # pyright: ignore[reportArgumentType]


def takes_schema(s: Schema[str]) -> None: ...


takes_schema(String)
takes_schema(NumberFromString)  # pyright: ignore[reportArgumentType]


def array[A, I, R1, R2](
    item: Codec[A, I, R1, R2],
) -> Bottom[tuple[A, ...], tuple[I, ...], R1, R2]: ...
def union[A, I, R1, R2](*members: Codec[A, I, R1, R2]) -> Bottom[A, I, R1, R2]: ...
def literals[L: LiteralString | int | bool | None](*values: L) -> Bottom[L]: ...


assert_type(array(User), Bottom[tuple[User, ...], tuple[Mapping[str, object], ...]])
# int joins float
assert_type(union(String, NumberFromString, NeedsDb), Bottom[str | float, str, Db])
assert_type(union(String, User), Bottom[str | User, str | Mapping[str, object]])
assert_type(literals("a", "b"), Bottom[Literal["a", "b"], Literal["a", "b"]])
ints: Bottom[Literal[1, 2]] = literals(1, 2)  # int literals need the expected type


# A curried combinator with a free type variable must be a class with a generic
# __call__: a function returning a generic Callable is not checked by .pipe.
class _DecodeTo[B, M, R3, R4]:
    def __call__[I, R1, R2](
        self, source: Codec[M, I, R1, R2], /
    ) -> Bottom[B, I, R1 | R3, R2 | R4]: ...


def decode_to[B, M, R3, R4](to: Codec[B, M, R3, R4]) -> _DecodeTo[B, M, R3, R4]: ...


assert_type(String.pipe(decode_to(NumberFromString)), Bottom[float, str])
Number.pipe(decode_to(NumberFromString))  # pyright: ignore[reportArgumentType]
