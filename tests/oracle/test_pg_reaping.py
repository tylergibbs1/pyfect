"""The throwaway PostgreSQL servers of ``_postgres`` never outlive their
owner: the watchdog stops one when its test process dies (however it dies),
and starting a server reaps any whose owner is gone, sparing the ones whose
owner is alive."""

from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from . import _pg_owner, _postgres

_REPO = Path(__file__).resolve().parents[2]


def _dead_owner() -> _pg_owner.Owner:
    proc = subprocess.Popen(["sleep", "60"])
    owner = _pg_owner.Owner.of(proc.pid)
    proc.kill()
    proc.wait()
    assert owner is not None
    return owner


def _server_dir(tempdir: Path, owner: _pg_owner.Owner | None) -> Path:
    root = Path(tempfile.mkdtemp(prefix=_pg_owner.PREFIX, dir=tempdir))
    if owner is not None:
        (root / "owner.json").write_text(json.dumps({"pid": owner.pid, "started": owner.started}))
    return root


@pytest.fixture
def tempdir() -> Iterator[Path]:
    # Short, so a server's Unix socket path fits macOS's 104-byte limit.
    path = Path(tempfile.mkdtemp(prefix="pgr-", dir="/tmp"))
    yield path
    for root in path.glob(f"{_pg_owner.PREFIX}*"):
        _pg_owner.stop_server(root)
    shutil.rmtree(path, ignore_errors=True)


def test_reaps_only_directories_whose_owner_is_gone(tempdir: Path) -> None:
    me = _pg_owner.Owner.of(os.getpid())
    assert me is not None
    live = _server_dir(tempdir, me)
    dead = _server_dir(tempdir, _dead_owner())
    reused_pid = _server_dir(tempdir, _pg_owner.Owner(me.pid, "Thu Jan  1 00:00:00 1998"))
    legacy_current = _server_dir(tempdir, None)
    legacy_old = _server_dir(tempdir, None)
    os.utime(legacy_old, (946684800, 946684800))
    unrelated = tempdir / "something-else"
    unrelated.mkdir()

    reaped = _pg_owner.reap(tempdir)

    assert sorted(reaped) == sorted([dead, reused_pid, legacy_old])
    assert live.exists() and legacy_current.exists() and unrelated.exists()
    assert not dead.exists() and not reused_pid.exists() and not legacy_old.exists()


def _require_postgres() -> None:
    pytest.importorskip("psycopg")
    if _postgres._binary("initdb") is None or _postgres._binary("pg_ctl") is None:  # pyright: ignore[reportPrivateUsage]
        pytest.skip("no local PostgreSQL")


# Python's own SIGINT handler, even if the test process ignores SIGINT (a
# child inherits that).
_CHILD = """
import signal, time
signal.signal(signal.SIGINT, signal.default_int_handler)
from tests.oracle import _postgres
server = _postgres.server()
watchdog = getattr(_postgres._Shared, "watchdog", None)
print(server.data_dir, watchdog.pid if watchdog else 0, flush=True)
time.sleep(60)
"""


def _start_child(tempdir: Path) -> tuple[subprocess.Popen[str], Path, int]:
    child = subprocess.Popen(
        [sys.executable, "-c", _CHILD],
        cwd=_REPO,
        env={**os.environ, "TMPDIR": str(tempdir)},
        stdout=subprocess.PIPE,
        text=True,
    )
    assert child.stdout is not None
    data_dir, watchdog = child.stdout.readline().split()
    return child, Path(data_dir), int(watchdog)


def _running(data_dir: Path) -> bool:
    return _pg_owner._postmaster(data_dir) is not None  # pyright: ignore[reportPrivateUsage]


def _gone_within(data_dir: Path, seconds: float) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if not _running(data_dir) and not data_dir.parent.exists():
            return True
        time.sleep(0.05)
    return False


@pytest.mark.parametrize("sig", [signal.SIGTERM, signal.SIGINT, signal.SIGKILL])
def test_a_server_stops_when_its_owner_dies(tempdir: Path, sig: signal.Signals) -> None:
    _require_postgres()
    child, data_dir, _ = _start_child(tempdir)
    assert _running(data_dir)
    child.send_signal(sig)
    child.wait(10)
    assert _gone_within(data_dir, 10)


def test_starting_a_server_reaps_one_whose_owner_and_watchdog_died(tempdir: Path) -> None:
    _require_postgres()
    child, data_dir, watchdog = _start_child(tempdir)
    if watchdog:
        os.kill(watchdog, signal.SIGKILL)
    child.kill()
    child.wait(10)
    assert _running(data_dir)

    survivor, survivor_dir, _ = _start_child(tempdir)

    assert _gone_within(data_dir, 10)
    assert _running(survivor_dir)
    assert _pg_owner.reap(tempdir) == []
    survivor.terminate()
    survivor.wait(10)
    assert _gone_within(survivor_dir, 10)
