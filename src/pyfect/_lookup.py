"""Running a system lookup without blocking a fiber, on the shared pool of
four lookup threads (``_blocking_pool.lookup_pool``), as Effect's
``NodeDns`` runs ``dns.lookup`` on libuv's pool. A lookup whose fiber is
interrupted before a thread took it leaves the queue; one already running
finishes on its thread and its answer is dropped."""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future

from pyfect._blocking_pool import lookup_pool
from pyfect._core import Effect
from pyfect._os_wait import Cancel, Resume, os_wait
from pyfect.effect import die


def on_lookup_thread[A, E](call: Callable[[], Effect[A, E]]) -> Effect[A, E]:
    """Run ``call`` on a lookup thread and continue with the effect it
    returns; a raise is a defect."""

    def register(resume: Resume[A, E]) -> Cancel:
        def done(future: Future[Effect[A, E]]) -> None:
            if future.cancelled():
                return
            error = future.exception()
            resume(future.result() if error is None else die(error))

        pool = lookup_pool()
        future = pool.submit(call)
        future.add_done_callback(done)
        return lambda: pool.withdraw(future)

    return os_wait(register, waits_for="work")
