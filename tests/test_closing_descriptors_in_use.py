"""Closing a file or socket waits for the operations still using its descriptor.

A descriptor's number is reused by the next ``open`` or ``socket`` once it is
closed. An operation that read the number before the close and calls the
system after it would read from, or write to, whatever took the number. Each
test here holds an operation at that point with an event, closes the owner,
lets something else take the lowest free number, and then lets the operation
go on: nothing may reach the newcomer.
"""

from __future__ import annotations

import asyncio
import os
import socket
import subprocess
import sys
import tempfile
import threading
from collections.abc import Buffer, Callable, Generator
from concurrent.futures import Future
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

import pyfect as fx
from pyfect import _blocking_pool
from pyfect._blocking_pool import BlockingPool
from pyfect.exit import Failure, Success
from pyfect.file_system import LiveFileSystem
from pyfect.http._asgi_listener import ListenOptions, make_listener
from pyfect.socket._loop import call_soon
from pyfect.socket.datagram._errors import DatagramSocketClosedError, DatagramSocketError
from pyfect.socket.datagram._live import _NativeSocket  # pyright: ignore[reportPrivateUsage]
from pyfect.socket.datagram._model import BackingAddress, BackingEvents
from pyfect.workers._process import _ProcessWorkerPort  # pyright: ignore[reportPrivateUsage]

_WAIT = 5.0
_CHILD_WAIT = 30.0


def _alone(body: Callable[[], None]) -> None:
    """Run ``body``, a function of this module, in a new Python process. Its
    newcomer must take the number a close freed, the lowest free one; in this
    process a thread another test left may open a descriptor in between."""
    child = subprocess.run(
        [sys.executable, "-W", "error::ResourceWarning", __file__, body.__name__],
        capture_output=True,
        text=True,
        timeout=_CHILD_WAIT,
        check=False,
    )
    assert child.returncode == 0, child.stderr


class _HeldPool:
    """The blocking pool, except that work submitted while ``holding`` waits
    until the test runs it: a thread of a busy pool may take it at any time,
    so also after work submitted later."""

    def __init__(self, pool: BlockingPool) -> None:
        self._pool = pool
        self.holding = False
        self.held: list[tuple[Callable[[], Any], Future[Any]]] = []

    def submit[A](self, thunk: Callable[[], A]) -> Future[A]:
        if not self.holding:
            return self._pool.submit(thunk)
        future: Future[A] = Future()
        self.held.append((thunk, future))
        return future

    def run_held(self) -> None:
        ((thunk, future),) = self.held
        self.held.clear()
        try:
            future.set_result(thunk())
        except Exception as error:  # the abandoned work's own failure
            future.set_exception(error)


@pytest.fixture
def held_pool(monkeypatch: pytest.MonkeyPatch) -> _HeldPool:
    held = _HeldPool(_blocking_pool.pool())
    monkeypatch.setattr(_blocking_pool._Shared, "pool", held)  # pyright: ignore[reportPrivateUsage]
    return held


class _Stalled(bytes):
    """Bytes whose buffer is handed over only once ``go`` is set: ``os.write``
    has read its descriptor by then and calls the system right after."""

    entered: threading.Event
    go: threading.Event

    def __buffer__(self, flags: int, /) -> memoryview:
        self.entered.set()
        assert self.go.wait(_WAIT)
        return memoryview(bytes(self))


def _stalled(data: bytes) -> _Stalled:
    stalled = _Stalled(data)
    stalled.entered = threading.Event()
    stalled.go = threading.Event()
    return stalled


@contextmanager
def _newcomer() -> Generator[tuple[socket.socket, socket.socket]]:
    """A socket pair opened now: it takes the lowest free numbers."""
    a, b = socket.socketpair()
    a.setblocking(False)
    b.setblocking(False)
    try:
        yield a, b
    finally:
        a.close()
        b.close()


