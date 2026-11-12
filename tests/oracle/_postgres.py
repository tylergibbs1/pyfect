"""A throwaway PostgreSQL server for the pg driver's tests.

``pg_server`` (session scope) starts one with ``initdb`` and ``pg_ctl`` in
a temporary directory the first time a test asks for it, and stops it when
the test process exits, however it exits (``_pg_owner``). Starting one first
reaps the servers whose owning process is gone, and never touches one whose
owner is alive. Without the binaries (or psycopg), the tests that need it
skip.

TCP connections authenticate with SCRAM (user ``postgres``, password
``postgres``); the Unix socket in ``socket_dir`` trusts everyone.
"""

from __future__ import annotations

import atexit
import contextlib
import os
import shutil
import socket
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import _ports
import pytest

import pyfect as fx
from pyfect import redacted

from . import _pg_owner

if TYPE_CHECKING:
    from pyfect.sql.pg.connection import PgConnection

_SEARCH = ("/opt/homebrew/bin", "/usr/local/bin", "/usr/lib/postgresql/17/bin")
PASSWORD = "postgres"


@dataclass(frozen=True)
class PgServer:
    host: str
    port: int
    socket_dir: str
    data_dir: str

    @property
    def uri(self) -> str:
        return f"postgres://postgres:{PASSWORD}@{self.host}:{self.port}/postgres"

    @property
    def url(self) -> redacted.Redacted[str]:
        return redacted.make(self.uri)


def _binary(name: str) -> str | None:
    found = shutil.which(name)
    if found is not None:
        return found
    for directory in _SEARCH:
        candidate = Path(directory) / name
        if candidate.exists():
            return str(candidate)
    return None


class _Shared:
    server: PgServer | None = None
    reason: str | None = None
    watchdog: subprocess.Popen[bytes] | None = None


def _stop(root: Path, watchdog: subprocess.Popen[bytes]) -> None:
    _pg_owner.stop_server(root)
    if watchdog.stdin is not None:
        watchdog.stdin.close()
    watchdog.wait()


def _start() -> PgServer:
    initdb, pg_ctl = _binary("initdb"), _binary("pg_ctl")
    if initdb is None or pg_ctl is None:
        raise RuntimeError("initdb / pg_ctl not found")
    _pg_owner.reap(Path(tempfile.gettempdir()))
    root = tempfile.mkdtemp(prefix=_pg_owner.PREFIX)
    _pg_owner.claim(Path(root))
    _Shared.watchdog = _pg_owner.watch(Path(root))
    atexit.register(_stop, Path(root), _Shared.watchdog)
    data_dir = os.path.join(root, "data")
    password_file = os.path.join(root, "password")
    Path(password_file).write_text(PASSWORD)
    subprocess.run(
        [
            initdb,
            "-D",
            data_dir,
            "-U",
            "postgres",
            "--auth-local=trust",
            "--auth-host=scram-sha-256",
            f"--pwfile={password_file}",
            "-E",
            "UTF8",
            "--no-sync",
        ],
        capture_output=True,
        check=True,
    )
    port = _ports.reserved_port()
    options = f"-p {port} -k {root} -c listen_addresses=127.0.0.1 -c fsync=off"
    subprocess.run(
        [pg_ctl, "-D", data_dir, "-l", os.path.join(root, "log"), "-o", options, "-w", "start"],
        capture_output=True,
        check=True,
    )
    return PgServer("127.0.0.1", port, root, data_dir)


def server() -> PgServer:
    """The shared server, started on first use; skips the test when it
    cannot start."""
    if _Shared.server is None and _Shared.reason is None:
        try:
            import psycopg  # noqa: F401  # pyright: ignore[reportUnusedImport]

            _Shared.server = _start()
        except (ImportError, RuntimeError, subprocess.CalledProcessError, OSError) as error:
            _Shared.reason = f"no local PostgreSQL: {error}"
    if _Shared.server is None:
        pytest.skip(_Shared.reason or "no local PostgreSQL")
    return _Shared.server


@pytest.fixture(scope="session")
def pg_server() -> PgServer:
    return server()


def query_now(sql: str) -> list[tuple[object, ...]]:
    """Run ``sql`` on a fresh blocking connection (for test setup)."""
    import psycopg

    with psycopg.connect(server().uri, autocommit=True) as conn:
        cursor = conn.execute(sql.encode())
        return cursor.fetchall() if cursor.description is not None else []


class ClosingListener:
    """A TCP port that accepts connections and closes them at once; counts
    the connections it saw. Stands in for Effect's failing ``stream``
    factories."""

    def __init__(self) -> None:
        import threading

        self._socket = socket.socket()
        self._socket.bind(("127.0.0.1", 0))
        self._socket.listen()
        self.port: int = self._socket.getsockname()[1]
        self.connections = 0
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self) -> None:
        while True:
            try:
                conn, _ = self._socket.accept()
            except OSError:
                return
            self.connections += 1
            conn.close()

    def close(self) -> None:
        self._socket.close()


