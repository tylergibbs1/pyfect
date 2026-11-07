"""``(pyfect)`` tests of the ClickHouse client on a real server (the
session's ``clickhouse/clickhouse-server`` container, ``_clickhouse``;
skipped without Docker or httpx): parameters of every inferred type,
streams and the error a server writes into a body it began, interrupts
killing the query, commands and inserts, migrations, error codes,
settings, query ids and the config's URL.

Effect has no tests against a server; these pin what its client does on
one, and found that its migrator records migrations with ``INSERT ...
VALUES`` run as a query, which a server rejects (``FORMAT JSON`` is read
as data): pyfect's records them with ``INSERT ... SELECT``.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Callable, Generator
from datetime import UTC, date, datetime
from typing import Any

import pytest

import pyfect as fx
from pyfect import case, redacted, stream
from pyfect.sql import SqlClient, clickhouse
from pyfect.sql.clickhouse import migrator
from pyfect.sql.error import AuthenticationError, SqlError, SqlSyntaxError, UnknownError

from ._clickhouse import PASSWORD, USER, ClickhouseServer, query_now

type Body = Callable[[], Generator[Any, Any, Any]]


def _config(server: ClickhouseServer, **fields: Any) -> clickhouse.ClickhouseClientConfig:
    fields.setdefault("url", server.url)
    fields.setdefault("username", USER)
    fields.setdefault("password", redacted.make(PASSWORD))
    return clickhouse.ClickhouseClientConfig(**fields)


def _on_server(server: ClickhouseServer, body: Body, **fields: Any) -> Any:
    program = fx.scoped(fx.gen(body)).pipe(fx.provide(clickhouse.layer(_config(server, **fields))))
    return fx.run_blocking(program.timeout("1 minute").or_die())


def _table(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def test_parameters_of_every_inferred_type_round_trip(clickhouse_server: ClickhouseServer):
    """(pyfect) parameters of every inferred type round trip"""
    when = datetime(2024, 1, 15, 14, 30, tzinfo=UTC)
    precise = datetime(2024, 1, 15, 14, 30, 0, 123456, tzinfo=UTC)
    before_epoch = datetime(1969, 12, 31, 23, 59, 58, 500000, tzinfo=UTC)

    def body():
        sql = yield from clickhouse.ClickhouseClient()
        rows = yield from sql(
            "SELECT {} AS i, {} AS f, {} AS s, {} AS b, {} AS n, {} AS d, {} AS p, {} AS day,"
            " {} AS a, {} AS m, {} AS t, {} AS e, {} AS old",
            42,
            1.5,
            "it's\ta\nline\\",
            True,
            sql.param("Nullable(Int32)", None),
            when,
            precise,
            date(2024, 1, 15),
            [1, 2, 3],
            sql.param("Map(String, Int32)", {"a": 1}),
            sql.param(
                "Tuple(Int32, String, Nullable(String))", clickhouse.TupleParam((7, "x", None))
            ),
            sql.param("Array(Date)", [when]),
            before_epoch,
        )
        assert rows == [
            {
                "i": 42,
                "f": 1.5,
                "s": "it's\ta\nline\\",
                "b": True,
                "n": None,
                "d": "2024-01-15 14:30:00",
                "p": "2024-01-15 14:30:00.123456",
                "day": "2024-01-15",
                "a": [1, 2, 3],
                "m": {"a": 1},
                "t": [7, "x", None],
                "e": ["2024-01-15"],
                "old": "1969-12-31 23:59:58.500000",
            }
        ]
        values = yield from sql("SELECT {} AS x, {} AS y", 1, "a").values
        assert values == [(1, "a")]

    _on_server(clickhouse_server, body)


def test_a_naive_datetime_or_an_unsupported_value_is_a_defect(
    clickhouse_server: ClickhouseServer,
):
    """(pyfect) a naive datetime or an unsupported value is a defect"""

    def body():
        sql = yield from clickhouse.ClickhouseClient()
        for value in (datetime(2024, 1, 1), object()):
            exit_ = yield from sql("SELECT {}", value).exit()
            assert isinstance(exit_, fx.exit.Failure)
            assert isinstance(exit_.cause.squash(), TypeError)

    _on_server(clickhouse_server, body)


_FAILS_LATE = "SELECT number, throwIf(number = 50, 'boom') AS t FROM numbers(60)"
# A block a row and no parallel formatting: the server sends the first rows
# (status 200) before the error, which then ends the body.
_SENT_EARLY: dict[str, int] = {"max_block_size": 1, "output_format_parallel_formatting": 0}


def test_streams_rows_and_fails_with_the_error_ending_the_body(
    clickhouse_server: ClickhouseServer,
):
    """(pyfect) streams rows, and fails with the error that ends a body"""

    def body():
        sql = yield from clickhouse.ClickhouseClient()
        count = yield from sql("SELECT number FROM numbers(2000)").stream.run_count()
        assert count == 2000
        failing = sql(_FAILS_LATE)
        collected = failing.stream.run_collect()
        error = yield from sql.with_clickhouse_settings(collected, _SENT_EARLY).flip()
        assert isinstance(error, SqlError)
        assert isinstance(error.reason, UnknownError)
        cause = error.reason.cause
        assert isinstance(cause, clickhouse.ClickhouseError)
        assert cause.code == 395
        assert cause.type == "FUNCTION_THROW_IF_VALUE_IS_NON_ZERO"

    _on_server(clickhouse_server, body)


def test_a_query_fails_with_the_error_ending_its_body(clickhouse_server: ClickhouseServer):
    """(pyfect) a query (FORMAT JSON) fails with the error that ends its body"""

    def body():
        sql = yield from clickhouse.ClickhouseClient()
        failing = sql(_FAILS_LATE)
        for statement in (failing, failing.values):
            error = yield from sql.with_clickhouse_settings(statement, _SENT_EARLY).flip()
            assert isinstance(error, SqlError)
            cause = error.reason.cause
            assert isinstance(cause, clickhouse.ClickhouseError)
            assert cause.code == 395

    _on_server(clickhouse_server, body)


def _running(query_id: str) -> bool:
    found = query_now(f"SELECT count() FROM system.processes WHERE query_id = '{query_id}'")
    return found.strip() != "0"


def test_interrupting_a_query_kills_it_on_the_server(clickhouse_server: ClickhouseServer):
    """(pyfect) interrupting a query kills it on the server"""
    query_id = f"pyfect-kill-{uuid.uuid4().hex}"

    def body():
        sql = yield from clickhouse.ClickhouseClient()
        endless = sql("SELECT sum(number) FROM numbers(100000000000)")
        fiber = yield from sql.with_query_id(endless, query_id).fork()
        for _ in range(100):
            if _running(query_id):
                break
            yield from fx.sleep("50 millis")
        assert _running(query_id)
        yield from fiber.interrupt()

    _on_server(clickhouse_server, body)
    deadline = time.monotonic() + 10
    while _running(query_id) and time.monotonic() < deadline:
        time.sleep(0.1)
    assert not _running(query_id)


def test_commands_and_inserts(clickhouse_server: ClickhouseServer):
    """(pyfect) as_command runs INSERT ... VALUES; insert_query sends rows, a
    CSV body and a stream"""
    table = _table("people")

    def body():
        sql = yield from clickhouse.ClickhouseClient()
        yield from sql.as_command(
            sql(
                "CREATE TABLE {} (id Int32, name String, seen DateTime) ENGINE = MergeTree"
                " ORDER BY id",
                sql.identifier(table),
            )
        )
        rows = [{"id": 1, "name": "Ada", "seen": datetime(2024, 1, 15, tzinfo=UTC)}]
        yield from sql.as_command(sql("INSERT INTO {} {}", sql.identifier(table), sql.insert(rows)))
        inserted = yield from sql.insert_query(
            table=table, values=[{"id": 2, "name": "Grace", "seen": rows[0]["seen"]}]
        )
        assert inserted.executed
        assert not (yield from sql.insert_query(table=table, values=[])).executed
        yield from sql.insert_query(
            table=table, values=b"3,Linus,2024-01-15 00:00:00\n", format="CSV"
        )
        yield from sql.insert_query(
            table=table,
            values=stream.from_iterable([{"id": 4, "name": "Barbara"}]),
            columns=["id", "name"],
        )
        found = yield from sql("SELECT id, name FROM {} ORDER BY id", sql.identifier(table))
        assert found == [
            {"id": 1, "name": "Ada"},
            {"id": 2, "name": "Grace"},
            {"id": 3, "name": "Linus"},
            {"id": 4, "name": "Barbara"},
        ]
        result = yield from sql.as_command(sql("SELECT 1").raw)
        assert isinstance(result, clickhouse.CommandResult)
        raw = yield from sql("SELECT 1 AS x").raw
        assert isinstance(raw, clickhouse.ResultSet)
        assert (yield from raw.json())["data"] == [{"x": 1}]

    _on_server(clickhouse_server, body)


def test_a_statement_without_output_gives_no_rows(clickhouse_server: ClickhouseServer):
    """(pyfect) a statement without output gives no rows"""
    table = _table("quiet")

    def body():
        sql = yield from clickhouse.ClickhouseClient()
        name = sql.identifier(table)
        created = yield from sql("CREATE TABLE {} (id Int32) ENGINE = MergeTree ORDER BY id", name)
        assert created == []
        assert (yield from sql("INSERT INTO {} SELECT {}", name, 1)) == []
        assert (yield from sql("SELECT id FROM {}", name)) == [{"id": 1}]

    _on_server(clickhouse_server, body)


def test_migrations_run_and_are_recorded(clickhouse_server: ClickhouseServer):
    """(pyfect) migrations run on a server and are recorded once"""
    ledger = _table("migrations")
    table = _table("migrated")

    def body():
        sql = yield from SqlClient()
        create = sql.as_command if isinstance(sql, clickhouse.ClickhouseClientService) else None
        assert create is not None
        loader = migrator.from_record(
            {
                "1_create": create(
                    sql(
                        "CREATE TABLE {} (id Int32) ENGINE = MergeTree ORDER BY id",
                        sql.identifier(table),
                    )
                ),
                "2_fill": create(sql("INSERT INTO {} VALUES (1)", sql.identifier(table))),
            }
        )
        assert (yield from migrator.run(loader=loader, table=ledger)) == [
            (1, "create"),
            (2, "fill"),
        ]
        assert (yield from migrator.run(loader=loader, table=ledger)) == []
        recorded = yield from sql(
            "SELECT migration_id, name FROM {} ORDER BY migration_id", sql.identifier(ledger)
        )
        assert recorded == [
            {"migration_id": 1, "name": "create"},
            {"migration_id": 2, "name": "fill"},
        ]

    _on_server(clickhouse_server, body)


def test_a_wrong_password_for_the_default_user_is_an_unknown_error(
    clickhouse_server: ClickhouseServer,
):
    """(pyfect) ClickHouse answers the ``default`` user's wrong password with 194, which
    Effect does not map either (run against @effect/sql-clickhouse): only 516 is an
    ``AuthenticationError``"""

    def wrong_password():
        sql = yield from clickhouse.ClickhouseClient()
        error = yield from sql("SELECT 1").flip()
        assert isinstance(error.reason, UnknownError)
        assert isinstance(error.reason.cause, clickhouse.error.ClickhouseError)
        assert error.reason.cause.code == 194
        assert error.reason.cause.type == "REQUIRED_PASSWORD"

    _on_server(
        clickhouse_server, wrong_password, username="default", password=redacted.make("wrong")
    )


def test_failures_carry_the_servers_code(clickhouse_server: ClickhouseServer):
    """(pyfect) failures carry the server's code and type"""

    def wrong_password():
        sql = yield from clickhouse.ClickhouseClient()
        error = yield from sql("SELECT 1").flip()
        assert isinstance(error.reason, AuthenticationError)

    # /ping checks no credentials, so the client starts.
    _on_server(clickhouse_server, wrong_password, password=redacted.make("wrong"))

    def syntax():
        sql = yield from clickhouse.ClickhouseClient()
        error = yield from sql("SELEC 1").flip()
        assert isinstance(error.reason, SqlSyntaxError)
        cause = error.reason.cause
        assert isinstance(cause, clickhouse.ClickhouseError)
        # The type is the first ``(UPPERCASE)`` group after the message, as
        # ``@clickhouse/client`` parses it: here the echoed ``(SELEC)``.
        assert cause.code == 62

    _on_server(clickhouse_server, syntax)