def _received(pair: tuple[socket.socket, socket.socket]) -> dict[int, bytes]:
    """What each end of ``pair`` has waiting, by descriptor."""
    out: dict[int, bytes] = {}
    for end in pair:
        try:
            out[end.fileno()] = end.recv(64)
        except BlockingIOError:
            out[end.fileno()] = b""
    return out


# --- FileSystem.open ------------------------------------------------------


def _open_then(
    path: Path, flag: str, then: Callable[[Any], fx.Effect[Any, Any]]
) -> tuple[int, Any]:
    """Open ``path`` in a scope, run ``then`` on the file, close the scope;
    the descriptor the file had, and ``then``'s exit."""
    fs = LiveFileSystem()
    got: list[int] = []

    def use(file: Any) -> fx.Effect[Any, Any]:
        got.append(file.fd)
        return then(file).exit()

    exit = fx.run_blocking(fx.scoped(fs.open(str(path), flag=flag).flat_map(use)).or_die())  # pyright: ignore[reportArgumentType]
    return got[0], exit


def test_a_write_the_pool_starts_after_the_close_writes_nowhere():
    _alone(_a_write_the_pool_starts_after_the_close_writes_nowhere)


def _a_write_the_pool_starts_after_the_close_writes_nowhere() -> None:
    with tempfile.TemporaryDirectory() as tmp, pytest.MonkeyPatch.context() as patch:
        held_pool = _HeldPool(_blocking_pool.pool())
        patch.setattr(_blocking_pool._Shared, "pool", held_pool)  # pyright: ignore[reportPrivateUsage]
        _write_after_the_close(Path(tmp) / "log", held_pool)


def _write_after_the_close(path: Path, held_pool: _HeldPool) -> None:
    """The closed number is the lowest free one, so the newcomer takes it."""

    def write(file: Any) -> fx.Effect[Any, Any]:
        def hold() -> None:
            held_pool.holding = True

        def release() -> None:
            held_pool.holding = False

        abandoned = file.write(b"X").timeout("1 millis")
        return fx.sync(hold).and_then(abandoned).ensuring(fx.sync(release))

    fd, exit = _open_then(path, "a", write)
    assert isinstance(exit, Failure)  # the write was abandoned
    with _newcomer() as pair:
        assert fd in (pair[0].fileno(), pair[1].fileno()), "the number was not reused"
        held_pool.run_held()
        assert _received(pair) == {pair[0].fileno(): b"", pair[1].fileno(): b""}
    assert path.read_bytes() == b""


def test_a_write_in_progress_at_the_close_ends_before_the_descriptor_closes(
    tmp_path: Path, held_pool: _HeldPool
):
    path = tmp_path / "log"
    data = _stalled(b"X")
    running: list[threading.Thread] = []

    def write(file: Any) -> fx.Effect[Any, Any]:
        def hold(on: bool) -> None:
            held_pool.holding = on

        def start() -> None:
            # A pool thread takes the write; it has the descriptor's number
            # when the scope closes.
            thread = threading.Thread(target=held_pool.run_held)
            thread.start()
            running.append(thread)
            assert data.entered.wait(_WAIT)

        abandoned = file.write(data).timeout("1 millis").exit()
        return (
            fx.sync(lambda: hold(True))
            .and_then(abandoned)
            .ensuring(fx.sync(lambda: hold(False)))
            .tap(lambda _: fx.sync(start))
        )

    fd, exit = _open_then(path, "a", write)
    assert isinstance(exit, Success)
    with _newcomer() as pair:
        data.go.set()
        running[0].join(_WAIT)
        assert not running[0].is_alive()
        received = _received(pair)
        assert fd not in received, "the descriptor closed while a write still used it"
        assert received == {pair[0].fileno(): b"", pair[1].fileno(): b""}
    assert path.read_bytes() == b"X"


