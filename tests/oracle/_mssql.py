"""A throwaway SQL Server for the mssql driver's tests, in Docker.

``mssql_server`` (session scope) starts one container the first time a
test asks for it and removes it when the test process exits; containers
carry the ``pyfect.test=mssql`` label and their owner's pid, and those of
dead runs are removed first (``_docker``). Without Docker (or pytds), the
tests that need a server skip.

The image is ``mcr.microsoft.com/mssql/server:2022-latest`` (Effect's), or
on ARM hosts Azure SQL Edge, the SQL Server engine built for ARM: SQL
Server 2022 under x86 emulation stops at start (Rosetta has no
asynchronous I/O for it) or crawls (QEMU). ``PYFECT_MSSQL_IMAGE``
overrides the choice. ``sa`` logs in; as in Effect's container, the
database is ``master``.

SQL Server 2022 now and then exits within seconds of its start, before it serves, with
``CoInitializeSecurity failure. (HRESULT 0x800706b5)`` (RPC_S_SERVER_UNAVAILABLE) from its
platform layer, while the same image starts in the other jobs of the run (CI run
44897877038). So a container that exits before it serves is replaced, up to ``_START_ATTEMPTS``
containers within the one ``_STARTUP_TIMEOUT``, each replacement a ``ContainerRestarted``
warning. A container that runs but does not serve in time is not replaced.
"""

from __future__ import annotations

import atexit
import os
import platform
import subprocess
import time
import warnings
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import _container_images
import pytest

from pyfect import redacted

from . import _docker as _containers
from ._shared_server import SharedServer

SQL_SERVER_IMAGE = _container_images.image("mssql").local
EDGE_IMAGE = _container_images.image("mssql-edge").local
LABEL = "pyfect.test=mssql"
PASSWORD = "Pyfect_test_1!"
DATABASE = "master"
_STARTUP_TIMEOUT = 240.0
"""Seconds from the first ``docker run`` until a server serves, across every attempt."""
_START_ATTEMPTS = 3
"""Containers started at most, each after the one before exited before it served."""


class ContainerRestarted(UserWarning):
    """A SQL Server container exited before it served, and another was started."""


def image() -> str:
    chosen = os.environ.get("PYFECT_MSSQL_IMAGE")
    if chosen:
        return chosen
    return EDGE_IMAGE if platform.machine().lower() in ("arm64", "aarch64") else SQL_SERVER_IMAGE


@dataclass(frozen=True)
class MssqlServer:
    host: str
    port: int
    container: str
    username: str = "sa"
    database: str = DATABASE

    @property
    def password(self) -> redacted.Redacted[str]:
        return redacted.make(PASSWORD)

    def config(self, **fields: Any) -> Any:
        """The ``MssqlClientConfig`` of this server (``sa``, TLS with its
        own certificate trusted, as Effect's container client)."""
        from pyfect.sql import mssql

        defaults: dict[str, Any] = {
            "server": self.host,
            "port": self.port,
            "database": self.database,
            "username": self.username,
            "password": self.password,
            "trust_server": True,
        }
        return mssql.MssqlClientConfig(**(defaults | fields))


def _login(host: str, port: int, database: str = DATABASE, timeout: float = 5) -> Any:
    import pytds  # pyright: ignore[reportMissingTypeStubs]

    connect: Any = pytds.connect
    return connect(
        dsn=host,
        port=port,
        user="sa",
        password=PASSWORD,
        database=database,
        login_timeout=timeout,
        autocommit=True,
        disable_connect_retry=True,
    )


STARTING = """
SELECT
    (SELECT COUNT(*) FROM sys.databases WHERE state_desc <> 'ONLINE'),
    (SELECT COUNT(*) FROM sys.dm_exec_requests
        WHERE session_id <> @@SPID
        AND (wait_type = 'STARTUP_DEPENDENCY_MANAGER' OR wait_type LIKE 'LCK[_]%'))
"""
"""Databases not yet online, and requests still waiting on startup or on a lock. A first login
can succeed while ``msdb`` is still recovering, and for seconds after recovery system tasks and
logins wait on each other's metadata locks; a test's first statements then waited behind them
(1.9 s on a ``tempdb`` database lock, against a 5 s test timeout)."""


