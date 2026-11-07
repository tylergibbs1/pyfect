"""(pyfect) Interrupting a MySQL statement ends it on the server, read over another
connection (``query_now``). With only the client's socket closed, MySQL 8.4 ended a ``SLEEP``
about 5 s after it began and was still running a busy ``SELECT`` 20 s later, with its locks."""

import logging
import time
import uuid
from collections.abc import Callable
from typing import Any

import pytest

pytest.importorskip("asyncmy")

import pyfect as fx
from pyfect import redacted, testing
from pyfect.sql import mysql

from ._interrupt_on_server import GONE_WITHIN, gone_soon, until_running
from ._mysql import MysqlServer, mysql_server, query_now

__all__ = ["mysql_server"]


def _marked(statement: str) -> tuple[str, str]:
    """``statement`` (a template) with a unique alias the process list shows."""
    marker = f"interrupt_{uuid.uuid4().hex}"
    return statement.format(marker), marker


def _running(marker: str) -> list[tuple[Any, ...]]:
    return query_now(
        "SELECT id, command FROM performance_schema.processlist "
        f"WHERE info LIKE '%AS {marker}%' AND info NOT LIKE '%processlist%'",
        root=True,
    )


def _with_client(
    server: MysqlServer, body: Callable[[], Any], **fields: Any
) -> fx.Effect[Any, Any]:
    config = mysql.MysqlClientConfig(url=server.url, **fields)
    return fx.scoped(fx.gen(body)).pipe(fx.provide(mysql.layer(config)))


_COLUMNS = "information_schema.columns"
_STATEMENTS = {
    "sleep": "SELECT SLEEP(30) AS {}",
    "busy": f"SELECT COUNT(*) AS {{}} FROM {_COLUMNS} a, {_COLUMNS} b, {_COLUMNS} c, {_COLUMNS} d",
}
_SLOW_ROWS = f"SELECT a.ordinal_position, SLEEP(0.001) AS {{}} FROM {_COLUMNS} a, {_COLUMNS} b"


@pytest.mark.parametrize("disable_prepared", [False, True], ids=["prepared", "text"])
@pytest.mark.parametrize("statement", _STATEMENTS.values(), ids=_STATEMENTS.keys())
@testing.live(timeout="30 seconds")
def test_a_timeout_ends_the_statement_on_the_server(
    mysql_server: MysqlServer, statement: str, disable_prepared: bool
):
    sql_text, marker = _marked(statement)

    def body():
        sql = yield from mysql.MysqlClient()
        yield from sql.unsafe(sql_text).timeout("300 millis").exit()
        yield from gone_soon(lambda: _running(marker))

    yield from _with_client(mysql_server, body, disable_prepared_statements=disable_prepared)


@pytest.mark.parametrize("statement", _STATEMENTS.values(), ids=_STATEMENTS.keys())
@testing.live(timeout="30 seconds")
def test_a_fiber_interrupt_ends_the_statement_on_the_server(
    mysql_server: MysqlServer, statement: str
):
    sql_text, marker = _marked(statement)

    def body():
        sql = yield from mysql.MysqlClient()
        fiber = yield from sql.unsafe(sql_text).fork()
        yield from until_running(lambda: _running(marker))
        yield from fiber.interrupt()
        yield from gone_soon(lambda: _running(marker))

    yield from _with_client(mysql_server, body)


@testing.live(timeout="30 seconds")
def test_an_interrupted_stream_ends_on_the_server(mysql_server: MysqlServer):
    source, marker = _marked(_SLOW_ROWS)

    def body():
        sql = yield from mysql.MysqlClient()
        fiber = yield from sql.unsafe(source).stream.run_drain().fork()
        yield from until_running(lambda: _running(marker))
        yield from fiber.interrupt()
        yield from gone_soon(lambda: _running(marker))

    yield from _with_client(mysql_server, body)


