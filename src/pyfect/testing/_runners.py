"""Running one effect as a test: ``run_test`` and ``run_test_async``."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from typing import Never

from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect.clock import Clock
from pyfect.console import CurrentConsole
from pyfect.context import Context
from pyfect.duration import Duration, to_seconds
from pyfect.exit import Exit
from pyfect.run import unwrap
from pyfect.scheduler import AsyncioScheduler
from pyfect.testing._clock import TestClock
from pyfect.testing._console import TestConsole
from pyfect.testing._runtime import SyncRuntime, run_on_loop


def run_test_exit[A, E](
    eff: Effect[A, E, Never],
    *,
    stall_timeout: float = 1.0,
    warning_delay: Duration = "1 second",
    timeout: Duration | None = None,
) -> Exit[A, E]:
    """Run ``eff`` on a synchronous scheduler with a ``TestClock`` and a
    ``TestConsole``.

    Raises ``StalledError`` when every fiber waits with nothing to wake it,
    and ``TestTimeoutError`` after ``timeout`` of real time; either way the
    effect is interrupted and its finalizers run first."""
    require_effect(eff, "eff")
    clock = TestClock(warning_delay=warning_delay)
    limit = None if timeout is None else to_seconds(timeout)
    try:
        return SyncRuntime(stall_timeout=stall_timeout).run(
            eff, Context.empty().add(Clock, clock).add(CurrentConsole, TestConsole()), timeout=limit
        )
    finally:
        clock.stop_warning()


def run_test[A](
    eff: Effect[A, Never, Never],
    *,
    stall_timeout: float = 1.0,
    warning_delay: Duration = "1 second",
    timeout: Duration | None = None,
) -> A:
    return unwrap(
        run_test_exit(
            eff, stall_timeout=stall_timeout, warning_delay=warning_delay, timeout=timeout
        )
    )


async def run_test_async_exit[A, E](
    eff: Effect[A, E, Never],
    *,
    warning_delay: Duration = "1 second",
    timeout: Duration | None = None,
) -> Exit[A, E]:
    """Run ``eff`` on the running asyncio loop with a ``TestClock`` and a
    ``TestConsole``, so
    ``from_async`` works on virtual time. Cancelling the awaiting task
    interrupts the effect and waits for its finalizers."""
    require_effect(eff, "eff")
    clock = TestClock(warning_delay=warning_delay)
    limit = None if timeout is None else to_seconds(timeout)
    try:
        return await run_on_loop(
            AsyncioScheduler.current(),
            eff,
            Context.empty().add(Clock, clock).add(CurrentConsole, TestConsole()),
            limit,
        )
    finally:
        clock.stop_warning()


async def run_test_async[A](
    eff: Effect[A, Never, Never],
    *,
    warning_delay: Duration = "1 second",
    timeout: Duration | None = None,
) -> A:
    return unwrap(await run_test_async_exit(eff, warning_delay=warning_delay, timeout=timeout))