def test_settings_query_ids_and_names(clickhouse_server: ClickhouseServer):
    """(pyfect) settings, query ids, the URL's database and name transforms"""
    table = _table("names")

    def body():
        sql = yield from clickhouse.ClickhouseClient()
        threads = sql("SELECT getSetting('max_threads') AS t")
        assert (yield from threads) == [{"t": 5}]
        assert (yield from sql.with_clickhouse_settings(threads, {"max_threads": 3})) == [{"t": 3}]
        assert (yield from sql.with_query_id(sql("SELECT queryID() AS q"), "my-id")) == [
            {"q": "my-id"}
        ]
        assert (yield from sql("SELECT currentDatabase() AS d")) == [{"d": "system"}]
        yield from sql.as_command(
            sql(
                "CREATE TABLE default.{} (user_id Int32) ENGINE = Memory",
                sql.identifier(table),
            )
        )
        found = yield from sql("SELECT 1 AS user_id")
        assert found == [{"userId": 1}]

    _on_server(
        clickhouse_server,
        body,
        url=f"http://{USER}:{PASSWORD}@{clickhouse_server.host}:{clickhouse_server.port}"
        "/system?ch_max_threads=5",
        username=None,
        password=None,
        transform_result_names=case.snake_to_camel,
        transform_query_names=case.camel_to_snake,
    )


