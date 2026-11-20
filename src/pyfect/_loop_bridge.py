"""Fibers running coroutines on an asyncio loop of pyfect's.

Every pyfect-owned loop (the sockets', SQL's, Redis's, the httpx client's, the
ASGI listener's) is a ``LoopBridge``. A driver hands ``run`` its coroutine, how
its errors become failures (``catch``), what an interrupt does to it
(``on_interrupt``) and how to release a value nobody will take (``release``).
The bridge owns the rest:

- The fiber never blocks: it waits on a ``Latch`` (an ``os_wait``) the loop
  sets, so a synchronous run knows the wait is outside work.
- An interrupt is posted to the loop, after the coroutine's start, so the loop
  alone decides, in order, whether the coroutine ran, is running or has ended.
  A value the coroutine makes for a fiber that has given up goes to
  ``release`` there, exactly once: as it arrives, or as the fiber gives up
  after the loop handed it over but before the fiber took it.
- An owned bridge (``OwnedLoopBridge``) fails a call made after ``close`` with
  ``Released`` (through ``catch``) and closes its loop only once its tasks
  have settled (``pyfect._loop_thread``). A shared one runs for the life of
  the process.

``tests/test_loop_bridge_guard.py`` keeps drivers from waiting on a loop any
other way.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
import contextlib
import threading
from collections.abc import Callable, Coroutine
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any, Never

from pyfect import _background as background
from pyfect._core import Effect, _Succeed, _Suspend
from pyfect._effect_resources import _call_user
from pyfect._loop_thread import ExceptionHandler, LoopThread
from pyfect._os_wait import Resume, WaitsFor, os_wait
from pyfect._released import Lifetime, Released
from pyfect.effect import fail, succeed, sync
from pyfect.process._os import Latch

type Make[A] = Callable[[], Coroutine[Any, Any, A]]
type Release[A] = Callable[[A], Coroutine[Any, Any, object]]
type Catch[E] = Callable[[BaseException], Effect[Never, E]]
type Stop = Callable[[asyncio.Task[Any]], Coroutine[Any, Any, None]]
"""Ends a running task early; it runs on the loop and returns once the task
has ended."""
type OnAbort = Callable[[Callable[[], None]], Callable[[], None]]
"""Calls its argument when something outside the fiber aborts the call (now,
if it has); returns a function that stops listening."""


async def cancel_task(task: asyncio.Task[Any]) -> None:
    task.cancel()
    await asyncio.wait([task])


@dataclass(frozen=True, slots=True)
class OnInterrupt:
    """What interrupting the waiting fiber does to its coroutine: ``stop`` runs
    on the loop (a coroutine that has not started yet is cancelled and never
    runs), and with ``wait`` the fiber goes on only once the coroutine has
    ended and what it made has been released."""

    stop: Stop
    wait: bool


CANCEL = OnInterrupt(cancel_task, wait=False)
"""Cancel the coroutine; the fiber goes on at once."""
CANCEL_AND_WAIT = OnInterrupt(cancel_task, wait=True)
"""Cancel the coroutine and wait until it has ended."""


def stop_with(stop: Stop) -> OnInterrupt:
    """Run ``stop`` on the task and wait until it has ended."""
    return OnInterrupt(stop, wait=True)


type _Outcome[A] = _Succeed[A] | BaseException


def _outcome_of[A](task: asyncio.Task[A]) -> _Outcome[A]:
    if task.cancelled():
        return asyncio.CancelledError()
    error = task.exception()
    return _Succeed(task.result()) if error is None else error


class _Call[A]:
    """One coroutine run for one fiber. Every method but ``abandon_later``
    and ``abort_later`` runs on the loop, so they never race each other."""

    __slots__ = (
        "_abandoned",
        "_began",
        "_handed",
        "_loop",
        "_make",
        "_on_interrupt",
        "_release",
        "_stopping",
        "_task",
        "outcome",
        "settled",
    )

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        make: Make[A],
        release: Release[A] | None,
        on_interrupt: OnInterrupt,
        waits_for: WaitsFor,
    ) -> None:
        self._loop = loop
        self._make = make
        self._release = release
        self._on_interrupt = on_interrupt
        self._task: asyncio.Task[A] | None = None
        self._abandoned = False
        self._began = False
        self._stopping = False
        self._handed: _Outcome[A] | None = None
        self.outcome: Latch[_Outcome[A]] = Latch(waits_for=waits_for)
        """Set once with what the coroutine gave, for the fiber."""
        self.settled: Latch[None] = Latch(waits_for="work")
        """Set once a fiber that gave up has nothing left running on the loop."""

    # --- loop side -------------------------------------------------------

    def begin(self) -> None:
        self._task = self._loop.create_task(self._run())
        self._task.add_done_callback(self._ended)

    def _started(self) -> asyncio.Task[A]:
        # Calls reach the loop in order, so ``begin`` has run by now.
        task = self._task
        assert task is not None
        return task

    async def _run(self) -> A:
        self._began = True
        return await self._make()

    def _ended(self, task: asyncio.Task[A]) -> None:
        outcome = _outcome_of(task)
        if not self._abandoned:
            self._handed = outcome
            self.outcome.set(outcome)
        elif not self._stopping:
            self._settle(outcome)

    def _abandon(self) -> None:
        self._abandoned = True
        handed = self._handed
        if handed is not None:
            # Handed over, but the fiber gave up before it took it.
            self._settle(handed)
            return
        task = self._started()
        if not self._began:
            # Cancelled before its first step, it never runs ``make``.
            task.cancel()
        elif not task.done():
            self._stopping = True
            background.start(self._stop_then_settle(task), self._loop)
        # Otherwise ``_ended`` settles it.

    async def _stop_then_settle(self, task: asyncio.Task[A]) -> None:
        try:
            with contextlib.suppress(Exception):
                await self._on_interrupt.stop(task)
        finally:
            await asyncio.wait([task])
            self._settle(_outcome_of(task))

    def _settle(self, outcome: _Outcome[A]) -> None:
        if isinstance(outcome, _Succeed) and self._release is not None:
            background.start(self._release_then_settle(self._release, outcome.value), self._loop)
        else:
            self.settled.set(None)

    async def _release_then_settle(self, release: Release[A], value: A) -> None:
        try:
            with contextlib.suppress(Exception):
                await release(value)
        finally:
            self.settled.set(None)

    def _abort(self) -> None:
        self._started().cancel()

    # --- fiber side ------------------------------------------------------

    def abandon_later(self, post: Callable[[Callable[[], object]], bool]) -> None:
        """The fiber gave up: let the loop stop the coroutine and release
        what it made. A loop already closed has settled everything."""
        if not post(self._abandon):
            self.settled.set(None)

    def abort_later(self, post: Callable[[Callable[[], object]], bool]) -> None:
        post(self._abort)


def _outcome[A, E](outcome: _Outcome[A], catch: Catch[E]) -> Effect[A, E]:
    if isinstance(outcome, _Succeed):
        return outcome
    return _call_user(catch, outcome)


class LoopBridge:
    """An asyncio loop on a daemon thread named ``name``, started on first use
    and running for the life of the process (or one already running, ``of``)."""

    __slots__ = ("_exception_handler", "_given", "_lock", "_name", "_thread")

    def __init__(self, name: str, *, exception_handler: ExceptionHandler | None = None) -> None:
        self._name = name
        self._exception_handler = exception_handler
        self._lock = threading.Lock()
        self._thread: LoopThread | None = None
        self._given: asyncio.AbstractEventLoop | None = None

    @classmethod
    def of(cls, loop: asyncio.AbstractEventLoop) -> LoopBridge:
        """A bridge to ``loop``, which someone else runs and stops."""
        bridge = cls("")
        bridge._given = loop
        return bridge

    def _loop_thread(self) -> LoopThread:
        with self._lock:
            if self._thread is None:
                self._thread = LoopThread(self._name, exception_handler=self._exception_handler)
            return self._thread

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        """The loop, started now if it has not been."""
        return self._given if self._given is not None else self._loop_thread().loop

    @property
    def started(self) -> asyncio.AbstractEventLoop | None:
        """The loop, if it has started."""
        if self._given is not None:
            return self._given
        with self._lock:
            return None if self._thread is None else self._thread.loop

    def _post(self, f: Callable[[], object]) -> bool:
        """Run ``f`` on the loop; ``False`` if the loop has closed."""
        loop = self.loop
        try:
            loop.call_soon_threadsafe(f)
        except RuntimeError:
            if not loop.is_closed():
                raise
            return False
        return True

    def _released(self) -> Released | None:
        """Why a call can't start (``OwnedLoopBridge``: the bridge is closed)."""
        return None

    def call_soon(self, f: Callable[[], object]) -> None:
        """Run ``f`` on the loop; once it has closed, nothing is left to do."""
        self._post(f)

    def start(self, make: Make[object]) -> None:
        """Run ``make()`` on the loop without waiting for it, to its end even
        while the loop stops."""
        loop = self.loop
        self._post(lambda: background.start(make(), loop))

    def spawn[A](self, make: Make[A]) -> Future[A]:
        """Run ``make()`` on the loop; its future, which ``wait`` waits for.
        Cancelling the future cancels it."""
        released = self._released()
        if released is None:
            try:
                return asyncio.run_coroutine_threadsafe(make(), self.loop)
            except RuntimeError:
                released = self._released()
                if released is None:
                    raise
        failed: Future[A] = Future()
        failed.set_exception(released)
        return failed

    def run[A, E](
        self,
        make: Make[A],
        catch: Catch[E],
        *,
        waits_for: WaitsFor,
        release: Release[A] | None = None,
        on_interrupt: OnInterrupt = CANCEL,
        aborted_by: OnAbort | None = None,
    ) -> Effect[A, E]:
        """Run ``make()`` on the loop and wait for its value; whatever it
        raises fails with ``catch`` of it (a raise in ``catch`` is a defect).
        Interrupting does what ``on_interrupt`` says, and a value ``make()``
        gives all the same goes to ``release`` on the loop. ``aborted_by``
        cancels it while the fiber still waits (failing with ``catch`` of a
        ``CancelledError``). ``waits_for`` says whether ``make()`` is work or
        waits for an event that may never come (``pyfect._os_wait``)."""

        def start() -> Effect[A, E]:
            released = self._released()
            if released is not None:
                return _call_user(catch, released)
            call = _Call(self.loop, make, release, on_interrupt, waits_for)
            if not self._post(call.begin):
                return _call_user(catch, self._released() or RuntimeError("the loop is closed"))
            taken = call.outcome.wait()
            if aborted_by is not None:
                stop_listening = aborted_by(lambda: call.abort_later(self._post))
                taken = taken.ensuring(sync(stop_listening))
            given_up = sync(lambda: call.abandon_later(self._post))
            if on_interrupt.wait:
                given_up = given_up.and_then(call.settled.wait())
            return taken.on_interrupt(given_up).flat_map(lambda outcome: _outcome(outcome, catch))

        return _Suspend(start)


