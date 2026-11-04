"""The MySQL client (Effect's ``@effect/sql-mysql2`` ``MysqlClient``): an
``SqlClient`` on a pool of asyncmy connections.

``make`` opens the pool and checks it with ``SELECT 1`` (within five
seconds); statements outside a transaction each take a connection for
themselves, a transaction or a stream keeps one until it ends::

    program.pipe(fx.provide(mysql.layer(mysql.MysqlClientConfig(url=redacted.make(url)))))
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Never, Unpack

from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect.config import Config, ConfigError, unwrap
from pyfect.context import Context, Tag
from pyfect.duration import to_seconds
from pyfect.effect import fail
from pyfect.layer import Layer, provide
from pyfect.layer import effect_context as layer_effect_context
from pyfect.reactivity import Reactivity
from pyfect.reactivity import layer as reactivity_layer
from pyfect.redacted import value as redacted_value
from pyfect.scope import Scope, scoped
from pyfect.sql.client import ClientFields, SqlClient, SqlClientService
from pyfect.sql.client import make as make_sql_client
from pyfect.sql.connection import Connection
from pyfect.sql.error import ConnectionError, SqlError
from pyfect.sql.mysql import _pool
from pyfect.sql.mysql._asyncmy import connect_keywords
from pyfect.sql.mysql._connection import MysqlConnection
from pyfect.sql.mysql.config import (
    DEFAULT_IDLE_TIMEOUT,
    DEFAULT_MAX_CONNECTIONS,
    MysqlClientConfig,
    parse_url,
)
from pyfect.sql.mysql.error import classify
from pyfect.sql.statement import Compiled, Compiler, default_escape, default_transforms
from pyfect.sql.statement import make_compiler as make_statement_compiler

_escape = default_escape("`")
_CONNECT_TIMEOUT = 5.0


class MysqlClientService(SqlClientService):
    """A MySQL client: an ``SqlClientService`` and its config."""

    __slots__ = ("config",)

    config: MysqlClientConfig

    def __init__(self, *, config: MysqlClientConfig, **fields: Unpack[ClientFields]) -> None:
        super().__init__(**fields)
        self.config = config


class MysqlClient(Tag[MysqlClientService], key="@effect/sql-mysql2/MysqlClient"):
    """The MySQL client service."""


def _nothing(*_args: object) -> Compiled:
    return ("", ())


def make_compiler(transform: Callable[[str], str] | None = None) -> Compiler:
    """MySQL's compiler: ``?`` placeholders and `` `quoted` `` names (renamed
    with ``transform`` unless a statement runs without transforms)."""

    def on_identifier(value: str, without_transform: bool) -> str:
        if transform is None or without_transform:
            return _escape(value)
        return _escape(transform(value))

    return make_statement_compiler(
        dialect="mysql",
        placeholder=lambda _index, _value: "?",
        on_identifier=on_identifier,
        on_record_update=_nothing,
        on_custom=_nothing,
    )


def connect_options(config: MysqlClientConfig) -> dict[str, Any]:
    """``asyncmy.connect``'s keywords for ``config``."""
    if config.url is not None:
        url = parse_url(redacted_value(config.url))
        fields: dict[str, Any] = {
            "host": url.host,
            "port": url.port or 3306,
            "user": url.username,
            "password": url.password or "",
            "database": url.database,
        }
        return connect_keywords(fields)
    fields = {
        **config.connect_options,
        "host": config.host or config.connect_options.get("host", "localhost"),
        "port": config.port or config.connect_options.get("port", 3306),
    }
    if config.database is not None:
        fields["database"] = config.database
    if config.username is not None:
        fields["user"] = config.username
    if config.password is not None:
        fields["password"] = redacted_value(config.password)
    return connect_keywords(fields)


def _connect_failed(error: SqlError) -> SqlError:
    cause = error.reason.cause
    return SqlError(
        reason=classify(cause, message="MysqlClient: Failed to connect", operation="connect")
    )


def _connect_timed_out() -> Effect[Never, SqlError]:
    return fail(
        SqlError(
            reason=ConnectionError(
                cause=Exception("connection timeout"),
                message="MysqlClient: Connection timeout",
                operation="connect",
            )
        )
    )