class _Window(socket.socket):
    """A socket whose sends stop between taking the descriptor's number and
    calling the system, as CPython's ``send`` / ``sendall`` read the number
    after letting go of the GIL: a close and an open on other threads fit in
    between. ``armed`` sends stop there until ``go`` is set."""

    armed = False
    entered: threading.Event
    go: threading.Event
    sent: threading.Event

    def arm(self) -> None:
        self.entered = threading.Event()
        self.go = threading.Event()
        self.sent = threading.Event()
        self.armed = True

    def _late(self, data: Buffer) -> int:
        number = self.fileno()
        self.entered.set()
        assert self.go.wait(_WAIT)
        try:
            return os.write(number, data)
        finally:
            self.sent.set()

    def send(self, data: Buffer, flags: int = 0, /) -> int:
        return self._late(data) if self.armed else super().send(data, flags)

    def sendall(self, data: Buffer, flags: int = 0, /) -> None:
        if self.armed:
            self._late(data)
        else:
            super().sendall(data, flags)


def _window_pair(kind: socket.SocketKind = socket.SOCK_STREAM) -> tuple[_Window, socket.socket]:
    ours, theirs = socket.socketpair(type=kind)
    return _Window(fileno=ours.detach()), theirs


# --- the ASGI servers' listening socket -------------------------------------


class _SlowToLetGo:
    """An ASGI engine (``_asgi_listener.Engine``) that serves on its socket
    and, told to exit, keeps it, cancelled or not, until ``let_go``; then
    closes its server, which takes the socket off the loop and closes it."""

    def __init__(self) -> None:
        self.started = False
        self._should_exit = False
        self.loop: asyncio.AbstractEventLoop | None = None
        self._exit: asyncio.Event | None = None
        self._let_go: asyncio.Event | None = None
        self.holding = threading.Event()
        self.done = threading.Event()

    @property
    def should_exit(self) -> bool:
        return self._should_exit

    @should_exit.setter
    def should_exit(self, value: bool) -> None:
        self._should_exit = value
        if value and self.loop is not None and self._exit is not None:
            self.loop.call_soon_threadsafe(self._exit.set)

    def let_go(self) -> None:
        assert self.loop is not None and self._let_go is not None
        self.loop.call_soon_threadsafe(self._let_go.set)

    async def serve(self, sockets: list[socket.socket]) -> None:
        self.loop = asyncio.get_running_loop()
        self._exit = asyncio.Event()
        self._let_go = asyncio.Event()
        server = await asyncio.start_server(_hang_up, sock=sockets[0])
        self.started = True
        try:
            await self._exit.wait()
            self.holding.set()
            while not self._let_go.is_set():
                try:
                    await self._let_go.wait()
                except asyncio.CancelledError:
                    continue
        finally:
            try:
                server.close()
            finally:
                self.done.set()


