"""Who owns a throwaway PostgreSQL server, and stopping the ones nobody owns.

``pg_ctl`` daemonizes the server, so its parent pid is always 1 and says
nothing about whether the test process that started it is still alive.
Each server's directory (``$TMPDIR/pyfect-pg-*``) therefore records its
owner in ``owner.json``: the pid plus that process's start time, so a pid
the OS reused for another process does not count as the owner.

- ``claim(root)`` records the current process as the owner.
- ``watch(root)`` starts a watchdog that stops the server when the owner
  exits for any reason (SIGTERM, SIGINT, SIGKILL, a crash): it waits for
  the end of a pipe only the owner holds.
- ``reap(tempdir)`` stops every server whose owner is gone. Directories from
  before owner records existed count as orphaned when no live pytest
  process started before them.

Run as a script (``python _pg_owner.py ROOT``), this file is the watchdog.
"""

from __future__ import annotations

import contextlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

PREFIX = "pyfect-pg-"
_OWNER_FILE = "owner.json"
_LSTART = "%a %b %d %H:%M:%S %Y"


def _ps(*args: str) -> str:
    done = subprocess.run(
        ["ps", *args],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "LC_ALL": "C"},
    )
    return done.stdout.strip()


@dataclass(frozen=True)
class Owner:
    pid: int
    started: str
    """The process's start time as ``ps -o lstart`` prints it."""

    @staticmethod
    def of(pid: int) -> Owner | None:
        started = _ps("-o", "lstart=", "-p", str(pid))
        return Owner(pid, started) if started else None

    def alive(self) -> bool:
        return Owner.of(self.pid) == self


def claim(root: Path) -> None:
    owner = Owner.of(os.getpid())
    assert owner is not None
    (root / _OWNER_FILE).write_text(json.dumps({"pid": owner.pid, "started": owner.started}))


def owner_of(root: Path) -> Owner | None:
    """The recorded owner; None for a directory without a readable record."""
    try:
        record = json.loads((root / _OWNER_FILE).read_text())
        return Owner(int(record["pid"]), str(record["started"]))
    except (OSError, ValueError, KeyError, TypeError):
        return None


def _postmaster(data_dir: Path) -> int | None:
    """The running postmaster of ``data_dir``, checked against its command
    line so a stale ``postmaster.pid`` never names an unrelated process."""
    try:
        pid = int((data_dir / "postmaster.pid").read_text().splitlines()[0])
    except (OSError, ValueError, IndexError):
        return None
    command = _ps("-o", "command=", "-p", str(pid))
    return pid if "postgres" in command and f"-D {data_dir}" in command else None


def stop_server(root: Path) -> None:
    """Stop the server in ``root`` (an immediate shutdown, as ``pg_ctl -m
    immediate``) and delete the directory. Safe to call more than once."""
    data_dir = root / "data"
    pid = _postmaster(data_dir)
    if pid is not None:
        with contextlib.suppress(ProcessLookupError):
            os.kill(pid, signal.SIGQUIT)
        deadline = time.monotonic() + 10
        while _postmaster(data_dir) == pid:
            if time.monotonic() > deadline:
                with contextlib.suppress(ProcessLookupError):
                    os.kill(pid, signal.SIGKILL)
            time.sleep(0.02)
    shutil.rmtree(root, ignore_errors=True)


def _pytest_start_times() -> list[datetime]:
    starts: list[datetime] = []
    for line in _ps("-axo", "lstart=,command=").splitlines():
        lstart, command = line[:24], line[24:]
        if "pytest" in command:
            with contextlib.suppress(ValueError):
                starts.append(datetime.strptime(lstart.strip(), _LSTART))
    return starts


def orphaned(root: Path, pytest_starts: list[datetime]) -> bool:
    owner = owner_of(root)
    if owner is not None:
        return not owner.alive()
    # No record: a directory from before owner records. Its owner started
    # before the directory was last written, so if no live pytest process
    # did, its owner is gone.
    written = datetime.fromtimestamp(root.stat().st_mtime)
    return not any(start <= written for start in pytest_starts)


def reap(tempdir: Path) -> list[Path]:
    """Stop and delete every server directory in ``tempdir`` whose owner is
    gone; returns the directories reaped. Servers whose owner is alive are
    left alone."""
    roots = sorted(path for path in tempdir.glob(f"{PREFIX}*") if path.is_dir())
    if not roots:
        return []
    starts = _pytest_start_times()
    reaped: list[Path] = []
    for root in roots:
        with contextlib.suppress(FileNotFoundError):
            if orphaned(root, starts):
                stop_server(root)
                reaped.append(root)
    return reaped


def watch(root: Path) -> subprocess.Popen[bytes]:
    """Start the watchdog for ``root``. It stops the server once the
    returned process's stdin closes, which happens when the owner exits
    however it exits; keep the returned object alive until then."""
    return subprocess.Popen(
        [sys.executable, "-I", __file__, str(root)],
        stdin=subprocess.PIPE,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


def _watchdog(root: Path) -> None:
    for name in ("SIGINT", "SIGHUP"):
        signal.signal(getattr(signal, name), signal.SIG_IGN)
    sys.stdin.buffer.read()
    stop_server(root)


if __name__ == "__main__":
    _watchdog(Path(sys.argv[1]))
