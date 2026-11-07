"""Ports of Effect's ``sql-mssql/test/Client.test.ts``.

Each test's docstring is the Effect test title; ``(pyfect)`` titles pin
the driver on the session's SQL Server (``_mssql.mssql_server``; skipped
without Docker). Effect's ``vi.mock("tedious")`` is ``_mssql_fake``, which
replaces the driver's ``connect``.

Adapted: the two "default parameter mapping" titles check tedious's
``validate`` of a JavaScript value; here the value goes to SQL Server and
back with the default types. "cancels an in-flight Tedious request when
interrupted" waits until the request reaches the driver, where Effect's
``execSql`` is reached synchronously. The commented-out "param types" test
is ported as the ``(pyfect)`` "param types".
"""

import threading
import time
from collections.abc import Callable, Generator
from typing import Any

import pytest

pytest.importorskip("pytds")

import pyfect as fx
from pyfect import testing
from pyfect.reactivity import layer as reactivity_layer
from pyfect.sql import SqlClient, mssql
from pyfect.sql import statement as st
from pyfect.sql.error import SqlError
from pyfect.sql.mssql import TYPES, Parameter, ParameterOptions, procedure

from . import _mssql_fake
from ._mssql import MssqlServer

type Body = Callable[[], Generator[Any, Any, Any]]

sql = st.make(fx.never, mssql.make_compiler(), [], None)


def _config(server: MssqlServer, **fields: Any) -> mssql.MssqlClientConfig:
    return mssql.MssqlClientConfig(
        server=server.host,
        port=server.port,
        database=server.database,
        username=server.username,
        password=server.password,
        trust_server=True,
        **fields,
    )


def _on_server(server: MssqlServer, body: Body, **fields: Any) -> fx.Effect[Any, Any]:
    return fx.scoped(fx.gen(body)).pipe(fx.provide(mssql.layer(_config(server, **fields))))


def _mocked(body: Body) -> fx.Effect[Any, Any]:
    return fx.scoped(fx.gen(body)).pipe(fx.provide(reactivity_layer))


def _bounded[A, E, R](effect: fx.Effect[A, E, R]) -> fx.Effect[A, Any, R]:
    return effect.timeout("2 seconds")


_answer = Parameter[int]("answer", TYPES.Int)
_get_answer = procedure.make("get_answer").output_param(_answer)


# --- the default parameter mapping ------------------------------------------------


@testing.live
def test_preserves_fractional_numbers_with_the_default_parameter_mapping(
    mssql_server: MssqlServer,
):
    """preserves fractional JavaScript numbers with the default parameter mapping"""

    def body():
        client = yield from mssql.MssqlClient()
        assert mssql.default_parameter_types["float"] == TYPES.Float
        rows = yield from client("SELECT {} AS value", 1.5)
        assert rows == [{"value": 1.5}]

    yield from _on_server(mssql_server, body)


@testing.live
def test_preserves_unicode_strings_with_the_default_parameter_mapping(mssql_server: MssqlServer):
    """preserves Unicode JavaScript strings with the default parameter mapping"""

    def body():
        client = yield from mssql.MssqlClient()
        assert mssql.default_parameter_types["string"] == TYPES.NVarChar
        rows = yield from client("SELECT {} AS value", "lambda: λ")
        assert rows == [{"value": "lambda: λ"}]

    yield from _on_server(mssql_server, body)


# --- the compiler -----------------------------------------------------------------


def test_insert_helper():
    """insert helper"""
    query, params = sql(
        "INSERT INTO {} {}", sql.identifier("people"), sql.insert({"name": "Tim", "age": 10})
    ).compile()
    assert query == "INSERT INTO [people] ([name],[age]) VALUES (@1,@2)"
    assert params == ("Tim", 10)


def test_insert_helper_returning():
    """insert helper returning"""
    query, params = sql(
        "INSERT INTO {} {}",
        sql.identifier("people"),
        sql.insert({"name": "Tim", "age": 10}).returning("*"),
    ).compile()
    assert query == "INSERT INTO [people] ([name],[age]) OUTPUT INSERTED.* VALUES (@1,@2)"
    assert params == ("Tim", 10)


