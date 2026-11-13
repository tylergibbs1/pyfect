"""WebSocket sockets (Effect's ``fromWebSocket`` and ``makeWebSocket``).

``from_web_socket`` adapts anything shaped like the browser ``WebSocket``
(``WebSocketLike``: ``ready_state``, event listeners, ``send``, ``close``)
into a ``SocketService``. Events may arrive on any thread: the reader keeps
its buffer under a lock and parked pulls are woken to retry, so a message
is never handed to a fiber that was interrupted meanwhile. A socket with
``pause``/``resume`` is paused while the buffer holds ``high_water_mark``
bytes; one without fails the read once that many are waiting unread.

``make_web_socket`` opens a client through the ``WebSocketConstructor``
service; ``pyfect.socket.ws`` provides one on the ``websockets`` library.
"""

from __future__ import annotations

import contextlib
import threading
import weakref
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal, Never, Protocol, final, runtime_checkable

from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect._js import text_encode
from pyfect._os_wait import Resume, os_wait
from pyfect.channel import Channel
from pyfect.channel import unwrap as unwrap_channel
from pyfect.context import Tag
from pyfect.duration import Input as DurationInput
from pyfect.effect import fail, gen, succeed, suspend, sync, void
from pyfect.exit import Exit, Success
from pyfect.latch import Latch
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.scope import Scope, acquire_release
from pyfect.socket._connection import Signal
from pyfect.socket._errors import (
    CloseEvent,
    SocketError,
    close_error,
    open_error,
    read_error,
    write_error,
)
from pyfect.socket._socket import (
    Chunk,
    Reader,
    Socket,
    SocketChannel,
    SocketService,
    Writer,
    make,
    to_channel,
    unsupported_upgrade,
)

DEFAULT_HIGH_WATER_MARK = 64 * 1024
DEFAULT_OPEN_TIMEOUT: DurationInput = "10 seconds"
DEFAULT_MAX_MESSAGE_SIZE = 100 * 1024 * 1024
"""The longest message pyfect's WebSocket servers and clients take (uvicorn's
``ws_max_size``); a longer one closes the connection with 1009."""

CONNECTING, OPEN, CLOSING, CLOSED = 0, 1, 2, 3

type WebSocketEventType = Literal["open", "message", "error", "close"]


@dataclass(frozen=True, slots=True, kw_only=True)
class WebSocketEvent:
    """What a listener receives: ``data`` for a message (``bytes`` or
    ``str``), ``code`` and ``reason`` for a close."""

    type: WebSocketEventType | None = None
    data: object = None
    code: int | None = None
    reason: str | None = None


type Listener = Callable[[WebSocketEvent], None]


class WebSocketLike(Protocol):
    """The browser ``WebSocket`` surface a socket is built on."""

    @property
    def ready_state(self) -> int: ...

    def add_event_listener(
        self, type: WebSocketEventType, listener: Listener, *, once: bool = False
    ) -> None: ...

    def remove_event_listener(self, type: WebSocketEventType, listener: Listener) -> None: ...

    def close(self, code: int | None = None, reason: str | None = None) -> None: ...

    def send(self, data: bytes | str) -> None: ...


@runtime_checkable
class Pausable(Protocol):
    """A WebSocket whose incoming messages can be paused."""

    def pause(self) -> None: ...

    def resume(self) -> None: ...


@runtime_checkable
class HasUrl(Protocol):
    """A WebSocket that knows the URL it connects to (the browser's
    ``url``; ``None`` for an accepted one): an open failure names it."""

    @property
    def url(self) -> str | None: ...


@runtime_checkable
class Drainable(Protocol):
    """A WebSocket that counts the bytes it was given but has not sent yet
    (the browser's ``bufferedAmount``): writes to it wait for them."""

    @property
    def buffered_amount(self) -> int: ...

    def when_drained(self, below: int, callback: Callable[[], None]) -> Callable[[], None]:
        """Call ``callback`` once, from any thread, when fewer than ``below``
        bytes are unsent or the socket closed; returns a function that
        cancels it."""
        ...


class Outgoing:
    """The unsent bytes of a ``Drainable`` WebSocket and the writers
    waiting for them, kept by the WebSocket: ``queued`` when ``send`` takes
    a message, ``sent`` once the transport took it, ``close`` when no more
    will be sent."""

    __slots__ = ("_closed", "_lock", "_waiters", "amount")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._waiters: list[tuple[int, Callable[[], None]]] = []
        self._closed = False
        self.amount = 0

    def queued(self, data: bytes | str) -> int:
        size = _byte_length(data)
        with self._lock:
            self.amount += size
        return size

    def sent(self, size: int) -> None:
        with self._lock:
            self.amount -= size
            ready = [entry for entry in self._waiters if self.amount < entry[0]]
            self._waiters = [entry for entry in self._waiters if self.amount >= entry[0]]
        for _, callback in ready:
            callback()

    def close(self) -> None:
        with self._lock:
            self._closed = True
            ready, self._waiters = self._waiters, []
        for _, callback in ready:
            callback()

    def when_drained(self, below: int, callback: Callable[[], None]) -> Callable[[], None]:
        entry = (below, callback)
        with self._lock:
            parked = not self._closed and self.amount >= below
            if parked:
                self._waiters.append(entry)
        if not parked:
            callback()

        def cancel() -> None:
            with self._lock, contextlib.suppress(ValueError):
                self._waiters.remove(entry)

        return cancel


