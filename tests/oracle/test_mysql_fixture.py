"""The MySQL container fixture (``_mysql``): it skips without Docker and
removes the containers a crashed run left."""

import shutil
import subprocess

import pytest

from . import _docker, _mysql


def _not_found(_name: str) -> None:
    return None


def test_skips_without_docker(monkeypatch: pytest.MonkeyPatch):
    _mysql.SERVER.forget(monkeypatch)
    monkeypatch.setattr(shutil, "which", _not_found)
    with pytest.raises(pytest.skip.Exception, match="docker not found"):
        _mysql.server()


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
            _mysql.LABEL,
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
        _mysql.reap_stale()
        left = subprocess.run(
            ["docker", "ps", "-a", "-q", "--no-trunc", "--filter", f"id={container}"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert left.stdout.strip() == ""
    finally:
        subprocess.run(["docker", "rm", "-f", container], capture_output=True, check=False)