def test_update_helper():
    """update helper"""
    query, params = sql(
        "UPDATE people SET name = data.name {}",
        sql.update_values([{"name": "Tim"}, {"name": "John"}], "data"),
    ).compile()
    assert query == "UPDATE people SET name = data.name FROM (values (@1),(@2)) AS [data]([name])"
    assert params == ("Tim", "John")


def test_update_helper_returning():
    """update helper returning"""
    query, params = sql(
        "UPDATE people SET name = data.name {}",
        sql.update_values([{"name": "Tim"}, {"name": "John"}], "data").returning("*"),
    ).compile()
    assert query == (
        "UPDATE people SET name = data.name OUTPUT INSERTED.* "
        "FROM (values (@1),(@2)) AS [data]([name])"
    )
    assert params == ("Tim", "John")


def test_update_single_helper_returning():
    """update single helper returning"""
    query, params = sql(
        "UPDATE people SET {}", sql.update({"name": "Tim"}).returning("*")
    ).compile()
    assert query == "UPDATE people SET [name] = @1 OUTPUT INSERTED.*"
    assert params == ("Tim",)


_RETURNING = pytest.mark.parametrize(
    "returning",
    [
        pytest.param(sql.identifier("INSERTED.name"), id="Identifier"),
        pytest.param(sql("{}", sql.identifier("INSERTED.name")), id="wrapped Identifier"),
    ],
)


@_RETURNING
def test_insert_helper_returning_identifier(returning: st.Identifier | st.Fragment):
    """insert helper returning ${name}"""
    result = sql(
        "INSERT INTO {} {}",
        sql.identifier("people"),
        sql.insert({"name": "Rowan", "age": 10}).returning(returning),
    ).compile()
    assert result == (
        "INSERT INTO [people] ([name],[age]) OUTPUT [INSERTED].[name] VALUES (@1,@2)",
        ("Rowan", 10),
    )


@_RETURNING
def test_update_helper_returning_identifier(returning: st.Identifier | st.Fragment):
    """update helper returning ${name}"""
    result = sql(
        "UPDATE people SET {}", sql.update({"name": "Rowan"}).returning(returning)
    ).compile()
    assert result == ("UPDATE people SET [name] = @1 OUTPUT [INSERTED].[name]", ("Rowan",))


@_RETURNING
def test_update_values_helper_returning_identifier(returning: st.Identifier | st.Fragment):
    """updateValues helper returning ${name}"""
    result = sql(
        "UPDATE people SET name = data.name {}",
        sql.update_values([{"name": "Rowan"}, {"name": "Mira"}], "data").returning(returning),
    ).compile()
    assert result == (
        "UPDATE people SET name = data.name OUTPUT [INSERTED].[name] "
        "FROM (values (@1),(@2)) AS [data]([name])",
        ("Rowan", "Mira"),
    )


def test_array_helper():
    """array helper"""
    query, params = sql(
        "SELECT * FROM {} WHERE id IN {}", sql.identifier("people"), sql.in_([1, 2, "string"])
    ).compile()
    assert query == "SELECT * FROM [people] WHERE id IN (@1,@2,@3)"
    assert params == (1, 2, "string")


def test_param_types():
    """(pyfect) param types"""
    client: Any = object.__new__(mssql.MssqlClientService)
    param = mssql.MssqlClientService.param(client, TYPES.BigInt, 1)
    query, params = sql("SELECT * FROM {} WHERE id = {}", sql.identifier("people"), param).compile()
    assert query == "SELECT * FROM [people] WHERE id = @1"
    [custom] = params
    assert st.is_custom("MssqlParam")(custom)
    assert (custom.param_a, custom.param_b, custom.param_c) == (
        TYPES.BigInt,
        1,
        ParameterOptions(),
    )


def test_escape_bracket():
    """escape ["""
    query, _ = sql("SELECT * FROM {}", sql.identifier("peo[]ple.te[st]ing")).compile()
    assert query == "SELECT * FROM [peo[]]ple].[te[st]]ing]"


# --- stored procedures and cancellation (mocked driver) ---------------------------


