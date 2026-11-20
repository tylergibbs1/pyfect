"""An asyncio loop on a daemon thread of its own, owning the close of
every async generator it runs.

asyncio closes a generator dropped mid-iteration (httpx's response
bodies, when a fiber lets go of a response) with a task it schedules from
whichever thread dropped it, and keeps no reference to that task; a loop
stopped and closed right after loses that close half done ("Task was
destroyed but it is pending", "coroutine method 'aclose' ... was never
awaited"). A ``LoopThread`` starts each such close with
``pyfect._background.start``, and ``stop`` closes the loop only once its
tasks and generators have settled: the background tasks (closes and
releases, its own and its users') run to their end, those started while it
stops included; any other coroutine still running is cancelled.
"""

from __future__ import annotations

import asyncio
import sys
import threading
import weakref
from collections.abc import AsyncGenerator, Callable, Coroutine
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any

from pyfect import _background as background

type ExceptionHandler = Callable[[asyncio.AbstractEventLoop, dict[str, Any]], object]
type _AnyGenerator = AsyncGenerator[Any, Any]


class LoopThread:
    """An asyncio loop running on a daemon thread named ``name`` until
    ``stop``. ``submit`` runs a coroutine on it, kept until it ends (as is
    every task of the loop) even if its future is dropped; at ``stop``, a
    coroutine still running is cancelled, and every async generator the loop ran is
    closed before the loop closes (``stopped`` is then done). A generator
    dropped after that is discarded without its close."""

    __slots__ = (
        "_closed",
        "_closing",
        "_generators",
        "_lock",
        "_stop",
        "loop",
        "stopped",
    )

    def __init__(self, name: str, *, exception_handler: ExceptionHandler | None = None) -> None:
        self.loop = asyncio.new_event_loop()
        # asyncio holds tasks weakly: a coroutine whose future was dropped
        # would be collected mid-flight, neither run to its end nor cancelled.
        background.keep_tasks(self.loop)
        # Named for the loop: its workers (name resolution, say) outlive any one caller.
        self.loop.set_default_executor(ThreadPoolExecutor(thread_name_prefix=f"{name}-executor"))
        if exception_handler is not None:
            self.loop.set_exception_handler(exception_handler)
        self.stopped: Future[None] = Future()
        """Done once the loop has closed."""
        self._lock = threading.RLock()
        """Reentrant: a generator may be dropped (and finalized) on the loop
        thread while it holds the lock."""
        self._closed = False
        self._generators: weakref.WeakSet[_AnyGenerator] = weakref.WeakSet()
        self._closing: set[_AnyGenerator] = set()
        """Generators dropped mid-iteration, kept until their close ends."""
        self._stop = self.loop.create_future()
        threading.Thread(target=self._run, name=name, daemon=True).start()

    def submit[A](self, make: Callable[[], Coroutine[Any, Any, A]]) -> Future[A]:
        """Run ``make()`` on the loop."""
        return asyncio.run_coroutine_threadsafe(make(), self.loop)

    def stop(self) -> None:
        """Cancel what still runs, close the generators, then close the
        loop (from any thread; stopping again does nothing)."""

        def stop() -> None:
            if not self._stop.done():
                self._stop.set_result(None)

        try:
            self.loop.call_soon_threadsafe(stop)
        except RuntimeError:
            if not self.loop.is_closed():
                raise

    def _run(self) -> None:
        # Running: a waiter giving up on ``stopped`` cannot cancel it.
        self.stopped.set_running_or_notify_cancel()
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._main())
        finally:
            self.loop.close()
            self.stopped.set_result(None)

    async def _main(self) -> None:
        # Set inside the run: ``run_forever`` installs the loop's own hooks
        # when it starts and restores the thread's previous ones at its end.
        sys.set_asyncgen_hooks(firstiter=self._generators.add, finalizer=self._finalize)
        await self._stop
        await self._settle()
        await self.loop.shutdown_default_executor()
        # Closes started while the executor shut down (that await let callbacks
        # run): the loop must not close under them.
        await background.settle()

    def _finalize(self, generator: _AnyGenerator) -> None:
        """A generator the loop ran was dropped before it ended (on any
        thread): close it on the loop, unless the loop is closing."""
        with self._lock:
            if self._closed:
                return
            self._generators.discard(generator)
            self._closing.add(generator)
        self.loop.call_soon_threadsafe(self._start_close, generator)

    def _start_close(self, generator: _AnyGenerator) -> None:
        background.start(self._close(generator), self.loop)

    async def _close(self, generator: _AnyGenerator) -> None:
        try:
            await generator.aclose()
        except Exception as error:
            self.loop.call_exception_handler(
                {
                    "message": "an error occurred during closing of asynchronous generator",
                    "exception": error,
                    "asyncgen": generator,
                }
            )
        finally:
            with self._lock:
                self._closing.discard(generator)

    async def _settle(self) -> None:
        """Until nothing is left: cancel the coroutines still running but
        the background tasks (closes run to their end), then close the
        generators still open; each round may drop more generators or start
        more closes."""
        current = asyncio.current_task()
        while True:
            # Let closes scheduled from other threads start.
            await asyncio.sleep(0)
            generators: list[_AnyGenerator] = []
            with self._lock:
                running = [task for task in asyncio.all_tasks() if task is not current]
                if not running and not self._closing:
                    generators = list(self._generators)
                    self._generators.clear()
                    if not generators:
                        self._closed = True
                        return
            kept = set(background.running(self.loop))
            for task in running:
                if task not in kept:
                    task.cancel()
            closes = [self._close(generator) for generator in generators]
            await asyncio.gather(*running, *closes, return_exceptions=True)


__all__ = ["ExceptionHandler", "LoopThread"]
