"""Question: ``workflow_1_schemas.py`` fixed an activity's ``A`` from its
schema with an invariant ``Exactly`` protocol. Does that hold whichever
order the call site writes ``success=`` and ``execute=`` in, and what does a
handler needing no extra services infer?

Q1. ``activity(execute=fx.succeed(1), success=S.String)``: rejected?
Q2. ``to_layer(handler)`` where the handler needs only the services the
    union removes: is ``R`` ``Never``?

Run: ``uv run pyright -p research/typing research/typing/workflow_2_exact_schemas.py``.

Answers:

Q1. Not with ``Exactly`` from ``workflow_1``: pyright solves arguments in
    the order written. With ``execute=`` first, ``A`` is ``int``; matching
    ``S.String``'s ``__codec__() -> Bottom[str, ...]`` (covariant in ``A``)
    then widens ``A`` to ``int | str`` despite the protocol's declared
    invariance. A protocol whose ``__codec__`` returns something with a
    ``make(input: T) -> T`` member (``T`` in and out) pins ``A`` from either
    side: the wrong effect is rejected in both orders, ``int`` still fits
    ``S.Number`` (``A`` is ``float``), and schema classes match. Adding a
    second member to that inner protocol (to also require no services)
    makes every schema fail to match, so services go unchecked.
Q2. Not when the effect needs nothing at all (``R`` of ``Never``): union
    matching then leaves the TypeVar ``Unknown``, its ``Never`` default
    notwithstanding (an effect needing only ``Engine`` gives ``Never``). A first overload whose parameter
    is exactly ``Effect[A, E, Engine | Instance | Scope]`` (no TypeVar)
    gives ``Never``; handlers needing more fall through to the second.
    The same holds for ``layer.merge`` of layers that all build ``Never``:
    the result builds ``Unknown``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Never, Protocol, TypeVar, assert_type, overload

import pyfect as fx
from pyfect import schema as S
from pyfect.context import Tag
from pyfect.scope import Scope


class Engine(Tag[object]):
    pass


class Db(Tag[object]):
    pass


T = TypeVar("T")


# Q1 ------------------------------------------------------------------------------------


class Covariant(Protocol[T]):  # pyright: ignore[reportInvalidTypeVarUse]
    def __codec__(self) -> S.Bottom[T, object, Never, Never]: ...


class _ExactBottom(Protocol[T]):
    def make(self, input: T, /) -> T: ...


class Exactly(Protocol[T]):
    def __codec__(self) -> _ExactBottom[T]: ...


def activity_covariant[A](*, execute: fx.Effect[A], success: Covariant[A]) -> fx.Effect[A]:
    return execute


def activity[A](*, execute: fx.Effect[A], success: Exactly[A]) -> fx.Effect[A]:
    return execute


class Point(S.Class):
    x: float


# execute= first widens with the covariant protocol...
assert_type(activity_covariant(execute=fx.succeed(1), success=S.String), fx.Effect[int | str])
# ...and is rejected, in either order, with the exact one.
activity(execute=fx.succeed(1), success=S.String)  # pyright: ignore[reportArgumentType]
activity(success=S.String, execute=fx.succeed(1))  # pyright: ignore[reportArgumentType]
assert_type(activity(execute=fx.succeed(1), success=S.Number), fx.Effect[float])
assert_type(activity(execute=fx.succeed(Point(x=1)), success=Point), fx.Effect[Point])


# Q2 ------------------------------------------------------------------------------------


class Layer[R](Protocol):
    def requirements(self) -> R: ...


def to_layer_single[R = Never](
    handler: Callable[[], fx.Effect[None, Never, R | Engine | Scope]],
) -> Layer[R]: ...


@overload
def to_layer(handler: Callable[[], fx.Effect[None, Never, Engine | Scope]]) -> Layer[Never]: ...
@overload
def to_layer[R](handler: Callable[[], fx.Effect[None, Never, R | Engine | Scope]]) -> Layer[R]: ...
def to_layer[R](handler: Callable[[], fx.Effect[None, Never, R | Engine | Scope]]) -> Layer[R]: ...


def plain() -> fx.Effect[None, Never, Engine]: ...
def with_db() -> fx.Effect[None, Never, Db | Engine]: ...


def activity_single[R = Never](execute: fx.Effect[None, Never, R | Engine | Scope]) -> Layer[R]: ...


assert_type(to_layer_single(plain), Layer[Never])
reveal_type(to_layer_single(lambda: fx.void))  # Layer[Unknown]
reveal_type(activity_single(fx.void))  # Layer[Unknown]
assert_type(to_layer(lambda: fx.void), Layer[Never])
assert_type(to_layer(plain), Layer[Never])
assert_type(to_layer(with_db), Layer[Db])