@testing.live
def test_returns_stored_procedure_output_parameters_under_output(monkeypatch: pytest.MonkeyPatch):
    """returns stored procedure output parameters under output"""
    _mssql_fake.install(monkeypatch)

    def body():
        client = yield from mssql.make(mssql.MssqlClientConfig(server="localhost"))
        result = yield from client.call(_get_answer.compile())
        assert result == procedure.Result(procedure.Outputs({"answer": 42}), [])
        assert result.output[_answer] == 42

    yield from _mocked(body)


@testing.live
def test_cancels_an_in_flight_request_when_interrupted(monkeypatch: pytest.MonkeyPatch):
    """cancels an in-flight Tedious request when interrupted"""
    fake = _mssql_fake.install(monkeypatch)

    def body():
        client = yield from mssql.make(mssql.MssqlClientConfig(server="localhost"))
        fake.complete_requests = False
        fiber = yield from client("WAITFOR DELAY '00:01:00'").fork()
        yield from fx.blocking(lambda: fake.pending_started.wait(2))
        calls_before_interrupt = fake.cancel_calls
        yield from _bounded(fiber.interrupt())
        assert fake.cancel_calls == calls_before_interrupt + 1

    yield from _mocked(body)


# --- MssqlClient connection lifecycle (mocked driver) -----------------------------


def _single_connection() -> mssql.MssqlClientConfig:
    return mssql.MssqlClientConfig(
        server="localhost", min_connections=0, max_connections=1, connection_ttl="1 hour"
    )


@testing.live
@pytest.mark.parametrize("operation", ["without_transforms", "call"])
def test_reuses_the_transaction_connection_with_a_single_connection_pool(
    monkeypatch: pytest.MonkeyPatch, operation: str
):
    """${operation} reuses the transaction connection with a single-connection pool"""
    _mssql_fake.install(monkeypatch)

    def body():
        client = yield from _bounded(
            mssql.make(
                mssql.MssqlClientConfig(
                    server="localhost",
                    min_connections=0,
                    max_connections=1,
                    transform_result_names=str.upper,
                )
            )
        )

        def inside():
            if operation == "without_transforms":
                rows = yield from client.without_transforms()("SELECT value")
                assert rows == [{"value": 42}]
            else:
                result = yield from client.call(_get_answer.compile())
                assert result == procedure.Result(procedure.Outputs({"answer": 42}), [])

        yield from _bounded(client.with_transaction(fx.gen(inside)))

    yield from _mocked(body)


@testing.live
def test_handles_a_late_error_after_an_ended_connection_is_discarded_and_recovers(
    monkeypatch: pytest.MonkeyPatch,
):
    """handles a late error after an ended connection is discarded and recovers"""
    fake = _mssql_fake.install(monkeypatch)

    def body():
        client = yield from _bounded(mssql.make(_single_connection()))
        connection = fake.connections[0]
        # A dropped socket: the driver ends the connection, and reports its
        # error only after the pool closed it. Wait for the cleanup, not time.
        connection.closed = True
        connection.end()
        yield from _bounded(fx.blocking(lambda: connection.closed_signal.wait(2)))
        connection.end()
        assert fake.emission_error is None
        rows = yield from _bounded(client.unsafe("SELECT recovered"))
        assert rows == [{"value": 42}]

    yield from _mocked(body)


@testing.live
def test_replaces_a_connection_that_ends_without_error_after_query_cancellation(
    monkeypatch: pytest.MonkeyPatch,
):
    """replaces a connection that ends without error after query cancellation"""
    fake = _mssql_fake.install(monkeypatch)

    def body():
        client = yield from _bounded(mssql.make(_single_connection()))
        connection = fake.connections[0]
        query = yield from client.unsafe("SELECT pending").fork_scoped()
        yield from _bounded(fx.blocking(lambda: fake.pending_started.wait(2)))
        yield from _bounded(query.interrupt())
        assert connection.cancellations == 1
        # The cancel timed out: the connection ends, without an error.
        connection.close()
        yield from fx.yield_now()
        rows = yield from _bounded(client.unsafe("SELECT recovered"))
        assert rows == [{"value": 42}]
        assert len(fake.connections) == 2
        assert "SELECT recovered" not in connection.queries
        assert "SELECT recovered" in fake.connections[1].queries

    yield from _mocked(body)


