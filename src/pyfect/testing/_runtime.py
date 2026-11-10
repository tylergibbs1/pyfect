"""Where tests run: a synchronous runtime and an asyncio one.

Both run an effect with a given context and an optional real-time
``timeout``. When the timeout passes, the test's fiber is interrupted and
its finalizers run to completion before ``TestTimeoutError`` is raised.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
from typing import Any, Never, Protocol

from pyfect._core import Effect
from pyfect._fiber import Fiber, root_fiber
from pyfect.clock import Clock
from pyfect.context import Context
from pyfect.duration import Duration
from pyfect.exit import Exit, Failure
from pyfect.run import await_fiber
from pyfect.scheduler import AsyncioScheduler, Cancel, Scheduler, StalledError, SyncScheduler
from pyfect.testing._clock import TestClock


class TestTimeoutError(TimeoutError):
    """A test ran past its timeout. It was interrupted and its finalizers
    ran before this was raised."""

    __test__ = False


class Runtime(Protocol):
    def run[A, E](
        self, eff: Effect[A, E, Never], context: Context, *, timeout: Duration | None
    ) -> Exit[A, E]: ...

    def close(self) -> None: ...


class _Deadline:
    """Interrupts a fiber once ``timeout`` of real time has passed."""

    __slots__ = ("_cancel", "expired", "timeout")

    def __init__(self, fiber: Fiber[Any, Any], timeout: Duration | None) -> None:
        self.timeout = timeout
        self.expired = False
        self._cancel: Cancel | None = None
        if timeout is None:
            return

        def expire() -> None:
            self.expired = True
            fiber.interrupt_as_unsafe(None)

        # A daemon timer: a stalled test still fails fast with StalledError.
        self._cancel = fiber._scheduler.call_later(timeout, expire, daemon=True)

    def _seconds(self) -> float | None:
        return None if self.timeout is None else self.timeout.to_seconds()

    def check[A, E](self, ex: Exit[A, E], context: Context) -> Exit[A, E]:

        if self._cancel is not None:
            self._cancel()
        if not self.expired:
            return ex
        error = TestTimeoutError(
            f"test timed out after {self._seconds()}s; it was interrupted and its finalizers ran"
        )
        if isinstance(ex, Failure) and not ex.cause.has_interrupts_only:
            error.add_note("While interrupting it:\n" + ex.cause.pretty())
        _note_sleepers(error, context)
        raise error

    def stalled_after_timeout(self, stall: StalledError, context: Context) -> TestTimeoutError:
        """The real failure when interrupting at the deadline left a finalizer stuck: the
        timeout, which ``StalledError`` would otherwise hide."""
        error = TestTimeoutError(
            f"test timed out after {self._seconds()}s; it was interrupted and a finalizer never "
            f"finished ({stall})"
        )
        _note_sleepers(error, context)
        return error


def _note_sleepers(error: BaseException, context: Context) -> None:
    _, clock = context.lookup(Clock)
    if isinstance(clock, TestClock) and clock.pending_sleeps:
        error.add_note(
            f"{clock.pending_sleeps} fiber(s) are sleeping on the TestClock. "
            "Move time with testing.adjust(...)."
        )


def _start[A, E](
    scheduler: Scheduler, eff: Effect[A, E, Never], context: Context, timeout: Duration | None
) -> tuple[Fiber[A, E], _Deadline]:
    fiber: Fiber[A, E] = root_fiber(scheduler, context)
    fiber._start(eff)
    return fiber, _Deadline(fiber, timeout)


class SyncRuntime:
    """Runs on a ``SyncScheduler``. Several runs share it, so fibers a
    shared layer forked keep running during each test."""

    def __init__(self, *, stall_timeout: float | None = 1.0) -> None:
        self.scheduler = SyncScheduler()
        self._stall_timeout = stall_timeout

    def run[A, E](
        self, eff: Effect[A, E, Never], context: Context, *, timeout: Duration | None
    ) -> Exit[A, E]:
        fiber, deadline = _start(self.scheduler, eff, context, timeout)

        def done() -> bool:
            return fiber._exit is not None

        try:
            self.scheduler.run_until(done, stall_timeout=self._stall_timeout)
        except StalledError as err:
            if deadline.expired:
                raise deadline.stalled_after_timeout(err, context) from err
            err.add_note("Every fiber is waiting; the test was interrupted to run its finalizers.")
            _note_sleepers(err, context)
            self._drain(fiber)
            raise
        except KeyboardInterrupt:
            self._drain(fiber)
            raise
        ex = fiber._exit
        assert ex is not None
        return deadline.check(ex, context)

    def _drain(self, fiber: Fiber[Any, Any]) -> None:
        """Interrupt ``fiber`` and let its finalizers run, unless they stall
        too."""
        fiber.interrupt_as_unsafe(None)
        try:
            self.scheduler.run_until(
                lambda: fiber._exit is not None, stall_timeout=self._stall_timeout
            )
        except StalledError:
            return

    def close(self) -> None:
        return


class AsyncioRuntime:
    """Runs on an event loop of its own, kept across runs."""

    def __init__(self) -> None:
        self._loop = asyncio.new_event_loop()
        self.scheduler = AsyncioScheduler(self._loop)

    def run[A, E](
        self, eff: Effect[A, E, Never], context: Context, *, timeout: Duration | None
    ) -> Exit[A, E]:
        return self._loop.run_until_complete(run_on_loop(self.scheduler, eff, context, timeout))

    def close(self) -> None:
        self._loop.run_until_complete(self._loop.shutdown_asyncgens())
        self._loop.close()


async def run_on_loop[A, E](
    scheduler: AsyncioScheduler,
    eff: Effect[A, E, Never],
    context: Context,
    timeout: Duration | None,
) -> Exit[A, E]:
    """Run on the running loop. Cancelling the awaiting task interrupts the
    fiber and waits for its finalizers."""
    fiber, deadline = _start(scheduler, eff, context, timeout)
    ex = await await_fiber(fiber)
    return deadline.check(ex, context)
