"""Workers in child Python processes (the counterpart of Node's
``child_process.fork`` with its IPC channel).

A ``ProcessWorker`` starts ``python <args>`` with one end of a socket pair
as an extra descriptor, named by the ``PYFECT_WORKER_FD`` environment
variable, as Node names its channel with ``NODE_CHANNEL_FD``; the child's
standard streams are the parent's. Messages are pickled (``_frames``). A
reader thread on each side puts what arrives into a ``Mailbox``; once the
child's end closes, the parent's reader waits for the process and reports
its exit code (negative for a signal, as ``subprocess``). The child treats
its parent closing the socket as being closed, so an orphaned worker ends.
"""

from __future__ import annotations

import atexit
import os
import socket
import subprocess
import sys
import threading
from collections.abc import Mapping, Sequence

from pyfect.workers._frames import FrameWriter, encode, read_frames
from pyfect.workers._port import (
    Disconnected,
    ParentPort,
    Received,
    Unreadable,
    WorkerHandle,
    WorkerPort,
)

CHANNEL_ENV = "PYFECT_WORKER_FD"

_FLUSH_TIMEOUT = 5.0
"""How long a worker process waits at exit for its last replies to be
written."""


class _ProcessWorkerPort(WorkerPort):
    __slots__ = ("_popen", "_sock", "_writer")

    def __init__(self, popen: subprocess.Popen[bytes], sock: socket.socket) -> None:
        super().__init__()
        self._popen = popen
        self._sock = sock
        self._writer = FrameWriter(sock, "pyfect-worker-writer")
        threading.Thread(target=self._read, name="pyfect-worker-reader", daemon=True).start()

    def post(self, message: object) -> None:
        self._writer.write(encode(message))

    def kill(self) -> None:
        if self.exited.get() is None:
            self._popen.kill()

    def _read(self) -> None:
        def received(message: object) -> None:
            self.events.put(Received(message))

        def unreadable(cause: BaseException) -> None:
            self.events.put(Unreadable(cause))

        read_frames(self._sock, received, unreadable)
        code = self._popen.wait()
        self._writer.close()
        self._sock.close()
        self.finish(code)


class ProcessWorker(WorkerHandle):
    """A worker running ``python <args>`` (``executable`` defaults to this
    interpreter), in ``cwd`` with ``env`` (default: this process's)."""

    __slots__ = ("args", "cwd", "env", "executable")

    def __init__(
        self,
        args: Sequence[str],
        *,
        executable: str | None = None,
        cwd: str | os.PathLike[str] | None = None,
        env: Mapping[str, str] | None = None,
    ) -> None:
        self.args = tuple(args)
        self.executable = executable
        self.cwd = cwd
        self.env = env

    def start(self) -> WorkerPort:
        parent, child = socket.socketpair()
        try:
            env = dict(os.environ if self.env is None else self.env)
            env[CHANNEL_ENV] = str(child.fileno())
            popen = subprocess.Popen(
                [self.executable or sys.executable, *self.args],
                pass_fds=(child.fileno(),),
                env=env,
                cwd=self.cwd,
            )
        except BaseException:
            parent.close()
            raise
        finally:
            child.close()
        return _ProcessWorkerPort(popen, parent)


class _ProcessParent(ParentPort):
    __slots__ = ("_closed", "_sock", "_writer")

    def __init__(self, sock: socket.socket) -> None:
        super().__init__()
        self._sock = sock
        self._closed = False
        self._writer = FrameWriter(sock, "pyfect-worker-writer")
        threading.Thread(target=self._read, name="pyfect-worker-reader", daemon=True).start()
        atexit.register(self._writer.close, _FLUSH_TIMEOUT)

    def post(self, message: object) -> None:
        self._writer.write(encode(message))

    def close(self) -> None:
        self._closed = True

    def _read(self) -> None:
        def received(message: object) -> None:
            if not self._closed:
                self.inbox.put(Received(message))

        def unreadable(cause: BaseException) -> None:
            self.inbox.put(Unreadable(cause))

        read_frames(self._sock, received, unreadable)
        self.inbox.put(Disconnected())


_lock = threading.Lock()
_parent: list[_ProcessParent] = []


def current_parent() -> ParentPort | None:
    """The parent of the worker process this code runs in, if any. The
    channel's variable is taken out of the environment, so processes this
    one starts do not see it."""
    with _lock:
        if _parent:
            return _parent[0]
        fd = os.environ.pop(CHANNEL_ENV, None)
        if fd is None:
            return None
        port = _ProcessParent(socket.socket(fileno=int(fd)))
        _parent.append(port)
        return port
