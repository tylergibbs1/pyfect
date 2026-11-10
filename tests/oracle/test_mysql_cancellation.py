"""Ports of Effect's ``sql-mysql2/test/Cancellation.integration.test.ts``, and of the three
"with a fake mysql2 pool" titles of ``sql-mysql2/test/MysqlClient.integration.test.ts``,
against the session's MySQL container (``_mysql.mysql_server``; skipped without Docker).

Each test's docstring is the Effect test title. Every test uses a pool of one connection, so
a statement or lease left behind by an interrupted fiber blocks the follow-up query.

Adapted: Effect's three fake-pool titles replace mysql2's pool and its ``Readable`` streams to
place the end of a streamed statement at each point of the cancellation; here they run on
the server, sweeping the same yield budgets, and check what Effect checks: the connection is
kept (the same ``CONNECTION_ID()``), a statement queued behind the stream is not killed, and
the next statement only runs once the streamed one has ended. "gives a shared connection back
when the kill connection cannot be created" makes the driver's kill connection fail to open,
as Effect's mock makes ``createConnection`` throw.
"""

import time
from collections.abc import Callable, Generator
from typing import Any

import pytest

pytest.importorskip("asyncmy")

import pyfect as fx
from pyfect import testing
from pyfect.scheduler import MaxOpsBeforeYield
from pyfect.sql import SqlClient, mysql
from pyfect.sql.mysql import _asyncmy

from ._mysql import MysqlServer

type Body = Callable[[], Generator[Any, Any, Any]]


def _single_connection(server: MysqlServer, body: Body) -> fx.Effect[Any, Any]:
    config = mysql.MysqlClientConfig(url=server.url, max_connections=1)
    return fx.scoped(fx.gen(body)).pipe(fx.provide(mysql.layer(config)))


@testing.live(timeout="30 seconds")
def test_interrupting_a_running_statement_kills_it(mysql_server: MysqlServer):
    """interrupting a running statement kills it"""

    def body():
        sql = yield from SqlClient()
        slow = yield from sql("SELECT SLEEP(10)").fork(start_immediately=True)
        yield from fx.sleep("200 millis")
        rows = yield from (
            slow.interrupt()
            .and_then(
                sql(
                    "SELECT COUNT(*) AS running FROM information_schema.processlist "
                    "WHERE info = 'SELECT SLEEP(10)'"
                )
            )
            .timeout("2 seconds")
        )
        assert rows == [{"running": 0}]

    yield from _single_connection(mysql_server, body)


@testing.live(timeout="30 seconds")
def test_interrupting_a_pending_reservation_returns_promptly(mysql_server: MysqlServer):
    """interrupting a pending reservation returns promptly and releases the late connection"""

    def body():
        sql = yield from SqlClient()
        busy = yield from sql("SELECT SLEEP(3)").fork(start_immediately=True)
        yield from fx.sleep("200 millis")
        waiting = yield from fx.scoped(sql.reserve).fork(start_immediately=True)
        yield from waiting.interrupt().timeout("1 second")

        yield from busy.join()
        rows = yield from sql("SELECT 1 AS value").timeout("2 seconds")
        assert rows == [{"value": 1}]

    yield from _single_connection(mysql_server, body)


@testing.live(timeout="30 seconds")
def test_ending_a_stream_early_stops_the_statement(mysql_server: MysqlServer):
    """ending a stream early stops the statement"""

    def body():
        sql = yield from SqlClient()
        # Rows arrive before the server reaches the SLEEP, so the stream can end
        # while the statement is still running.
        rows, next_ = yield from fx.all(
            sql(
                "WITH RECURSIVE seq (n) AS "
                "(SELECT 1 UNION ALL SELECT n + 1 FROM seq WHERE n < 100000) "
                "SELECT /*+ SET_VAR(cte_max_recursion_depth = 100000) */ n, "
                "IF(n = 100000, SLEEP(10), 0) AS slept FROM seq"
            )
            .stream.take(5)
            .run_collect(),
            sql("SELECT 1 AS value"),
        ).timeout("2 seconds")
        assert len(rows) == 5
        assert next_ == [{"value": 1}]

    yield from _single_connection(mysql_server, body)


@testing.live(timeout="30 seconds")
def test_ending_a_stream_whose_remaining_rows_are_already_buffered_keeps_the_connection(
    mysql_server: MysqlServer,
):
    """ending a stream whose remaining rows are already buffered keeps the connection"""

    def body():
        sql = yield from SqlClient()
        for size in (1400, 1500, 1600, 1700):
            before, _, after = yield from fx.all(
                sql("SELECT CONNECTION_ID() AS id"),
                sql(
                    "WITH RECURSIVE seq (n) AS "
                    "(SELECT 1 UNION ALL SELECT n + 1 FROM seq WHERE n < {}) "
                    "SELECT /*+ SET_VAR(cte_max_recursion_depth = 100000) */ n, "
                    "REPEAT('x', 100) AS padding FROM seq",
                    size,
                )
                .stream.map_effect(lambda row: fx.sleep("200 millis").as_(row))
                .take(1)
                .run_collect(),
                sql("SELECT CONNECTION_ID() AS id"),
            ).timeout("2 seconds")
            assert after == before

    yield from _single_connection(mysql_server, body)


@testing.live(timeout="30 seconds")
def test_a_stream_consumer_can_run_statements_on_the_same_connection(
    mysql_server: MysqlServer,
):
    """a stream consumer can run statements on the same connection once the streamed statement ends"""  # noqa: E501

    def body():
        sql = yield from SqlClient()
        rows = yield from sql.with_transaction(
            sql("SELECT 1 AS value")
            .stream.map_effect(lambda _: sql("SELECT 2 AS value"))
            .run_collect()
        ).timeout("2 seconds")
        assert list(rows) == [[{"value": 2}]]

    yield from _single_connection(mysql_server, body)


