"""Throwaway database containers for the driver tests (``_mysql``,
``_mssql``): the ``docker`` command, the reaping of labelled containers
whose owning test process is gone, published ports, and the wait for a
started container to serve.

A container that does not start fails with ``ContainerFailed``, which
carries its state (exit code, whether the kernel killed it for memory) and
the end of its logs. Containers run without ``--rm``, so that state and
those logs outlive a crash; the owner removes them at exit (``remove``), or
the next run does (``reap_stale``).
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

import _container_images

OWNER = "pyfect.test.owner"
"""The label holding the pid of the process that started a container."""

PLACEHOLDER_IMAGE = _container_images.image("busybox").local
"""A few megabytes: what a test of the labels creates (never starts) a container from."""


class ContainerFailed(Exception):
    """A started container that stopped, or did not serve in time: never skipped, unlike a
    missing Docker (``require_docker``)."""


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
        raise ContainerFailed(f"the container published no port {port}: {diagnosis(container)}")
    return int(mapped[0].rsplit(":", 1)[1])


_STATE = (
    "status={{.State.Status}} exit_code={{.State.ExitCode}} oom_killed={{.State.OOMKilled}} "
    "error={{.State.Error}} started={{.State.StartedAt}} finished={{.State.FinishedAt}}"
)


def _host_memory() -> str:
    meminfo = Path("/proc/meminfo")
    if not meminfo.exists():
        return ""
    fields = dict(line.split(":", 1) for line in meminfo.read_text().splitlines() if ":" in line)
    return f"; host MemAvailable {fields.get('MemAvailable', '?').strip()}"


def diagnosis(container: str) -> str:
    """The container's state, its memory use and the host's, and the end of its logs."""
    state = docker("inspect", "-f", _STATE, container)
    usage = docker("stats", "--no-stream", "--format", "{{.MemUsage}}", container)
    logs = docker("logs", "--tail", "40", container)
    return (
        f"{(state.stdout or state.stderr).strip()}; memory {usage.stdout.strip() or '?'}"
        f"{_host_memory()}\n--- its last log lines ---\n{logs.stdout}{logs.stderr}"
    )


def running(container: str) -> bool:
    return docker("inspect", "-f", "{{.State.Running}}", container).stdout.strip() == "true"


def wait_ready(
    name: str, container: str, waiting: Callable[[], str | None], timeout: float, poll: float
) -> None:
    """Until ``waiting()`` returns ``None``; until then it says what the server still lacks.
    ``ContainerFailed`` (with the ``diagnosis``) when the container stops, at once, or when
    ``timeout`` seconds pass."""
    deadline = time.monotonic() + timeout
    while (missing := waiting()) is not None:
        if not running(container):
            raise ContainerFailed(
                f"the {name} container stopped ({missing}): {diagnosis(container)}"
            )
        if time.monotonic() > deadline:
            raise ContainerFailed(
                f"{name} did not start in {timeout:g} s ({missing}): {diagnosis(container)}"
            )
        time.sleep(poll)


def pull(image: str) -> None:
    """Make ``image`` available: one of tests/container_images.json's local tags is loaded or
    pulled by digest (``_container_images.ensure``); any other name (``PYFECT_MSSQL_IMAGE``)
    is pulled unless it is there."""
    pinned = next((i for i in _container_images.IMAGES.values() if i.local == image), None)
    if pinned is not None:
        _container_images.ensure(pinned)
        return
    if docker("image", "inspect", image).returncode == 0:
        return
    pulled = docker("pull", image, timeout=900)
    if pulled.returncode != 0:
        raise RuntimeError(f"cannot pull {image}: {pulled.stderr.strip()}")


__all__ = [
    "OWNER",
    "PLACEHOLDER_IMAGE",
    "ContainerFailed",
    "alive",
    "diagnosis",
    "docker",
    "published_port",
    "pull",
    "reap_stale",
    "remove",
    "running",
    "wait_ready",
]
