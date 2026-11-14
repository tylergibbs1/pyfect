"""The parent's ends of a child's pipes, as byte streams and sinks.

A ``Reader`` has a thread that reads only while a fiber waits for data, so
an unread pipe fills up and the child waits for it, as a Node stream's
backpressure makes it. Chunks it has read wait in the reader until taken,
so an interrupted pull loses nothing. A ``Writer`` writes what the pipe
takes at once, as Node does, and leaves the rest to a thread, started by
the first write that needs it, which writes in short waits on a
non-blocking descriptor, so an interrupted write stops within one of those
waits. Each
pipe has threads of its own, never a shared pool, so a pipe waiting on its
child never holds up another pipe. Both close their descriptor themselves,
once no thread is using it.
"""

from __future__ import annotations

import contextlib
import errno
import os
import select
import socket
import threading
from collections import deque
from collections.abc import Callable
from typing import Never

from pyfect import sink as sink_
from pyfect import stream as stream_
from pyfect._core import Effect
from pyfect._os_wait import Cancel, Resume, os_wait
from pyfect.effect import die, fail, succeed, suspend, sync
from pyfect.errors import Done
from pyfect.platform_error import PREMATURE_CLOSE, WRITE_AFTER_END, PlatformError, StreamError
from pyfect.sink import Sink
from pyfect.stream import Stream

CHUNK_SIZE = 64 * 1024
_POLL = 0.05
"""Seconds a pipe thread waits for its descriptor before checking whether
it was closed."""

type OnError = Callable[[OSError | StreamError], PlatformError]
type _Pull = Effect[tuple[bytes, ...], PlatformError | Done]


def _ready(fd: int, *, write: bool) -> bool:
    if os.name == "nt":
        return True
    ready = select.select([], [fd], [], _POLL) if write else select.select([fd], [], [], _POLL)
    return bool(ready[0] or ready[1])


class Reader:
    """Reads the pipe ``fd`` on demand; ``stream`` is its bytes."""

    __slots__ = (
        "_chunks",
        "_closing",
        "_cond",
        "_ended",
        "_error",
        "_fd",
        "_on_error",
        "_waiters",
    )

    def __init__(self, fd: int, on_error: OnError) -> None:
        self._fd = fd
        self._on_error = on_error
        self._cond = threading.Condition()
        self._chunks: deque[bytes] = deque()
        self._ended = False
        self._closing = False
        self._error: OSError | None = None
        self._waiters: list[Resume[tuple[bytes, ...], PlatformError | Done]] = []
        threading.Thread(target=self._run, name="pyfect-process-reader", daemon=True).start()

    @property
    def stream(self) -> Stream[bytes, PlatformError]:
        return stream_.from_pull(succeed(self._pull()))

    def close(self) -> None:
        """Stop reading once what the pipe holds now is read (all a child
        that has exited wrote); then pulls end the stream."""
        with self._cond:
            self._closing = True
            self._cond.notify()

    def fail(self, error: OSError) -> None:
        """Fail the stream with ``error`` (a write to the same duplex
        descriptor failed), as Node destroys the readable side: kept until a
        reader pulls, so it neither goes unseen nor leaves the reader
        waiting."""
        with self._cond:
            if self._ended:
                return
            self._chunks.clear()
            self._error = error
            self._ended = True
            waiters, self._waiters = self._waiters, []
            self._cond.notify()
        self._wake(waiters)

    def _pull(self) -> _Pull:
        def register(resume: Resume[tuple[bytes, ...], PlatformError | Done]) -> Cancel | None:
            with self._cond:
                taken = self._take()
                if taken is None:
                    self._waiters.append(resume)
                    self._cond.notify()
            if taken is not None:
                resume(taken)
                return None
            return lambda: self._forget(resume)

        return os_wait(register, waits_for="event")

    def _take(self) -> _Pull | None:
        if self._chunks:
            return succeed((self._chunks.popleft(),))
        if self._error is not None:
            return fail(self._on_error(self._error))
        if self._ended:
            return fail(Done())
        return None

    def _forget(self, resume: Resume[tuple[bytes, ...], PlatformError | Done]) -> None:
        with self._cond:
            if resume in self._waiters:
                self._waiters.remove(resume)

    def _wake(self, waiters: list[Resume[tuple[bytes, ...], PlatformError | Done]]) -> None:
        # Woken pulls run again rather than being handed a chunk: one that
        # was interrupted meanwhile takes nothing.
        for resume in waiters:
            resume(suspend(self._pull))

    def _wanted(self) -> bool:
        return bool(self._waiters) and not self._chunks

    def _run(self) -> None:
        try:
            while self._read_once():
                pass
        finally:
            os.close(self._fd)

    def _read_once(self) -> bool:  # noqa: PLR0911
        with self._cond:
            while not self._ended and not self._closing and not self._wanted():
                self._cond.wait()
            if self._ended:
                return False
            closing = self._closing
        if closing:
            self._end(*self._drain())
            return False
        data = b""
        error: OSError | None = None
        try:
            if not _ready(self._fd, write=False):
                return True
            data = os.read(self._fd, CHUNK_SIZE)
        except BlockingIOError:
            # A duplex descriptor shares its non-blocking flag with its writer.
            return True
        except OSError as e:
            error = e
        if not data:
            self._end([], error)
            return False
        with self._cond:
            if self._ended:  # failed meanwhile
                return False
            self._chunks.append(data)
            waiters, self._waiters = self._waiters, []
        self._wake(waiters)
        return True

    def _drain(self) -> tuple[list[bytes], OSError | None]:
        """What the pipe holds now, without waiting for more."""
        chunks: list[bytes] = []
        if os.name == "nt":
            return chunks, None
        try:
            while select.select([self._fd], [], [], 0)[0]:
                data = os.read(self._fd, CHUNK_SIZE)
                if not data:
                    break
                chunks.append(data)
        except OSError as error:
            return chunks, error
        return chunks, None

    def _end(self, chunks: list[bytes], error: OSError | None) -> None:
        with self._cond:
            if self._ended:  # failed meanwhile
                return
            self._chunks.extend(chunks)
            self._error = error
            self._ended = True
            waiters, self._waiters = self._waiters, []
        self._wake(waiters)


