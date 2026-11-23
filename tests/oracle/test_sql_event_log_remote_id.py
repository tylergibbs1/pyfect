"""Servers that start at once on a new database agree on its remote id, on
SQLite, PostgreSQL, MySQL and SQL Server (each server skipped without one).

Effect's ``makeStorage`` reads the remote id table and inserts a new id if
it finds none. Two starts that both read before either inserts each wrote
their own id (its primary key is the id itself, so both inserts succeed),
and the servers then disagreed about which log they serve. A barrier holds
each start between its read and its insert until the other gets there too.
"""

from __future__ import annotations

import contextlib
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import pyfect as fx
from pyfect.eventlog import event_journal as J
from pyfect.eventlog import event_log_server_encrypted as Server
from pyfect.eventlog._sql_server_encrypted import upgrade
from pyfect.eventlog.event_journal import RemoteId
from pyfect.persistence._columns import column_bytes
from pyfect.sql.client import SqlClient

from ._legacy_eventlog import DIALECTS, LegacyDb, any_db


@pytest.fixture(params=DIALECTS)
def db(request: pytest.FixtureRequest, tmp_path: Path) -> LegacyDb:
    return any_db(request, tmp_path)


def _start(db: LegacyDb) -> RemoteId:
    def body():
        return (yield from (yield from Server.Storage()).get_id)

    started = db.run(body)
    assert isinstance(started, fx.Success)
    return started.value


def _stored_ids(db: LegacyDb) -> list[bytes]:
    def body():
        sql = (yield from SqlClient()).without_transforms()
        rows = yield from sql("SELECT remote_id FROM {}", sql.identifier(db.remote_id_table))
        return [column_bytes(row["remote_id"]) for row in rows]

    found = db.tool(fx.gen(body))
    assert isinstance(found, fx.Success)
    return found.value


def test_servers_starting_at_once_on_a_new_database_share_one_remote_id(
    db: LegacyDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    both_found_none = threading.Barrier(2, timeout=5)

    def make_once_both_found_none() -> RemoteId:
        with contextlib.suppress(threading.BrokenBarrierError):
            both_found_none.wait()
        return J.make_remote_id_unsafe()

    monkeypatch.setattr(upgrade, "make_remote_id_unsafe", make_once_both_found_none)
    with ThreadPoolExecutor(2) as pool:
        ids = [started.result() for started in [pool.submit(_start, db) for _ in "ab"]]
    assert ids[0] == ids[1]
    assert _stored_ids(db) == [ids[0]]
    assert _start(db) == ids[0]
