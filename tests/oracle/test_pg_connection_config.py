"""Ports of Effect's ``sql-pg/test/PgConnection.test.ts``
(``describe("PgConnection config")``), ``TransactionAcquire.test.ts`` and
the behavior-level titles of ``PgConnection.in-process.test.ts`` (what the
config resolves to), checked against the throwaway server's settings
instead of a scripted server's startup packet.

Adapted: Effect's tests hand the client a ``stream`` factory to see whether
it connects; libpq opens its own sockets, so these point it at a local port
that accepts and closes connections (``ClosingListener``) and count what
arrives. "withTransaction surfaces stream factory failures instead of
defecting" connects to a port nothing listens on; "surfaces startup
transport failures" to one that closes the connection during startup.

Omitted from ``PgConnection.in-process``: the keepalive socket options, TLS
negotiation, the SCRAM, MD5 and cleartext exchanges, ``Terminate``,
``stream`` factories, ``maxMessageSize``, multiplexed writes, prepared
statement names, and the startup and FATAL ``ErrorResponse`` frames only a
scripted server sends: they test the wire protocol, which libpq implements
(a FATAL sent before the server hangs up is checked by "preserves the
server error when a listener backend is terminated" in ``test_pg_pool``).
"""
# pyright: reportPrivateUsage=false

import socket
from dataclasses import replace
from typing import Any

import pytest

pytest.importorskip("psycopg")

import pyfect as fx
from pyfect import redacted, testing
from pyfect.sql import pg
from pyfect.sql.error import ConnectionError, SqlError

from ._postgres import PASSWORD, ClosingListener, PgServer, refused_port

_INVALID_STARTUP = [
    {"startup_parameters": {"REPLICATION": "database"}},
    {"startup_parameters": {"client_encoding": "LATIN1"}},
    {"startup_parameters": {"": "value"}},
    {"startup_parameters": {"search_path": "public\0private"}},
    {"startup_options": "-c lock_timeout=2345\0"},
    {"url": redacted.make("postgres://test@localhost/db?options=%00")},
]


def _connect_error(config: pg.PgConnectionConfig):
    return fx.scoped(pg.connection.make(config)).flip()


@testing.effect
def test_rejects_sub_second_keepalive_before_connecting(closing_listener: ClosingListener):
    """rejects sub-second keepalive before connecting"""
    error = yield from _connect_error(
        pg.PgConnectionConfig(
            username="test", host="127.0.0.1", port=closing_listener.port, keep_alive="999 millis"
        )
    )
    assert closing_listener.connections == 0
    assert isinstance(error.reason, ConnectionError)


@pytest.mark.parametrize("fields", _INVALID_STARTUP)
@testing.effect
def test_rejects_invalid_startup_config_before_connecting(
    closing_listener: ClosingListener, fields: dict[str, object]
):
    """rejects invalid startup config %j before connecting"""
    config = pg.PgConnectionConfig(
        username="test",
        host="127.0.0.1",
        port=closing_listener.port,
        **fields,  # pyright: ignore[reportArgumentType]
    )
    error = yield from _connect_error(config)
    assert closing_listener.connections == 0
    assert isinstance(error.reason, ConnectionError)


@testing.effect
def test_interrupts_a_stalled_password_provider_when_connect_timeout_expires(
    closing_listener: ClosingListener,
):
    """interrupts a stalled password provider when connectTimeout expires"""
    interrupted: list[bool] = []
    password: fx.Effect[redacted.Redacted[str]] = fx.never.on_interrupt(
        fx.sync(lambda: interrupted.append(True))
    )
    config = pg.PgConnectionConfig(
        username="test",
        host="127.0.0.1",
        port=closing_listener.port,
        password=password,
        connect_timeout="1 second",
    )
    fiber = yield from _connect_error(config).fork()
    yield from testing.adjust("1 second")
    error = yield from fiber.join()
    assert interrupted == [True]
    assert closing_listener.connections == 0
    assert isinstance(error.reason, ConnectionError)
    assert error.reason.message == "PgConnection: Connection timed out"
    assert error.is_retryable


