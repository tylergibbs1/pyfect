"""Sockets, servers and SQL clients let go of what they handled once the run
ends, without the cycle collector (see ``tests/test_closure_cycles.py``)."""

from __future__ import annotations

from pathlib import Path

from _closure_release import Handled, assert_freed_after_run

import pyfect as fx
from pyfect.clock import Clock, LiveClock
from pyfect.sql import sqlite
from pyfect.sql.client import SqlClient


class _HeldClock(LiveClock):
    """The live clock, holding a value the program handles."""

    def __init__(self, held: Handled) -> None:
        self.held = held


def test_sqlite_wal_setup_frees_the_clock_it_read(tmp_path: Path) -> None:
    config = sqlite.SqliteClientConfig(filename=str(tmp_path / "app.db"))

    def build(value: Handled) -> fx.Effect[object, object]:
        def body():
            sql = yield from SqlClient()
            return (yield from sql("SELECT 1 AS one"))

        return (
            fx.gen(body)
            .pipe(fx.provide(sqlite.layer(config)))
            .pipe(fx.provide_service(Clock, _HeldClock(value)))
        )

    assert_freed_after_run(build)
