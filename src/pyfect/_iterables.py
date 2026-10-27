"""Effects over iterables of values or effects: ``first_success_of``,
``filter``, ``partition``, ``validate``."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from typing import Any, Literal, Never, TypeIs, overload

from pyfect._concurrency import Concurrency, for_each
from pyfect._core import Effect, _FailCause, _Succeed, _Suspend
from pyfect.cause import die, fail
from pyfect.result import Err, Ok, Result


def first_success_of[A, EE = Never, RR = Never](
    effects: Iterable[Effect[A, EE, RR]],
) -> Effect[A, EE, RR]:
    """Run the effects in order until one succeeds. If all fail, fail with
    the last one's error; later effects never run. ``effects`` is read each
    time the effect runs, and an empty one is a defect."""

    def start() -> Effect[A, EE, RR]:
        it = iter(effects)
        first = next(it, None)
        if first is None:
            return _FailCause(die(ValueError("Received an empty collection of effects")))
        return _try_next(first, it)

    return _Suspend(start)


def _try_next[A, E, R](
    current: Effect[A, E, R], rest: Iterator[Effect[A, E, R]]
) -> Effect[A, E, R]:
    following = next(rest, None)
    if following is None:
        return current
    return current.catch_all(lambda _: _try_next(following, rest))


@overload
def filter[A, B](items: Iterable[A], predicate: Callable[[A], TypeIs[B]]) -> Effect[list[B]]: ...
@overload
def filter[A](items: Iterable[A], predicate: Callable[[A], bool]) -> Effect[list[A]]: ...
@overload
def filter[A, E = Never, R = Never](
    items: Iterable[A],
    predicate: Callable[[A], Effect[bool, E, R]],
    *,
    concurrency: Concurrency = None,
) -> Effect[list[A], E, R]: ...
def filter(
    items: Iterable[Any],
    predicate: Callable[[Any], bool | Effect[bool, Any, Any]],
    *,
    concurrency: Concurrency = None,
) -> Effect[list[Any], Any, Any]:
    """Keep the items that pass ``predicate``, in order. An effectful
    predicate runs like ``for_each``, ``concurrency`` included."""

    def keep(item: Any) -> Effect[tuple[bool, Any], Any, Any]:
        verdict = predicate(item)
        if isinstance(verdict, Effect):
            return verdict.map(lambda passed: (passed, item))
        return _Succeed((verdict, item))

    return for_each(items, keep, concurrency=concurrency).map(
        lambda checked: [item for passed, item in checked if passed]
    )


def partition[T, B, E = Never, R = Never](
    items: Iterable[T],
    f: Callable[[T], Effect[B, E, R]],
    *,
    concurrency: Concurrency = None,
) -> Effect[tuple[list[B], list[E]], Never, R]:
    """Run ``f`` on every item, like ``for_each``, without stopping at
    failures: the values that succeeded and the typed errors, each in
    order. Defects and interruptions still propagate."""
    return for_each(items, lambda item: f(item).result(), concurrency=concurrency).map(_split)


def _split[B, E](results: list[Result[B, E]]) -> tuple[list[B], list[E]]:
    passes = [r.value for r in results if isinstance(r, Ok)]
    fails = [r.error for r in results if isinstance(r, Err)]
    return passes, fails


@overload
def validate[T, B, R = Never](
    items: Iterable[T],
    f: Callable[[T], Effect[B, Never, R]],
    *,
    concurrency: Concurrency = None,
    discard: Literal[False] = False,
) -> Effect[list[B], Never, R]: ...
@overload
def validate[T, R = Never](
    items: Iterable[T],
    f: Callable[[T], Effect[object, Never, R]],
    *,
    concurrency: Concurrency = None,
    discard: Literal[True],
) -> Effect[None, Never, R]: ...
@overload
def validate[T, B, E = Never, R = Never](
    items: Iterable[T],
    f: Callable[[T], Effect[B, E, R]],
    *,
    concurrency: Concurrency = None,
    discard: Literal[False] = False,
) -> Effect[list[B], tuple[E, *tuple[E, ...]], R]: ...
@overload
def validate[T, E = Never, R = Never](
    items: Iterable[T],
    f: Callable[[T], Effect[object, E, R]],
    *,
    concurrency: Concurrency = None,
    discard: Literal[True],
) -> Effect[None, tuple[E, *tuple[E, ...]], R]: ...
def validate(
    items: Iterable[Any],
    f: Callable[[Any], Effect[Any, Any, Any]],
    *,
    concurrency: Concurrency = None,
    discard: bool = False,
) -> Effect[Any, Any, Any]:
    """Like ``partition``, but fail with every typed error (never an empty
    tuple) if any item failed; otherwise succeed with the values, or with
    ``None`` when ``discard`` is set."""

    def decide(split: tuple[list[Any], list[Any]]) -> Effect[Any, Any, Never]:
        passes, fails = split
        if fails:
            return _FailCause(fail((fails[0], *fails[1:])))
        return _Succeed(None if discard else passes)

    return partition(items, f, concurrency=concurrency).flat_map(decide)