@dataclass(frozen=True, slots=True, kw_only=True)
class WebSocketClientOptions:
    """Options of the opening handshake: subprotocols and extra headers."""

    protocols: str | Sequence[str] | None = None
    headers: Mapping[str, str] | None = None


type WebSocketConstructorService = Callable[[str, WebSocketClientOptions], WebSocketLike]


class WebSocketConstructor(
    Tag[WebSocketConstructorService], key="@effect/platform/Socket/WebSocketConstructor"
):
    """Opens a WebSocket client connection to a URL."""


class WebSocket(Tag[WebSocketLike], key="~effect/socket/Socket/WebSocket"):
    """The native WebSocket a server hands to its handler."""


def close_code(exit: Exit[object, object]) -> int:
    """The code a server closes an upgraded WebSocket with when its
    handler's scope ends (Effect's ``closeCode``): 1000 on success, 1001
    when interrupted, 1011 on failure."""
    if isinstance(exit, Success):
        return 1000
    return 1001 if exit.cause.has_interrupts_only else 1011


def _byte_length(data: bytes | str) -> int:
    return len(text_encode(data)) if isinstance(data, str) else len(data)


@final
class _Forward:
    """A listener calling one of a buffer's handlers. It holds the buffer
    weakly: the buffer keeps its listeners (to remove them), and a bound
    method would point back, a cycle that kept the socket alive after the
    run."""

    __slots__ = ("buffer", "handler")

    def __init__(self, buffer: _Buffer, handler: Callable[[_Buffer, WebSocketEvent], None]) -> None:
        self.buffer = weakref.ref(buffer)
        self.handler = handler

    def __call__(self, event: WebSocketEvent) -> None:
        buffer = self.buffer()
        if buffer is not None:
            self.handler(buffer, event)