async def _hang_up(_reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    writer.close()


def test_a_listener_opened_while_the_old_server_lets_go_of_its_socket_accepts():
    engine = _SlowToLetGo()
    options: ListenOptions = {"host": "127.0.0.1", "disable_preemptive_shutdown": True}
    listener = make_listener(options, lambda _dispatch: engine)
    fx.run_blocking(fx.scoped(listener.as_(None)).or_die())
    assert engine.holding.is_set() and not engine.done.is_set()
    loop = engine.loop
    assert loop is not None
    accepted = threading.Event()

    async def accept(_reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        accepted.set()
        writer.close()

    newcomer = socket.create_server(("127.0.0.1", 0))
    started = asyncio.run_coroutine_threadsafe(asyncio.start_server(accept, sock=newcomer), loop)
    server = started.result(_WAIT)
    try:
        with socket.create_connection(newcomer.getsockname()[:2], timeout=_WAIT):
            assert accepted.wait(_WAIT), "the new listener never accepted"
    finally:
        engine.let_go()
        assert engine.done.wait(_WAIT)
        loop.call_soon_threadsafe(server.close)


# --- worker processes' channel ----------------------------------------------


class _Exited:
    """A ``subprocess.Popen`` whose process has exited."""

    def wait(self) -> int:
        return 0

    def kill(self) -> None:
        return None


def test_a_message_sent_while_the_worker_exits_goes_to_the_old_channel():
    ours, theirs = _window_pair()
    ours.arm()
    port = _ProcessWorkerPort(_Exited(), ours)  # pyright: ignore[reportArgumentType]
    port.post("late", ())
    assert ours.entered.wait(_WAIT)  # the writer thread has the number
    theirs.close()  # the worker exits: the reader thread closes the channel
    assert fx.run_blocking(port.exited.wait()) == 0
    with _newcomer() as pair:
        ours.go.set()
        assert ours.sent.wait(_WAIT)
        assert _received(pair) == {pair[0].fileno(): b"", pair[1].fileno(): b""}


# --- UDP sockets ------------------------------------------------------------


def _udp_pair() -> tuple[_Window, socket.socket]:
    peer = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    peer.bind(("127.0.0.1", 0))
    peer.setblocking(False)
    ours = _Window(socket.AF_INET, socket.SOCK_DGRAM)
    ours.bind(("127.0.0.1", 0))
    ours.connect(peer.getsockname())
    ours.setblocking(False)
    return ours, peer


def _ignore(*_: object) -> None:
    return None


def _on_the_loop() -> None:
    """Wait until the socket loop has run what was given to it before."""
    ran = threading.Event()
    call_soon(ran.set)
    assert ran.wait(_WAIT)


def test_a_datagram_sent_while_the_socket_closes_goes_to_the_old_peer():
    ours, peer = _udp_pair()
    events = BackingEvents(_ignore, _ignore, _ignore, _ignore)
    native = _NativeSocket(
        ours, events, {}, BackingAddress(*peer.getsockname()[:2]), connected=True
    )
    ours.arm()
    results: list[object] = []
    sender = threading.Thread(target=native.send, args=(b"late", None, results.append))
    sender.start()
    assert ours.entered.wait(_WAIT)
    native.close()
    _on_the_loop()
    with _newcomer() as pair:
        ours.go.set()
        sender.join(_WAIT)
        assert _received(pair) == {pair[0].fileno(): b"", pair[1].fileno(): b""}
    assert results == [None]
    assert peer.recv(64) == b"late"
    peer.close()


def test_a_datagram_sent_after_close_fails_as_closed():
    ours, peer = _udp_pair()
    events = BackingEvents(_ignore, _ignore, _ignore, _ignore)
    native = _NativeSocket(
        ours, events, {}, BackingAddress(*peer.getsockname()[:2]), connected=True
    )
    native.close()
    results: list[object] = []
    native.send(b"late", None, results.append)
    assert len(results) == 1 and isinstance(results[0], DatagramSocketError)
    assert isinstance(results[0].reason, DatagramSocketClosedError)
    peer.close()


def test_a_descriptor_this_process_opens_before_the_newcomer_does_not_take_its_number(
    monkeypatch: pytest.MonkeyPatch,
):
    """A thread another test left in the test process may open a descriptor
    between the close and the newcomer, and take the number the close freed."""
    taken: list[socket.socket] = []
    socketpair = socket.socketpair

    def after_another_open(*args: Any, **kwargs: Any) -> tuple[socket.socket, socket.socket]:
        taken.append(socket.socket())
        return socketpair(*args, **kwargs)

    monkeypatch.setattr(socket, "socketpair", after_another_open)
    try:
        test_a_write_the_pool_starts_after_the_close_writes_nowhere()
    finally:
        for sock in taken:
            sock.close()


if __name__ == "__main__":  # a body _alone runs
    unraisable: list[object] = []
    sys.unraisablehook = unraisable.append
    globals()[sys.argv[1]]()
    assert not unraisable, unraisable