@testing.live
def test_handles_an_error_immediately_after_the_connect_callback(
    monkeypatch: pytest.MonkeyPatch,
):
    """handles an error immediately after the connect callback and does not reuse the failed connection"""  # noqa: E501
    fake = _mssql_fake.install(monkeypatch)

    def body():
        client = yield from _bounded(mssql.make(_single_connection()))
        original = fake.connections[0]
        yield from fx.yield_now()
        # Retire the healthy connection through a driver error, then end the
        # next connection of this pool as it is made.
        fake.error_after_connect = True
        original.end()
        yield from _bounded(fx.blocking(lambda: original.closed_signal.wait(2)))
        yield from _bounded(client.unsafe("SELECT during_race").result())
        assert fake.emission_error is None, "the driver's error emission must not raise"

        failed = fake.connections[1]
        assert failed.closed
        assert "SELECT during_race" not in failed.queries
        rows = yield from _bounded(client.unsafe("SELECT recovered"))
        assert rows == [{"value": 42}]
        assert "SELECT recovered" not in failed.queries
        assert any("SELECT recovered" in c.queries for c in fake.connections[2:])

    yield from _mocked(body)


# --- the driver on SQL Server -----------------------------------------------------


@testing.live
def test_commits_rolls_back_and_rolls_back_to_savepoints(mssql_server: MssqlServer):
    """(pyfect) commits, rolls back and rolls back to savepoints"""

    def body():
        client = yield from mssql.MssqlClient()
        yield from client("DROP TABLE IF EXISTS mssql_tx")
        yield from client("CREATE TABLE mssql_tx (id INT PRIMARY KEY)")

        def nested():
            yield from client("INSERT INTO mssql_tx VALUES (2)")
            yield from fx.fail("inner")

        def outer():
            yield from client("INSERT INTO mssql_tx VALUES (1)")
            yield from client.with_transaction(fx.gen(nested)).result()
            [level] = yield from client("SELECT @@TRANCOUNT AS level")
            assert level == {"level": 1}

        yield from client.with_transaction(fx.gen(outer))
        yield from client.with_transaction(
            client("INSERT INTO mssql_tx VALUES (3)").and_then(fx.fail("rolled back"))
        ).result()
        rows = yield from client("SELECT id FROM mssql_tx ORDER BY id")
        assert rows == [{"id": 1}]

    yield from _on_server(mssql_server, body)


@testing.live
def test_calls_a_procedure_with_inputs_outputs_and_rows(mssql_server: MssqlServer):
    """(pyfect) calls a procedure with inputs, outputs and rows"""
    name = Parameter[str]("name", TYPES.NVarChar, ParameterOptions(length=50))
    doubled = Parameter[int]("doubled", TYPES.Int)
    count = Parameter[int]("count", TYPES.Int)
    greet = procedure.make("pyfect_greet").param(name).param(count).output_param(doubled)

    def body():
        client = yield from mssql.MssqlClient()
        yield from client(
            "CREATE OR ALTER PROCEDURE pyfect_greet @name NVARCHAR(50), @count INT, "
            "@doubled INT OUTPUT AS BEGIN SET @doubled = @count * 2; "
            "SELECT @name AS greeted_name, @count AS greeted_count END"
        )
        result = yield from client.call(greet.compile(name("Tim"), count(21)))
        assert result.output[doubled] == 42
        assert list(result.rows) == [{"greetedName": "Tim", "greetedCount": 21}]

    yield from _on_server(mssql_server, body, transform_result_names=_camel)


def _camel(name: str) -> str:
    from pyfect import case

    return case.snake_to_camel(name)


def test_compile_checks_the_inputs():
    """(pyfect) compile takes one value for each input, and nothing else"""
    name = Parameter[str]("name", TYPES.NVarChar)
    other = Parameter[str]("other", TYPES.NVarChar)
    greet = procedure.make("greet").param(name)
    with pytest.raises(ValueError, match="needs values"):
        greet.compile()
    with pytest.raises(ValueError, match="not an input"):
        greet.compile(name("a"), other("b"))
    with pytest.raises(ValueError, match="twice"):
        greet.compile(name("a"), name("b"))
    assert greet.compile(name("a")).values == {"name": "a"}