class _Buffer:
    """The reader's state, shared with the listeners."""

    def __init__(self, ws: WebSocketLike, high_water_mark: int | None) -> None:
        self.ws = ws
        self.target: str | None = ws.url if isinstance(ws, HasUrl) else None
        self.pausable: Pausable | None = ws if isinstance(ws, Pausable) else None
        self.high_water_mark = (
            high_water_mark
            if high_water_mark is not None
            else (DEFAULT_HIGH_WATER_MARK if self.pausable else None)
        )
        self.lock = threading.Lock()
        self.signal = Signal(self.lock)
        self.open = ws.ready_state == OPEN
        self.paused = self.pausable is not None and getattr(ws, "is_paused", False) is True
        self.chunks: list[Chunk] = []
        self.size = 0
        self.error: SocketError | None = None
        # One object per listener, so removing it finds the one added.
        self.on_message: Listener = _Forward(self, _Buffer._on_message)
        self.on_error: Listener = _Forward(self, _Buffer._on_error)
        self.on_close: Listener = _Forward(self, _Buffer._on_close)
        self.on_open: Listener = _Forward(self, _Buffer._on_open)

    def attach(self) -> None:
        self.ws.add_event_listener("message", self.on_message)
        self.ws.add_event_listener("error", self.on_error, once=True)
        self.ws.add_event_listener("close", self.on_close, once=True)

    def detach(self) -> None:
        # Resume a pull parked in another fiber before detaching.
        self.fail(close_error(1006))
        ws = self.ws
        ws.remove_event_listener("message", self.on_message)
        # Keep late errors handled when release aborts a pending handshake.
        ws.add_event_listener("error", _ignore)
        ws.remove_event_listener("error", self.on_error)
        ws.remove_event_listener("close", self.on_close)
        # Let the close handshake proceed once nothing is pulling.
        with self.lock, contextlib.suppress(Exception):
            self.resume()

    def _on_message(self, event: WebSocketEvent) -> None:
        try:
            data = _message_data(event.data)
        except TypeError as cause:
            self.fail(read_error(cause))
            return
        self.push(data)

    def _on_error(self, event: WebSocketEvent) -> None:
        self.fail(read_error(event) if self.open else open_error(event, target=self.target))

    def _on_close(self, event: WebSocketEvent) -> None:
        code = event.code if isinstance(event.code, int) else 1006
        self.fail(close_error(code, event.reason))

    def _on_open(self, _event: WebSocketEvent) -> None:
        with self.lock:
            self.open = True
            waiters = self.signal.notify_locked()
        for wake in waiters:
            wake()

    def wait_open(self) -> Effect[None, SocketError]:
        """Wait for the open event, or the failure that comes first."""

        def register() -> None:
            self.ws.add_event_listener("open", self.on_open, once=True)
            # It may have opened (on another thread) before the listener.
            if self.ws.ready_state == OPEN:
                self.on_open(WebSocketEvent(type="open"))

        def check(_: None) -> Effect[None, SocketError]:
            return void if self.open or self.error is None else fail(self.error)

        waiting = self.signal.wait(lambda: self.open or self.error is not None).flat_map(check)
        unregister = sync(lambda: self.ws.remove_event_listener("open", self.on_open))
        return sync(register).and_then(waiting).ensuring(unregister)

    def started(self) -> None:
        """The reader is ready: let messages flow unless the buffer is full."""
        with self.lock:
            hwm = self.high_water_mark
            if self.error is None and (hwm is None or self.size < hwm):
                self.resume()

    # Pausing and resuming happen under the lock, so they reach the socket
    # in the order the buffer's size called for them.

    def _pause(self) -> None:
        if self.pausable is not None and not self.paused:
            self.pausable.pause()
            self.paused = True

    def resume(self) -> None:
        if self.pausable is not None and self.paused:
            self.pausable.resume()
            self.paused = False

    def push(self, data: Chunk) -> None:
        with self.lock:
            self.chunks.append(data)
            hwm = self.high_water_mark
            if hwm is not None:
                self.size += _byte_length(data)
            waiters = self.signal.notify_locked()
            if hwm is not None and self.size >= hwm and self.pausable is not None:
                self._pause()
            elif hwm is not None and self.size > hwm and self.pausable is None and not waiters:
                cause = RuntimeError(f"Socket highWaterMark of {hwm} bytes exceeded")
                self._fail_locked(read_error(cause))
        for wake in waiters:
            wake()

    def fail(self, error: SocketError) -> None:
        with self.lock:
            self._fail_locked(error)
            waiters = self.signal.notify_locked()
        for wake in waiters:
            wake()

    def _fail_locked(self, error: SocketError) -> None:
        if self.error is None:
            self.error = error

    def _take(self) -> tuple[Chunk, ...] | SocketError | None:
        with self.lock:
            if self.chunks:
                chunks = tuple(self.chunks)
                self.chunks.clear()
                self.size = 0
                if self.error is None:
                    self.resume()
                return chunks
            return self.error

    def _readable(self) -> bool:
        return bool(self.chunks) or self.error is not None

    def pull(self) -> Effect[tuple[Chunk, ...], SocketError]:
        def step() -> Effect[tuple[Chunk, ...], SocketError]:
            taken = self._take()
            if isinstance(taken, tuple):
                return succeed(taken)
            if taken is not None:
                return fail(taken)
            return self.signal.wait(self._readable).flat_map(lambda _: self.pull())

        return suspend(step)


def _message_data(data: object) -> Chunk:
    if isinstance(data, (str, bytes)):
        return data
    if isinstance(data, (bytearray, memoryview)):
        return bytes(data)  # pyright: ignore[reportUnknownArgumentType]
    raise TypeError(f"unsupported WebSocket message data: {type(data).__name__}")


def _ignore(_: WebSocketEvent) -> None:
    pass


def _open_timeout(target: str | None) -> Effect[Never, SocketError]:
    cause = TimeoutError('timeout waiting for "open"')
    return fail(open_error(cause, "Timeout", target=target))


class _Current:
    """The WebSocket the current reader got, which its writes use; a write
    waits while ``write_limit`` bytes are unsent."""

    __slots__ = ("latch", "write_limit", "ws")

    def __init__(self, write_limit: int) -> None:
        self.ws: WebSocketLike | None = None
        self.latch = Latch(False)
        self.write_limit = write_limit

    def _drained(self, ws: WebSocketLike) -> Effect[None, SocketError]:
        write_limit = self.write_limit
        if not isinstance(ws, Drainable) or ws.buffered_amount < write_limit:
            return void

        def register(resume: Resume[None, SocketError]) -> Callable[[], None]:
            return ws.when_drained(write_limit, lambda: resume(void))

        return os_wait(register, waits_for="event")

    def write(self, chunk: Chunk | CloseEvent) -> Effect[None, SocketError]:
        def start() -> Effect[None, SocketError]:
            ws = self.ws
            if ws is None:
                return self.latch.when_open(self.write(chunk))
            try:
                if isinstance(chunk, CloseEvent):
                    ws.close(chunk.code, chunk.reason)
                    return void
                ws.send(chunk)
            except Exception as cause:
                return fail(write_error(cause))
            return self._drained(ws)

        return suspend(start)

    def write_all(self, chunks: Sequence[Chunk]) -> Effect[None, SocketError]:
        def start() -> Effect[None, SocketError]:
            ws = self.ws
            if ws is None:
                return self.latch.when_open(self.write_all(chunks))
            try:
                for chunk in chunks:
                    ws.send(chunk)
            except Exception as cause:
                return fail(write_error(cause))
            return self._drained(ws)

        return suspend(start)


