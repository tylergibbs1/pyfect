# pyright: strict
"""Layer 1: can ``a: Layer[Db] = succeed(Other, x)`` be rejected?

``Layer``'s services are contravariant (a layer building ``Db | Other`` is a
``Layer[Db]``), and ``succeed`` reads ``T`` from the tag through
``TagLike``, covariant in ``T`` because ``ServiceEffect`` is. With an
expected type pyright solves ``T`` as ``Db | Other`` and accepts the
assignment; the same layer held in a variable first is rejected.

Tried: making ``ServiceEffect`` invariant in the tag. That breaks every
``TagLike`` reader that wants the covariance (``Context.get`` on a
``Context[A | B]``, ``omit``, ``pick``) and ``Reference``, whose effect
requires ``Never``. A protocol member besides ``__call__`` loses literal
shapes (below). Adopted: calling a tag gives a ``TagEffect[S, R, T]``, a
``ServiceEffect[S, R]`` that also holds the tag ``T`` invariantly; layer
constructors take ``Provides[S, T]``, whose ``__call__`` reads it.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any, Generic, Literal, Never, Protocol, Self, TypeVar

A_co = TypeVar("A_co", covariant=True)
S_inv = TypeVar("S_inv")
T_co = TypeVar("T_co", covariant=True)
T_inv = TypeVar("T_inv")
ROut = TypeVar("ROut", contravariant=True)
E = TypeVar("E", covariant=True, default=Never)
R = TypeVar("R", covariant=True, default=Never)


class Effect(Generic[A_co, E, R]):
    def __iter__(self) -> Generator[Effect[Any, E, R], Any, A_co]:
        raise NotImplementedError


class Layer(Generic[ROut, E, R]): ...


# --- today: T read covariantly --------------------------------------------------------


class ServiceEffect(Effect[S_inv, Never, T_co]): ...


class Tag[S]:
    def __new__(cls) -> ServiceEffect[S, Self]:
        raise NotImplementedError


class TagLike[S, T](Protocol):
    def __call__(self) -> ServiceEffect[S, T]: ...


def succeed[S, T](tag: TagLike[S, T], service: S) -> Layer[T]:
    raise NotImplementedError


class Db(Tag[str]): ...


class Other(Tag[str]): ...


widened: Layer[Db] = succeed(Other, "x")  # accepted: T solved as Db | Other
held = succeed(Other, "x")
rejected: Layer[Db] = held  # pyright: ignore[reportAssignmentType]


# --- a protocol member besides __call__: literal shapes break ------------------------
# ``def __tag_of__(cls) -> Exact[S, Self]`` on the tag, matched by a protocol,
# pins ``T``, but pyright widens literal shapes when it solves ``S`` from a
# class member (``Tag[Literal[1, 2] | None]`` then rejects ``1``), so the
# shape must keep coming from ``__call__``.

# --- adopted: the tag's effect also holds the tag invariantly -------------------------


class TagEffect(ServiceEffect[S_inv, T_co], Generic[S_inv, T_co, T_inv]): ...


class ExactTag[S]:
    def __new__(cls) -> TagEffect[S, Self, Self]:
        raise NotImplementedError


class ExactReference[S](ExactTag[S]):
    def __new__(cls) -> TagEffect[S, Never, Self]:
        raise NotImplementedError


class Provides[S, T](Protocol):
    def __call__(self) -> TagEffect[S, Any, T]: ...


def exact_succeed[S, T](tag: Provides[S, T], service: S) -> Layer[T]:
    raise NotImplementedError


def get[S, T](tag: TagLike[S, T], built: Layer[T]) -> S:
    raise NotImplementedError


class ExactDb(ExactTag[str]): ...


class ExactOther(ExactTag[str]): ...


class Level(ExactReference[Literal[1, 2] | None]): ...


exact_widened: Layer[ExactDb] = exact_succeed(ExactOther, "x")  # pyright: ignore[reportAssignmentType]
exact_ok: Layer[ExactDb] = exact_succeed(ExactDb, "x")
builds_less: Layer[Never] = exact_succeed(ExactDb, "x")
wrong_shape = exact_succeed(ExactDb, 1)  # pyright: ignore[reportArgumentType]
literal_shape: Layer[Level] = exact_succeed(Level, 1)
wrong_literal = exact_succeed(Level, 3)  # pyright: ignore[reportArgumentType]
reveal_type(exact_succeed(ExactDb, "x"))

# Reading a service still widens: ``TagEffect`` is a covariant ``ServiceEffect``.
both: Effect[str, Never, ExactDb | ExactOther] = ExactDb()
pair: Layer[ExactDb | ExactOther] = exact_succeed(ExactDb, "x")  # pyright: ignore[reportAssignmentType]
reveal_type(get(ExactDb, exact_succeed(ExactDb, "x")))


def program() -> Generator[Effect[Any, Never, ExactDb | ExactOther], Any, str]:
    db = yield from ExactDb()
    other = yield from ExactOther()
    return db + other