@testing.live
def test_typed_parameters_reach_the_server_as_their_types(mssql_server: MssqlServer):
    """(pyfect) typed parameters reach the server as their types"""

    def body():
        client = yield from mssql.MssqlClient()
        rows = yield from client(
            "SELECT SQL_VARIANT_PROPERTY({}, 'BaseType') AS a, "
            "SQL_VARIANT_PROPERTY({}, 'BaseType') AS b, "
            "SQL_VARIANT_PROPERTY({}, 'MaxLength') AS c, "
            "SQL_VARIANT_PROPERTY({}, 'BaseType') AS d",
            client.param(TYPES.Int, 7),
            client.param(TYPES.Decimal, 1.25, ParameterOptions(precision=10, scale=2)),
            client.param(TYPES.VarChar, "abc", ParameterOptions(length=20)),
            10,
        )
        assert rows == [{"a": "int", "b": "decimal", "c": 20, "d": "bigint"}]

    yield from _on_server(mssql_server, body)


@testing.live
def test_interrupting_a_statement_cancels_it_on_the_server(mssql_server: MssqlServer):
    """(pyfect) interrupting a statement cancels it on the server, and the
    connection goes on"""

    def body():
        client = yield from mssql.MssqlClient()
        started = time.monotonic()
        result = yield from client("WAITFOR DELAY '00:00:30'").timeout("500 millis").result()
        assert isinstance(result, fx.Err)
        rows = yield from client("SELECT @@SPID AS spid")
        assert len(rows) == 1
        assert time.monotonic() - started < 5

    yield from _on_server(mssql_server, body, max_connections=1)


@testing.live
def test_classifies_server_errors(mssql_server: MssqlServer):
    """(pyfect) classifies the server's errors by number"""
    from pyfect.sql.error import SqlError, SqlSyntaxError, UniqueViolation

    def body():
        client = yield from mssql.MssqlClient()
        yield from client("DROP TABLE IF EXISTS mssql_unique")
        yield from client(
            "CREATE TABLE mssql_unique (id INT CONSTRAINT PK_mssql_unique PRIMARY KEY)"
        )
        yield from client("INSERT INTO mssql_unique VALUES (1)")
        duplicate = yield from client("INSERT INTO mssql_unique VALUES (1)").flip()
        assert isinstance(duplicate, SqlError)
        assert isinstance(duplicate.reason, UniqueViolation)
        assert duplicate.reason.constraint == "PK_mssql_unique"
        missing = yield from client("SELECT * FROM mssql_missing_table").flip()
        assert isinstance(missing.reason, SqlSyntaxError)

    yield from _on_server(mssql_server, body)


@testing.live
def test_a_rejected_login_is_an_authentication_error(mssql_server: MssqlServer):
    """(pyfect) a rejected login is an AuthenticationError, inside the
    ConnectionError of the client's check (Effect's classifyError of the
    SqlError)"""
    from pyfect import redacted
    from pyfect.sql.error import AuthenticationError, ConnectionError, SqlError

    def body():
        error = yield from mssql.make(
            _config(mssql_server).__replace__(password=redacted.make("wrong"))
        ).flip()
        assert isinstance(error.reason, ConnectionError)
        assert error.reason.message == "MssqlClient: Failed to connect"
        assert isinstance(error.reason.cause, SqlError)
        assert isinstance(error.reason.cause.reason, AuthenticationError)

    yield from fx.scoped(fx.gen(body)).pipe(fx.provide(reactivity_layer))


@testing.live
def test_encrypts_only_the_login_without_encrypt(mssql_server: MssqlServer):
    """(pyfect) encrypt=False encrypts only the login"""

    def body():
        client = yield from mssql.MssqlClient()
        [row] = yield from client(
            "SELECT encrypt_option AS encrypted FROM sys.dm_exec_connections "
            "WHERE session_id = @@SPID"
        )
        assert row == {"encrypted": "FALSE"}

    yield from _on_server(mssql_server, body, encrypt=False)

    def with_tls():
        client = yield from mssql.MssqlClient()
        [row] = yield from client(
            "SELECT encrypt_option AS encrypted FROM sys.dm_exec_connections "
            "WHERE session_id = @@SPID"
        )
        assert row == {"encrypted": "TRUE"}

    yield from _on_server(mssql_server, with_tls)


