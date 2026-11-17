"""Workers on threads (the counterpart of Node's ``worker_threads``).

A ``ThreadWorker`` runs ``target`` on a new daemon thread; the code there
runs its own runtime (``run_blocking`` or ``run_async``) and finds its parent
through ``python_worker_runner.layer``. Each message is copied when it is
sent, by a pickle round trip, as a process worker's is (Effect's structured
clone at ``postMessage``): one that cannot be pickled fails the send, one
that cannot be unpickled arrives as unreadable. Values in the message's
transfer list are moved: the other side gets those objects themselves. The thread
exits when ``target`` returns (code 0) or raises (an error event, then
code 1). A thread cannot be killed: ``kill`` reports it as exited with code
1 and drops what it sends from then on.
"""

from __future__ import annotations

import io
import pickle
import threading
from collections.abc import Callable, Sequence
from typing import cast

from pyfect.workers._port import (
    Disconnected,
    ParentPort,
    Raised,
    Received,
    Unreadable,
    WorkerHandle,
    WorkerPort,
)

_local = threading.local()


class _Pickler(pickle.Pickler):
    def __init__(self, file: io.BytesIO, moved: dict[int, int]) -> None:
        super().__init__(file, protocol=pickle.HIGHEST_PROTOCOL)
        self._moved = moved

    def persistent_id(self, obj: object) -> int | None:
        return self._moved.get(id(obj))


class _Unpickler(pickle.Unpickler):
    def __init__(self, file: io.BytesIO, transfers: Sequence[object]) -> None:
        super().__init__(file)
        self._transfers = transfers

    def persistent_load(self, pid: object) -> object:
        return self._transfers[cast("int", pid)]


class _Copy:
    """A message pickled when sent, with the values it moves."""

    __slots__ = ("_payload", "_transfers")

    def __init__(self, message: object, transfers: Sequence[object]) -> None:
        transfers = tuple(transfers)
        buffer = io.BytesIO()
        _Pickler(buffer, {id(value): index for index, value in enumerate(transfers)}).dump(message)
        self._payload = buffer.getvalue()
        self._transfers = transfers

    def read(self) -> Received | Unreadable:
        try:
            return Received(_Unpickler(io.BytesIO(self._payload), self._transfers).load())
        except Exception as cause:  # reported as an unreadable message, as from a process
            return Unreadable(cause)


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

    def post(self, message: object, transfers: Sequence[object]) -> None:
        self._worker.deliver(_Copy(message, transfers))

    def close(self) -> None:
        self._closed = True

    def deliver(self, message: _Copy) -> None:
        if not self._closed:
            self.inbox.put(message.read())


class _ThreadWorkerPort(WorkerPort):
    __slots__ = ("_killed", "parent")

    def __init__(self) -> None:
        super().__init__()
        self._killed = False
        self.parent = _ThreadParent(self)

    def post(self, message: object, transfers: Sequence[object]) -> None:
        self.parent.deliver(_Copy(message, transfers))

    def deliver(self, message: _Copy) -> None:
        if not self._killed:
            self.events.put(message.read())

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
