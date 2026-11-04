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
"""

from __future__ import annotations

import atexit
import os
import platform
import subprocess
import time
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import pytest

from pyfect import redacted

from . import _docker as _containers

SQL_SERVER_IMAGE = "mcr.microsoft.com/mssql/server:2022-latest"
EDGE_IMAGE = "mcr.microsoft.com/azure-sql-edge:latest"
LABEL = "pyfect.test=mssql"
PASSWORD = "Pyfect_test_1!"
DATABASE = "master"
_STARTUP_TIMEOUT = 240.0


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


def _wait_ready(server: MssqlServer) -> None:
    deadline = time.monotonic() + _STARTUP_TIMEOUT
    while True:
        try:
            _login(server.host, server.port).close()
        except Exception as error:
            running = _containers.docker(
                "inspect", "-f", "{{.State.Running}}", server.container
            ).stdout.strip()
            if running != "true":
                logs = _containers.docker("logs", "--tail", "20", server.container)
                raise RuntimeError(f"the SQL Server container stopped: {logs.stdout}") from error
            if time.monotonic() > deadline:
                raise RuntimeError("SQL Server did not start in time") from error
            time.sleep(1)
        else:
            return


def _start() -> MssqlServer:
    _containers.require_docker()
    _containers.reap_stale(LABEL)
    chosen = image()
    _containers.pull(chosen)
    started = _containers.docker(
        "run",
        "-d",
        "--rm",
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
        raise RuntimeError(f"cannot start SQL Server: {started.stderr.strip()}")
    container = started.stdout.strip()
    atexit.register(_containers.remove, container)
    try:
        server = MssqlServer("127.0.0.1", _containers.published_port(container, 1433), container)
        _wait_ready(server)
    except BaseException:
        _containers.remove(container)
        raise
    return server


class _Shared:
    server: MssqlServer | None = None
    reason: str | None = None


def server() -> MssqlServer:
    """The shared server, started on first use; skips the test when it
    cannot start."""
    if _Shared.server is None and _Shared.reason is None:
        try:
            import pytds  # noqa: F401  # pyright: ignore[reportUnusedImport, reportMissingTypeStubs]

            _Shared.server = _start()
        except (ImportError, RuntimeError, OSError, subprocess.SubprocessError) as error:
            _Shared.reason = f"no SQL Server: {error}"
    if _Shared.server is None:
        pytest.skip(_Shared.reason or "no SQL Server")
    return _Shared.server


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
    "MssqlServer",
    "image",
    "mssql_server",
    "query_now",
    "server",
]
