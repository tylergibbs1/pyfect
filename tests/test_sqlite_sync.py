"""SQLite files a test opens commit without fsync unless it is marked ``sqlite_fsync``
(tests/_sqlite_sync.py)."""

from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

import pytest


def _sync(path: Path, *, autocommit: bool = True) -> object:
    with closing(sqlite3.connect(path, autocommit=autocommit)) as conn:
        return conn.execute("PRAGMA synchronous").fetchone()[0]


def test_a_file_opened_in_a_test_skips_fsync(tmp_path: Path):
    assert _sync(tmp_path / "a.db") == 0


@pytest.mark.sqlite_fsync
def test_a_marked_test_keeps_the_default_sync(tmp_path: Path):
    assert _sync(tmp_path / "a.db") == 2


def test_a_connection_that_opens_in_a_transaction_still_opens(tmp_path: Path):
    # PEP 249 mode begins at once, and SQLite refuses a sync change inside a transaction.
    assert _sync(tmp_path / "a.db", autocommit=False) == 2
