"""Ports of the ``PersistedQueue`` suites of Effect's
``sql-sqlite-node/test/Persistence.test.ts``: the ``PersistedQueueTest``
suite (``_persisted_queue_suite``) on ``layer_store_sql``
(``PersistedQueue (sql-sqlite-node)``) and the ``PersistedQueueSqlTest``
suite (``_persisted_queue_sql_suite``), over a SQLite database in a
temporary directory, fresh for each test.

Each test's docstring is the Effect test title. The file's other suites
are in ``test_sqlite_persistence.py``.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import pyfect as fx
from pyfect.persistence import persisted_queue as pq
from pyfect.sql import sqlite

from . import _persisted_queue_sql_suite as sql_suite
from . import _persisted_queue_suite as suite

pytestmark = pytest.mark.filterwarnings("ignore::pyfect.testing.ClockNotAdvancedWarning")


class _Database:
    directory: Path

    @pytest.fixture(autouse=True)
    def _directory(self, tmp_path: Path) -> None:
        self.directory = tmp_path

    def client(self) -> fx.Layer[Any, Any]:
        filename = str(self.directory / "test.db")
        return sqlite.layer(sqlite.SqliteClientConfig(filename=filename))


class TestPersistedQueueSqlite(_Database, suite.PersistedQueueSuite):
    """PersistedQueue (sql-sqlite-node)"""

    def make_layer(self) -> fx.Layer[pq.PersistedQueueStore, Any, Any]:
        return pq.layer_store_sql().pipe(fx.provide(self.client()))


class TestPersistedQueueSqliteSql(_Database, sql_suite.PersistedQueueSqlSuite):
    """PersistedQueue SQL delays / PersistedQueue SQL claims (sql-sqlite-node)"""