class _Write:
    """One write waiting for, or held by, a writer's thread. It holds the
    bytes, never a view of them: the writer's thread makes its own views and
    releases them before it resumes the write (free-threaded CPython's
    ``memoryview`` is not safe to share between threads)."""

    __slots__ = ("cancelled", "data", "resume", "start")

    def __init__(self, data: bytes, start: int, resume: Resume[None, PlatformError]) -> None:
        self.data = data
        self.start = start
        """How much of ``data`` was written before the thread took it."""
        self.resume = resume
        self.cancelled = False

    def cancel(self) -> None:
        """Skip the rest of the write: its thread stops at its next wait or
        never starts it."""
        self.cancelled = True


class Writer:
    """Writes to the pipe ``fd``; ``sink`` writes its input."""

    __slots__ = (
        "_closed",
        "_cond",
        "_fd",
        "_half_close",
        "_on_error",
        "_on_failed",
        "_queue",
        "_started",
    )

    def __init__(
        self,
        fd: int,
        on_error: OnError,
        *,
        half_close: bool = False,
        on_failed: Callable[[OSError], None] | None = None,
    ) -> None:
        """``half_close``: ``fd`` is a socket another descriptor also reads,
        so closing shuts down its write side first (the peer reads the end).
        ``on_failed`` hears of each write the system refused."""
        self._fd = fd
        self._on_error = on_error
        self._half_close = half_close
        self._on_failed = on_failed
        self._cond = threading.Condition()
        self._queue: deque[_Write] = deque()
        self._closed: tuple[str, str] | None = None
        """Why later writes fail, as Node's stream says it: ended, or destroyed."""
        self._started = False
        if os.name != "nt":
            os.set_blocking(fd, False)

    def sink(self, *, end_on_done: bool) -> Sink[None, bytes, Never, PlatformError]:
        """Write each chunk; with ``end_on_done``, close the pipe however the
        input ends."""
        write: Sink[None, bytes, Never, PlatformError] = sink_.for_each(self.write)
        return write.ensuring(sync(self.end)) if end_on_done else write

    def text_sink(
        self, encode: Callable[[str], bytes], *, end_on_done: bool
    ) -> Sink[None, bytes | str, Never, PlatformError]:
        """``sink``, also taking text, made bytes by ``encode`` (Node's
        writable ``encoding``)."""

        def write(chunk: bytes | str) -> Effect[None, PlatformError]:
            return self.write(encode(chunk) if isinstance(chunk, str) else chunk)

        sink: Sink[None, bytes | str, Never, PlatformError] = sink_.for_each(write)
        return sink.ensuring(sync(self.end)) if end_on_done else sink

    def write(self, data: bytes) -> Effect[None, PlatformError]:
        """Write ``data``. As Node's stream, a write first tries the pipe at once and leaves
        what it could not write to the thread."""

        def register(resume: Resume[None, PlatformError]) -> Cancel | None:
            request: _Write | None = None
            written: int | OSError = 0
            with self._cond:
                closed = self._closed
                if closed is None:
                    written = self._write_now(data) if not self._queue else 0
                    if isinstance(written, int) and written < len(data):
                        request = _Write(data, written, resume)
                        self._queue.append(request)
                        self._start()
                        self._cond.notify()
            if closed is not None:
                resume(fail(self._on_error(StreamError(*closed))))
                return None
            if request is not None:
                return request.cancel
            resume(succeed(None) if isinstance(written, int) else self._failed(written))
            return None

        return os_wait(register, waits_for="work")

    def _write_now(self, data: bytes) -> int | OSError:
        """What the pipe takes of ``data`` without waiting: the bytes written, or the
        error."""
        if os.name == "nt":
            return 0  # A blocking pipe: only the thread writes.
        try:
            return os.write(self._fd, data)
        except BlockingIOError:
            return 0
        except OSError as error:
            return error

    def end(self) -> None:
        """End the pipe, as Node's ``end``: later writes fail with ``write after end``."""
        self._close(WRITE_AFTER_END)

    def destroy(self) -> None:
        """Close the pipe as Node destroys a child's ``stdin`` when the child exits: writes
        made before fail with ``ECANCELED``, later ones with ``Premature close``. A pipe
        already ended stays ended."""
        self._close(PREMATURE_CLOSE)

    def _close(self, why: tuple[str, str]) -> None:
        """A write in progress or queued stops and fails with ``ECANCELED``
        (as a Node stream's destroy fails it); after ``end`` queued writes
        fail as later writes do."""
        with self._cond:
            if self._closed is not None:
                return
            self._closed = why
            started = self._started
            self._cond.notify()
        if not started:
            self._release()

    def _start(self) -> None:
        if not self._started:
            self._started = True
            threading.Thread(target=self._run, name="pyfect-process-writer", daemon=True).start()

    def _run(self) -> None:
        try:
            while (request := self._next()) is not None:
                self._serve(request)
        finally:
            self._release()

    def _release(self) -> None:
        if self._half_close:
            sock = socket.socket(fileno=self._fd)
            with contextlib.suppress(OSError):
                sock.shutdown(socket.SHUT_WR)
            sock.close()
        else:
            os.close(self._fd)

    def _failed(self, error: OSError) -> Effect[None, PlatformError]:
        if self._on_failed is not None:
            self._on_failed(error)
        return fail(self._on_error(error))

    def _next(self) -> _Write | None:
        with self._cond:
            while not self._queue and self._closed is None:
                self._cond.wait()
            closed = self._closed
            if closed is None:
                return self._queue[0]
            queued, self._queue = list(self._queue), deque()
        error = _cancelled() if closed == PREMATURE_CLOSE else StreamError(*closed)
        for request in queued:
            request.resume(fail(self._on_error(error)))
        return None

    def _serve(self, request: _Write) -> None:
        try:
            result = self._write_out(request)
        except Exception as error:  # A dead thread would leave every write waiting.
            result = die(error)
        with self._cond:
            self._queue.popleft()
            request.resume(result)

    def _write_out(self, request: _Write) -> Effect[None, PlatformError]:
        """Write ``request`` in short waits until one of the outcomes below
        decides its result. The view is this thread's alone."""
        with memoryview(request.data) as data:
            written = request.start
            while True:
                if written == len(data):
                    return succeed(None)
                if request.cancelled:
                    return succeed(None)  # Interrupted: nobody takes the result.
                if self._closed is not None:
                    return fail(self._on_error(_cancelled()))
                try:
                    if _ready(self._fd, write=True):
                        written += os.write(self._fd, data[written:])
                except BlockingIOError:
                    continue
                except OSError as error:
                    return self._failed(error)


def _cancelled() -> OSError:
    return OSError(errno.ECANCELED, "write ECANCELED")
