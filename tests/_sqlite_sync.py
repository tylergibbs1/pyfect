"""SQLite files a test opens commit without fsync, unless the test is marked ``sqlite_fsync``.

A commit with SQLite's default sync waits for the disk to flush. On a CI runner the disk is
shared with the containers the suite loads and starts, and there a flush can take seconds: the
libSQL driver's local-file round trip (eleven autocommits) once outlasted its 5 s timeout, and
the same statements took a median 3.8 s and up to 14 s against 2 ms unsynced under a
concurrent writer. Tests check logic, not durability, so every ``sqlite3.connect`` made while
a test runs (pyfect's ``sqlite`` and ``libsql`` drivers both open through it) starts with
``PRAGMA synchronous = OFF``. A test about the sync setting itself takes the marker.
"""

from __future__ import annotations

import functools
import sqlite3
from collections.abc import Callable, Generator
from typing import Any

import pytest

MARKER = "sqlite_fsync"

_keep_sync = [False]
"""Whether the running test is marked ``sqlite_fsync``."""


def _unsynced(connect: Callable[..., sqlite3.Connection]) -> Callable[..., sqlite3.Connection]:
    @functools.wraps(connect)
    def connect_unsynced(*args: Any, **kwargs: Any) -> sqlite3.Connection:
        conn = connect(*args, **kwargs)
        # PEP 249 mode (``autocommit=False``) opens a transaction at once, and SQLite refuses
        # to change the sync inside one.
        if not _keep_sync[0] and not conn.in_transaction:
            conn.execute("PRAGMA synchronous = OFF")
        return conn

    return connect_unsynced


# Here, not in pytest_configure: a pytester run configures again, and must not wrap twice.
sqlite3.connect = _unsynced(sqlite3.connect)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_protocol(item: pytest.Item) -> Generator[None, object, object]:
    _keep_sync[0] = item.get_closest_marker(MARKER) is not None
    try:
        return (yield)
    finally:
        _keep_sync[0] = False


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers",
        f"{MARKER}: SQLite files the test opens keep the default sync (tests/_sqlite_sync.py)",
    )
