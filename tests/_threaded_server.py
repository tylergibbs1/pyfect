"""Test servers on threads, closed in the one safe order.

``serving(handle)`` accepts connections on a thread and runs ``handle(conn, stopping)`` for each
on a thread of its own. A connection's socket is closed only by its own thread, after
``handle`` returns. Leaving the ``with`` block stops accepting, sets ``stopping``, shuts every
open connection down (which wakes a thread blocked on it but keeps its descriptor), waits for
every handler thread to end, and only then closes the listener.

Closing a socket while another thread is still inside a call on it frees its descriptor number
for the next socket the process opens, and the thread then reads from and writes to that
unrelated socket: OpenSSL keeps the number it was given, so a TLS server thread whose peer
hung up wrote its alert into a later test's connection. tests/test_threaded_server_guard.py
makes server threads that accept connections use this module.
"""

from __future__ import annotations

import contextlib
import select
import socket
import ssl
import threading
from collections.abc import Callable, Generator
from contextlib import contextmanager

type Handler = Callable[[socket.socket, threading.Event], None]
"""Serves one connection (a TLS socket, its handshake done, when the server has a context);
``stopping`` is set once the server is closing. It may return at any time: its connection is
then closed."""


class Server:
    """A running ``serving`` server."""

    def __init__(
        self,
        listener: socket.socket,
        handle: Handler,
        tls: ssl.SSLContext | None,
        join_seconds: float,
    ) -> None:
        self._listener = listener
        self._join_seconds = join_seconds
        self._handle = handle
        self._tls = tls
        self._lock = threading.Lock()
        self._open: set[socket.socket] = set()
        self._threads: list[threading.Thread] = []
        self._wake, self._woken = socket.socketpair()
        self.stopping = threading.Event()
        self.connected = threading.Event()
        """Set once a connection is being served."""
        host, port = listener.getsockname()[:2]
        self.address: tuple[str, int] = (host, port)
        self.port: int = port
        self._acceptor = threading.Thread(
            target=self._accept, name=f"test-server-{port}", daemon=True
        )
        self._acceptor.start()

    def drop(self) -> None:
        """Shut down every open connection now, as a server that hangs up on its clients."""
        with self._lock:
            for conn in self._open:
                _shut_down(conn)

    def _accept(self) -> None:
        while True:
            readable, _, _ = select.select([self._listener, self._woken], [], [])
            if self._woken in readable:
                return
            try:
                conn, _ = self._listener.accept()
            except OSError:
                continue
            thread = threading.Thread(
                target=self._serve, args=(conn,), name=f"test-server-{self.port}", daemon=True
            )
            with self._lock:
                self._threads.append(thread)
            thread.start()

    def _serve(self, conn: socket.socket) -> None:
        with self._lock:
            if self.stopping.is_set():
                conn.close()
                return
            if self._tls is not None:
                conn = self._tls.wrap_socket(conn, server_side=True, do_handshake_on_connect=False)
            self._open.add(conn)
        self.connected.set()
        try:
            with contextlib.suppress(OSError):
                if isinstance(conn, ssl.SSLSocket):
                    conn.do_handshake()
                self._handle(conn, self.stopping)
        finally:
            with self._lock:
                self._open.discard(conn)
            conn.close()

    def close(self) -> None:
        self._wake.send(b"x")
        self._acceptor.join()
        with self._lock:
            self.stopping.set()
            threads = list(self._threads)
            for conn in self._open:
                _shut_down(conn)
        for thread in threads:
            thread.join(self._join_seconds)
        stuck = [thread.name for thread in threads if thread.is_alive()]
        self._wake.close()
        self._woken.close()
        self._listener.close()
        assert not stuck, f"handler threads still running after shutdown: {stuck}"


def _shut_down(conn: socket.socket) -> None:
    # socket.socket's own shutdown: SSLSocket.shutdown also drops the SSL object, under a
    # thread that may be using it.
    with contextlib.suppress(OSError):
        socket.socket.shutdown(conn, socket.SHUT_RDWR)


@contextmanager
def serving(
    handle: Handler,
    *,
    tls: ssl.SSLContext | None = None,
    listener: socket.socket | None = None,
    join_seconds: float = 10.0,
) -> Generator[Server]:
    """A server on ``listener`` (a new one on a free local port when ``None``), closed when
    the block ends; closing fails if a handler is still running ``join_seconds`` after its
    connection was shut down."""
    server = Server(listener or socket.create_server(("127.0.0.1", 0)), handle, tls, join_seconds)
    try:
        yield server
    finally:
        server.close()


def hold(conn: socket.socket, stopping: threading.Event) -> None:
    """Keep the connection open, reading nothing, until the server closes."""
    stopping.wait()


def drain(conn: socket.socket, stopping: threading.Event) -> None:
    """Read and drop what the client sends until it hangs up or the server closes."""
    while conn.recv(65536):
        pass
