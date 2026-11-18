"""A throwaway ClickHouse server for the clickhouse driver's tests, in Docker.

``clickhouse_server`` (session scope) starts one container of
``clickhouse/clickhouse-server`` the first time a test asks for it and
removes it when the test process exits; containers carry the
``pyfect.test=clickhouse`` label and are reaped like the MySQL ones
(``_docker``). Without Docker (or httpx), the tests that need a server
skip. The user ``pyfect`` (password ``pyfect``) owns the ``default``
database; ``query_now`` runs a statement over HTTP without pyfect. The
server also answers HTTPS (``https_url``) with the ``fixtures/tls``
certificate, and lets ``pyfect_cert`` in with that certificate as a client
certificate (``fixtures/clickhouse-tls``).
"""

from __future__ import annotations

import atexit
import base64
import os
import subprocess
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import _container_images
import pytest

from . import _docker as _containers
from ._shared_server import SharedServer

IMAGE = _container_images.image("clickhouse").local
LABEL = "pyfect.test=clickhouse"
USER = "pyfect"
PASSWORD = "pyfect"
CERT_USER = "pyfect_cert"
_STARTUP_TIMEOUT = 120.0
FIXTURES = Path(__file__).parent / "fixtures"
TLS = FIXTURES / "tls"
_TLS_CONFIG = FIXTURES / "clickhouse-tls"


@dataclass(frozen=True)
class ClickhouseServer:
    host: str
    port: int
    container: str
    https_port: int = 0

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def https_url(self) -> str:
        return f"https://{self.host}:{self.https_port}"


def reap_stale() -> list[str]:
    """Remove the labelled containers whose owning process is gone."""
    return _containers.reap_stale(LABEL)


def _request(server: ClickhouseServer, sql: str) -> str:
    token = base64.b64encode(f"{USER}:{PASSWORD}".encode()).decode()
    request = urllib.request.Request(
        f"{server.url}/", data=sql.encode(), headers={"Authorization": f"Basic {token}"}
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read().decode()


def _waiting(server: ClickhouseServer) -> str | None:
    """``None`` once the server runs queries for ``pyfect``."""
    try:
        _request(server, "SELECT 1")
    except (OSError, urllib.error.HTTPError) as error:
        return f"no query runs yet: {type(error).__name__}: {error}"
    return None


def _wait_ready(server: ClickhouseServer) -> None:
    _containers.wait_ready(
        "ClickHouse server", server.container, lambda: _waiting(server), _STARTUP_TIMEOUT, 0.25
    )


def _start() -> ClickhouseServer:
    _containers.require_docker()
    reap_stale()
    _containers.pull(IMAGE)
    started = _containers.docker(
        "run",
        "-d",
        "--label",
        LABEL,
        "--label",
        f"{_containers.OWNER}={os.getpid()}",
        "--ulimit",
        "nofile=262144:262144",
        "-p",
        "127.0.0.1::8123",
        "-p",
        "127.0.0.1::8443",
        "-v",
        f"{_TLS_CONFIG / 'tls.xml'}:/etc/clickhouse-server/config.d/tls.xml:ro",
        "-v",
        f"{_TLS_CONFIG / 'cert_user.xml'}:/etc/clickhouse-server/users.d/cert_user.xml:ro",
        "-v",
        f"{TLS}:/etc/clickhouse-server/tls:ro",
        "-e",
        f"CLICKHOUSE_USER={USER}",
        "-e",
        f"CLICKHOUSE_PASSWORD={PASSWORD}",
        "-e",
        "CLICKHOUSE_DEFAULT_ACCESS_MANAGEMENT=1",
        IMAGE,
    )
    if started.returncode != 0:
        raise _containers.ContainerFailed(
            f"cannot start the ClickHouse server: {started.stderr.strip()}"
        )
    container = started.stdout.strip()
    atexit.register(_containers.remove, container)
    try:
        server = ClickhouseServer(
            "127.0.0.1",
            _containers.published_port(container, 8123),
            container,
            _containers.published_port(container, 8443),
        )
        _wait_ready(server)
    except BaseException:
        _containers.remove(container)
        raise
    return server


SERVER = SharedServer[ClickhouseServer](
    "ClickHouse server", "httpx", (RuntimeError, OSError, subprocess.SubprocessError)
)


def server() -> ClickhouseServer:
    """The shared server, started on first use (``_shared_server``)."""
    return SERVER.get(_start)


def query_now(sql: str) -> str:
    """Run ``sql`` on the shared server as ``pyfect``; its body."""
    return _request(server(), sql)


@pytest.fixture(scope="session")
def clickhouse_server() -> ClickhouseServer:
    return server()


__all__ = [
    "CERT_USER",
    "IMAGE",
    "LABEL",
    "PASSWORD",
    "TLS",
    "USER",
    "ClickhouseServer",
    "clickhouse_server",
    "query_now",
    "reap_stale",
    "server",
]
