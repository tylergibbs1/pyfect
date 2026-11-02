"""``make_from_backing_socket``: a ``DatagramSocket`` over a platform
socket.

The core owns the receive queue and its overflow strategy, reader
exclusivity, sticky errors, lazy address parsing, the writer latch and
destination formatting. Packets arrive from the adapter's thread into a
state read under a lock; a pull takes them in its own step and parks on a
``Signal`` until there is something to take, so an interrupt between a
wake-up and the take cannot lose packets.
"""

from __future__ import annotations

import contextlib
import threading
from collections import deque
from collections.abc import Callable, Generator, Mapping, Sequence
from ipaddress import IPv4Address
from typing import Any, Never, overload

from pyfect._context_effects import context, provide_context
from pyfect._core import Effect, Restore, uninterruptible_mask
from pyfect._fiber import Fiber
from pyfect._js import text_encode
from pyfect._os_wait import Resume, os_wait
from pyfect.context import Context
from pyfect.effect import fail, gen, succeed, suspend, sync, void
from pyfect.exit import Exit, Success
from pyfect.latch import Latch
from pyfect.net.net_address import (
    InetAddress,
    IpAddress,
    format_native_host,
    inet_address_from_native_unsafe,
    is_multicast,
)
from pyfect.scope import Scope, acquire_release
from pyfect.socket._connection import Signal
from pyfect.socket.datagram._errors import (
    DatagramSocketError,
    DatagramSocketWriteError,
    closed_error,
)
from pyfect.socket.datagram._model import (
    BackingAddress,
    BackingEvents,
    BackingSocket,
    Datagram,
    DatagramSocketService,
    Outgoing,
    Reader,
    ReceiveBuffer,
    ReceivedDatagram,
    Writer,
)

type Open[R] = Callable[[BackingEvents], Effect[BackingSocket, DatagramSocketError, R]]
type OnError = Callable[[DatagramSocketError], None]

_NO_SCOPE_IDS: Mapping[str, int] = {}


def _encode(payload: bytes | str) -> bytes:
    return text_encode(payload) if isinstance(payload, str) else payload


def _target_of(datagram: Outgoing) -> InetAddress | ReceivedDatagram | None:
    """Where a write goes: a received datagram keeps its raw sender address;
    a hand-built one gives its ``address``."""
    target = datagram if isinstance(datagram, Datagram) else datagram.address
    if isinstance(target, Datagram) and not isinstance(target, ReceivedDatagram):
        return target.address
    return target


class ReaderState:
    """One open socket: its receive queue, sticky failure and sends."""

    def __init__(self, buffer: ReceiveBuffer, listener: OnError | None) -> None:
        self.lock = threading.Lock()
        self.signal = Signal(self.lock)
        self.capacity = buffer.capacity
        self.sliding = buffer.strategy == "sliding"
        self.listener = listener
        self.events = BackingEvents(
            on_packet=self.push,
            on_read_error=self.fail,
            on_error=self.report,
            on_close=lambda: self.fail(closed_error()),
        )
        # Set once the open completes; packets can arrive before that.
        self.handle: BackingSocket | None = None
        self.failure: DatagramSocketError | None = None
        # Separate from ``failure``: after a sticky read error the socket is
        # still open, so ICMP reports still reach ``on_error``.
        self.closed = False
        self.queue: deque[ReceivedDatagram] = deque(maxlen=self.capacity if self.sliding else None)
        self.dropped = 0
        self.scope_ids: Mapping[str, int] = _NO_SCOPE_IDS

    # --- the adapter's side (any thread) -----------------------------------

    def push(self, payload: bytes, host: str, port: int) -> None:
        with self.lock:
            if self.failure is not None:
                return
            if len(self.queue) >= self.capacity:
                self.dropped += 1
                if not self.sliding:
                    return
            # A sliding queue's ``maxlen`` discards the oldest packet.
            self.queue.append(ReceivedDatagram(payload, host, port, self))
            waiters = self.signal.notify_locked()
        for wake in waiters:
            wake()

    def fail(self, error: DatagramSocketError) -> None:
        with self.lock:
            if self.failure is not None:
                return
            self.failure = error
            waiters = self.signal.notify_locked()
        for wake in waiters:
            wake()

    def report(self, error: DatagramSocketError) -> None:
        listener = self.listener
        if listener is None or self.closed:
            return
        # A listener cannot fail the platform's callback.
        with contextlib.suppress(Exception):
            listener(error)

    # --- the fibers' side --------------------------------------------------

    def opened(self, handle: BackingSocket) -> None:
        self.handle = handle
        self.scope_ids = handle.scope_ids

    def close(self) -> None:
        with self.lock:
            self.closed = True
            self.queue.clear()
            self.failure = closed_error()
            waiters = self.signal.notify_locked()
        for wake in waiters:
            wake()
        if self.handle is not None:
            self.handle.close()

    def pull(self) -> Effect[tuple[Datagram, ...], DatagramSocketError]:
        def take() -> Effect[tuple[Datagram, ...], DatagramSocketError]:
            with self.lock:
                if self.queue:
                    batch = tuple(self.queue)
                    self.queue.clear()
                    return succeed(batch)
                failure = self.failure
            if failure is not None:
                return fail(failure)
            return self.signal.wait(self._ready).and_then(pulling)

        pulling: Effect[tuple[Datagram, ...], DatagramSocketError] = suspend(take)
        return pulling

    def _ready(self) -> bool:
        return bool(self.queue) or self.failure is not None


