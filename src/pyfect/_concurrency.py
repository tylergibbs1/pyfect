"""Running effects concurrently: ``for_each``, ``all``, racing, timeouts.

Everything here forks child fibers of the calling fiber, so the rules are
the same everywhere: if the caller is interrupted, the children are
interrupted and awaited; if one child fails, its siblings are interrupted
and awaited before the failure is reported. Nothing outlives the call.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import sys
from collections.abc import Callable, Iterable
from typing import Any, Literal, Never, overload

from pyfect._cause_election import race_failure_cause
from pyfect._core import (
    Effect,
    _Callback,
    _FailCause,
    _FromExit,
    _Succeed,
    _WithFiber,
)
from pyfect._effect_args import require_effects
from pyfect._effect_base import Step
from pyfect._effect_resources import _run_finalizer
from pyfect._fiber import Fiber
from pyfect._fiber_all import interrupt_all
from pyfect._for_each import for_each_into as _for_each_into
from pyfect._primitives import _OnExit
from pyfect.cause import Cause, Interrupt, fail
from pyfect.duration import Input as DurationInput
from pyfect.duration import from_input_unsafe
from pyfect.errors import TimeoutException
from pyfect.exit import Exit, Success
from pyfect.option import Option, Some

_VOID: Effect[None] = _Succeed(None)

type Concurrency = int | Literal["unbounded"] | None
"""``None`` runs one at a time; an ``int`` caps how many run at once."""


def _resolve_concurrency(concurrency: int | Literal["unbounded"]) -> int:
    """How many run at once, as Effect's ``resolveConcurrency``: a limit under
    1 runs them one at a time. It does not see the items, so the choice between
    the sequential loop and child fibers never depends on how many there are."""
    return sys.maxsize if concurrency == "unbounded" else max(concurrency, 1)


def _drop_own_interrupts(causes: list[Cause[Any]], by: int) -> Cause[Any]:
    """Combine the racers' causes, dropping the interrupts we sent ourselves."""
    return race_failure_cause(
        Cause(tuple(r for r in c.reasons if not (isinstance(r, Interrupt) and r.fiber_id == by)))
        for c in causes
    )


@overload
def for_each[T, B, E = Never, R = Never](
    items: Iterable[T],
    f: Callable[[T], Effect[B, E, R]],
    *,
    concurrency: Concurrency = None,
    discard: Literal[False] = False,
) -> Effect[list[B], E, R]: ...
@overload
def for_each[T, E = Never, R = Never](
    items: Iterable[T],
    f: Callable[[T], Effect[object, E, R]],
    *,
    concurrency: Concurrency = None,
    discard: Literal[True],
) -> Effect[None, E, R]: ...
def for_each(
    items: Iterable[Any],
    f: Callable[[Any], Effect[Any, Any, Any]],
    *,
    concurrency: Concurrency = None,
    discard: bool = False,
) -> Effect[Any, Any, Any]:
    """Run ``f`` on every item and collect the results in order, or with
    ``discard`` succeed with ``None`` and keep none.

    With ``concurrency``, up to that many run at once. The first failure
    interrupts the rest. ``items`` is read each time the effect runs.
    """
    return for_each_into(items, f, concurrency, None if discard else _as_is)


def for_each_into[T, B, X, E, R](
    items: Iterable[T],
    f: Callable[[T], Effect[B, E, R]],
    concurrency: Concurrency,
    collect: Callable[[list[B]], X] | None,
) -> Effect[X, E, R]:
    """``for_each``, ending with ``collect(results)``, or with ``None`` and
    no results kept if ``collect`` is ``None`` (Effect's ``discard``)."""
    limit = 1 if concurrency is None else _resolve_concurrency(concurrency)
    return _for_each_into(items, f, limit, collect)


def _as_is[T](x: T) -> T:
    return x


# --- racing -------------------------------------------------------------------


def _race(effects: list[Effect[Any, Any, Any]], *, first_exit_wins: bool) -> Effect[Any, Any, Any]:
    """Effect's ``raceAll`` and ``raceAllFirst``: ``withFiber``, an exit
    hook on the caller's stack (``onExitUnsafe``, no op), and a callback
    that forks every racer at once."""

    def body(parent: Fiber[Any, Any]) -> Effect[Any, Any, Any]:
        fibers: list[Fiber[Any, Any]] = []

        def register(resume: Callable[[Effect[Any, Any, Any]], None]) -> None:
            remaining = len(effects)
            decided = False
            causes: list[Cause[Any]] = []

            def observer(ex: Exit[Any, Any]) -> None:
                nonlocal remaining, decided
                remaining -= 1
                if decided:
                    return
                if isinstance(ex, Success) or first_exit_wins:
                    decided = True
                    resume(_FromExit(ex))
                    return
                causes.append(ex.cause)
                if remaining == 0:
                    decided = True
                    resume(_FailCause(_drop_own_interrupts(causes, parent.id)))

            # Started at once, as in Effect: each runs before the next is
            # forked, and once one has decided the race no other starts.
            for e in effects:
                if decided:
                    break
                f = parent._fork(e, daemon=True, start_immediately=True)
                fibers.append(f)
                f.add_observer_unsafe(observer)

        def stop_losers(ex: Exit[Any, Any]) -> Step:
            # However the race ends, won, lost or interrupted (also in a
            # pause after the winner resumed it), as Effect's ``onExitUnsafe``
            # hook in ``raceAll``: never in the effect handed to ``resume``,
            # which an interrupt can skip. With every racer done, the exit
            # goes straight on.
            live = [f for f in fibers if f._exit is None]
            if not live:
                return _FromExit(ex)
            return _run_finalizer(interrupt_all(live), ex)

        parent._push(_OnExit(_VOID, stop_losers))
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
