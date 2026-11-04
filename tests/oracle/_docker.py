"""Throwaway database containers for the driver tests (``_mysql``,
``_mssql``): the ``docker`` command, the reaping of labelled containers
whose owning test process is gone, and published ports."""

from __future__ import annotations

import os
import shutil
import subprocess

OWNER = "pyfect.test.owner"
"""The label holding the pid of the process that started a container."""


def docker(*args: str, timeout: float = 60) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=False, timeout=timeout
    )


def require_docker() -> None:
    """``RuntimeError`` unless the Docker daemon can be used."""
    if shutil.which("docker") is None:
        raise RuntimeError("docker not found")
    if docker("info", "--format", "{{.ServerVersion}}").returncode != 0:
        raise RuntimeError("the Docker daemon is not running")


def alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def reap_stale(label: str) -> list[str]:
    """Remove the containers labelled ``label`` whose owning process is
    gone."""
    listed = docker(
        "ps",
        "-a",
        "--filter",
        f"label={label}",
        "--format",
        f'{{{{.ID}}}} {{{{.Label "{OWNER}"}}}}',
    )
    stale: list[str] = []
    for line in listed.stdout.splitlines():
        container, _, owner = line.partition(" ")
        if not owner.isdigit() or not alive(int(owner)):
            stale.append(container)
    if stale:
        docker("rm", "-f", "-v", *stale)
    return stale


def remove(container: str) -> None:
    docker("rm", "-f", "-v", container)


def published_port(container: str, port: int) -> int:
    mapped = docker("port", container, f"{port}/tcp").stdout.split()
    if not mapped:
        raise RuntimeError(f"the container published no port {port}")
    return int(mapped[0].rsplit(":", 1)[1])


def pull(image: str, *platform: str) -> None:
    """Pull ``image`` unless it is there."""
    if docker("image", "inspect", image).returncode == 0:
        return
    pulled = docker("pull", *platform, image, timeout=900)
    if pulled.returncode != 0:
        raise RuntimeError(f"cannot pull {image}: {pulled.stderr.strip()}")


__all__ = ["OWNER", "alive", "docker", "published_port", "pull", "reap_stale", "remove"]