@pytest.mark.parametrize("sslmode", ["prefer", "allow"])
@testing.live
def test_accepts_sslmode_in_a_url(closing_listener: ClosingListener, sslmode: str):
    """accepts sslmode=%s in a URL"""
    url = f"postgres://user@127.0.0.1:{closing_listener.port}/db?sslmode={sslmode}"
    error = yield from _connect_error(pg.PgConnectionConfig(url=redacted.make(url)))
    assert closing_listener.connections > 0
    assert isinstance(error.reason, ConnectionError)
    assert error.reason.message == "PgConnection: Failed to connect"


@testing.effect
def test_rejects_an_unrecognized_sslmode_before_connecting(closing_listener: ClosingListener):
    """rejects an unrecognized sslmode before connecting"""
    url = f"postgresql://user@127.0.0.1:{closing_listener.port}/db?sslmode=invalid"
    error = yield from _connect_error(pg.PgConnectionConfig(url=redacted.make(url)))
    assert closing_listener.connections == 0
    assert isinstance(error.reason, ConnectionError)
    assert error.reason.message == 'PgConnection: Unrecognized sslmode in URL: "invalid"'


@testing.effect
def test_rejects_a_non_postgres_url_protocol():
    """rejects a non-postgres URL protocol"""
    error = yield from _connect_error(
        pg.PgConnectionConfig(url=redacted.make("mysql://user@localhost/db"))
    )
    assert isinstance(error.reason, ConnectionError)


def _transaction_error(port: int) -> fx.Effect[SqlError, object]:
    def body():
        sql = yield from pg.make(pg.PgPoolConfig(username="test", host="127.0.0.1", port=port))
        return (yield from sql.with_transaction(sql("SELECT 1")).flip())

    return fx.scoped(fx.gen(body)).pipe(fx.provide(fx.reactivity.layer))


@testing.live
def test_with_transaction_surfaces_stream_factory_failures_instead_of_defecting():
    """withTransaction surfaces stream factory failures instead of defecting"""
    error = yield from _transaction_error(refused_port())
    assert isinstance(error, SqlError)
    assert error.reason._tag == "ConnectionError"
    assert error.reason.operation == "connect"


@testing.live
def test_with_transaction_surfaces_startup_transport_failures_instead_of_defecting(
    closing_listener: ClosingListener,
):
    """withTransaction surfaces startup transport failures instead of defecting"""
    error = yield from _transaction_error(closing_listener.port)
    assert isinstance(error, SqlError)
    assert error.reason._tag == "ConnectionError"
    assert error.reason.operation == "connect"
    assert closing_listener.connections > 0


# --- PgConnection.in-process: what reaches the server --------------------------


def _settings(connection: pg.PgConnection) -> fx.Effect[dict[str, Any], SqlError]:
    query = (
        "SELECT current_user AS user, current_database() AS database,"
        " current_setting('application_name') AS application_name,"
        " current_setting('search_path') AS search_path,"
        " current_setting('client_encoding') AS client_encoding,"
        " current_setting('statement_timeout') AS statement_timeout,"
        " current_setting('lock_timeout') AS lock_timeout"
    )
    return connection.query(query).map(lambda result: result.rows[0])