def _starting(connection: Any) -> str | None:
    """What the server is still doing after startup, or ``None`` once it has settled."""
    cursor = connection.cursor()
    cursor.execute(STARTING)
    offline, waiting = cursor.fetchall()[0]
    if offline or waiting:
        return f"{offline} databases not online, {waiting} requests waiting on startup or a lock"
    return None


def _waiting(server: MssqlServer) -> str | None:
    """What the server still lacks: a login for ``sa``, then the end of startup (``STARTING``)."""
    try:
        connection = _login(server.host, server.port)
    except Exception as error:
        return f"sa cannot log in yet: {type(error).__name__}: {error}"
    try:
        return _starting(connection)
    finally:
        connection.close()


def _wait_ready(server: MssqlServer, since: float) -> None:
    _containers.wait_ready(
        "SQL Server", server.container, lambda: _waiting(server), _STARTUP_TIMEOUT, 1, since=since
    )


def _start() -> MssqlServer:
    _containers.require_docker()
    _containers.reap_stale(LABEL)
    chosen = image()
    _containers.pull(chosen)
    since = time.monotonic()
    stopped: list[str] = []
    while True:
        try:
            return _start_container(chosen, since)
        except _containers.ContainerStopped as error:
            stopped.append(f"start {len(stopped) + 1}: {error}")
            if len(stopped) == _START_ATTEMPTS or time.monotonic() >= since + _STARTUP_TIMEOUT:
                raise _containers.ContainerStopped("\n".join(stopped)) from None
            warnings.warn(
                ContainerRestarted(f"starting another SQL Server container: {error}"),
                stacklevel=1,
            )


def _start_container(chosen: str, since: float) -> MssqlServer:
    started = _containers.docker(
        "run",
        "-d",
        "--label",
        LABEL,
        "--label",
        f"{_containers.OWNER}={os.getpid()}",
        "-p",
        "127.0.0.1::1433",
        "-e",
        "ACCEPT_EULA=Y",
        "-e",
        f"MSSQL_SA_PASSWORD={PASSWORD}",
        chosen,
    )
    if started.returncode != 0:
        raise _containers.ContainerFailed(f"cannot start SQL Server: {started.stderr.strip()}")
    container = started.stdout.strip()
    atexit.register(_containers.remove, container)
    try:
        server = MssqlServer("127.0.0.1", _containers.published_port(container, 1433), container)
        _wait_ready(server, since)
    except BaseException:
        _containers.remove(container)
        raise
    return server


SERVER = SharedServer[MssqlServer](
    "SQL Server", "pytds", (RuntimeError, OSError, subprocess.SubprocessError)
)


def server() -> MssqlServer:
    """The shared server, started on first use (``_shared_server``)."""
    return SERVER.get(_start)


@pytest.fixture(scope="session")
def mssql_server() -> MssqlServer:
    return server()


def query_now(
    sql: str, params: Sequence[object] = (), *, database: str = DATABASE
) -> list[tuple[Any, ...]]:
    """Run ``sql`` on its own connection (for test setup and checks): the
    rows of its last result set."""
    current = server()
    conn = _login(current.host, current.port, database)
    try:
        cursor = conn.cursor()
        cursor.execute(sql, tuple(params) or None)
        rows: list[tuple[Any, ...]] = []
        while True:
            if cursor.description is not None:
                rows = [tuple(row) for row in cursor.fetchall()]
            if not cursor.nextset():
                return rows
    finally:
        conn.close()


__all__ = [
    "EDGE_IMAGE",
    "LABEL",
    "SQL_SERVER_IMAGE",
    "ContainerRestarted",
    "MssqlServer",
    "image",
    "mssql_server",
    "query_now",
    "server",
]
