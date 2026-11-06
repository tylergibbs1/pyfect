"""Ports of Effect's ``sql-mysql2/test/MysqlClient.integration.test.ts`` and
``Client.integration.test.ts``, against the session's MySQL container
(``_mysql.mysql_server``; skipped without Docker).

Each test's docstring is the Effect test title; ``(pyfect)`` titles pin
the driver's own behavior. Adapted: tables are dropped first, since the
server is shared by every test of the session (Effect's container is the
file's own). "uses query when prepared statements are disabled" replaces
asyncmy's connection, as Effect mocks ``mysql2``'s pool, and records
which protocol each statement takes.
"""

from collections.abc import Callable, Generator
from typing import Any

import pytest

pytest.importorskip("asyncmy")

import asyncmy

import pyfect as fx
from pyfect import case, config, config_provider, redacted, testing
from pyfect.logger import Logger
from pyfect.logger import layer as logger_layer
from pyfect.reactivity import layer as reactivity_layer
from pyfect.sql import SqlClient, mysql
from pyfect.sql.error import AuthenticationError, SqlError, UniqueViolation
from pyfect.sql.statement import CurrentTransformer, Statement

from ._mysql import MysqlServer

type Body = Callable[[], Generator[Any, Any, Any]]


def _config(server: MysqlServer, **fields: Any) -> mysql.MysqlClientConfig:
    return mysql.MysqlClientConfig(url=server.url, **fields)


def _with_client(server: MysqlServer, body: Body, **fields: Any) -> fx.Effect[Any, Any]:
    return fx.scoped(fx.gen(body)).pipe(fx.provide(mysql.layer(_config(server, **fields))))


# --- MysqlClient ---------------------------------------------------------------


@testing.effect
def test_stream_returns_same_rows_as_direct_execution(mysql_server: MysqlServer):
    """stream returns same rows as direct execution"""

    def body():
        sql = yield from mysql.MysqlClient()
        yield from sql("DROP TABLE IF EXISTS stream_regression_test")
        yield from sql(
            "CREATE TABLE stream_regression_test "
            "(id INT PRIMARY KEY AUTO_INCREMENT, value VARCHAR(255))"
        )
        test_data = [{"value": f"row_{i}"} for i in range(100)]
        yield from sql("INSERT INTO stream_regression_test {}", sql.insert(test_data))
        direct = yield from sql("SELECT * FROM stream_regression_test")
        streamed = yield from sql("SELECT * FROM stream_regression_test").stream.run_collect()
        yield from sql("DROP TABLE stream_regression_test")
        assert len(streamed) == len(direct), (
            f"Stream returned {len(streamed)} rows, expected {len(direct)}"
        )
        assert list(streamed) == list(direct)

    yield from _with_client(mysql_server, body)


class _FakeCursor:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls
        self.description: Any = None
        self.rowcount = 0
        self.lastrowid = 0

    async def execute(self, query: str) -> int:
        self._calls.append("query")
        return 0

    async def fetchall(self) -> list[Any]:
        return []

    async def nextset(self) -> None:
        return None

    async def close(self) -> None:
        return None


class _FakeResult:
    description = None
    rows = None
    affected_rows = 0
    insert_id = 0


class _FakeStatement:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    async def execute(self, args: tuple[object, ...]) -> _FakeResult:
        self._calls.append("execute")
        return _FakeResult()

    async def close(self) -> None:
        return None


class _FakeConnection:
    connected = True
    server_status = 0

    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def escape(self, obj: object) -> str:
        return repr(obj)

    def thread_id(self) -> int:
        return 1

    def cursor(self, cursor: type[Any]) -> _FakeCursor:
        return _FakeCursor(self._calls)

    async def prepare(self, query: str) -> _FakeStatement:
        return _FakeStatement(self._calls)

    async def ensure_closed(self) -> None:
        return None

    def close(self) -> None:
        return None


