"""The parent side of Python workers (Effect's ``NodeWorker``).

``layer(spawn)`` provides the ``WorkerPlatform`` and a ``Spawner`` giving,
for each worker id, a ``ThreadWorker(target)`` (a function run on a thread
of its own, which runs its own runtime) or a ``ProcessWorker(args)`` (a
child Python process). The code in the worker serves its parent with
``python_worker_runner.layer``. Closing a run's scope asks the worker to
close and waits up to five seconds for it to exit before killing it::

    platform = python_worker.layer(lambda _: ProcessWorker(["-m", "app.worker"]))

A worker that exits, raises or sends a message that cannot be read fails
its run with a ``WorkerError`` (``WorkerReceiveError``); one that cannot
start fails it with a ``WorkerSpawnError``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import cast

from pyfect import exit as Exit
from pyfect._core import Effect
from pyfect.effect import gen, sync, try_
from pyfect.layer import Layer, merge
from pyfect.layer import succeed as layer_succeed
from pyfect.scope import fork_in
from pyfect.workers._port import Exited, Raised, Received, Unreadable, WorkerHandle, WorkerPort
from pyfect.workers._process import ProcessWorker
from pyfect.workers._thread import ThreadWorker
from pyfect.workers.worker import (
    ListenOptions,
    PlatformMessage,
    SetupOptions,
    Spawner,
    Transfers,
    WorkerPlatform,
    layer_spawner,
    make_platform,
)
from pyfect.workers.worker_error import WorkerError, WorkerReceiveError, WorkerSpawnError

CLOSE_TIMEOUT = "5 seconds"
"""Seconds a closing worker gets to exit before it is killed."""


class _Port:
    """A started worker as the platform's port."""

    __slots__ = ("worker",)

    def __init__(self, worker: WorkerPort) -> None:
        self.worker = worker

    def post_message(self, message: object, transfers: Transfers) -> None:
        self.worker.post(message)


def _receive_error(message: str, cause: BaseException | None = None) -> WorkerError:
    return WorkerError(reason=WorkerReceiveError(message=message, cause=cause))


def _setup(options: SetupOptions[WorkerHandle]) -> Effect[_Port, WorkerError]:
    handle = options.worker

    def spawn_error(cause: Exception) -> WorkerError:
        return WorkerError(reason=WorkerSpawnError(message="Failed to spawn worker", cause=cause))

    @gen
    def setup():
        worker = yield from try_(handle.start, spawn_error)

        def close(_: object) -> Effect[None]:
            def ask() -> None:
                worker.post((1,))

            return (
                try_(ask)
                .flat_map(lambda _: worker.exited.wait())
                .timeout(CLOSE_TIMEOUT)
                .as_void()
                .catch_cause(lambda _: sync(worker.kill))
            )

        yield from options.scope.add_finalizer(close)
        return _Port(worker)

    return setup


def _listen(options: ListenOptions[_Port]) -> Effect[None]:
    events = options.port.worker.events

    def failed(error: WorkerError) -> None:
        options.deferred.done_unsafe(Exit.fail(error))

    @gen
    def pump():
        while True:
            event = yield from events.take()
            match event:
                case Received(data=data):
                    options.emit(cast("PlatformMessage", data))
                case Unreadable(cause=cause):
                    failed(_receive_error("A messageerror event was emitted", cause))
                case Raised(cause=cause):
                    failed(_receive_error("An error event was emitted", cause))
                case Exited(code=code):
                    failed(_receive_error(f"The worker has exited with code: {code}"))
                    return

    return fork_in(pump, options.scope).as_void()


layer_platform: Layer[WorkerPlatform] = layer_succeed(
    WorkerPlatform, make_platform(setup=_setup, listen=_listen)
)
"""The ``WorkerPlatform`` for ``ThreadWorker`` and ``ProcessWorker``."""


def layer(spawn: Callable[[int], WorkerHandle]) -> Layer[WorkerPlatform | Spawner]:
    """``layer_platform`` with ``spawn`` as the ``Spawner``."""
    return merge(layer_spawner(spawn), layer_platform)


__all__ = [
    "CLOSE_TIMEOUT",
    "ProcessWorker",
    "ThreadWorker",
    "WorkerHandle",
    "layer",
    "layer_platform",
]