class OwnedLoopBridge(LoopBridge):
    """A loop thread owned by one resource (``owner``, as in "the Redis client
    is closed"), closed with it."""

    __slots__ = ("_lifetime",)

    def __init__(
        self, name: str, owner: str, *, exception_handler: ExceptionHandler | None = None
    ) -> None:
        super().__init__(name, exception_handler=exception_handler)
        self._lifetime = Lifetime(owner)

    def _released(self) -> Released | None:
        return self._lifetime.error() if self._lifetime.closed else None

    def close(self, shutdown: Make[None] | None = None) -> Effect[None]:
        """Run ``shutdown()`` on the loop, refuse later calls, then stop the loop
        and wait until it has closed (its tasks settled first)."""

        def close() -> Effect[None]:
            if self._lifetime.closed:
                return succeed(None)
            shut = None if shutdown is None else self.spawn(shutdown)
            self._lifetime.close()
            with self._lock:
                thread = self._thread
            stopping = sync(lambda: None if thread is None else thread.stop())
            stopped = succeed(None) if thread is None else wait(thread.stopped, waits_for="work")
            closing = succeed(None) if shut is None else wait(shut, waits_for="work").ignore()
            return closing.and_then(stopping).and_then(stopped.ignore())

        return _Suspend(close)


def wait[A](future: Future[A], *, waits_for: WaitsFor) -> Effect[A, BaseException]:
    """``future``'s outcome (it is done on any thread) without blocking;
    interrupting leaves it running."""

    def register(resume: Resume[A, BaseException]) -> None:
        def done(finished: Future[A]) -> None:
            if finished.cancelled():
                resume(fail(asyncio.CancelledError()))
                return
            error = finished.exception()
            resume(succeed(finished.result()) if error is None else fail(error))

        future.add_done_callback(done)

    return os_wait(register, waits_for=waits_for)


__all__ = [
    "CANCEL",
    "CANCEL_AND_WAIT",
    "Catch",
    "LoopBridge",
    "Make",
    "OnAbort",
    "OnInterrupt",
    "OwnedLoopBridge",
    "Release",
    "Stop",
    "cancel_task",
    "stop_with",
    "wait",
]
