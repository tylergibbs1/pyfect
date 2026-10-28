"""The asyncio loop the live sockets run on: one per process, on a daemon
thread of its own, started on first use. Fibers never run on it: they ask
it to act (``call_soon``, ``run``) and wait through ``os_wait``, which keeps
a synchronous run (and its stall detection) aware of the outside work."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Coroutine
from concurrent.futures import Future
from typing import Any

from pyfect._core import Effect
from pyfect.effect import fail, succeed
from pyfect.process._os import Resume, os_wait


class _Shared:
    lock = threading.Lock()
    loop: asyncio.AbstractEventLoop | None = None


def _quiet(loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
    """Connection errors are reported to the socket that saw them; the
    loop's own report of them (a failed TLS handshake, a reset during
    close) would only be noise."""
    if not isinstance(context.get("exception"), OSError):
        loop.default_exception_handler(context)


def get_loop() -> asyncio.AbstractEventLoop:
    with _Shared.lock:
        if _Shared.loop is None:
            loop = asyncio.new_event_loop()
            loop.set_exception_handler(_quiet)
            threading.Thread(target=loop.run_forever, name="pyfect-net", daemon=True).start()
            _Shared.loop = loop
        return _Shared.loop


def call_soon(f: Callable[[], object]) -> None:
    """Run ``f`` on the loop thread."""
    get_loop().call_soon_threadsafe(f)


def run[A](make: Callable[[], Coroutine[Any, Any, A]]) -> Effect[A, BaseException]:
    """Run the coroutine ``make()`` on the loop and wait for its result;
    interrupting cancels it."""

    def register(resume: Resume[A, BaseException]) -> Callable[[], None]:
        future: Future[A] = asyncio.run_coroutine_threadsafe(make(), get_loop())

        def done(finished: Future[A]) -> None:
            if finished.cancelled():
                resume(fail(asyncio.CancelledError()))
                return
            error = finished.exception()
            resume(succeed(finished.result()) if error is None else fail(error))

        future.add_done_callback(done)

        def cancel() -> None:
            future.cancel()

        return cancel

    return os_wait(register)