def _take_lock_at_once(table: str) -> bool:
    """Whether another connection can lock the row now (``NOWAIT``: no queueing behind it)."""
    try:
        query_now(f"SELECT id FROM {table} WHERE id = 1 FOR UPDATE NOWAIT", root=True)
    except RuntimeError as error:
        assert "3572" in str(error), error
        return False
    return True


@testing.live(timeout="30 seconds")
def test_another_connection_gets_the_row_lock_soon_after_an_interrupt(mysql_server: MysqlServer):
    table = f"interrupted_{uuid.uuid4().hex}"

    def body():
        sql = yield from mysql.MysqlClient()
        yield from sql.unsafe(f"CREATE TABLE {table} (id INT PRIMARY KEY)")
        yield from sql.unsafe(f"INSERT INTO {table} VALUES (1)")

        def holder():
            yield from sql.unsafe(f"SELECT id FROM {table} WHERE id = 1 FOR UPDATE")
            yield from sql("SELECT SLEEP(30)")

        fiber = yield from sql.with_transaction(fx.gen(holder)).fork()
        deadline = time.monotonic() + 10
        while (yield from fx.blocking(lambda: _take_lock_at_once(table))):
            assert time.monotonic() < deadline, "the transaction never took the lock"
            yield from fx.sleep("20 millis")
        yield from fx.sleep("200 millis")
        yield from fiber.interrupt()
        deadline = time.monotonic() + GONE_WITHIN
        while not (yield from fx.blocking(lambda: _take_lock_at_once(table))):
            assert time.monotonic() < deadline, "the row is still locked"
            yield from fx.sleep("50 millis")

    yield from _with_client(mysql_server, body, max_connections=2)


@testing.live(timeout="30 seconds")
def test_taking_part_of_a_slow_stream_ends_it_on_the_server(mysql_server: MysqlServer):
    """Ending a stream early must not wait for the server to send every row left."""
    source, marker = _marked(_SLOW_ROWS)

    def body():
        sql = yield from mysql.MysqlClient()
        first = yield from sql("SELECT CONNECTION_ID() AS id")
        started = time.monotonic()
        yield from sql.unsafe(source).stream.take(1).run_collect().timeout("20 seconds")
        assert time.monotonic() - started < 10
        yield from gone_soon(lambda: _running(marker))
        # Only the statement ended: the connection serves the next one.
        assert (yield from sql("SELECT 1 AS x").timeout("5 seconds")) == [{"x": 1}]
        rows = yield from sql("SELECT CONNECTION_ID() AS id")
        assert rows[0]["id"] == first[0]["id"]

    yield from _with_client(mysql_server, body, max_connections=1)


@testing.live(timeout="30 seconds")
def test_a_kill_that_cannot_be_sent_is_reported(
    mysql_server: MysqlServer, caplog: pytest.LogCaptureFixture
):
    """The statement then stays on the server, which nobody would otherwise learn."""
    user = f"u{uuid.uuid4().hex[:12]}"
    query_now(f"CREATE USER '{user}'@'%' IDENTIFIED BY 'gone'", root=True)
    sql_text, marker = _marked("SELECT SLEEP(2) AS {}")

    def body():
        sql = yield from mysql.MysqlClient()
        fiber = yield from sql.unsafe(sql_text).fork()
        yield from until_running(lambda: _running(marker))
        # Further logins fail, so the kill cannot get its connection.
        yield from fx.blocking(lambda: query_now(f"DROP USER '{user}'@'%'", root=True))
        yield from fiber.interrupt()

    url = redacted.make(f"mysql://{user}:gone@{mysql_server.host}:{mysql_server.port}")
    with caplog.at_level(logging.WARNING, logger="pyfect.sql.mysql"):
        yield from fx.scoped(fx.gen(body)).pipe(
            fx.provide(mysql.layer(mysql.MysqlClientConfig(url=url)))
        )
    assert any("KILL" in record.getMessage() for record in caplog.records)
