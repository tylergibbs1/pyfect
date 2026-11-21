"""The SQL Server container fixture (``_mssql``): it skips without Docker,
picks the image for the machine, waits until the server has finished starting, and removes the
containers a crashed run left."""

import math
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest

from . import _docker, _mssql


def _not_found(_name: str) -> None:
    return None


def test_skips_without_docker(monkeypatch: pytest.MonkeyPatch):
    _mssql.SERVER.forget(monkeypatch)
    monkeypatch.setattr(shutil, "which", _not_found)
    with pytest.raises(pytest.skip.Exception, match="docker not found"):
        _mssql.server()


@pytest.mark.parametrize(
    ("machine", "expected"),
    [
        ("arm64", _mssql.EDGE_IMAGE),
        ("aarch64", _mssql.EDGE_IMAGE),
        ("x86_64", _mssql.SQL_SERVER_IMAGE),
    ],
)
def test_picks_azure_sql_edge_on_arm(monkeypatch: pytest.MonkeyPatch, machine: str, expected: str):
    # SQL Server 2022 does not start under amd64 emulation on Apple silicon.
    monkeypatch.delenv("PYFECT_MSSQL_IMAGE", raising=False)
    monkeypatch.setattr(platform, "machine", lambda: machine)
    assert _mssql.image() == expected