def _span_attributes(config: MysqlClientConfig) -> list[tuple[str, object]]:
    attributes: list[tuple[str, object]] = [
        *config.span_attributes.items(),
        ("db.system.name", "mysql"),
        ("server.address", config.host or "localhost"),
        ("server.port", config.port or 3306),
    ]
    if config.database:
        attributes.append(("db.namespace", config.database))
    return attributes


def make(config: MysqlClientConfig) -> Effect[MysqlClientService, SqlError, Scope | Reactivity]:
    """A client on a pool of connections; it closes with the scope."""
    prepare = not config.disable_prepared_statements
    idle = (
        DEFAULT_IDLE_TIMEOUT if config.connection_ttl is None else to_seconds(config.connection_ttl)
    )
    pool = _pool.make(
        connect_options(config),
        max_connections=config.max_connections or DEFAULT_MAX_CONNECTIONS,
        idle_timeout=idle,
    )

    def build(
        check_out: Effect[Any, SqlError, Scope],
    ) -> Effect[MysqlClientService, SqlError, Reactivity]:
        acquirer: Effect[Connection, SqlError, Scope] = check_out.map(
            lambda session: MysqlConnection(session, prepare=prepare)
        )

        def borrow[A, E, R](
            f: Callable[[Connection], Effect[A, E, R]],
        ) -> Effect[A, E | SqlError, R]:
            return scoped(acquirer.flat_map(f))

        connected = (
            scoped(
                acquirer.flat_map(
                    lambda conn: conn.execute_unprepared("SELECT 1", (), None)
                ).map_error(_connect_failed)
            )
            .timeout_or_else(_CONNECT_TIMEOUT, _connect_timed_out)
            .as_void()
        )
        transform_rows = (
            None
            if config.transform_result_names is None
            else default_transforms(config.transform_result_names).array
        )
        client = make_sql_client(
            driver="mysql2",
            acquirer=acquirer,
            borrower=borrow,
            transaction_acquirer=acquirer,
            release_savepoint=lambda name: f"RELEASE SAVEPOINT {name}",
            compiler=make_compiler(config.transform_query_names),
            span_attributes=_span_attributes(config),
            transform_rows=transform_rows,
        )
        return connected.and_then(
            client.map(lambda c: MysqlClientService(config=config, **c.fields()))
        )

    return pool.flat_map(build)


def _contexts(client: MysqlClientService) -> Context[MysqlClient | SqlClient]:
    return Context.empty().add(MysqlClient, client).add(SqlClient, client)


def layer_from[E](
    acquire: Effect[MysqlClientService, E, Scope | Reactivity],
) -> Layer[MysqlClient | SqlClient, E]:
    """Provides the client ``acquire`` makes as ``MysqlClient`` and
    ``SqlClient``, with its own ``Reactivity``."""
    require_effect(acquire, "acquire")
    return layer_effect_context(acquire.map(_contexts)).pipe(provide(reactivity_layer))


def layer(config: MysqlClientConfig) -> Layer[MysqlClient | SqlClient, SqlError]:
    """Provides a client (``make``)."""
    return layer_from(make(config))


def layer_config(
    config: Config[MysqlClientConfig] | Mapping[str, Any],
) -> Layer[MysqlClient | SqlClient, ConfigError | SqlError]:
    """``layer`` with the config read from the ``ConfigProvider``: a
    ``Config`` of the whole config, or a mapping from field names to their
    ``Config`` (Effect's ``Config.Wrap``)::

        mysql.layer_config({"url": fx.config.redacted("DATABASE_URL")})
    """
    read: Effect[MysqlClientConfig, ConfigError] = (
        config
        if isinstance(config, Config)
        else unwrap(config).map(lambda fields: MysqlClientConfig(**fields))
    )
    return layer_from(read.flat_map(make))


__all__ = [
    "MysqlClient",
    "MysqlClientService",
    "SqlError",
    "connect_options",
    "layer",
    "layer_config",
    "layer_from",
    "make",
    "make_compiler",
]
