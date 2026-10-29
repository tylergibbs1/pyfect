"""The worker side of Python workers (Effect's ``NodeWorkerRunner``).

``layer`` provides the ``WorkerRunnerPlatform`` for code running in a
``ThreadWorker`` or a ``ProcessWorker``: its runner tells the parent it is
ready, calls the handler for each message the parent sends (with port id
``0``), sends replies back, and ends its ``run`` when the parent closes
it (or, in a process, goes away). Outside a worker, ``start`` fails with a
``WorkerSpawnError``. A worker's main program is typically::

    fx.run_sync_exit(MainLayer.launch())

which ends once the parent closes the worker.
"""

from __future__ import annotations

from typing import Any, cast

from pyfect._core import Effect
from pyfect.cause import Cause
from pyfect.effect import fail, gen, provide_service, succeed, suspend
from pyfect.fiber_set import FiberSet
from pyfect.layer import Layer
from pyfect.layer import succeed as layer_succeed
from pyfect.logger import log_error
from pyfect.scope import CloseableScope, Scope, scoped_with
from pyfect.workers import _process, _thread
from pyfect.workers._port import Disconnected, ParentPort, Received, Unreadable
from pyfect.workers.worker import Transfers
from pyfect.workers.worker_error import WorkerError, WorkerReceiveError, WorkerSpawnError
from pyfect.workers.worker_runner import (
    Handler,
    WorkerRunner,
    WorkerRunnerPlatform,
    WorkerRunnerPlatformService,
)

_VOID: Effect[None] = succeed(None)


def _current_parent() -> ParentPort | None:
    return _thread.current_parent() or _process.current_parent()


_CLOSE = (1,)


def _payload(data: object) -> object:
    """The message of a ``(0, message)`` request."""
    return cast("tuple[int, object]", data)[1]


def _log_unhandled(cause: Cause[Any]) -> Effect[None]:
    if cause.has_interrupts_only:
        return _VOID
    return log_error("unhandled error in worker", cause)


def _runner(parent: ParentPort) -> WorkerRunner[Any, Any]:
    def send_unsafe(_port_id: int, message: object, _transfers: Transfers) -> None:
        parent.post((1, message))

    def run(handler: Handler) -> Effect[None, WorkerError, Any]:
        # The messages are handled on the run's own fiber, so a handler that
        # raises ends the run, as Node's uncaught exception ends the worker.
        def in_scope(scope: CloseableScope) -> Effect[None, WorkerError, Any]:
            @gen
            def running():
                fiber_set = yield from FiberSet[Any, Any].make().pipe(provide_service(Scope, scope))
                parent.post((0,))
                while True:
                    event = yield from parent.inbox.take()
                    match event:
                        case Received(data=data) if data == _CLOSE:
                            parent.close()
                            return
                        case Received(data=data):
                            result = handler(0, _payload(data))
                            if result is not None:
                                yield from fiber_set.run(result.catch_cause(_log_unhandled))
                        case Disconnected():
                            return
                        case Unreadable(cause=cause):
                            error = WorkerReceiveError(
                                message="received messageerror event", cause=cause
                            )
                            return (yield from fail(WorkerError(reason=error)))

            return running

        return scoped_with(in_scope)

    return WorkerRunner(run=run, send_unsafe=send_unsafe)


def _start() -> Effect[WorkerRunner[Any, Any], WorkerError]:
    def body() -> Effect[WorkerRunner[Any, Any], WorkerError]:
        parent = _current_parent()
        if parent is None:
            return fail(WorkerError(reason=WorkerSpawnError(message="not in a worker")))
        return succeed(_runner(parent))

    return suspend(body)


layer: Layer[WorkerRunnerPlatform] = layer_succeed(
    WorkerRunnerPlatform, WorkerRunnerPlatformService(_start)
)
"""The ``WorkerRunnerPlatform`` of the thread or process worker this code
runs in."""

__all__ = ["layer"]