def test_an_image_in_the_environment_wins(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PYFECT_MSSQL_IMAGE", "example/mssql:1")
    assert _mssql.image() == "example/mssql:1"


def _dead_pid() -> int:
    probe = subprocess.Popen(["true"])
    probe.wait()
    return probe.pid


class _Starting:
    """A server that takes logins while it is still starting: each login's ``STARTING``
    query reads the next of ``states`` (databases not online, requests waiting)."""

    def __init__(self, *states: tuple[int, int]) -> None:
        self.states = list(states)
        self.logins = 0
        self.closed = 0

    def login(self, *_args: object, **_kwargs: object) -> Any:
        self.logins += 1
        return self

    def cursor(self) -> Any:
        return self

    def execute(self, sql: str) -> None:
        assert sql == _mssql.STARTING

    def fetchall(self) -> list[tuple[int, int]]:
        return [self.states.pop(0)]

    def close(self) -> None:
        self.closed += 1


def _no_wait(_seconds: float) -> None:
    return None


def _always_running(_container: str) -> bool:
    return True


def test_is_ready_only_once_the_server_has_finished_starting(monkeypatch: pytest.MonkeyPatch):
    # Seen on a fresh container: the first login came while msdb was still recovering, then
    # system tasks and logins waited on each other's locks for about 3 s more; a test's first
    # statements waited behind them.
    server = _Starting((1, 4), (0, 2), (0, 0))
    monkeypatch.setattr(_mssql, "_login", server.login)
    monkeypatch.setattr(_mssql, "_STARTUP_TIMEOUT", math.inf)
    monkeypatch.setattr(_docker, "running", _always_running)
    monkeypatch.setattr(_docker.time, "sleep", _no_wait)
    _mssql._wait_ready(_mssql.MssqlServer("127.0.0.1", 1433, "container"), 0.0)  # pyright: ignore[reportPrivateUsage]
    assert (server.logins, server.closed, server.states) == (3, 3, [])


def test_reaps_containers_of_processes_that_are_gone():
    try:
        _docker.require_docker()
    except RuntimeError as error:
        pytest.skip(f"no Docker: {error}")
    _docker.pull(_docker.PLACEHOLDER_IMAGE)
    created = subprocess.run(
        [
            "docker",
            "create",
            "--label",
            _mssql.LABEL,
            "--label",
            f"{_docker.OWNER}={_dead_pid()}",
            _docker.PLACEHOLDER_IMAGE,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    container = created.stdout.strip()
    try:
        # Any process starting a server reaps it too (another xdist worker, another run), so
        # the test checks that it is gone, not which call removed it.
        _docker.reap_stale(_mssql.LABEL)
        left = subprocess.run(
            ["docker", "ps", "-a", "-q", "--no-trunc", "--filter", f"id={container}"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert left.stdout.strip() == ""
    finally:
        subprocess.run(["docker", "rm", "-f", container], capture_output=True, check=False)


_FAKE_DOCKER = """#!/bin/sh
# Containers fake-mssql-1, -2, ... in the order of their runs; those from $READY_FROM on run.
here=$(dirname "$0")
container=$(eval echo \\${$#})
n=${container##*-}
case "$1" in
  run)
    runs=$(($(cat "$here/runs" 2>/dev/null || echo 0) + 1))
    echo "$runs" > "$here/runs"
    echo "fake-mssql-$runs" ;;
  port) echo "127.0.0.1:$((40000 + ${2##*-}))" ;;
  inspect)
    case "$3" in
      *Running*) if [ "$n" -ge "$READY_FROM" ]; then echo true; else echo false; fi ;;
      *) echo "status=exited exit_code=255 oom_killed=false" ;;
    esac ;;
  logs) echo "ERROR: CoInitializeSecurity failure. (HRESULT 0x800706b5)" ;;
  rm) shift; echo "$@" >> "$here/removed" ;;
esac
"""


class _FakeDocker:
    """A ``docker`` on PATH whose first containers exit at once, as SQL Server 2022's did in
    CI run 44897877038 (``CoInitializeSecurity failure``), and whose later ones serve."""

    def __init__(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, ready_from: int) -> None:
        self.dir = tmp_path
        script = tmp_path / "docker"
        script.write_text(_FAKE_DOCKER)
        script.chmod(0o755)
        monkeypatch.setenv("PATH", f"{tmp_path}{os.pathsep}{os.environ['PATH']}")
        monkeypatch.setenv("READY_FROM", str(ready_from))
        monkeypatch.setenv("PYFECT_MSSQL_IMAGE", "example/mssql:fake")
        self.ready_port = 40000 + ready_from
        self.at_exit: list[tuple[object, ...]] = []
        monkeypatch.setattr(_mssql.atexit, "register", self.register_at_exit)
        monkeypatch.setattr(_mssql, "_login", self.login)
        monkeypatch.setattr(_docker.time, "sleep", _no_wait)
        _mssql.SERVER.forget(monkeypatch)

    def register_at_exit(self, *call: object) -> None:
        self.at_exit.append(call)

    def login(self, _host: str, port: int, *_args: object, **_kwargs: object) -> Any:
        if port != self.ready_port:
            raise TimeoutError
        return _Starting((0, 0))

    def runs(self) -> int:
        return int((self.dir / "runs").read_text())

    def removed(self) -> list[str]:
        removed = self.dir / "removed"
        return removed.read_text().split() if removed.exists() else []


def test_replaces_a_container_that_exits_before_it_serves(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    fake = _FakeDocker(tmp_path, monkeypatch, ready_from=3)
    with pytest.warns(_mssql.ContainerRestarted, match="CoInitializeSecurity") as restarts:
        server = _mssql.server()
    assert (server.container, fake.runs(), len(restarts)) == ("fake-mssql-3", 3, 2)
    assert [r for r in fake.removed() if r.startswith("fake")] == ["fake-mssql-1", "fake-mssql-2"]
    assert [call[1] for call in fake.at_exit] == ["fake-mssql-1", "fake-mssql-2", "fake-mssql-3"]


def test_fails_with_every_start_after_the_last_attempt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    fake = _FakeDocker(tmp_path, monkeypatch, ready_from=99)
    with (
        pytest.warns(_mssql.ContainerRestarted),
        pytest.raises(_docker.ContainerStopped) as failed,
    ):
        _mssql.server()
    assert fake.runs() == _mssql._START_ATTEMPTS  # pyright: ignore[reportPrivateUsage]
    message = str(failed.value)
    for start in range(1, fake.runs() + 1):
        assert f"start {start}: the SQL Server container stopped" in message
    assert message.count("CoInitializeSecurity failure") == fake.runs()
    assert [r for r in fake.removed() if r.startswith("fake")] == [
        f"fake-mssql-{n}" for n in range(1, fake.runs() + 1)
    ]


def test_does_not_replace_a_container_past_the_startup_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    fake = _FakeDocker(tmp_path, monkeypatch, ready_from=3)
    monkeypatch.setattr(_mssql, "_STARTUP_TIMEOUT", 0.0)
    with pytest.raises(_docker.ContainerStopped, match=r"^start 1: "):
        _mssql.server()
    assert fake.runs() == 1
