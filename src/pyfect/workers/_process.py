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
import errno
import os
import socket
import subprocess
import sys
import threading
from collections.abc import Mapping, Sequence

from pyfect import _batch_files
from pyfect._owned_fd import OwnedFd
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
PARENT_ENV = "PYFECT_WORKER_PARENT"
"""The pid of the process that passed the channel: a process another one
started with the variables inherited reads no pickles from its descriptor."""

_FLUSH_TIMEOUT = 5.0
"""How long a worker process waits at exit for its last replies to be
written."""


class _ProcessWorkerPort(WorkerPort):
    __slots__ = ("_channel", "_popen", "_writer")

    def __init__(self, popen: subprocess.Popen[bytes], sock: socket.socket) -> None:
        super().__init__()
        self._popen = popen
        self._channel = OwnedFd(sock, socket.socket.close)
        self._writer = FrameWriter(self._channel, "pyfect-worker-writer")
        threading.Thread(target=self._read, name="pyfect-worker-reader", daemon=True).start()

    def post(self, message: object, transfers: Sequence[object]) -> None:
        # Nothing moves to another process: transferred values are pickled too.
        self._writer.write(encode(message))

    def kill(self) -> None:
        if self.exited.get() is None:
            self._popen.kill()

    def _read(self) -> None:
        def received(message: object) -> None:
            self.events.put(Received(message))

        def unreadable(cause: BaseException) -> None:
            self.events.put(Unreadable(cause))

        self._channel.use(lambda sock: read_frames(sock, received, unreadable))
        code = self._popen.wait()
        self._writer.close()
        self._channel.close_when_unused()
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
        program = self.executable or sys.executable
        if _batch_files.refuses_batch_file(
            program, shell=False, platform=_batch_files.current_platform()
        ):
            raise OSError(
                errno.EINVAL, "spawn EINVAL: a worker cannot run a .bat or .cmd file", program
            )
        parent, child = socket.socketpair()
        try:
            env = dict(os.environ if self.env is None else self.env)
            env[CHANNEL_ENV] = str(child.fileno())
            env[PARENT_ENV] = str(os.getpid())
            popen = subprocess.Popen(
                [program, *self.args],
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
    __slots__ = ("_channel", "_closed", "_writer")

    def __init__(self, sock: socket.socket) -> None:
        super().__init__()
        self._channel = OwnedFd(sock, socket.socket.close)
        self._closed = False
        self._writer = FrameWriter(self._channel, "pyfect-worker-writer")
        threading.Thread(target=self._read, name="pyfect-worker-reader", daemon=True).start()
        atexit.register(self._writer.close, _FLUSH_TIMEOUT)

    def post(self, message: object, transfers: Sequence[object]) -> None:
        # Nothing moves to another process: transferred values are pickled too.
        self._writer.write(encode(message))

    def close(self) -> None:
        self._closed = True

    def _read(self) -> None:
        def received(message: object) -> None:
            if not self._closed:
                self.inbox.put(Received(message))

        def unreadable(cause: BaseException) -> None:
            self.inbox.put(Unreadable(cause))

        self._channel.use(lambda sock: read_frames(sock, received, unreadable))
        self.inbox.put(Disconnected())


_lock = threading.Lock()
_parent: list[_ProcessParent] = []


def current_parent() -> ParentPort | None:
    """The parent of the worker process this code runs in, if any. The
    channel's variables are taken out of the environment, so processes this
    one starts do not see them."""
    with _lock:
        if _parent:
            return _parent[0]
        fd = os.environ.pop(CHANNEL_ENV, None)
        parent_pid = os.environ.pop(PARENT_ENV, None)
        if fd is None or parent_pid != str(os.getppid()):
            return None
        # pass_fds left the channel inheritable: keep it from the processes this one starts.
        os.set_inheritable(int(fd), False)
        port = _ProcessParent(socket.socket(fileno=int(fd)))
        _parent.append(port)
        return port
