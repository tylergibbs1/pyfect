"""Messages over a socket between a parent and its worker process.

Each message is a pickle behind its four-byte length. A ``FrameWriter``
writes on a thread of its own, so posting never waits on the socket;
``read_frames`` reads on the calling thread (a reader thread) until the
other end closes.
"""

from __future__ import annotations

import pickle
import queue
import socket
import struct
import threading
from collections.abc import Callable

_HEADER = struct.Struct(">I")


def encode(message: object) -> bytes:
    payload = pickle.dumps(message, protocol=pickle.HIGHEST_PROTOCOL)
    return _HEADER.pack(len(payload)) + payload


def read_frames(
    sock: socket.socket,
    on_message: Callable[[object], None],
    on_unreadable: Callable[[BaseException], None],
) -> None:
    """Read messages until the socket ends or fails."""
    with sock.makefile("rb") as stream:
        while True:
            try:
                header = stream.read(_HEADER.size)
                if len(header) < _HEADER.size:
                    return
                (size,) = _HEADER.unpack(header)
                payload = stream.read(size)
            except OSError:
                return
            if len(payload) < size:
                return
            try:
                message = pickle.loads(payload)  # our own child or parent
            except Exception as cause:  # reported as an unreadable message
                on_unreadable(cause)
                continue
            on_message(message)


class FrameWriter:
    """Writes frames in order on its own thread; once the socket fails,
    frames are dropped."""

    __slots__ = ("_frames", "_sock", "_thread")

    def __init__(self, sock: socket.socket, name: str) -> None:
        self._sock = sock
        self._frames: queue.SimpleQueue[bytes | None] = queue.SimpleQueue()
        self._thread = threading.Thread(target=self._run, name=name, daemon=True)
        self._thread.start()

    def write(self, frame: bytes) -> None:
        self._frames.put(frame)

    def close(self, timeout: float | None = None) -> None:
        """Stop once what was written is sent, waiting at most ``timeout``
        for it."""
        self._frames.put(None)
        if timeout is not None and threading.current_thread() is not self._thread:
            self._thread.join(timeout)

    def _run(self) -> None:
        while True:
            frame = self._frames.get()
            if frame is None:
                return
            try:
                self._sock.sendall(frame)
            except OSError:
                return