def _protocols(monkeypatch: pytest.MonkeyPatch, **fields: Any) -> list[str]:
    """The protocol of each statement a client of ``fields`` runs, after
    its connection check."""
    calls: list[str] = []

    async def connect(**_options: Any) -> _FakeConnection:
        return _FakeConnection(calls)

    monkeypatch.setattr(asyncmy, "connect", connect)

    def body():
        sql = yield from mysql.MysqlClient()
        calls.clear()
        yield from sql("SELECT {}", 1)
        yield from sql("SELECT {}", 1).values
        yield from sql.unsafe("SELECT ?", [1]).raw

    layer = mysql.layer(mysql.MysqlClientConfig(**fields))
    fx.run_sync(fx.scoped(fx.gen(body)).pipe(fx.provide(layer)).or_die())
    return calls


def test_uses_query_when_prepared_statements_are_disabled(monkeypatch: pytest.MonkeyPatch):
    """uses query when prepared statements are disabled"""
    assert _protocols(monkeypatch, disable_prepared_statements=True) == ["query"] * 3


def test_prepares_statements_by_default(monkeypatch: pytest.MonkeyPatch):
    """(pyfect) statements run prepared unless disabled, as mysql2's ``execute``"""
    assert _protocols(monkeypatch) == ["execute"] * 3


# --- sql (Client.integration.test.ts) -------------------------------------------------


@testing.effect
def test_releases_completed_nested_savepoints(mysql_server: MysqlServer):
    """releases completed nested savepoints"""

    def body():
        sql = yield from SqlClient()
        yield from sql("DROP TABLE IF EXISTS savepoint_release")
        yield from sql("CREATE TABLE savepoint_release (value INTEGER)")

        def transaction():
            for rollback in (False, True):
                nested = sql("INSERT INTO savepoint_release VALUES (1)").and_then(
                    fx.fail("rollback") if rollback else fx.void
                )
                yield from sql.with_transaction(nested).ignore()
                error = yield from sql("RELEASE SAVEPOINT effect_sql_1").unprepared.flip()
                assert isinstance(error, SqlError)

        yield from sql.with_transaction(fx.gen(transaction))
        assert (yield from sql("SELECT value FROM savepoint_release")) == [{"value": 1}]

    yield from _with_client(mysql_server, body)


@testing.effect
def test_in_helper_with_an_empty_list(mysql_server: MysqlServer):
    """in helper with an empty list"""

    def body():
        sql = yield from SqlClient()
        yield from sql("DROP TABLE IF EXISTS empty_in")
        yield from sql("CREATE TABLE empty_in (id INTEGER)")
        yield from sql("INSERT INTO empty_in VALUES (1)")
        assert (yield from sql("SELECT id FROM empty_in WHERE id IN {}", sql.in_([]))) == []
        assert (yield from sql("SELECT id FROM empty_in WHERE id NOT IN {}", sql.in_([]))) == [
            {"id": 1}
        ]

    yield from _with_client(mysql_server, body)


@testing.effect
def test_tranformers(mysql_server: MysqlServer):
    """tranformers"""
    logs: list[object] = []

    def log_statement(statement: Statement[Any], *_: Any) -> fx.Effect[Statement[Any]]:
        query, params = statement.compile()
        return (
            fx.log("executing sql").annotate_logs({"query": query, "params": params}).as_(statement)
        )

    def body():
        sql = yield from SqlClient()
        recording = logger_layer([Logger.make(lambda options: logs.append(options.message))])
        result = yield from sql("SELECT 1 + 1 AS result").pipe(fx.provide(recording))
        assert result == [{"result": 2}]
        assert logs == [("executing sql",)]

    yield from _with_client(mysql_server, body).pipe(
        fx.provide_service(CurrentTransformer, log_statement)
    )


# --- (pyfect) the driver --------------------------------------------------------------


