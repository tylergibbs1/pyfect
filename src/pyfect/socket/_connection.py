"""A stream connection on the socket loop: an asyncio protocol whose state
fibers read under a lock.

The loop thread fills the read buffer and records how the connection ended;
fibers take from the buffer in their own step and park on ``Signal`` until
there is something to take, so an interrupt between a wake-up and the take
cannot lose bytes. Reading pauses while the buffer holds ``HIGH_WATER_MARK``
bytes.

How the read side ends follows Node's sockets: the peer ending the stream
delivers the buffered bytes, then a close with code 1000; an error or a
teardown discards them and fails with that error.

``start_tls`` adds a TLS layer (``TlsSession``) over the layers the
connection has, as Node's upgrade puts a ``TLSSocket`` over whatever the
socket is: bytes are decrypted by each layer, outermost first, before they
reach the buffer, and encrypted by each on the way out.
"""

from __future__ import annotations

import asyncio
import ssl
import threading
from collections import deque
from collections.abc import Callable

from pyfect._core import Effect
from pyfect._os_wait import Resume, os_wait
from pyfect.effect import fail, succeed, suspend, void
from pyfect.socket._errors import SocketError, close_error, read_error, write_error
from pyfect.socket._loop import call_soon
from pyfect.socket._tls_session import Received, TlsSession

HIGH_WATER_MARK = 64 * 1024


class Signal:
    """Fibers parked until a condition holds, woken from any thread to
    retry. Conditions are checked under ``lock``, the lock of the state
    they read. One signal serves several conditions, so a wake means only
    that something changed."""

    __slots__ = ("_waiters", "lock")

    def __init__(self, lock: threading.Lock) -> None:
        self.lock = lock
        self._waiters: list[Callable[[], None]] = []

    def wait(self, ready: Callable[[], bool]) -> Effect[None]:
        """Wait until ``ready`` holds, parking again after a wake for some
        other condition."""
        return self._wait_once(ready).flat_map(lambda _: void if ready() else self.wait(ready))

    def _wait_once(self, ready: Callable[[], bool]) -> Effect[None]:
        def register(resume: Resume[None, object]) -> Callable[[], None] | None:
            def wake() -> None:
                resume(void)

            with self.lock:
                parked = not ready()
                if parked:
                    self._waiters.append(wake)
            if not parked:
                wake()
                return None
            return lambda: self._forget(wake)

        return os_wait(register, waits_for="event")  # pyright: ignore[reportReturnType]

    def notify_locked(self) -> list[Callable[[], None]]:
        """Take the waiters (holding ``lock``); call them after releasing
        it."""
        waiters, self._waiters = self._waiters, []
        return waiters

    def _forget(self, wake: Callable[[], None]) -> None:
        with self.lock:
            if wake in self._waiters:
                self._waiters.remove(wake)


