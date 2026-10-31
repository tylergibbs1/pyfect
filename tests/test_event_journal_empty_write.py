"""An empty ``write_many`` writes nothing in every journal (QA ai-workflow
EL-4): the SQLite journal died on ``sql.insert([])`` where the memory one
succeeded. Effect types the batch as non-empty, so it has no case."""

from __future__ import annotations

from typing import Any

import pyfect as fx
from pyfect import testing
from pyfect.eventlog import event_journal as J
from pyfect.eventlog import sql_event_journal as SqlJ
from pyfect.reactivity import layer as reactivity_layer
from pyfect.sql import sqlite
from pyfect.sql.client import SqlClient


def _sqlite_journal() -> fx.Effect[J.EventJournalService, Any, Any]:
    @fx.gen
    def run():
        client = yield from sqlite.make(sqlite.SqliteClientConfig(filename=":memory:"))
        return (yield from SqlJ.make().pipe(fx.provide_service(SqlClient, client)))

    return run


@testing.effect
def test_an_empty_write_many_writes_nothing_on_sqlite():
    journal = yield from _sqlite_journal().pipe(fx.provide(reactivity_layer))
    assert (yield from journal.write_many([], fx.succeed)) == []
    assert (yield from journal.entries) == []


@testing.effect
def test_an_empty_write_many_writes_nothing_in_memory():
    journal = yield from J.make_memory
    assert (yield from journal.write_many([], fx.succeed)) == []
    assert (yield from journal.entries) == []
