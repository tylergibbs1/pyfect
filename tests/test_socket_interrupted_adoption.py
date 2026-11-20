"""A fiber interrupted while ``from_socket`` hands its socket to the socket loop leaves no
descriptor open.

The loop watches a duplicate of the caller's socket. It was made on the fiber before the loop
was asked to adopt it, so an interrupt that landed before the loop started the adoption left
the duplicate open for good: nothing owned it, and the reader's scope closed only the caller's
socket."""

from __future__ import annotations

import asyncio
import socket
import threading
from collections.abc import Callable, Iterator
from typing import Any

import pytest

import pyfect as fx
from pyfect.exit import Failure
from pyfect.scope import scoped
from pyfect.socket import SocketService, from_socket


@fx.fn
def _open_reader(sock: SocketService):
    yield from sock.reader


def _socket_loop() -> asyncio.AbstractEventLoop:
    """The loop adopted sockets run on, seen from inside an adoption."""
    seen: list[asyncio.AbstractEventLoop] = []
    original = asyncio.BaseEventLoop.connect_accepted_socket

    async def adopt(self: asyncio.BaseEventLoop, *args: Any, **kwargs: Any) -> Any:
        seen.append(self)
        return await original(self, *args, **kwargs)

    ours, peer = socket.socketpair()
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(asyncio.BaseEventLoop, "connect_accepted_socket", adopt)
        fx.run_blocking(scoped(_open_reader(from_socket(fx.succeed(ours)))).or_die())
    peer.close()
    return seen[0]


@pytest.fixture
def duplicates(monkeypatch: pytest.MonkeyPatch) -> Iterator[list[socket.socket]]:
    made: list[socket.socket] = []
    original = socket.socket.dup

    def dup(self: socket.socket) -> socket.socket:
        duplicate = original(self)
        made.append(duplicate)
        return duplicate

    monkeypatch.setattr(socket.socket, "dup", dup)
    yield made
    for duplicate in made:
        duplicate.close()


def _held(
    loop: asyncio.AbstractEventLoop, released: threading.Event, patch: pytest.MonkeyPatch
) -> threading.Event:
    """Hold ``loop`` until ``released`` is set; the event returned is set once something
    is next handed to the loop from another thread."""
    handed = threading.Event()
    original: Callable[..., Any] = loop.call_soon_threadsafe

    def call_soon_threadsafe(*args: Any, **kwargs: Any) -> Any:
        handed.set()
        return original(*args, **kwargs)

    original(lambda: released.wait(10))
    patch.setattr(loop, "call_soon_threadsafe", call_soon_threadsafe)
    return handed


def test_an_adoption_interrupted_before_the_loop_starts_it_leaves_no_descriptor_open(
    duplicates: list[socket.socket], monkeypatch: pytest.MonkeyPatch
) -> None:
    loop = _socket_loop()
    duplicates.clear()
    ours, peer = socket.socketpair()
    released = threading.Event()
    handed = _held(loop, released, monkeypatch)

    @fx.gen
    def program():
        fiber = yield from scoped(_open_reader(from_socket(fx.succeed(ours)))).fork()
        # The fiber has asked the held loop to adopt the socket.
        yield from fx.blocking(handed.wait)
        yield from fx.sync(lambda: fiber.interrupt_as_unsafe(None))
        yield from fx.sync(released.set)
        return (yield from fiber.await_exit())

    try:
        exit = fx.run_blocking(program.timeout("10 seconds").or_die())
    finally:
        released.set()
        monkeypatch.undo()
        peer.close()
    assert isinstance(exit, Failure) and exit.cause.has_interrupts_only
    assert ours.fileno() == -1
    assert [duplicate for duplicate in duplicates if duplicate.fileno() != -1] == []
