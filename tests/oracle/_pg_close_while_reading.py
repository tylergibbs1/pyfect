"""Run as a script by ``test_pg_close_while_reading``: closes a session on
the SQL loop while a read on it has its reply waiting, then lets the loop
go. ``statement`` closes it by releasing the pin of a running statement;
``stream`` closes the session's own scope (no pin taken) while a stream's
first pull reads.

The read waits on an advisory lock held by another session, so it is
parked reading when the loop is held; the lock is then released and the
reply reaches the socket while the loop is still held. Once the loop runs
again, the close and the read are queued together. Prints the read's exit
and exits 0 unless the process dies first.
"""

from __future__ import annotations

import sys
import threading
import time
from collections.abc import Generator
from typing import Any, LiteralString

import psycopg

import pyfect as fx
from pyfect import redacted
from pyfect.result import Ok
from pyfect.scope import Scope
from pyfect.sql import pg
from pyfect.sql._loop import get_loop
from pyfect.sql.error import SqlError

_LOCK = 4242
_SETTLE = 30.0


def _until(watcher: psycopg.Connection[Any], sql: LiteralString, pid: int) -> fx.Effect[None]:
    """Poll until ``sql`` finds a row for ``pid``, sleeping between polls so
    the fibers the test waits on keep running."""
    deadline = time.monotonic() + _SETTLE

    def check() -> fx.Effect[None]:
        if watcher.execute(sql, (pid,)).fetchone() is not None:
            return fx.void
        if time.monotonic() >= deadline:
            return fx.die(TimeoutError(sql))
        return fx.sleep("10 millis").and_then(fx.suspend(check))

    return fx.suspend(check)


def _kind(exit: fx.Exit[object, SqlError]) -> str:
    """``Success``, ``SqlError`` (a typed failure), or ``Other`` (a defect
    or an interruption)."""
    if isinstance(exit, fx.Success):
        return "Success"
    return "SqlError" if isinstance(exit.cause.find_error(), Ok) else "Other"


def main(uri: str, mode: str) -> None:
    blocker = psycopg.connect(uri, autocommit=True)
    watcher = psycopg.connect(uri, autocommit=True)
    blocker.execute("SELECT pg_advisory_lock(%s)", (_LOCK,))

    def parked_then_closed(pid: int, close: fx.Effect[None]) -> Generator[fx.Effect[Any], Any]:
        # Parked: PostgreSQL has the read waiting on the lock.
        yield from _until(
            watcher,
            "SELECT 1 FROM pg_stat_activity WHERE pid = %s AND wait_event_type = 'Lock'",
            pid,
        )
        go = threading.Event()
        get_loop().call_soon_threadsafe(go.wait)
        try:
            blocker.execute("SELECT pg_advisory_unlock(%s)", (_LOCK,))
            # The reply is sent: the backend is idle again.
            yield from _until(
                watcher, "SELECT 1 FROM pg_stat_activity WHERE pid = %s AND state = 'idle'", pid
            )
            time.sleep(0.05)
            closing = yield from close.fork(start_immediately=True)
        finally:
            go.set()
        yield from closing.join()

    config = pg.PgConnectionConfig(url=redacted.make(uri))
    sql = f"SELECT pg_advisory_lock({_LOCK}) AS n"

    @fx.gen
    def statement():
        connection = yield from pg.connection.make(config)
        pin_scope = fx.CloseableScope()
        pinned = yield from connection.pin.pipe(fx.provide_service(Scope, pin_scope))
        reading = yield from pinned.query(sql).fork(start_immediately=True)
        yield from parked_then_closed(connection.process_id, pin_scope.close(fx.Success(None)))
        return (yield from reading.await_exit())

    @fx.gen
    def stream():
        session_scope = fx.CloseableScope()
        connection = yield from pg.connection.make(config).pipe(
            fx.provide_service(Scope, session_scope)
        )
        stream_scope = fx.CloseableScope()
        first_pull = connection.stream(sql).to_pull().flat_map(lambda pull: pull)
        reading = yield from first_pull.pipe(fx.provide_service(Scope, stream_scope)).fork(
            start_immediately=True
        )
        yield from parked_then_closed(connection.process_id, session_scope.close(fx.Success(None)))
        read = yield from reading.await_exit()
        yield from stream_scope.close(fx.Success(None))
        return read

    program = statement if mode == "statement" else stream
    exit = fx.run_blocking(fx.scoped(program).exit())
    print(_kind(exit), exit)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
