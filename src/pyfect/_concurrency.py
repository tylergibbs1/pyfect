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

from pyfect._cause_election import late_sibling_cause, race_failure_cause
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
from pyfect.cause import Cause, Interrupt, fail
from pyfect.duration import Input as DurationInput
from pyfect.duration import from_input_unsafe
from pyfect.errors import TimeoutException
from pyfect.exit import Exit, Failure, Success
from pyfect.option import Option, Some

type Concurrency = int | Literal["unbounded"] | None
"""``None`` runs one at a time; an ``int`` caps how many run at once."""


def _parse_limit(concurrency: int | Literal["unbounded"]) -> Callable[[int], int]:
    """Maps the number of items (known when it runs) to how many run at once.
    As in Effect, a limit under 1 runs them one at a time."""
    if concurrency == "unbounded":
        return lambda n: max(n, 1)
    return lambda _: max(concurrency, 1)


def _drop_own_interrupts(causes: list[Cause[Any]], by: int) -> Cause[Any]:
    """Combine the racers' causes, dropping the interrupts we sent ourselves."""
    return race_failure_cause(
        Cause(tuple(r for r in c.reasons if not (isinstance(r, Interrupt) and r.fiber_id == by)))
        for c in causes
    )


def _with_late_failure(failure: Cause[Any] | None, late: Cause[Any]) -> Cause[Any] | None:
    """Add a failure that came after the first (or after the caller was
    interrupted): its interrupts are dropped, as Effect's ``forEach`` does,
    since they only report how the sibling was stopped."""
    reasons = tuple(r for r in late.reasons if not isinstance(r, Interrupt))
    if not reasons:
        return failure
    return Cause(reasons) if failure is None else late_sibling_cause(failure, Cause(reasons))


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
        # Once an item fails (or the caller is interrupted), no worker takes
        # another item, as Effect's forEach starts no item after its
        # terminal exit; this matters where the workers cannot be
        # interrupted (inside ``uninterruptible``).
        stopped = False
        # The first failure's cause, then what later failures add.
        failure: Cause[Any] | None = None

        def worker():
            nonlocal next_index
            while not stopped and next_index < n:
                i = next_index
                next_index += 1
                results[i] = yield from f(items[i])

        def register(resume: Callable[[Effect[Any, Any, Any]], None]) -> Effect[None]:
            workers: list[Fiber[Any, Any]] = []
            remaining = 0
            forking = True

            def result() -> Effect[Any, Any, Any]:
                return _Succeed(results) if failure is None else _FailCause(failure)

            def observer(ex: Exit[Any, Any]) -> None:
                # Record first: interrupting siblings finishes them (and
                # re-enters this observer) before the loop below returns.
                nonlocal remaining, stopped, failure
                remaining -= 1
                failed_first = False
                if isinstance(ex, Failure):
                    if not stopped:
                        stopped = failed_first = True
                        failure = ex.cause
                    else:
                        failure = _with_late_failure(failure, ex.cause)
                if remaining == 0 and not forking:
                    resume(result())
                elif failed_first:
                    for w in workers:
                        w.interrupt_as_unsafe(parent.id, parent._interruptor_annotations())

            # Started at once, as in Effect, each as interruptible as the
            # parent; a worker runs before the next is forked, so once an
            # item has failed no further worker starts.
            for _ in range(min(limit, n)):
                if stopped or next_index >= n:
                    break
                w = parent._fork(
                    _Gen(worker), daemon=False, start_immediately=True, uninterruptible="inherit"
                )
                workers.append(w)
                remaining += 1
                w.add_observer_unsafe(observer)
            forking = False
            if remaining == 0:
                resume(result())

            def cancel() -> Effect[None]:
                # Interrupted from outside: report what the workers did too.
                nonlocal stopped
                stopped = True
                return interrupt_all(
                    workers, parent.id, parent._interruptor_annotations()
                ).and_then(_Suspend(report))

            def report() -> Effect[None]:
                return _Succeed(None) if failure is None else _FailCause(failure)

            return _Suspend(cancel)

        return _Callback(register)

    return _WithFiber(body)


# --- racing -------------------------------------------------------------------


def _race(effects: list[Effect[Any, Any, Any]], *, first_exit_wins: bool) -> Effect[Any, Any, Any]:
    def body(parent: Fiber[Any, Any]) -> Effect[Any, Any, Any]:
        def register(resume: Callable[[Effect[Any, Any, Any]], None]) -> Effect[None]:
            fibers: list[Fiber[Any, Any]] = []
            remaining = len(effects)
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

                        def stop_losers() -> Effect[None]:
                            # Read when the parent goes on, as Effect's
                            # exit hook does: a loser still starting when
                            # this one won (it may be what settled the
                            # race) is in ``fibers`` by then.
                            losers = [f for f in fibers if f is not me]
                            return interrupt_all(
                                losers, parent.id, parent._interruptor_annotations()
                            )

                        resume(
                            _SetInterruptible(_Suspend(stop_losers), False).and_then(_FromExit(ex))
                        )
                        return
                    causes.append(ex.cause)
                    if remaining == 0:
                        decided = True
                        resume(_FailCause(_drop_own_interrupts(causes, parent.id)))

                return observer

            # Started at once, as in Effect: each runs before the next is
            # forked, and once one has decided the race no other starts.
            for e in effects:
                if decided:
                    break
                f = parent._fork(e, daemon=False, start_immediately=True)
                fibers.append(f)
                f.add_observer_unsafe(observer_for(f))
            return interrupt_all(fibers, parent.id, parent._interruptor_annotations())

        return _Callback(register)

    return _WithFiber(body)


# The public types for these two live on ``Effect.race`` / ``Effect.race_first``.


def race(a: Effect[Any, Any, Any], b: Effect[Any, Any, Any]) -> Effect[Any, Any, Any]:
    return _race([a, b], first_exit_wins=False)


def race_first(a: Effect[Any, Any, Any], b: Effect[Any, Any, Any]) -> Effect[Any, Any, Any]:
    return _race([a, b], first_exit_wins=True)


def race_all[A = Never, EE = Never, RR = Never](*effects: Effect[A, EE, RR]) -> Effect[A, EE, RR]:
    """The first to succeed wins; the rest are interrupted. Fails only if
    all fail. With no effects it never finishes, as in Effect."""
    require_effects(effects, "effects")
    return _race(list(effects), first_exit_wins=False)


def race_all_first[A = Never, EE = Never, RR = Never](
    *effects: Effect[A, EE, RR],
) -> Effect[A, EE, RR]:
    """The first to finish wins, success or failure; the rest are
    interrupted. With no effects it never finishes, as in Effect."""
    require_effects(effects, "effects")
    return _race(list(effects), first_exit_wins=True)


# The public types of the timeouts live on the ``Effect`` methods.


def timeout_option[A, E, R](
    eff: Effect[A, E, R], duration: DurationInput
) -> Effect[Option[A], E, R]:
    from pyfect.clock import sleep

    return race_first(eff.map(Some), sleep(duration).as_(None))


def timeout_or_else(
    eff: Effect[Any, Any, Any],
    duration: DurationInput,
    or_else: Callable[[], Effect[Any, Any, Any]],
) -> Effect[Any, Any, Any]:
    return timeout_option(eff, duration).flat_map(
        lambda found: or_else() if found is None else _Succeed(found.value)
    )


def timeout(eff: Effect[Any, Any, Any], duration: DurationInput) -> Effect[Any, Any, Any]:
    seconds = from_input_unsafe(duration)
    return timeout_or_else(eff, seconds, lambda: _FailCause(fail(TimeoutException(seconds))))
