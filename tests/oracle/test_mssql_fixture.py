"""The SQL Server container fixture (``_mssql``): it skips without Docker,
picks the image for the machine, and removes the containers a crashed run
left."""

import platform
import shutil
import subprocess

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
