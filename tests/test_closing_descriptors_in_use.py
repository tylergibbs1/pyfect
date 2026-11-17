"""Closing a file or socket waits for the operations still using its descriptor.

A descriptor's number is reused by the next ``open`` or ``socket`` once it is
closed. An operation that read the number before the close and calls the
system after it would read from, or write to, whatever took the number. Each
test here holds an operation at that point with an event, closes the owner,
lets something else take the lowest free number, and then lets the operation
go on: nothing may reach the newcomer.
"""

from __future__ import annotations

import socket
import threading
from collections.abc import Callable, Iterator
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

_WAIT = 5.0


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
def _newcomer() -> Iterator[tuple[socket.socket, socket.socket]]:
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


def test_a_write_the_pool_starts_after_the_close_writes_nowhere(
    tmp_path: Path, held_pool: _HeldPool
):
    path = tmp_path / "log"

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
