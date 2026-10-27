"""Running effects concurrently: ``for_each``, ``all``, racing, timeouts.

Everything here forks child fibers of the calling fiber, so the rules are
the same everywhere: if the caller is interrupted, the children are
interrupted and awaited; if one child fails, its siblings are interrupted
and awaited before the failure is reported. Nothing outlives the call.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Iterable
from typing import Any, Literal, Never

from pyfect._core import (
    Effect,
    _Callback,
    _FailCause,
    _FromExit,
    _Gen,
    _SetInterruptible,
    _Succeed,
    _Suspend,
    _WithFiber,
)
from pyfect._effect_args import require_effects
from pyfect._fiber import Fiber, interrupt_all
from pyfect.cause import Cause, Interrupt, fail, merge
from pyfect.duration import Duration, to_seconds
from pyfect.errors import TimeoutException
from pyfect.exit import Exit, Failure, Success
from pyfect.option import Option, Some

type Concurrency = int | Literal["unbounded"] | None
"""``None`` runs one at a time; an ``int`` caps how many run at once."""


def _parse_limit(concurrency: int | Literal["unbounded"]) -> Callable[[int], int]:
    """Validate a limit when the effect is built; the result maps the
    number of items (known when it runs) to how many run at once."""
    if concurrency == "unbounded":
        return lambda n: max(n, 1)
    if concurrency < 1:
        raise ValueError(f"concurrency must be at least 1, got {concurrency}")
    return lambda _: concurrency


def _drop_own_interrupts(causes: list[Cause[Any]], by: int) -> Cause[Any]:
    """Combine sibling causes, dropping the interrupts we sent ourselves."""
    return merge(
        *(
            Cause(
                tuple(r for r in c.reasons if not (isinstance(r, Interrupt) and r.fiber_id == by))
            )
            for c in causes
        )
    )


def for_each[T, B, E = Never, R = Never](
    items: Iterable[T],
    f: Callable[[T], Effect[B, E, R]],
    *,
    concurrency: Concurrency = None,
) -> Effect[list[B], E, R]:
    """Run ``f`` on every item and collect the results in order.

    With ``concurrency``, up to that many run at once. The first failure
    interrupts the rest. ``items`` is read each time the effect runs.
    """
    if concurrency is None:
        return _for_each_sequential(items, f)
    limit_for = _parse_limit(concurrency)

    def start() -> Effect[list[B], E, R]:
        snapshot = list(items)
        limit = limit_for(len(snapshot))
        if limit == 1:
            return _for_each_sequential(snapshot, f)
        return _for_each_concurrent(snapshot, f, limit)

    return _Suspend(start)


def _for_each_sequential[T, B, E, R](
    items: Iterable[T], f: Callable[[T], Effect[B, E, R]]
) -> Effect[list[B], E, R]:
    def loop():
        out: list[B] = []
        for item in items:
            out.append((yield from f(item)))  # noqa: PERF401 - yield is not allowed in comprehensions
        return out

    return _Gen(loop)


def _for_each_concurrent[T, B, E, R](
    items: list[T], f: Callable[[T], Effect[B, E, R]], limit: int
) -> Effect[list[B], E, R]:
    def body(parent: Fiber[Any, Any]) -> Effect[list[B], E, R]:
        n = len(items)
        if n == 0:
            return _Succeed([])
        results: list[Any] = [None] * n
        next_index = 0

        def worker():
            nonlocal next_index
            while next_index < n:
                i = next_index
                next_index += 1
                results[i] = yield from f(items[i])

        def register(resume: Callable[[Effect[Any, Any, Any]], None]) -> Effect[None]:
            # Started at once, as in Effect, each as interruptible as the parent.
            workers = [
                parent._fork(
                    _Gen(worker), daemon=False, start_immediately=True, uninterruptible="inherit"
                )
                for _ in range(min(limit, n))
            ]
            remaining = len(workers)
            causes: list[Cause[Any]] = []

            def observer(ex: Exit[Any, Any]) -> None:
                # Record first: interrupting siblings finishes them (and
                # re-enters this observer) before the loop below returns.
                nonlocal remaining
                remaining -= 1
                failed_first = isinstance(ex, Failure) and not causes
                if isinstance(ex, Failure):
                    causes.append(ex.cause)
                if remaining == 0:
                    if causes:
                        resume(_FailCause(_drop_own_interrupts(causes, parent.id)))
                    else:
                        resume(_Succeed(results))
                elif failed_first:
                    for w in workers:
                        w.unsafe_interrupt_as(parent.id)

            def cancel() -> Effect[None]:
                # Interrupted from outside: report what the workers did too.
                failed = _drop_own_interrupts(causes, parent.id)
                return _FailCause(failed) if failed.reasons else _Succeed(None)

            for w in workers:
                w.unsafe_add_observer(observer)
            return interrupt_all(workers, parent.id).and_then(_Suspend(cancel))

        return _Callback(register)

    return _WithFiber(body)


# --- racing -------------------------------------------------------------------


def _race(effects: list[Effect[Any, Any, Any]], *, first_exit_wins: bool) -> Effect[Any, Any, Any]:
    def body(parent: Fiber[Any, Any]) -> Effect[Any, Any, Any]:
        def register(resume: Callable[[Effect[Any, Any, Any]], None]) -> Effect[None]:
            # Started at once, as in Effect: they run before anything else.
            fibers = [parent._fork(e, daemon=False, start_immediately=True) for e in effects]
            remaining = len(fibers)
            decided = False
            causes: list[Cause[Any]] = []

            def observer_for(me: Fiber[Any, Any]) -> Callable[[Exit[Any, Any]], None]:
                def observer(ex: Exit[Any, Any]) -> None:
                    nonlocal remaining, decided
                    remaining -= 1
                    if decided:
                        return
                    if isinstance(ex, Success) or first_exit_wins:
                        decided = True
                        losers = [f for f in fibers if f is not me]
                        # At once, so a loser that has not started never does.
                        for loser in losers:
                            loser.unsafe_interrupt_as(parent.id)
                        resume(
                            _SetInterruptible(interrupt_all(losers, parent.id), False).and_then(
                                _FromExit(ex)
                            )
                        )
                        return
                    causes.append(ex.cause)
                    if remaining == 0:
                        decided = True
                        resume(_FailCause(_drop_own_interrupts(causes, parent.id)))

                return observer

            for f in fibers:
                f.unsafe_add_observer(observer_for(f))
            return interrupt_all(fibers, parent.id)

        return _Callback(register)

    return _WithFiber(body)


# The public types for these two live on ``Effect.race`` / ``Effect.race_first``.


def race(a: Effect[Any, Any, Any], b: Effect[Any, Any, Any]) -> Effect[Any, Any, Any]:
    return _race([a, b], first_exit_wins=False)


def race_first(a: Effect[Any, Any, Any], b: Effect[Any, Any, Any]) -> Effect[Any, Any, Any]:
    return _race([a, b], first_exit_wins=True)


def race_all[A, EE = Never, RR = Never](*effects: Effect[A, EE, RR]) -> Effect[A, EE, RR]:
    """The first to succeed wins; the rest are interrupted. Fails only if
    all fail."""
    require_effects(effects, "effects")
    if not effects:
        raise ValueError("race_all needs at least one effect")
    return _race(list(effects), first_exit_wins=False)


def race_all_first[A, EE = Never, RR = Never](*effects: Effect[A, EE, RR]) -> Effect[A, EE, RR]:
    """The first to finish wins, success or failure; the rest are
    interrupted."""
    require_effects(effects, "effects")
    if not effects:
        raise ValueError("race_all_first needs at least one effect")
    return _race(list(effects), first_exit_wins=True)


# The public types of the timeouts live on the ``Effect`` methods.


def timeout_option[A, E, R](eff: Effect[A, E, R], duration: Duration) -> Effect[Option[A], E, R]:
    from pyfect.clock import sleep

    return race_first(eff.map(Some), sleep(duration).as_(None))


def timeout_or_else(
    eff: Effect[Any, Any, Any], duration: Duration, or_else: Callable[[], Effect[Any, Any, Any]]
) -> Effect[Any, Any, Any]:
    return timeout_option(eff, duration).flat_map(
        lambda found: or_else() if found is None else _Succeed(found.value)
    )


def timeout(eff: Effect[Any, Any, Any], duration: Duration) -> Effect[Any, Any, Any]:
    seconds = to_seconds(duration)
    return timeout_or_else(eff, seconds, lambda: _FailCause(fail(TimeoutException(seconds))))