@testing.live
def test_runs_migrations(mssql_server: MssqlServer):
    """(pyfect) runs migrations"""
    from pyfect.sql.mssql import migrator

    create = SqlClient().flat_map(lambda c: c("CREATE TABLE mssql_migrated (id INT)"))

    def body():
        client = yield from mssql.MssqlClient()
        yield from client("DROP TABLE IF EXISTS mssql_migrated, mssql_migrations")
        applied = yield from migrator.run(
            loader=migrator.from_record({"1_create": create}), table="mssql_migrations"
        )
        again = yield from migrator.run(
            loader=migrator.from_record({"1_create": create}), table="mssql_migrations"
        )
        assert (list(applied), list(again)) == ([(1, "create")], [])
        rows = yield from client("SELECT COUNT(*) AS n FROM mssql_migrated")
        assert rows == [{"n": 0}]

    yield from _on_server(mssql_server, body)


@testing.live
def test_an_output_parameter_without_a_length_holds_the_whole_value(mssql_server: MssqlServer):
    """(pyfect) an output parameter without a length holds the whole value
    (tedious sizes a null text or binary value at its type's maximum)"""
    text = Parameter[str]("text", TYPES.NVarChar)
    narrow = Parameter[str]("narrow", TYPES.VarChar)
    data = Parameter[bytes]("data", TYPES.VarBinary)
    fill = procedure.make("pyfect_fill").output_param(text).output_param(narrow)
    fill = fill.output_param(data)

    def body():
        client = yield from mssql.MssqlClient()
        yield from client(
            "CREATE OR ALTER PROCEDURE pyfect_fill @text NVARCHAR(4000) OUTPUT, "
            "@narrow VARCHAR(8000) OUTPUT, @data VARBINARY(8000) OUTPUT AS BEGIN "
            "SET @text = REPLICATE(N'λ', 4000); SET @narrow = REPLICATE('x', 8000); "
            "SET @data = CAST(REPLICATE('y', 8000) AS VARBINARY(8000)) END"
        )
        result = yield from client.call(fill.compile())
        assert result.output[text] == "λ" * 4000
        assert result.output[narrow] == "x" * 8000
        assert result.output[data] == b"y" * 8000

    yield from _on_server(mssql_server, body)


@testing.live
def test_an_interrupt_after_the_request_ended_does_not_cancel_the_next(
    mssql_server: MssqlServer, monkeypatch: pytest.MonkeyPatch
):
    """(pyfect) an interrupt arriving after a request ended, while its call is
    still finishing, does not cancel the connection's next request"""
    import threading

    from pyfect.sql.mssql import _tds

    finished = threading.Event()
    release = threading.Event()
    cancelled = threading.Event()
    execute = _tds.TdsConnection.execute
    cancel = _tds.TdsConnection.cancel

    def held_execute(self: _tds.TdsConnection, query: str, params: Any, /) -> Any:
        rows = execute(self, query, params)
        if query == "SELECT 'held' AS v":
            finished.set()
            release.wait(5)
        return rows

    def noted_cancel(self: _tds.TdsConnection) -> None:
        cancel(self)
        cancelled.set()

    monkeypatch.setattr(_tds.TdsConnection, "execute", held_execute)
    monkeypatch.setattr(_tds.TdsConnection, "cancel", noted_cancel)

    def body():
        client = yield from mssql.MssqlClient()
        held = yield from client("SELECT 'held' AS v").fork()
        yield from fx.blocking(lambda: finished.wait(5))
        yield from held.interrupt().fork()
        yield from fx.blocking(lambda: cancelled.wait(5))
        release.set()
        yield from _bounded(held.await_exit())
        rows = yield from _bounded(client("SELECT 1 AS v"))
        assert rows == [{"v": 1}]

    yield from _on_server(mssql_server, body, max_connections=1)


@testing.live
def test_strings_outside_the_bmp_keep_every_character(mssql_server: MssqlServer):
    """(pyfect) a string with characters outside the BMP is sized in UTF-16
    code units, as tedious sizes a JavaScript string, so none is cut"""

    def body():
        client = yield from mssql.MssqlClient()
        rows = yield from client("SELECT {} AS a, {} AS b", "😀", "a😀b")
        assert rows == [{"a": "😀", "b": "a😀b"}]

    yield from _on_server(mssql_server, body)