@testing.effect
def test_results_follow_mysql2(mysql_server: MysqlServer):
    """(pyfect) rows for a query, a ResultSetHeader through raw for a
    statement without rows, a list of each statement's result for several,
    and [] as the rows of a statement without any"""

    def body():
        sql = yield from SqlClient()
        yield from sql("DROP TABLE IF EXISTS results_shape")
        yield from sql("CREATE TABLE results_shape (id INT PRIMARY KEY AUTO_INCREMENT, v TEXT)")
        header = yield from sql("INSERT INTO results_shape (v) VALUES ('a'), ('b')").raw
        assert header == mysql.ResultSetHeader(affected_rows=2, insert_id=1)
        assert (yield from sql("UPDATE results_shape SET v = 'c'")) == []
        both = yield from sql(
            "UPDATE results_shape SET v = 'd' WHERE id = 1; SELECT v FROM results_shape"
        ).unprepared
        assert both == [
            mysql.ResultSetHeader(affected_rows=1, insert_id=0),
            [{"v": "d"}, {"v": "c"}],
        ]
        assert (yield from sql("SELECT id, v FROM results_shape").values) == [(1, "d"), (2, "c")]

    yield from _with_client(mysql_server, body)


@pytest.mark.parametrize("disable", [False, True], ids=["prepared", "text"])
@testing.effect
def test_values_round_trip(mysql_server: MysqlServer, disable: bool):
    """(pyfect) parameters and columns keep their Python types over both
    protocols; a ``?`` in a quoted string is not a placeholder"""
    from datetime import datetime
    from decimal import Decimal

    table = f"round_trip_{'text' if disable else 'prepared'}"
    values = {
        "i": 2**40,
        "s": "it's ?",
        "b": b"\x00\xff",
        "n": None,
        "d": Decimal("1.25"),
        "t": datetime(2024, 5, 6, 7, 8, 9, 123000),
        "j": '{"a": [1]}',
    }

    def body():
        sql = yield from SqlClient()
        yield from sql("DROP TABLE IF EXISTS {}", sql.identifier(table))
        yield from sql(
            "CREATE TABLE {} (i BIGINT, s TEXT, b BLOB, n INT, d DECIMAL(10, 2), "
            "t DATETIME(6), j JSON)",
            sql.identifier(table),
        )
        yield from sql("INSERT INTO {} {}", sql.identifier(table), sql.insert(values))
        rows = yield from sql(
            "SELECT *, '?' AS q FROM {} WHERE s = {}", sql.identifier(table), "it's ?"
        )
        assert rows == [{**values, "j": {"a": [1]}, "q": "?"}]

    yield from _with_client(mysql_server, body, disable_prepared_statements=disable)


@testing.effect
def test_transforms_names(mysql_server: MysqlServer):
    """(pyfect) transform_query_names / transform_result_names rename
    identifiers and result columns"""

    def body():
        sql = yield from SqlClient()
        yield from sql("DROP TABLE IF EXISTS transform_names")
        yield from sql("CREATE TABLE transform_names (user_id INT, full_name TEXT)")
        yield from sql(
            "INSERT INTO {} {}",
            sql.identifier("transformNames"),
            sql.insert({"userId": 1, "fullName": "Ada"}),
        )
        assert (yield from sql("SELECT * FROM transform_names")) == [
            {"userId": 1, "fullName": "Ada"}
        ]
        streamed = yield from sql("SELECT * FROM transform_names").stream.run_collect()
        assert list(streamed) == [{"userId": 1, "fullName": "Ada"}]

    yield from _with_client(
        mysql_server,
        body,
        transform_query_names=case.camel_to_snake,
        transform_result_names=case.snake_to_camel,
    )


@testing.effect
def test_rolls_back_failed_transactions(mysql_server: MysqlServer):
    """(pyfect) a failed transaction rolls back; a unique violation names
    its key"""

    def body():
        sql = yield from SqlClient()
        yield from sql("DROP TABLE IF EXISTS tx_rollback")
        yield from sql("CREATE TABLE tx_rollback (id INT PRIMARY KEY)")
        yield from sql("INSERT INTO tx_rollback VALUES (1)")

        def transaction():
            yield from sql("INSERT INTO tx_rollback VALUES (2)")
            yield from sql("INSERT INTO tx_rollback VALUES (1)")

        error = yield from sql.with_transaction(fx.gen(transaction)).flip()
        assert isinstance(error.reason, UniqueViolation)
        assert error.reason.constraint == "tx_rollback.PRIMARY"
        assert error.reason.operation == "execute"
        assert (yield from sql("SELECT id FROM tx_rollback")) == [{"id": 1}]

    yield from _with_client(mysql_server, body)