@testing.live
def test_forwards_startup_defaults_and_lets_explicit_fields_override_url_values(
    pg_server: PgServer,
):
    """forwards startup defaults and lets explicit fields override URL values"""
    url = (
        f"postgres://postgres:{PASSWORD}@localhost/postgres"
        "?application_name=url-app&options=-c%20statement_timeout%3D1234"
    )
    config = pg.PgConnectionConfig(
        host="127.0.0.1",
        port=pg_server.port,
        url=redacted.make(url),
        startup_parameters={
            "SEARCH_PATH": "public",
            "CLIENT_ENCODING": "uTf-8",
            "application_name": "named-app",
        },
    )
    settings = yield from _settings((yield from pg.connection.make(config)))
    assert settings == {
        "user": "postgres",
        "database": "postgres",
        "application_name": "named-app",
        "search_path": "public",
        "client_encoding": "UTF8",
        "statement_timeout": "1234ms",
        "lock_timeout": "0",
    }

    explicit = replace(
        config, application_name="explicit-app", startup_options="-c lock_timeout=2345"
    )
    settings = yield from _settings((yield from pg.connection.make(explicit)))
    assert settings["application_name"] == "explicit-app"
    assert (settings["statement_timeout"], settings["lock_timeout"]) == ("0", "2345ms")


@testing.live
def test_lets_url_query_host_and_port_override_the_authority(pg_server: PgServer):
    """lets URL query host and port override the authority"""
    url = (
        f"postgres://postgres:{PASSWORD}@invalid.invalid:1/postgres"
        f"?host=127.0.0.1&port={pg_server.port}"
    )
    connection = yield from pg.connection.make(pg.PgConnectionConfig(url=redacted.make(url)))
    assert (yield from connection.query("SELECT 1 AS one")).rows == [{"one": 1}]


@testing.live
def test_resolves_a_password_effect_for_each_connection(pg_server: PgServer):
    """resolves a password Effect for each connection"""
    calls: list[None] = []

    def password() -> redacted.Redacted[str]:
        calls.append(None)
        return redacted.make(PASSWORD)

    acquire = pg.connection.make(
        pg.PgConnectionConfig(
            host=pg_server.host,
            port=pg_server.port,
            username="postgres",
            password=fx.sync(password),
        )
    )
    yield from fx.scoped(acquire)
    yield from acquire
    assert len(calls) == 2


@testing.live
def test_derives_a_unix_socket_path_from_a_slash_prefixed_host(pg_server: PgServer):
    """derives a unix socket path from a slash-prefixed host"""
    connection = yield from pg.connection.make(
        pg.PgConnectionConfig(host=pg_server.socket_dir, port=pg_server.port, username="postgres")
    )
    rows = (yield from connection.query("SELECT inet_server_addr() IS NULL AS unix")).rows
    assert rows == [{"unix": True}]


@testing.live
def test_lets_explicit_fields_override_url_connection_and_startup_values(pg_server: PgServer):
    """lets explicit fields override URL connection and startup values"""
    url = "postgres://url-user@invalid.invalid:1/url-db?application_name=url-app"
    connection = yield from pg.connection.make(
        pg.PgConnectionConfig(
            url=redacted.make(url),
            host="127.0.0.1",
            port=pg_server.port,
            username="postgres",
            password=redacted.make(PASSWORD),
            database="postgres",
            application_name="explicit-app",
        )
    )
    settings = yield from _settings(connection)
    assert settings["user"] == "postgres"
    assert settings["database"] == "postgres"
    assert settings["application_name"] == "explicit-app"
    assert settings["client_encoding"] == "UTF8"


# The connect is work on psycopg's loop that never ends, so adjust waits
# warning_delay for it and warns before moving time.
@pytest.mark.filterwarnings("ignore::pyfect.testing.BusyFiberWarning")
@testing.effect
def test_treats_url_connect_timeout_0_as_no_timeout():
    """treats URL connect_timeout=0 as no timeout"""
    # A port that completes the TCP handshake and never answers startup.
    silent = socket.socket()
    silent.bind(("127.0.0.1", 0))
    silent.listen()
    port = silent.getsockname()[1]
    url = f"postgres://test@127.0.0.1:{port}/db?connect_timeout=0"
    fiber = yield from _connect_error(pg.PgConnectionConfig(url=redacted.make(url))).fork()
    yield from testing.adjust("6 seconds")
    assert fiber.poll_unsafe() is None
    silent.close()
    error = yield from fiber.join()
    assert isinstance(error.reason, ConnectionError)
    assert error.reason.message == "PgConnection: Failed to connect"