def test_the_url_sets_credentials_settings_and_headers():
    """(pyfect) the URL sets credentials, the database, settings and headers"""
    config = clickhouse.ClickhouseClientConfig(
        url="https://u%40x:p%3Ass@host:8443/db?ch_a=1&clickhouse_setting_b=2&http_header_X-Y=z"
        "&application=app&pathname=/ch/&session_id=s&request_timeout=1500",
        clickhouse_settings={"a": 0, "c": 3},
        role=["r1", "r2"],
    )
    connection = config.connection
    assert connection.url == "https://host:8443/ch"
    assert connection.database == "db"
    assert redacted.value(connection.authorization) == "Basic dUB4OnA6c3M="
    assert connection.clickhouse_settings == {"a": "1", "c": 3, "b": "2"}
    assert connection.http_headers == {"X-Y": "z"}
    assert (connection.application, connection.session_id) == ("app", "s")
    assert connection.role == ("r1", "r2")
    assert connection.request_timeout == 1.5
    token = clickhouse.ClickhouseClientConfig(access_token=redacted.make("jwt"))
    assert redacted.value(token.connection.authorization) == "Bearer jwt"
    with pytest.raises(ValueError, match="Unknown URL parameters: nope"):
        clickhouse.ClickhouseClientConfig(url="http://h?nope=1")
    with pytest.raises(ValueError, match="not offered here: compression_request, log_level"):
        clickhouse.ClickhouseClientConfig(url="http://h?compression_request=1&log_level=INFO")
    for timeout in ("nan", "1_000", "x"):
        with pytest.raises(ValueError, match='"request_timeout" has invalid numeric value'):
            clickhouse.ClickhouseClientConfig(url=f"http://h?request_timeout={timeout}")
    with pytest.raises(ValueError, match="protocol must be either http or https"):
        clickhouse.ClickhouseClientConfig(url="tcp://h:9000")
    with pytest.raises(ValueError, match="Both access token and username/password"):
        clickhouse.ClickhouseClientConfig(username="u", access_token=redacted.make("jwt"))