@testing.live(timeout=30)
def test_interrupting_a_statement_ends_it_on_the_server(mysql_server: MysqlServer):
    """(pyfect) interrupting a statement ends it on the server and frees
    its locks; the pool replaces the connection"""

    def body():
        sql = yield from SqlClient()
        yield from sql("DROP TABLE IF EXISTS interrupted_locks")
        yield from sql("CREATE TABLE interrupted_locks (id INT PRIMARY KEY)")
        yield from sql("INSERT INTO interrupted_locks VALUES (1)")

        def holder():
            yield from sql("SELECT id FROM interrupted_locks WHERE id = 1 FOR UPDATE")
            yield from sql("SELECT SLEEP(60)")

        fiber = yield from sql.with_transaction(fx.gen(holder)).fork()
        yield from fx.sleep(0.5)
        yield from fiber.interrupt()
        yield from fiber.await_exit()
        # The row lock is free again at once (innodb_lock_wait_timeout is 50s).
        locked = sql("SELECT id FROM interrupted_locks WHERE id = 1 FOR UPDATE")
        assert (yield from sql.with_transaction(locked).timeout(5)) == [{"id": 1}]
        sleeping = yield from sql(
            "SELECT COUNT(*) AS n FROM information_schema.processlist "
            "WHERE info = 'SELECT SLEEP(60)'"
        )
        assert sleeping == [{"n": 0}]

    yield from _with_client(mysql_server, body, max_connections=2)


@testing.effect
def test_ending_a_stream_early_keeps_the_connection(mysql_server: MysqlServer):
    """(pyfect) a stream taken in part reads past the rest, and the
    connection serves the next statement"""

    def body():
        sql = yield from SqlClient()
        first = (
            yield from sql(
                "WITH RECURSIVE n (i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 1000) "
                "SELECT i FROM n"
            )
            .stream.take(3)
            .run_collect()
        )
        assert list(first) == [{"i": 1}, {"i": 2}, {"i": 3}]
        assert (yield from sql("SELECT CONNECTION_ID() = CONNECTION_ID() AS ok")) == [{"ok": 1}]

    yield from _with_client(mysql_server, body, max_connections=1)


@testing.effect
def test_layer_config_reads_the_config(mysql_server: MysqlServer):
    """(pyfect) layer_config reads each field from the ConfigProvider"""

    def body():
        sql = yield from mysql.MysqlClient()
        assert (yield from sql("SELECT DATABASE() AS db")) == [{"db": "test"}]
        assert sql.config.url is not None

    provider = config_provider.from_unknown({"DATABASE_URL": mysql_server.uri()})
    layer = mysql.layer_config({"url": config.redacted("DATABASE_URL")})
    yield from (
        fx.scoped(fx.gen(body))
        .pipe(fx.provide(layer))
        .pipe(fx.provide(config_provider.layer(provider)))
    )


def test_connects_with_separate_fields(mysql_server: MysqlServer):
    """(pyfect) host, port, database, username and password connect without
    a URL, and set the span attributes"""
    config = mysql.MysqlClientConfig(
        host=mysql_server.host,
        port=mysql_server.port,
        database="test",
        username="test",
        password=redacted.make("test"),
    )

    def body():
        sql = yield from mysql.MysqlClient()
        assert (yield from sql("SELECT CURRENT_USER() LIKE 'test@%' AS ok")) == [{"ok": 1}]
        attributes = dict(sql.span_attributes)
        assert attributes["db.system.name"] == "mysql"
        assert attributes["db.namespace"] == "test"
        assert attributes["server.port"] == mysql_server.port

    fx.run_sync(fx.scoped(fx.gen(body)).pipe(fx.provide(mysql.layer(config))).or_die())


def test_wrong_password_is_an_authentication_error(mysql_server: MysqlServer):
    """(pyfect) the connection check reports a rejected login as an
    AuthenticationError (errno 1045)"""
    config = mysql.MysqlClientConfig(
        url=redacted.make(f"mysql://test:wrong@{mysql_server.host}:{mysql_server.port}/test")
    )
    failed = fx.scoped(mysql.make(config)).flip().or_die()
    error = fx.run_sync(failed.pipe(fx.provide(reactivity_layer)))
    assert isinstance(error.reason, AuthenticationError)
    assert error.reason.operation == "connect"


