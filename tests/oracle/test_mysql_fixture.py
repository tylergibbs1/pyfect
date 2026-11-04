"""The MySQL container fixture (``_mysql``): it skips without Docker and
removes the containers a crashed run left."""

import shutil
import subprocess

import pytest

from . import _mysql


def _not_found(_name: str) -> None:
    return None


def test_skips_without_docker(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(_mysql._Shared, "server", None)  # pyright: ignore[reportPrivateUsage]
    monkeypatch.setattr(_mysql._Shared, "reason", None)  # pyright: ignore[reportPrivateUsage]
    monkeypatch.setattr(shutil, "which", _not_found)
    with pytest.raises(pytest.skip.Exception, match="docker not found"):
        _mysql.server()


def _dead_pid() -> int:
    probe = subprocess.Popen(["true"])
    probe.wait()
    return probe.pid


def test_reaps_containers_of_processes_that_are_gone():
    if (
        shutil.which("docker") is None
        or subprocess.run(
            ["docker", "image", "inspect", _mysql.IMAGE], capture_output=True, check=False
        ).returncode
    ):
        pytest.skip("no Docker, or no MySQL image")
    created = subprocess.run(
        [
            "docker",
            "create",
            "--label",
            _mysql.LABEL,
            "--label",
            f"pyfect.test.owner={_dead_pid()}",
            _mysql.IMAGE,
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    container = created.stdout.strip()
    try:
        reaped = _mysql.reap_stale()
        assert any(container.startswith(r) or r.startswith(container[:12]) for r in reaped)
        left = subprocess.run(
            ["docker", "ps", "-a", "-q", "--no-trunc", "--filter", f"id={container}"],
            capture_output=True,
            text=True,
            check=True,
        )
        assert left.stdout.strip() == ""
    finally:
        subprocess.run(["docker", "rm", "-f", container], capture_output=True, check=False)
