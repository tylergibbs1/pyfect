"""A throwaway MySQL server for the mysql driver's tests, in Docker.

``mysql_server`` (session scope) starts one container of the official
``mysql`` image the first time a test asks for it and removes it when the
test process exits. Containers carry the ``pyfect.test=mysql`` label and
the pid of the process that started them; a session first removes the
labelled containers of processes that are gone (a crashed run), so none
outlive their session for long. Without Docker (or asyncmy), the tests
that need a server skip.

The database ``test`` is empty at start; ``root`` (password ``root``) and
``test`` (password ``test``, all privileges on ``test``) can log in.
"""

from __future__ import annotations

import atexit
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from typing import Any

import pytest

from pyfect import redacted

IMAGE = "mysql:lts"
LABEL = "pyfect.test=mysql"
_OWNER = "pyfect.test.owner"
_STARTUP_TIMEOUT = 180.0


@dataclass(frozen=True)
class MysqlServer:
    host: str
    port: int
    container: str

    def uri(self, root: bool = False) -> str:
        user = "root:root" if root else "test:test"
        return f"mysql://{user}@{self.host}:{self.port}/test"

    @property
    def url(self) -> redacted.Redacted[str]:
        return redacted.make(self.uri())

    @property
    def root_url(self) -> redacted.Redacted[str]:
        return redacted.make(self.uri(root=True))


def _docker(*args: str, timeout: float = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=False, timeout=timeout
    )


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def reap_stale() -> list[str]:
    """Remove the labelled containers whose owning process is gone."""
    listed = _docker(
        "ps",
        "-a",
        "--filter",
        f"label={LABEL}",
        "--format",
        f'{{{{.ID}}}} {{{{.Label "{_OWNER}"}}}}',
    )
    stale: list[str] = []
    for line in listed.stdout.splitlines():
        container, _, owner = line.partition(" ")
        if not owner.isdigit() or not _alive(int(owner)):
            stale.append(container)
    if stale:
        _docker("rm", "-f", "-v", *stale)
    return stale


def _remove(container: str) -> None:
    _docker("rm", "-f", "-v", container)


def _port(container: str) -> int:
    mapped = _docker("port", container, "3306/tcp").stdout.split()
    if not mapped:
        raise RuntimeError("the MySQL container published no port")
    return int(mapped[0].rsplit(":", 1)[1])


def _wait_ready(server: MysqlServer) -> None:
    """Until ``test`` can log in over TCP: the image's init server listens
    on no port, so a TCP login means the final server is up."""
    deadline = time.monotonic() + _STARTUP_TIMEOUT
    while True:
        probe = _docker(
            "exec",
            server.container,
            "mysql",
            "--protocol=TCP",
            "-h127.0.0.1",
            "-utest",
            "-ptest",
            "-e",
            "SELECT 1",
            "test",
            timeout=30,
        )
        if probe.returncode == 0:
            return
        state = _docker("inspect", "-f", "{{.State.Running}}", server.container).stdout.strip()
        if state != "true":
            raise RuntimeError(f"the MySQL container stopped: {probe.stderr.strip()}")
        if time.monotonic() > deadline:
            raise RuntimeError("MySQL did not start in time")
        time.sleep(0.5)


def _start() -> MysqlServer:
    if shutil.which("docker") is None:
        raise RuntimeError("docker not found")
    if _docker("info", "--format", "{{.ServerVersion}}").returncode != 0:
        raise RuntimeError("the Docker daemon is not running")
    reap_stale()
    if _docker("image", "inspect", IMAGE).returncode != 0:
        pulled = _docker("pull", IMAGE, timeout=600)
        if pulled.returncode != 0:
            raise RuntimeError(f"cannot pull {IMAGE}: {pulled.stderr.strip()}")
    started = _docker(
        "run",
        "-d",
        "--rm",
        "--label",
        LABEL,
        "--label",
        f"{_OWNER}={os.getpid()}",
        "-p",
        "127.0.0.1::3306",
        "--tmpfs",
        "/var/lib/mysql",
        "-e",
        "MYSQL_ROOT_PASSWORD=root",
        "-e",
        "MYSQL_ROOT_HOST=%",
        "-e",
        "MYSQL_DATABASE=test",
        "-e",
        "MYSQL_USER=test",
        "-e",
        "MYSQL_PASSWORD=test",
        IMAGE,
        "--innodb-flush-log-at-trx-commit=0",
        "--skip-log-bin",
    )
    if started.returncode != 0:
        raise RuntimeError(f"cannot start MySQL: {started.stderr.strip()}")
    container = started.stdout.strip()
    atexit.register(_remove, container)
    try:
        server = MysqlServer("127.0.0.1", _port(container), container)
        _wait_ready(server)
    except BaseException:
        _remove(container)
        raise
    return server


class _Shared:
    server: MysqlServer | None = None
    reason: str | None = None


def server() -> MysqlServer:
    """The shared server, started on first use; skips the test when it
    cannot start."""
    if _Shared.server is None and _Shared.reason is None:
        try:
            import asyncmy  # noqa: F401  # pyright: ignore[reportUnusedImport]

            _Shared.server = _start()
        except (ImportError, RuntimeError, OSError, subprocess.SubprocessError) as error:
            _Shared.reason = f"no MySQL server: {error}"
    if _Shared.server is None:
        pytest.skip(_Shared.reason or "no MySQL server")
    return _Shared.server


@pytest.fixture(scope="session")
def mysql_server() -> MysqlServer:
    return server()


def query_now(sql: str, *, root: bool = False) -> list[tuple[Any, ...]]:
    """Run ``sql`` with the ``mysql`` client in the container (for test
    setup); the rows come back as tab-separated text."""
    current = server()
    user, password = ("root", "root") if root else ("test", "test")
    ran = _docker(
        "exec",
        current.container,
        "mysql",
        "--protocol=TCP",
        "-h127.0.0.1",
        f"-u{user}",
        f"-p{password}",
        "-N",
        "-B",
        "-e",
        sql,
        "test",
    )
    if ran.returncode != 0:
        raise RuntimeError(ran.stderr.strip())
    return [tuple(line.split("\t")) for line in ran.stdout.splitlines()]


__all__ = ["IMAGE", "LABEL", "MysqlServer", "mysql_server", "query_now", "reap_stale", "server"]
