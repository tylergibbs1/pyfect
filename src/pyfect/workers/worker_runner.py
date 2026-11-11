"""The worker side of workers (Effect's ``WorkerRunner``).

A ``WorkerRunner[O, I]`` runs inside a worker: ``run(handler)`` tells the
parent the worker is ready, then calls ``handler(port_id, message)`` for
each ``I`` the parent sends, running the effect it returns (if any) on a
fiber of its own, until the parent closes the worker. ``send`` replies with
an ``O``. ``WorkerRunnerPlatform`` starts the runner of the current
platform; ``python_worker_runner.layer`` is the one for Python threads and
child processes (Effect's ``NodeWorkerRunner``).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Literal, Never, Self, cast

from pyfect._core import Effect
from pyfect._service_copy import replaced
from pyfect.context import Tag
from pyfect.effect import sync
from pyfect.queue import Dequeue
from pyfect.workers.worker import Transfers
from pyfect.workers.worker_error import WorkerError

type PlatformMessage[I] = tuple[Literal[0], I] | tuple[Literal[1]]
"""What a parent sends its worker: ``(0, message)``, or ``(1,)`` to close
it."""

type Handler = Callable[[int, Any], Effect[Any, Any, Any] | None]


class WorkerRunner[O = Any, I = Any]:
    """The worker's end: ``run`` a handler for the parent's messages,
    ``send`` it replies. ``disconnects`` gives the ports that went away, on
    platforms with several (``None`` otherwise)."""

    __slots__ = ("_run", "_send_unsafe", "disconnects")

    def __init__(
        self,
        *,
        run: Callable[[Handler], Effect[None, WorkerError, Any]],
        send_unsafe: Callable[[int, Any, Transfers], None],
        disconnects: Dequeue[int, Never] | None = None,
    ) -> None:
        self._run = run
        self._send_unsafe = send_unsafe
        self.disconnects = disconnects

    def run[A, E = Never, R = Never](
        self, handler: Callable[[int, I], Effect[A, E, R] | None]
    ) -> Effect[None, WorkerError, R]:
        """Handle the parent's messages until it closes the worker. A
        handler's failure is logged, not propagated."""
        return cast("Effect[None, WorkerError, R]", self._run(handler))

    def send(self, port_id: int, message: O, transfers: Transfers = ()) -> Effect[None]:
        return sync(lambda: self._send_unsafe(port_id, message, transfers))

    def send_unsafe(self, port_id: int, message: O, transfers: Transfers = ()) -> None:
        self._send_unsafe(port_id, message, transfers)


class WorkerRunnerPlatformService:
    """Starts the runner of the worker this code runs in (Effect's
    ``WorkerRunner.WorkerRunnerPlatform``)."""

    __slots__ = ("_start",)

    def __replace__(self, **changes: Any) -> Self:
        """A copy with ``changes`` to the constructor's arguments (``copy.replace``)."""
        return replaced(self, changes)

    def __init__(self, start: Callable[[], Effect[WorkerRunner[Any, Any], WorkerError]]) -> None:
        self._start = start

    def start(self) -> Effect[WorkerRunner[Any, Any], WorkerError]:
        """The runner of the worker this code runs in; fails with a
        ``WorkerError`` (``WorkerSpawnError``) outside a worker."""
        return self._start()


class WorkerRunnerPlatform(
    Tag[WorkerRunnerPlatformService], key="effect/workers/WorkerRunner/WorkerRunnerPlatform"
):
    """Starts the runner of the current platform's worker."""


__all__ = [
    "Handler",
    "PlatformMessage",
    "WorkerError",
    "WorkerRunner",
    "WorkerRunnerPlatform",
    "WorkerRunnerPlatformService",
]