# --- opening a connection ---------------------------------------------------------


def _mocked_config(**fields: Any) -> mssql.MssqlClientConfig:
    return mssql.MssqlClientConfig(
        server="localhost", password=fx.redacted.make("pass"), trust_server=True, **fields
    )


def _build_client(**fields: Any) -> fx.Effect[Any, Any]:
    return fx.scoped(mssql.make(_mocked_config(**fields))).pipe(fx.provide(reactivity_layer))


def _wait_for(condition: Callable[[], bool]) -> None:
    deadline = time.monotonic() + 5
    while not condition():
        assert time.monotonic() < deadline
        time.sleep(0.005)


@pytest.mark.parametrize(
    ("field", "default"),
    [("connect_timeout", 15.0), ("cancel_timeout", 5.0), ("connection_retry_interval", 0.5)],
)
def test_a_timeout_of_0_is_the_driver_s_default(
    monkeypatch: pytest.MonkeyPatch, field: str, default: float
):
    """(pyfect) Effect passes these to tedious as ``options.x ? ... : undefined``,
    so the number 0 leaves tedious's default"""
    fake = _mssql_fake.install(monkeypatch)
    fx.run_blocking_exit(_build_client(**{field: 0}))
    assert getattr(fake.options[0], field) == default


def test_a_timeout_of_nan_is_the_driver_s_default(monkeypatch: pytest.MonkeyPatch):
    """(pyfect) ``NaN`` is falsy in ``options.x ? ... : undefined``, so it is unset too"""
    fake = _mssql_fake.install(monkeypatch)
    fx.run_blocking_exit(_build_client(cancel_timeout=float("nan")))
    assert fake.options[0].cancel_timeout == 5.0


def test_a_timeout_of_a_zero_duration_reaches_the_driver(monkeypatch: pytest.MonkeyPatch):
    """(pyfect) a ``timedelta(0)`` is a value as ``Duration.zero`` is an object,
    which tedious reads as no time at all"""
    from datetime import timedelta

    fake = _mssql_fake.install(monkeypatch)
    fx.run_blocking_exit(_build_client(cancel_timeout=timedelta(0)))
    assert fake.options[0].cancel_timeout == 0


def test_interrupting_a_connection_while_it_opens_returns_at_once(
    monkeypatch: pytest.MonkeyPatch,
):
    """(pyfect) as Effect's ``callback`` around ``conn.connect``: nothing waits
    for the driver, and a connection made all the same is closed"""
    fake = _mssql_fake.install(monkeypatch)
    fake.hold_connect = threading.Event()

    @fx.gen
    def body():
        fiber = yield from _build_client(connect_timeout="30 seconds").fork()
        while not fake.connect_started.is_set():
            yield from fx.sleep("5 millis")
        yield from fiber.interrupt()
        return (yield from fiber.await_exit())

    started = time.monotonic()
    try:
        ex = fx.run_blocking(body)
        assert time.monotonic() - started < 5
        assert isinstance(ex, fx.Failure) and ex.cause.has_interrupts
    finally:
        fake.hold_connect.set()
    _wait_for(lambda: len(fake.connections) == 1 and fake.connections[0].closed)


def test_a_connection_check_that_times_out_does_not_wait_for_the_open(
    monkeypatch: pytest.MonkeyPatch,
):
    """(pyfect) ``make`` fails at ``connect_timeout`` with the driver still
    connecting, as Effect's ``timeoutOrElse`` does"""
    fake = _mssql_fake.install(monkeypatch)
    fake.hold_connect = threading.Event()
    started = time.monotonic()
    try:
        ex = fx.run_blocking_exit(_build_client(connect_timeout="50 millis"))
        assert time.monotonic() - started < 5
    finally:
        fake.hold_connect.set()
    assert isinstance(ex, fx.Failure)
    error = ex.cause.find_error()
    assert isinstance(error, fx.Ok) and isinstance(error.value, SqlError)
    assert error.value.reason.message == "MssqlClient: Connection timeout"
    _wait_for(lambda: len(fake.connections) == 1 and fake.connections[0].closed)
