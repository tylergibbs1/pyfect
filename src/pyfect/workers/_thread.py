"""Workers on threads (the counterpart of Node's ``worker_threads``).

A ``ThreadWorker`` runs ``target`` on a new daemon thread; the code there
runs its own runtime (``run_sync`` or ``run_async``) and finds its parent
through ``python_worker_runner.layer``. Messages are handed over as they
are, not copied: send values neither side changes afterwards. The thread
exits when ``target`` returns (code 0) or raises (an error event, then
code 1). A thread cannot be killed: ``kill`` reports it as exited with code
1 and drops what it sends from then on.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from pyfect.workers._port import (
    Disconnected,
    ParentPort,
    Raised,
    Received,
    WorkerHandle,
    WorkerPort,
)

_local = threading.local()


def current_parent() -> ParentPort | None:
    """The parent of the thread worker this code runs in, if any."""
    port: ParentPort | None = getattr(_local, "port", None)
    return port


class _ThreadParent(ParentPort):
    __slots__ = ("_closed", "_worker")

    def __init__(self, worker: _ThreadWorkerPort) -> None:
        super().__init__()
        self._worker = worker
        self._closed = False

    def post(self, message: object) -> None:
        self._worker.deliver(message)

    def close(self) -> None:
        self._closed = True

    def deliver(self, message: object) -> None:
        if not self._closed:
            self.inbox.put(Received(message))


class _ThreadWorkerPort(WorkerPort):
    __slots__ = ("_killed", "parent")

    def __init__(self) -> None:
        super().__init__()
        self._killed = False
        self.parent = _ThreadParent(self)

    def post(self, message: object) -> None:
        self.parent.deliver(message)

    def deliver(self, message: object) -> None:
        if not self._killed:
            self.events.put(Received(message))

    def kill(self) -> None:
        self._killed = True
        self.parent.inbox.put(Disconnected())
        self.finish(1)


class ThreadWorker(WorkerHandle):
    """A worker running ``target()`` on a thread of its own."""

    __slots__ = ("name", "target")

    def __init__(self, target: Callable[[], object], *, name: str | None = None) -> None:
        self.target = target
        self.name = name

    def start(self) -> WorkerPort:
        port = _ThreadWorkerPort()
        name = self.name or "pyfect-worker"
        threading.Thread(target=self._main, args=(port,), name=name, daemon=True).start()
        return port

    def _main(self, port: _ThreadWorkerPort) -> None:
        _local.port = port.parent
        code = 0
        try:
            self.target()
        except BaseException as cause:  # reported to the parent, as Node's error event
            port.events.put(Raised(cause))
            code = 1
        finally:
            _local.port = None
            port.finish(code)