class _Open:
    """A reader's state once its socket is open: what writes, the bound
    address and multicast joins use."""

    __slots__ = ("_bound", "_last_destination", "_last_target", "handle", "state")

    def __init__(self, state: ReaderState, handle: BackingSocket) -> None:
        self.state = state
        self.handle = handle
        self._bound: InetAddress | None = None
        self._last_target: InetAddress | None = None
        self._last_destination: BackingAddress | None = None

    @property
    def address(self) -> InetAddress:
        if self._bound is None:
            bound = self.handle.address
            self._bound = inet_address_from_native_unsafe(
                bound.host, bound.port, self.handle.scope_ids
            )
        return self._bound

    def write(self, datagram: Outgoing) -> Effect[None, DatagramSocketError]:
        failure = self.state.failure
        if failure is not None:
            return fail(failure)
        target = _target_of(datagram)
        destination = self._destination(target)
        if isinstance(destination, DatagramSocketError):
            return fail(destination)
        payload = _encode(datagram.payload)

        def register(resume: Resume[None, DatagramSocketError]) -> None:
            def done(error: DatagramSocketError | None) -> None:
                resume(void if error is None else fail(self._with_address(error, target)))

            self.handle.send(payload, destination, _once(done))

        return os_wait(register, waits_for="work")

    def write_all(self, datagrams: Sequence[Outgoing]) -> Effect[None, DatagramSocketError]:
        failure = self.state.failure
        if failure is not None:
            return fail(failure)
        if not datagrams:
            return void
        destinations: list[BackingAddress | None] = []
        for datagram in datagrams:
            destination = self._destination(_target_of(datagram))
            if isinstance(destination, DatagramSocketError):
                return fail(destination)
            destinations.append(destination)
        payloads = [_encode(datagram.payload) for datagram in datagrams]

        def register(resume: Resume[None, DatagramSocketError]) -> None:
            def done(error: DatagramSocketError | None, index: int | None = None) -> None:
                if error is None:
                    resume(void)
                elif index is None:
                    resume(fail(error))
                else:
                    resume(fail(self._with_address(error, _target_of(datagrams[index]))))

            self.handle.send_many(payloads, destinations, _once(done))

        return os_wait(register, waits_for="work")

    def _destination(
        self, target: InetAddress | ReceivedDatagram | None
    ) -> BackingAddress | DatagramSocketError | None:
        handle = self.handle
        if target is None:
            if handle.connected:
                return None
            return handle.peer or _rejection(
                "DatagramSocket write has no destination and the socket has no peer"
            )
        if isinstance(target, ReceivedDatagram):
            return None if handle.connected else BackingAddress(target.host, target.port)
        if handle.connected:
            return _rejection(
                "an explicit address cannot be used on a connected DatagramSocket", target
            )
        if target is self._last_target:
            return self._last_destination
        destination = BackingAddress(format_native_host(target, handle.scope_ids), target.port)
        self._last_target = target
        self._last_destination = destination
        return destination

    def _with_address(
        self, error: DatagramSocketError, target: InetAddress | ReceivedDatagram | None
    ) -> DatagramSocketError:
        reason = error.reason
        if not isinstance(reason, DatagramSocketWriteError) or reason.address is not None:
            return error
        address = self._address_of(target)
        if address is None:
            return error
        return DatagramSocketError(DatagramSocketWriteError(reason.kind, reason.cause, address))

    def _address_of(self, target: InetAddress | ReceivedDatagram | None) -> InetAddress | None:
        try:
            if isinstance(target, ReceivedDatagram):
                return target.address
            if target is not None:
                return target
            peer = self.handle.peer
            if peer is None:
                return None
            return inet_address_from_native_unsafe(peer.host, peer.port, self.handle.scope_ids)
        except ValueError:
            # An unknown IPv6 zone leaves the address out.
            return None


def _rejection(message: str, address: InetAddress | None = None) -> DatagramSocketError:
    return DatagramSocketError(DatagramSocketWriteError("Unknown", Exception(message), address))


def _once[**P](done: Callable[P, None]) -> Callable[P, None]:
    """``done``, ignoring every call after the first."""
    called = threading.Event()

    def call(*args: P.args, **kwargs: P.kwargs) -> None:
        if not called.is_set():
            called.set()
            done(*args, **kwargs)

    return call