@pytest.fixture
def closing_listener():
    listener = ClosingListener()
    yield listener
    listener.close()


def refused_port() -> int:
    """A local port that refuses connections."""
    return _ports.refused_tcp_port()


_CANCEL_REQUEST = (16).to_bytes(4) + (80877102).to_bytes(4)


class CancelGate:
    """A TCP proxy to ``server`` that holds back PostgreSQL cancel requests
    until ``release()`` (Effect's ``LateCancelProxy``): the client sees its
    cancel sent at once, the server gets it late. ``intercepted`` is set
    when a cancel arrives, ``delivered`` once the server took it.
    ``pause()`` stops forwarding anything, as a server that stops
    answering, until ``resume()``; ``accepted`` counts the connections it
    took (cancel requests aside)."""

    def __init__(self, server: PgServer) -> None:
        import threading

        self._server = server
        self._socket = socket.socket()
        self._socket.bind(("127.0.0.1", 0))
        self._socket.listen()
        self.port: int = self._socket.getsockname()[1]
        self.intercepted = threading.Event()
        self.delivered = threading.Event()
        self._released = threading.Event()
        self._flowing = threading.Event()
        self._flowing.set()
        self.accepted = 0
        self._ends: list[socket.socket] = []
        self._pumps: list[threading.Thread] = []
        self._thread = threading.Thread
        self._thread(target=self._serve, daemon=True).start()

    @property
    def url(self) -> redacted.Redacted[str]:
        return redacted.make(f"postgres://postgres:{PASSWORD}@127.0.0.1:{self.port}/postgres")

    def release(self) -> None:
        self._released.set()

    def pause(self) -> None:
        self._flowing.clear()

    def resume(self) -> None:
        self._flowing.set()

    def _serve(self) -> None:
        while True:
            try:
                client, _ = self._socket.accept()
            except OSError:
                return
            self._thread(target=self._handle, args=(client,), daemon=True).start()

    def _handle(self, client: socket.socket) -> None:
        head = _read_exactly(client, 8)
        if head == _CANCEL_REQUEST:
            request = head + _read_exactly(client, 8)
            client.close()
            self.intercepted.set()
            self._released.wait()
            with socket.create_connection((self._server.host, self._server.port)) as backend:
                backend.sendall(request)
                while backend.recv(1024):
                    pass
            self.delivered.set()
            return
        backend = socket.create_connection((self._server.host, self._server.port))
        self._ends += [client, backend]
        self.accepted += 1
        backend.sendall(head)
        pump = self._thread(target=self._pump, args=(backend, client), daemon=True)
        self._pumps.append(pump)
        pump.start()
        self._pump(client, backend)

    def _pump(self, source: socket.socket, target: socket.socket) -> None:
        try:
            while chunk := source.recv(65536):
                self._flowing.wait()
                if self._closed:
                    break
                target.sendall(chunk)
        except OSError:
            pass
        finally:
            for end in (source, target):
                with contextlib.suppress(OSError):
                    end.shutdown(socket.SHUT_RDWR)

    _closed = False

    def close(self) -> None:
        self._closed = True
        self._released.set()
        self._flowing.set()
        self._socket.close()
        for end in self._ends:
            with contextlib.suppress(OSError):
                end.shutdown(socket.SHUT_RDWR)
        for pump in self._pumps:
            pump.join(5)
        for end in self._ends:
            end.close()


def _read_exactly(conn: socket.socket, size: int) -> bytes:
    data = b""
    while len(data) < size:
        chunk = conn.recv(size - len(data))
        if not chunk:
            break
        data += chunk
    return data


@pytest.fixture
def cancel_gate(pg_server: PgServer):
    gate = CancelGate(pg_server)
    yield gate
    gate.close()


def wait_until_active(
    observer: PgConnection, pid: int, advisory_lock: bool = False
) -> fx.Effect[None, Any]:
    """Poll ``pg_stat_activity`` until backend ``pid`` runs a statement
    (blocked on an advisory lock, with ``advisory_lock``)."""

    def body():
        started = time.monotonic()
        while time.monotonic() - started < 10:
            result = yield from observer.query(
                "SELECT count(*)::int4 AS active FROM pg_stat_activity"
                " WHERE pid = $1 AND state = 'active'"
                " AND (NOT $2::boolean OR (wait_event_type = 'Lock' AND wait_event = 'advisory'))",
                [pid, advisory_lock],
            )
            if result.rows[0]["active"] == 1:
                return
            yield from fx.sleep("10 millis")
        raise AssertionError(f"PostgreSQL backend {pid} did not become active within 10 seconds")

    return fx.gen(body)


def wait_until_advisory_lock(observer: PgConnection, pid: int) -> fx.Effect[None, Any]:
    return wait_until_active(observer, pid, True)


__all__ = [
    "PASSWORD",
    "CancelGate",
    "ClosingListener",
    "PgServer",
    "cancel_gate",
    "closing_listener",
    "pg_server",
    "query_now",
    "refused_port",
    "server",
    "wait_until_active",
    "wait_until_advisory_lock",
]
