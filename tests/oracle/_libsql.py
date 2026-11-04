"""A throwaway libSQL server (sqld) for the libsql driver's remote tests, in
Docker, as Effect's ``LibsqlContainer``.

``libsql_server`` (session scope) starts one container of
``ghcr.io/tursodatabase/libsql-server`` the first time a test asks for it
and removes it when the test process exits; containers carry the
``pyfect.test=libsql`` label and are reaped like the MySQL ones
(``_docker``). Without Docker (or httpx), the tests that need a server
skip. The server's one database starts empty and needs no token.
"""

from __future__ import annotations

import atexit
import os
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass

import pytest

from . import _docker as _containers

IMAGE = "ghcr.io/tursodatabase/libsql-server:main"
LABEL = "pyfect.test=libsql"
_STARTUP_TIMEOUT = 60.0


@dataclass(frozen=True)
class LibsqlServer:
    host: str
    port: int
    container: str

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"


def reap_stale() -> list[str]:
    """Remove the labelled containers whose owning process is gone."""
    return _containers.reap_stale(LABEL)


def _wait_ready(server: LibsqlServer) -> None:
    """Until the server answers HTTP (Effect's ``waitForServer``)."""
    deadline = time.monotonic() + _STARTUP_TIMEOUT
    while True:
        try:
            with urllib.request.urlopen(f"{server.url}/v2", timeout=5):
                return
        except urllib.error.HTTPError:
            return
        except OSError:
            if time.monotonic() > deadline:
                raise RuntimeError("the libSQL server did not start in time") from None
            time.sleep(0.25)


def _start() -> LibsqlServer:
    _containers.require_docker()
    reap_stale()
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
        "127.0.0.1::8080",
        "-e",
        "SQLD_NODE=primary",
        IMAGE,
        "sqld",
        "--no-welcome",
        "--http-listen-addr",
        "0.0.0.0:8080",
    )
    if started.returncode != 0:
        raise RuntimeError(f"cannot start the libSQL server: {started.stderr.strip()}")
    container = started.stdout.strip()
    atexit.register(_containers.remove, container)
    try:
        server = LibsqlServer("127.0.0.1", _containers.published_port(container, 8080), container)
        _wait_ready(server)
    except BaseException:
        _containers.remove(container)
        raise
    return server


class _Shared:
    server: LibsqlServer | None = None
    reason: str | None = None


def server() -> LibsqlServer:
    """The shared server, started on first use; skips the test when it
    cannot start."""
    if _Shared.server is None and _Shared.reason is None:
        try:
            import httpx  # noqa: F401  # pyright: ignore[reportUnusedImport]

            _Shared.server = _start()
        except (ImportError, RuntimeError, OSError, subprocess.SubprocessError) as error:
            _Shared.reason = f"no libSQL server: {error}"
    if _Shared.server is None:
        pytest.skip(_Shared.reason or "no libSQL server")
    return _Shared.server


@pytest.fixture(scope="session")
def libsql_server() -> LibsqlServer:
    return server()


__all__ = ["IMAGE", "LABEL", "LibsqlServer", "libsql_server", "reap_stale", "server"]