@pytest.mark.parametrize(
    "url",
    ["postgres://u@h/db", "mysql://u@h/db?ssl=true", "mysql:///db", "mysql://u@h:99999/db"],
)
def test_rejects_urls_it_cannot_follow(url: str):
    """(pyfect) a URL that is not ``mysql://host...`` (or carries options)
    fails when the config is made"""
    with pytest.raises(ValueError):
        mysql.MysqlClientConfig(url=redacted.make(url))


@testing.live(timeout=30)
def test_a_stream_failing_mid_result_keeps_the_connection(mysql_server: MysqlServer):
    """(pyfect) a statement failing after its columns (here past
    cte_max_recursion_depth) fails the stream, and the connection serves
    the next statement and the transaction it is in"""
    failing = (
        "WITH RECURSIVE n (i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 5000) "
        "SELECT i FROM n"
    )

    def body():
        sql = yield from SqlClient()

        def transaction():
            error = yield from sql(failing).stream.run_collect().flip()
            assert isinstance(error, SqlError)
            assert error.reason.operation == "stream"
            return (yield from sql("SELECT CONNECTION_ID() AS id"))

        inside = yield from sql.with_transaction(fx.gen(transaction)).timeout(5)
        assert (yield from sql("SELECT CONNECTION_ID() AS id").timeout(5)) == inside

    yield from _with_client(mysql_server, body, max_connections=1)


@testing.live(timeout=30)
def test_interrupting_a_stream_ends_it_on_the_server(mysql_server: MysqlServer):
    """(pyfect) interrupting a stream still sending rows ends at once, and
    the pool serves the next statement on a new connection"""
    slow = (
        "SELECT a.ordinal_position, SLEEP(0.001) FROM information_schema.columns a, "
        "information_schema.columns b"
    )

    def body():
        sql = yield from SqlClient()
        fiber = yield from sql(slow).stream.run_drain().fork()
        yield from fx.sleep(0.5)
        yield from fiber.interrupt().timeout(5)
        assert (yield from sql("SELECT 1 AS x").timeout(5)) == [{"x": 1}]

    yield from _with_client(mysql_server, body, max_connections=1)


@pytest.mark.parametrize("disable", [False, True], ids=["prepared", "text"])
@testing.effect
def test_dicts_and_lists_bind_as_json(mysql_server: MysqlServer, disable: bool):
    """(pyfect) a dict or list parameter is sent as its JSON text, as
    mysql2's ``execute`` does, over both protocols"""

    def body():
        sql = yield from SqlClient()
        rows = yield from sql(
            "SELECT CAST({} AS JSON) AS d, CAST({} AS JSON) AS l",
            {"a": [1, "x"]},
            [1, None],
        )
        assert rows == [{"d": {"a": [1, "x"]}, "l": [1, None]}]

    yield from _with_client(mysql_server, body, disable_prepared_statements=disable)


@testing.effect
def test_no_backslash_escapes_binds_text_as_the_server_reads_it(mysql_server: MysqlServer):
    """(pyfect) under ``NO_BACKSLASH_ESCAPES`` a text statement's literals and
    placeholders follow the mode: a backslash is plain text, also in the
    parameters, whichever session mode was set last"""

    def body():
        sql = yield from SqlClient()
        yield from sql("SET SESSION sql_mode = 'NO_BACKSLASH_ESCAPES'").unprepared
        rows = yield from sql(
            "SELECT 'a\\' AS plain, {} AS bound, {} AS quote", "b\\", "' OR 1=1 -- "
        )
        yield from sql("SET SESSION sql_mode = ''").unprepared
        return rows

    rows = yield from _with_client(
        mysql_server, body, disable_prepared_statements=True, max_connections=1
    )
    assert rows == [{"plain": "a\\", "bound": "b\\", "quote": "' OR 1=1 -- "}]