class _StateReader:
    """The ``Reader`` of one open socket."""

    __slots__ = ("_open", "pull")

    def __init__(self, opened: _Open) -> None:
        self._open = opened
        self.pull = opened.state.pull()

    @property
    def address(self) -> InetAddress:
        return self._open.address

    def dropped(self) -> int:
        return self._open.state.dropped

    def join_multicast(
        self,
        group: IpAddress,
        *,
        interface: IPv4Address | int | None = None,
        source: IpAddress | None = None,
    ) -> Effect[None, DatagramSocketError, Scope]:
        if not is_multicast(group):
            raise ValueError(f"{group} is not a multicast address")
        state = self._open.state
        handle = self._open.handle

        def join() -> Effect[None, DatagramSocketError, Scope]:
            if state.failure is not None:
                return fail(state.failure)
            return acquire_release(
                handle.join_multicast(group, interface, source),
                lambda leave, _exit: void if state.closed else leave().ignore_cause(),
            ).as_void()

        return suspend(join)


@overload
def make_from_backing_socket(
    open: Open[Scope],
    *,
    receive_buffer: ReceiveBuffer | None = None,
    on_error: OnError | None = None,
) -> Effect[DatagramSocketService]: ...
@overload
def make_from_backing_socket[R](
    open: Open[R | Scope],
    *,
    receive_buffer: ReceiveBuffer | None = None,
    on_error: OnError | None = None,
) -> Effect[DatagramSocketService, Never, R]: ...
def make_from_backing_socket(
    open: Open[Any],
    *,
    receive_buffer: ReceiveBuffer | None = None,
    on_error: OnError | None = None,
) -> Effect[DatagramSocketService, Never, Any]:
    """A ``DatagramSocket`` that calls ``open`` for each reader acquisition.

    ``open`` gets the event callbacks before the socket exists and runs in
    the reader's scope, with the services of the fiber that built the
    socket (the acquiring fiber's own take precedence). If the acquisition
    is interrupted while ``open`` runs, the interruption returns at once,
    ``open`` is left to finish and the socket it gives is closed; the next
    reader waits until it has settled, so two sockets never exist at once.
    ``on_error`` gets errors no write is left to fail; what it raises is
    ignored."""
    buffer = receive_buffer or ReceiveBuffer()
    return context().map(lambda services: _build(open, services, buffer, on_error))


class _Shared:
    """Reader ownership and the state of the open reader, which writes use."""

    __slots__ = ("current", "free", "latch")

    def __init__(self) -> None:
        self.free = Latch(True)
        self.latch = Latch(False)
        self.current: _Open | None = None

    def abandon(self, state: ReaderState, opening: Fiber[BackingSocket, Any]) -> None:
        state.close()

        # Ownership is released only once the interrupted open settles.
        def settled(exit: Exit[BackingSocket, Any]) -> None:
            if isinstance(exit, Success):
                exit.value.close()
            self.free.open_unsafe()

        opening.add_observer_unsafe(settled)

    def release(self, state: ReaderState) -> None:
        state.close()
        self.current = None
        self.latch.close_unsafe()
        self.free.open_unsafe()


def _build(
    open: Open[Any],
    services: Context[Any],
    buffer: ReceiveBuffer,
    on_error: OnError | None,
) -> DatagramSocketService:
    shared = _Shared()

    def acquire(restore: Restore) -> Generator[Effect[Any, Any, Any], Any, Reader]:
        while not shared.free.close_unsafe():
            yield from restore(shared.free.wait())
        scope = yield from Scope()
        state = ReaderState(buffer, on_error)
        current: Context[Any] = yield from context()
        run_open = open(state.events).pipe(
            provide_context(services.merge(current).add(Scope, scope))
        )
        opening = yield from run_open.fork_daemon(start_immediately=True)
        handle: BackingSocket = yield from restore(opening.join()).on_error(
            lambda _: sync(lambda: shared.abandon(state, opening))
        )
        state.opened(handle)
        opened = _Open(state, handle)
        shared.current = opened
        shared.latch.open_unsafe()
        yield from scope.add_finalizer(lambda _: sync(lambda: shared.release(state)))
        return _StateReader(opened)

    reader: Effect[Reader, DatagramSocketError, Scope] = uninterruptible_mask(
        lambda restore: gen(lambda: acquire(restore))
    )

    def write(datagram: Outgoing) -> Effect[None, DatagramSocketError]:
        def start() -> Effect[None, DatagramSocketError]:
            state = shared.current
            if state is None:
                return shared.latch.when_open(write(datagram))
            return state.write(datagram)

        return suspend(start)

    def write_all(datagrams: Sequence[Outgoing]) -> Effect[None, DatagramSocketError]:
        def start() -> Effect[None, DatagramSocketError]:
            state = shared.current
            if state is None:
                return shared.latch.when_open(write_all(datagrams))
            return state.write_all(datagrams)

        return suspend(start)

    return DatagramSocketService(reader, succeed(Writer(write, write_all)))