@testing.live(timeout="30 seconds")
def test_interrupting_a_statement_queued_on_a_shared_connection_leaves_the_running_one_alone(
    mysql_server: MysqlServer,
):
    """interrupting a statement queued on a shared connection leaves the running one alone"""

    def body():
        sql = yield from SqlClient()
        yield from sql("DROP TABLE IF EXISTS cancel_queued")
        yield from sql("CREATE TABLE cancel_queued (id INT)")

        def in_transaction():
            running = yield from sql("SELECT SLEEP(1) AS first").fork(start_immediately=True)
            yield from fx.sleep("200 millis")
            queued = yield from sql("INSERT INTO cancel_queued VALUES (1)").fork(
                start_immediately=True
            )
            yield from fx.sleep("50 millis")
            yield from queued.interrupt()
            return (yield from running.join())

        first = yield from sql.with_transaction(fx.gen(in_transaction))
        # SLEEP returns 1 when it is killed and 0 when it runs to completion.
        assert first == [{"first": 0}]
        assert (yield from sql("SELECT id FROM cancel_queued")) == []
        yield from sql("DROP TABLE cancel_queued")

    yield from _single_connection(mysql_server, body)


# --- MysqlClient.integration.test.ts, "with a fake mysql2 pool" ----------------------------

_BUDGETS = (3, 4, 5, 6, 7, 8)


@testing.live(timeout="60 seconds")
def test_keeps_the_connection_when_a_cancelled_stream_settles_before_its_kill_is_registered(
    mysql_server: MysqlServer,
):
    """keeps the connection when a cancelled stream settles before its kill is registered

    ``sql-mysql2/test/MysqlClient.integration.test.ts``"""

    def body():
        sql = yield from SqlClient()
        [before] = yield from sql("SELECT CONNECTION_ID() AS id")
        for budget in _BUDGETS:
            queued: list[fx.Fiber[Any, Any]] = []

            def queue(_: object, queued: list[fx.Fiber[Any, Any]] = queued) -> fx.Effect[None]:
                # Queue a statement on the same connection while the stream runs.
                return sql("SELECT 2 AS value").fork(start_immediately=True).map(queued.append)

            def in_transaction(budget: int = budget, queued: list[fx.Fiber[Any, Any]] = queued):
                yield from (
                    sql("SELECT 1 AS value")
                    .stream.tap(queue)
                    .take(1)
                    .run_collect()
                    .pipe(fx.provide_service(MaxOpsBeforeYield, budget))
                )
                return (yield from queued[0].join())

            # A kill reaching the queued statement would fail it.
            rows = yield from sql.with_transaction(fx.gen(in_transaction)).timeout("5 seconds")
            assert rows == [{"value": 2}], f"budget {budget}"
            [after] = yield from sql("SELECT CONNECTION_ID() AS id")
            assert after == before, f"budget {budget}: the connection was replaced"

    yield from _single_connection(mysql_server, body)


@testing.live(timeout="60 seconds")
def test_kills_a_streams_statement_when_interrupted_before_the_first_row(
    mysql_server: MysqlServer,
):
    """kills a stream's statement when interrupted before the first row

    ``sql-mysql2/test/MysqlClient.integration.test.ts``"""

    def body():
        sql = yield from SqlClient()
        for budget in _BUDGETS:

            def in_transaction(budget: int = budget):
                consumer = yield from (
                    sql("SELECT SLEEP(5) AS slept")
                    .stream.run_drain()
                    .pipe(fx.provide_service(MaxOpsBeforeYield, budget))
                    .fork()
                )
                yield from fx.sleep("100 millis")
                started = time.monotonic()
                yield from consumer.interrupt()
                yield from consumer.await_exit()
                rows = yield from sql("SELECT 2 AS value")
                return rows, time.monotonic() - started

            rows, elapsed = yield from sql.with_transaction(fx.gen(in_transaction)).timeout(
                "10 seconds"
            )
            assert rows == [{"value": 2}], f"budget {budget}"
            # The streamed statement was killed rather than waited for.
            assert elapsed < 4, f"budget {budget}: {elapsed}"

    yield from _single_connection(mysql_server, body)


@testing.live(timeout="60 seconds")
def test_gives_a_shared_connection_back_when_the_kill_connection_cannot_be_created(
    mysql_server: MysqlServer, monkeypatch: pytest.MonkeyPatch
):
    """gives a shared connection back when the kill connection cannot be created

    ``sql-mysql2/test/MysqlClient.integration.test.ts``"""

    async def unavailable(_options: object) -> Any:
        raise OSError("SSH tunnel unavailable")

    def body():
        sql = yield from SqlClient()
        conn = yield from sql.reserve
        # The pooled connection is open; only the kill connection fails to open.
        monkeypatch.setattr(_asyncmy, "connect", unavailable)
        # Unless it is killed, the statement ends on its own after 300 ms.
        consumer = (
            yield from conn.execute_stream("SELECT SLEEP(0.3) AS value", [], None)
            .run_drain()
            .fork()
        )
        yield from fx.sleep("20 millis")
        yield from consumer.interrupt()
        # The connection may be retired instead of reused, so the statement
        # only has to settle rather than succeed.
        settled = yield from conn.execute("SELECT 2 AS value", [], None).exit().timeout("2 seconds")
        assert isinstance(settled, fx.Success | fx.Failure)

    yield from _single_connection(mysql_server, body)