def from_web_socket(
    acquire: Effect[WebSocketLike, SocketError, Scope],
    *,
    open_timeout: DurationInput | None = None,
    high_water_mark: int | None = None,
) -> SocketService:
    """A socket over the WebSocket each acquisition of the reader gets from
    ``acquire``. The reader waits for it to open (``open_timeout``, ten
    seconds by default); a close fails pulls with a ``SocketCloseError``
    (code 1000 for a normal close). On a ``Drainable`` WebSocket a write
    waits while ``high_water_mark`` (64 KiB by default) bytes are unsent."""
    require_effect(acquire, "acquire")
    current = _Current(DEFAULT_HIGH_WATER_MARK if high_water_mark is None else high_water_mark)
    timeout = DEFAULT_OPEN_TIMEOUT if open_timeout is None else open_timeout

    def reader():
        scope = yield from Scope()
        ws = yield from acquire
        buffer = _Buffer(ws, high_water_mark)
        buffer.attach()

        def release(_: Exit[object, object]) -> Effect[None]:
            def run_release() -> None:
                buffer.detach()
                current.latch.close_unsafe()
                current.ws = None

            return sync(run_release)

        yield from scope.add_finalizer(release)
        if ws.ready_state >= CLOSING:
            return (yield from fail(buffer.error or close_error(1006)))
        if not buffer.open:
            yield from buffer.wait_open().timeout_or_else(
                timeout, lambda: _open_timeout(buffer.target)
            )
        buffer.started()
        current.ws = ws
        current.latch.open_unsafe()
        return Reader(buffer.pull(), unsupported_upgrade)

    return make(gen(reader), succeed(Writer(current.write, current.write_all)))


def make_web_socket(
    url: str | Effect[str],
    *,
    open_timeout: DurationInput | None = None,
    protocols: str | Sequence[str] | None = None,
    headers: Mapping[str, str] | None = None,
    high_water_mark: int | None = None,
) -> Effect[SocketService, Never, WebSocketConstructor]:
    """A WebSocket client socket: each acquisition of the reader connects
    to ``url`` through the ``WebSocketConstructor`` (closed with code 1000
    when its scope closes)."""
    if not isinstance(url, str):
        require_effect(url, "url")
    url_effect: Effect[str] = succeed(url) if isinstance(url, str) else url
    options = WebSocketClientOptions(protocols=protocols, headers=headers)

    def build(construct: WebSocketConstructorService) -> SocketService:
        acquire = acquire_release(
            url_effect.map(lambda target: construct(target, options)),
            lambda ws, _: sync(lambda: ws.close(1000)),
        )
        return from_web_socket(acquire, open_timeout=open_timeout, high_water_mark=high_water_mark)

    return WebSocketConstructor().map(build)


def make_web_socket_channel[IE = Never](
    url: str,
    *,
    open_timeout: DurationInput | None = None,
    protocols: str | Sequence[str] | None = None,
    headers: Mapping[str, str] | None = None,
    high_water_mark: int | None = None,
) -> Channel[
    tuple[bytes, ...],
    SocketError | IE,
    None,
    tuple[Chunk | CloseEvent, ...],
    IE,
    object,
    WebSocketConstructor,
]:
    """``to_channel`` of a ``make_web_socket`` socket."""

    def channel(socket: SocketService) -> SocketChannel[bytes, IE]:
        return to_channel(socket)

    socket = make_web_socket(
        url,
        open_timeout=open_timeout,
        protocols=protocols,
        headers=headers,
        high_water_mark=high_water_mark,
    )
    return unwrap_channel(socket.map(channel))


def layer_web_socket(
    url: str | Effect[str],
    *,
    open_timeout: DurationInput | None = None,
    protocols: str | Sequence[str] | None = None,
    headers: Mapping[str, str] | None = None,
    high_water_mark: int | None = None,
) -> Layer[Socket, Never, WebSocketConstructor]:
    """``Socket`` as a ``make_web_socket`` client."""
    return layer_effect(
        Socket,
        make_web_socket(
            url,
            open_timeout=open_timeout,
            protocols=protocols,
            headers=headers,
            high_water_mark=high_water_mark,
        ),
    )
