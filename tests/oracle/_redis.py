"""A throwaway Redis server for the redis-py tests.

``server()`` starts one ``redis-server`` (no persistence) in a temporary
directory the first time a test asks for it, on a free localhost port, and
stops it when the test process exits. Without the binary it runs the
``redis`` image in Docker instead (labelled like ``_mysql``'s containers, so
a crashed run's are reaped); without either (or redis-py), the tests that
need it skip. It never touches a server it did not start. ``flush()``
empties it between tests.
"""

from __future__ import annotations

import atexit
import os
import shutil
import socket
import subprocess
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

import _ports

from . import _docker as _containers
from ._shared_server import SharedServer

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


IMAGE = "redis:8.2-alpine"
LABEL = "pyfect.test=redis"


def _start_container() -> RedisServer:
    _containers.require_docker()
    _containers.reap_stale(LABEL)
    _containers.pull(IMAGE)
    started = _containers.docker(
        "run",
        "-d",
        "--rm",
        "--label",
        LABEL,
        "--label",
        f"{_containers.OWNER}={os.getpid()}",
        "-p",
        "127.0.0.1::6379",
        IMAGE,
        "redis-server",
        "--save",
        "",
        "--appendonly",
        "no",
    )
    if started.returncode != 0:
        raise RuntimeError(f"cannot start Redis: {started.stderr.strip()}")
    container = started.stdout.strip()
    atexit.register(_containers.remove, container)
    try:
        port = _containers.published_port(container, 6379)
        deadline = time.monotonic() + 30
        while not _ready(port):
            if time.monotonic() > deadline:
                raise RuntimeError("the Redis container did not start")
            time.sleep(0.05)
    except BaseException:
        _containers.remove(container)
        raise
    return RedisServer("127.0.0.1", port)


def _start() -> RedisServer:
    binary = _binary("redis-server")
    if binary is None:
        return _start_container()
    root = tempfile.mkdtemp(prefix="pyfect-redis-")
    port = _ports.reserved_port()
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


SERVER = SharedServer[RedisServer](
    "local Redis", "redis", (RuntimeError, OSError, subprocess.SubprocessError)
)


def server() -> RedisServer:
    """The shared server, started on first use (``_shared_server``)."""
    return SERVER.get(_start)


def flush() -> None:
    """Empty the shared server."""
    with socket.create_connection(("127.0.0.1", server().port), timeout=5) as connection:
        connection.sendall(b"FLUSHALL\r\n")
        assert connection.recv(16).startswith(b"+OK")