class Connection(asyncio.Protocol):
    """One stream connection. Created on a fiber, driven by the loop.
    ``on_made`` runs (on the loop) once it is connected: after the
    handshake when it is accepted with ``server_tls``."""

    def __init__(
        self,
        on_made: Callable[[Connection], None] | None = None,
        *,
        server_tls: ssl.SSLContext | None = None,
    ) -> None:
        self._on_made = on_made
        self._server_tls = server_tls
        self.lock = threading.Lock()
        self.signal = Signal(self.lock)
        self.transport: asyncio.Transport | None = None
        # Outermost first; the last one is what plaintext is written to.
        self._tls: tuple[TlsSession, ...] = ()
        self._chunks: deque[bytes] = deque()
        self._size = 0
        self._error: SocketError | None = None
        self._discard = False
        self._reading_paused = False
        self._writing_paused = False
        self._close_requested: bool | None = None
        self.lost = False
        self.open = False

    # --- loop side ----------------------------------------------------------

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        assert isinstance(transport, asyncio.Transport)
        self.transport = transport
        if self._close_requested is not None:
            self._apply_close(self._close_requested)
        elif self._server_tls is not None:
            handshake = self.start_tls(self._server_tls, server_side=True, hostname=None)
            handshake.add_done_callback(self._server_handshake_done)
        elif self._on_made is not None:
            self._on_made(self)

    def _server_handshake_done(self, handshake: asyncio.Future[None]) -> None:
        if handshake.cancelled() or handshake.exception() is not None:
            self._apply_close(graceful=False)
        elif self._on_made is not None:
            self._on_made(self)

    def data_received(self, data: bytes) -> None:
        received = Received((data,))
        for session in self._tls:
            received = session.feed(received)
        self._deliver(received)

    def _deliver(self, received: Received) -> None:
        if received.data:
            with self.lock:
                if not self._discard:
                    self._chunks.extend(received.data)
                    self._size += sum(map(len, received.data))
                    self._pause_if_full()
                waiters = self.signal.notify_locked()
            for wake in waiters:
                wake()
        if received.error is not None:
            self.fail(read_error(received.error))
        elif received.eof:
            self.end(close_error(1000))

    def _pause_if_full(self) -> None:
        transport = self.transport
        if self._size >= HIGH_WATER_MARK and not self._reading_paused and transport is not None:
            self._reading_paused = True
            transport.pause_reading()

    def eof_received(self) -> bool:
        self.end(close_error(1000))
        # Stay half-open: the write side ends when the writer is released.
        return True

    def connection_lost(self, exc: Exception | None) -> None:
        with self.lock:
            self.lost = True
            waiters = self.signal.notify_locked()
        for wake in waiters:
            wake()
        for session in self._tls:
            if not session.handshake.done():
                session.handshake.set_exception(exc or ConnectionError("socket closed"))
        if exc is None:
            self.end(close_error(1000))
        else:
            self.fail(read_error(exc))

    def pause_writing(self) -> None:
        with self.lock:
            self._writing_paused = True

    def resume_writing(self) -> None:
        with self.lock:
            self._writing_paused = False
            waiters = self.signal.notify_locked()
        for wake in waiters:
            wake()

    def start_tls(
        self, context: ssl.SSLContext, *, server_side: bool, hostname: str | None
    ) -> asyncio.Future[None]:
        """Begin a TLS handshake (on the loop) inside the TLS layers the
        connection has; bytes already buffered are the peer's first
        handshake bytes. The future settles with it."""
        transport = self.transport
        assert transport is not None
        lower = self._tls[-1] if self._tls else transport
        session = TlsSession(lower, context, server_side=server_side, hostname=hostname)
        self._tls = (*self._tls, session)
        with self.lock:
            buffered = tuple(self._chunks)
            self._chunks.clear()
            self._size = 0
        self._deliver(session.start(buffered))
        return session.handshake

    def upgrade(
        self, context: ssl.SSLContext, *, server_side: bool, hostname: str | None
    ) -> Effect[None, BaseException]:
        """``start_tls`` from a fiber, waiting for the handshake. It starts
        in the order of the fiber's other loop calls, so a write made after
        it is encrypted (queued until the handshake is done)."""

        def register(resume: Resume[None, BaseException]) -> None:
            def begin() -> None:
                transport = self.transport
                if transport is None or transport.is_closing():
                    resume(fail(ConnectionError("socket closed during TLS upgrade")))
                    return
                handshake = self.start_tls(context, server_side=server_side, hostname=hostname)

                def done(finished: asyncio.Future[None]) -> None:
                    error = finished.exception()
                    resume(void if error is None else fail(error))

                handshake.add_done_callback(done)

            call_soon(begin)

        return os_wait(register, waits_for="work")

    # --- either side ----------------------------------------------------------

    def end(self, error: SocketError) -> None:
        """The read side ended normally: buffered bytes are still taken
        before ``error``."""
        self._finish(error, discard=False)

    def fail(self, error: SocketError) -> None:
        """The connection failed or was torn down: buffered bytes are
        dropped."""
        self._finish(error, discard=True)

    def _finish(self, error: SocketError, *, discard: bool) -> None:
        with self.lock:
            if self._error is None:
                self._error = error
            if discard:
                self._discard = True
                self._chunks.clear()
                self._size = 0
            waiters = self.signal.notify_locked()
        for wake in waiters:
            wake()

    # --- fiber side -------------------------------------------------------------

    def _take(self, limit: int | None) -> tuple[bytes, ...] | SocketError | None:
        with self.lock:
            if self._chunks:
                if limit is None or len(self._chunks) <= limit:
                    chunks = tuple(self._chunks)
                    self._chunks.clear()
                    self._size = 0
                else:
                    chunks = tuple(self._chunks.popleft() for _ in range(limit))
                    self._size -= sum(map(len, chunks))
                if self._reading_paused and self._error is None and self._size < HIGH_WATER_MARK:
                    self._reading_paused = False
                    transport = self.transport
                    if transport is not None:
                        call_soon(transport.resume_reading)
                return chunks
            return self._error

    def _readable(self) -> bool:
        return bool(self._chunks) or self._error is not None

    def pull(self, limit: int | None = None) -> Effect[tuple[bytes, ...], SocketError]:
        """The buffered chunks (at most ``limit``, the rest left for the next
        pull), waiting for some; the read side's error once the buffer is empty."""
        return self.pull_into(lambda chunks: chunks, limit)

    def pull_into[A](
        self, take: Callable[[tuple[bytes, ...]], A], limit: int | None = None
    ) -> Effect[A, SocketError]:
        """``take`` of the buffered chunks (at most ``limit``), called in the step
        that takes them, so an interrupt cannot lose them."""

        def step() -> Effect[A, SocketError]:
            taken = self._take(limit)
            if isinstance(taken, tuple):
                return succeed(take(taken))
            if taken is not None:
                return fail(taken)
            return self.signal.wait(self._readable).flat_map(lambda _: suspend(step))

        return suspend(step)

    def closed(self) -> Effect[None]:
        """Wait until the transport is lost."""
        return self.signal.wait(lambda: self.lost)

    def read_ended(self) -> Effect[None]:
        """Wait until the read side has ended or failed."""
        return self.signal.wait(lambda: self._error is not None)

    def discard_input(self) -> None:
        """Drop what was received and everything received from now on,
        reading on (a server ignoring the rest of a request it rejected)."""

        def run() -> None:
            with self.lock:
                self._discard = True
                self._chunks.clear()
                self._size = 0
                resume = self._reading_paused
                self._reading_paused = False
            transport = self.transport
            if resume and transport is not None and not transport.is_closing():
                transport.resume_reading()

        call_soon(run)

    def peer_name(self) -> object:
        """The transport's ``peername``, ``None`` before it is made."""
        transport = self.transport
        return None if transport is None else transport.get_extra_info("peername")

    @property
    def encrypted(self) -> bool:
        return bool(self._tls) or self._server_tls is not None

    def write(self, chunks: tuple[bytes, ...]) -> Effect[None, SocketError]:
        """Write ``chunks`` on the loop, then wait while the transport's
        buffer is over its high-water mark."""
        return self.write_with(lambda: chunks)

    def write_with(self, make: Callable[[], tuple[bytes, ...]]) -> Effect[None, SocketError]:
        """``write`` of the chunks ``make`` gives, called on the loop: writes made one
        after another are made, and so encoded, in that order."""

        def register(resume: Resume[None, SocketError]) -> None:
            def run() -> None:
                transport = self.transport
                if transport is None or transport.is_closing():
                    resume(fail(write_error(ConnectionError("socket closed"))))
                    return
                try:
                    chunks = make()
                    (self._tls[-1] if self._tls else transport).writelines(chunks)
                except Exception as cause:
                    resume(fail(write_error(cause)))
                    return
                resume(void)

            call_soon(run)

        return os_wait(register, waits_for="work").flat_map(lambda _: self._drained())

    def _drained(self) -> Effect[None, SocketError]:
        def ready() -> bool:
            return not self._writing_paused or self.lost

        def check(_: None) -> Effect[None, SocketError]:
            if self.lost and self._writing_paused:
                return fail(write_error(ConnectionError("socket closed")))
            return void

        return self.signal.wait(ready).flat_map(check)

    def end_writing(self) -> None:
        """Half-close once buffered writes are flushed: close_notify from
        each TLS layer, innermost first, then end-of-stream."""

        def run() -> None:
            transport = self.transport
            if transport is None or transport.is_closing():
                return
            for session in reversed(self._tls):
                session.shutdown()
            if transport.can_write_eof():
                transport.write_eof()

        call_soon(run)

    def close(self, *, graceful: bool) -> None:
        """Close the connection: flushing buffered writes first when
        ``graceful``, else at once; a connection still being made is closed
        when it is."""

        def run() -> None:
            self._close_requested = graceful
            self._apply_close(graceful)

        call_soon(run)

    def _apply_close(self, graceful: bool) -> None:
        transport = self.transport
        if transport is None:
            return
        if graceful:
            transport.close()
        else:
            transport.abort()
