"""Where tests run: a synchronous runtime and an asyncio one.

Both run an effect with a given context and an optional real-time
``timeout``. When the timeout passes, the test's fiber is interrupted and
its finalizers run to completion before ``TestTimeoutError`` is raised.
Time the host froze the whole process for, as a ``leave_out_host_freezes``
source reports it, is left out of the timeout, up to the timeout again.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Never, Protocol

from pyfect._core import Effect
from pyfect._fiber import Fiber, root_fiber
from pyfect.clock import Clock
from pyfect.context import Context
from pyfect.duration import Duration, zero
from pyfect.exit import Exit, Failure
from pyfect.run import await_fiber
from pyfect.scheduler import AsyncioScheduler, Cancel, Scheduler, StalledError, SyncScheduler
from pyfect.testing._clock import TestClock


class TestTimeoutError(TimeoutError):
    """A test ran past its timeout. It was interrupted and its finalizers
    ran before this was raised."""

    __test__ = False


@dataclass(frozen=True, slots=True)
class HostFreezes:
    """Real time the host froze the whole process for, which a test's timeout leaves out."""

    total: Duration
    """Every freeze seen so far. It only grows."""
    settling: Duration | None = None
    """A freeze may be ending now, not counted yet: ask again after this long."""


type HostFreezeSource = Callable[[], HostFreezes]


@dataclass(slots=True)
class _Hook:
    source: HostFreezeSource | None = None


_host_freezes = _Hook()


def leave_out_host_freezes(source: HostFreezeSource | None) -> None:
    """Leaves the host freezes ``source`` reports out of every test's timeout, up to the
    timeout again; ``None`` stops. A stall watchdog that tells a frozen process from a
    blocked one sets it: a frozen host is no time the test ran."""
    _host_freezes.source = source


class Runtime(Protocol):
    def run[A, E](
        self, eff: Effect[A, E, Never], context: Context, *, timeout: Duration | None
    ) -> Exit[A, E]: ...

    def close(self) -> None: ...


class _Expiry:
    """Interrupts ``fiber`` when called, and remembers that it did."""

    __slots__ = ("expired", "fiber")

    def __init__(self, fiber: Fiber[Any, Any]) -> None:
        self.fiber = fiber
        self.expired = False

    def __call__(self) -> None:
        self.expired = True
        self.fiber.interrupt_as_unsafe(None)


class _Deadline:
    """Interrupts a fiber once ``timeout`` of real time has passed, host freezes left out."""

    __slots__ = (
        "_cancel",
        "_elapsed",
        "_expiry",
        "_frozen",
        "_frozen_before",
        "_given",
        "_scheduler",
        "_source",
        "_started",
        "timeout",
    )

    def __init__(self, fiber: Fiber[Any, Any], timeout: Duration | None) -> None:
        self.timeout = timeout
        self._expiry = _Expiry(fiber)
        self._scheduler = fiber._scheduler
        self._cancel: Cancel | None = None
        self._source = _host_freezes.source
        self._frozen_before = zero if self._source is None else self._source().total
        self._frozen = zero
        """The host freezes left out of the timeout."""
        self._given = zero
        """Real time added to the timeout: the freezes, and waits for one to settle."""
        self._started = time.monotonic()
        self._elapsed = 0.0
        if timeout is None:
            return
        self._arm(timeout)

    def _arm(self, delay: Duration) -> None:
        # A daemon timer: a stalled test still fails fast with StalledError.
        self._cancel = self._scheduler.call_later(delay, self._due, daemon=True)

    def _due(self) -> None:
        """The timeout passed: add the host freezes since the start not added yet (and wait
        for one that may be ending), up to the timeout again; else interrupt."""
        if self._source is not None and self.timeout is not None:
            report = self._source()
            frozen = report.total - self._frozen_before
            self._frozen = min(frozen, self.timeout)
            if self._given < self._frozen:
                more, self._given = self._frozen - self._given, self._frozen
                self._arm(more)
                return
            if report.settling is not None and self._given < self.timeout:
                self._given += report.settling
                self._arm(report.settling)
                return
        self._elapsed = time.monotonic() - self._started
        self._expiry()

    @property
    def expired(self) -> bool:
        return self._expiry.expired

    def _seconds(self) -> float | None:
        return None if self.timeout is None else self.timeout.to_seconds()

    def _timed_out(self) -> str:
        if self._frozen <= zero:
            return f"test timed out after {self._seconds()}s"
        return (
            f"test timed out after {self._seconds()} s of running time ({self._elapsed:.1f} s "
            f"elapsed; host froze the process {self._frozen.to_seconds():.1f} s, not counted)"
        )

    def check[A, E](self, ex: Exit[A, E], context: Context) -> Exit[A, E]:

        if self._cancel is not None:
            self._cancel()
        if not self.expired:
            return ex
        if not isinstance(ex, Failure):
            # The interrupt came while the test could not be interrupted (a finalizer, an
            # uninterruptible region), which then finished it.
            raise TestTimeoutError(f"{self._timed_out()}; it finished, but after its timeout")
        error = TestTimeoutError(f"{self._timed_out()}; it was interrupted and its finalizers ran")
        if not ex.cause.has_interrupts_only:
            error.add_note("While interrupting it:\n" + ex.cause.pretty())
        _note_sleepers(error, context)
        raise error

    def stalled_after_timeout(self, stall: StalledError, context: Context) -> TestTimeoutError:
        """The real failure when interrupting at the deadline left a finalizer stuck: the
        timeout, which ``StalledError`` would otherwise hide."""
        error = TestTimeoutError(
            f"{self._timed_out()}; it was interrupted and a finalizer never finished ({stall})"
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
