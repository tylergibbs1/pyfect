"""A throwaway Redis server for the redis-py tests.

``server()`` starts one ``redis-server`` (no persistence) in a temporary
directory the first time a test asks for it, on a free localhost port, and
stops it when the test process exits; without the binary (or redis-py),
the tests that need it skip. It never touches a server it did not start.
``flush()`` empties it between tests.
"""

from __future__ import annotations

import atexit
import shutil
import socket
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

_SEARCH = ("/opt/homebrew/bin", "/usr/local/bin", "/usr/bin")


@dataclass(frozen=True)
class RedisServer:
    host: str
    port: int

    @property
    def url(self) -> str:
        return f"redis://{self.host}:{self.port}"


def _binary(name: str) -> str | None:
    found = shutil.which(name)
    if found is not None:
        return found
    for directory in _SEARCH:
        candidate = Path(directory) / name
        if candidate.exists():
            return str(candidate)
    return None


def free_port() -> int:
    """A localhost port nothing listens on."""
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _ready(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.2) as connection:
            connection.sendall(b"PING\r\n")
            return connection.recv(16).startswith(b"+PONG")
    except OSError:
        return False


def _stop(process: subprocess.Popen[bytes], root: str) -> None:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
    shutil.rmtree(root, ignore_errors=True)


def _start() -> RedisServer:
    binary = _binary("redis-server")
    if binary is None:
        raise RuntimeError("redis-server not found")
    root = tempfile.mkdtemp(prefix="pyfect-redis-")
    port = free_port()
    process = subprocess.Popen(
        [
            binary,
            "--port",
            str(port),
            "--bind",
            "127.0.0.1",
            "--dir",
            root,
            "--save",
            "",
            "--appendonly",
            "no",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    atexit.register(_stop, process, root)
    deadline = time.monotonic() + 10
    while not _ready(port):
        if process.poll() is not None or time.monotonic() > deadline:
            raise RuntimeError("redis-server did not start")
        time.sleep(0.02)
    return RedisServer("127.0.0.1", port)


class _Shared:
    server: RedisServer | None = None
    reason: str | None = None


def server() -> RedisServer:
    """The shared server, started on first use; skips the test when it
    cannot start."""
    if _Shared.server is None and _Shared.reason is None:
        try:
            import redis  # noqa: F401  # pyright: ignore[reportUnusedImport]

            _Shared.server = _start()
        except (ImportError, RuntimeError, OSError) as error:
            _Shared.reason = f"no local Redis: {error}"
    if _Shared.server is None:
        pytest.skip(_Shared.reason or "no local Redis")
    return _Shared.server


def flush() -> None:
    """Empty the shared server."""
    with socket.create_connection(("127.0.0.1", server().port), timeout=5) as connection:
        connection.sendall(b"FLUSHALL\r\n")
        assert connection.recv(16).startswith(b"+OK")
