"""A ``file:`` URI opens the file it names, writable or not (as
``node:sqlite``); a readonly client adds ``mode=ro`` to it."""

from pathlib import Path

import pyfect as fx
from pyfect import reactivity, testing
from pyfect.sql import sqlite
from pyfect.sql.error import SqlError


def _make(
    filename: str, *, readonly: bool = False
) -> fx.Effect[sqlite.SqliteClientService, SqlError, fx.Scope]:
    config = sqlite.SqliteClientConfig(filename=filename, readonly=readonly)
    return sqlite.make(config).pipe(fx.provide(reactivity.layer))


@testing.effect
def test_opens_a_writable_file_uri_at_its_path(tmp_path: Path):
    path = tmp_path / "uri-write.db"
    sql = yield from _make(path.as_uri())
    yield from sql("CREATE TABLE test (id INTEGER PRIMARY KEY)")
    yield from sql("INSERT INTO test (id) VALUES (1)")
    assert (yield from sql("SELECT * FROM test")) == [{"id": 1}]
    assert path.exists()
    assert list(tmp_path.glob("file*")) == []


@testing.effect
def test_a_readonly_client_overrides_the_uri_mode(tmp_path: Path):
    path = tmp_path / "uri-mode.db"
    yield from fx.scoped(_make(str(path)).flat_map(lambda sql: sql("CREATE TABLE t (id INTEGER)")))
    sql = yield from _make(f"{path.as_uri()}?mode=rw", readonly=True)
    error = yield from sql("INSERT INTO t VALUES (1)").flip()
    assert "readonly" in str(error.reason.cause).lower()
