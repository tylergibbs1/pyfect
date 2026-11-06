"""The SQL Server client (Effect's ``@effect/sql-mssql`` ``MssqlClient``):
an ``SqlClient`` on a pool of pytds connections, with typed parameters
(``param``) and stored procedure calls (``call``).

``make`` opens the pool and checks it with ``SELECT 1`` (within
``connect_timeout``, five seconds by default); statements outside a
transaction each take a connection for themselves, a transaction keeps
one until it ends, and its savepoints are never released (SQL Server has
no ``RELEASE SAVEPOINT``). Streams are not implemented, as in Effect::

    program.pipe(fx.provide(mssql.layer(mssql.MssqlClientConfig(server="localhost", ...))))
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Never, Unpack, cast

from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect.config import Config, ConfigError, unwrap
from pyfect.context import Context, Tag
from pyfect.effect import fail
from pyfect.layer import Layer, provide
from pyfect.layer import effect_context as layer_effect_context
from pyfect.reactivity import Reactivity
from pyfect.reactivity import layer as reactivity_layer
from pyfect.redacted import value as redacted_value
from pyfect.scope import Scope, scoped
from pyfect.sql.client import (
    ClientFields,
    SqlClient,
    SqlClientService,
    TransactionOptions,
    make_with_transaction,
    transaction_connection,
)
from pyfect.sql.client import make as make_sql_client
from pyfect.sql.connection import Connection
from pyfect.sql.error import ConnectionError, SqlError
from pyfect.sql.mssql import _pool
from pyfect.sql.mssql._connection import MssqlConnection, is_mssql_param, mssql_param
from pyfect.sql.mssql._driver import ConnectOptions
from pyfect.sql.mssql._names import escape
from pyfect.sql.mssql.config import (
    DEFAULT_CANCEL_TIMEOUT,
    DEFAULT_CHECK_TIMEOUT,
    DEFAULT_CONNECT_TIMEOUT,
    DEFAULT_CONNECTION_RETRY_INTERVAL,
    DEFAULT_CONNECTION_TTL,
    DEFAULT_MAX_CONNECTIONS,
    DEFAULT_MAX_RETRIES_ON_TRANSIENT_ERRORS,
    DEFAULT_MIN_CONNECTIONS,
    DEFAULT_PORT,
    MssqlClientConfig,
    driver_seconds_or,
    seconds_or,
)
from pyfect.sql.mssql.error import classify
from pyfect.sql.mssql.procedure import ProcedureWithValues, Result
from pyfect.sql.mssql.types import DataType, ParameterOptions
from pyfect.sql.statement import (
    Compiled,
    Compiler,
    Custom,
    Fragment,
    Placeholder,
    default_transforms,
)
from pyfect.sql.statement import make_compiler as make_statement_compiler


class MssqlClientService(SqlClientService):
    """A SQL Server client: an ``SqlClientService``, its config, typed
    parameters and stored procedure calls."""

    __slots__ = ("config",)

    config: MssqlClientConfig

    def __init__(self, *, config: MssqlClientConfig, **fields: Unpack[ClientFields]) -> None:
        super().__init__(**fields)
        self.config = config

    def param(
        self,
        type: DataType,
        value: object,
        options: ParameterOptions | None = None,
    ) -> Fragment:
        """A parameter sent as ``type`` (``client.param(TYPES.BigInt, 1)``)."""
        return Fragment((mssql_param(type, value, options or ParameterOptions()),))

    def call[A](self, procedure: ProcedureWithValues[A]) -> Effect[Result[A], SqlError]:
        """Run a stored procedure (on the transaction's connection inside
        one): its output parameters and rows, renamed as the client renames
        results."""
        transform_rows = self.transform_rows
        return scoped(
            self.acquirer.flat_map(
                lambda conn: cast("MssqlConnection", conn).call(procedure, transform_rows)
            )
        )


class MssqlClient(Tag[MssqlClientService], key="@effect/sql-mssql/MssqlClient"):
    """The SQL Server client service."""


def _on_insert(
    columns: Sequence[str],
    placeholders: str,
    values: Sequence[Sequence[object]],
    returning: Compiled | None,
) -> Compiled:
    output = ""
    binds: list[object] = []
    if returning is not None:
        output = " OUTPUT INSERTED.*" if returning[0] == "*" else f" OUTPUT {returning[0]}"
        binds.extend(returning[1])
    for row in values:
        binds.extend(row)
    return (f"({','.join(columns)}){output} VALUES {placeholders}", tuple(binds))


def _on_record_update(
    placeholders: str,
    alias: str,
    columns: str,
    values: Sequence[Sequence[object]],
    returning: Compiled | None,
) -> Compiled:
    output = ""
    binds: list[object] = []
    if returning is not None:
        output = "OUTPUT INSERTED.* " if returning[0] == "*" else f"OUTPUT {returning[0]} "
        binds.extend(returning[1])
    for row in values:
        binds.extend(row)
    return (f"{output}FROM (values {placeholders}) AS {alias}{columns}", tuple(binds))


def _on_custom(
    segment: Custom[Any, Any, Any, Any], placeholder: Placeholder, _without_transform: bool
) -> Compiled:
    if is_mssql_param(segment):
        return (placeholder(None), (segment,))
    return ("", ())


def make_compiler(transform: Callable[[str], str] | None = None) -> Compiler:
    """SQL Server's compiler: ``@1``, ``@2``, ... placeholders, ``[quoted]``
    names (renamed with ``transform`` unless a statement runs without
    transforms) and ``OUTPUT INSERTED`` for ``returning``."""

    def on_identifier(value: str, without_transform: bool) -> str:
        if transform is None or without_transform:
            return escape(value)
        return escape(transform(value))

    return make_statement_compiler(
        dialect="mssql",
        placeholder=lambda index, _value: f"@{index}",
        on_identifier=on_identifier,
        on_record_update=_on_record_update,
        on_custom=_on_custom,
        on_insert=_on_insert,
    )


def connect_options(config: MssqlClientConfig) -> ConnectOptions:
    """What the driver connects with, for ``config``."""
    retries = config.max_retries_on_transient_errors
    return ConnectOptions(
        server=config.server,
        port=config.port if config.port is not None or config.instance_name else DEFAULT_PORT,
        instance_name=config.instance_name,
        database=config.database,
        username=config.username,
        password=None if config.password is None else redacted_value(config.password),
        encrypt=config.encrypt,
        trust_server=config.trust_server,
        connect_timeout=driver_seconds_or(config.connect_timeout, DEFAULT_CONNECT_TIMEOUT),
        cancel_timeout=driver_seconds_or(config.cancel_timeout, DEFAULT_CANCEL_TIMEOUT),
        connection_retry_interval=driver_seconds_or(
            config.connection_retry_interval, DEFAULT_CONNECTION_RETRY_INTERVAL
        ),
        max_retries_on_transient_errors=DEFAULT_MAX_RETRIES_ON_TRANSIENT_ERRORS
        if retries is None
        else retries,
    )


def _span_attributes(config: MssqlClientConfig) -> list[tuple[str, object]]:
    return [
        *config.span_attributes.items(),
        ("db.system.name", "microsoft.sql_server"),
        ("db.namespace", config.database or "master"),
        ("server.address", config.server),
        ("server.port", config.port or DEFAULT_PORT),
    ]


def _connect_failed(error: SqlError) -> SqlError:
    return SqlError(
        reason=classify(
            error,
            message="MssqlClient: Failed to connect",
            operation="connect",
            fallback="connection",
        )
    )


def _connect_timed_out() -> Effect[Never, SqlError]:
    return fail(
        SqlError(
            reason=ConnectionError(
                cause=Exception("connection timeout"),
                message="MssqlClient: Connection timeout",
                operation="connect",
            )
        )
    )


def make(config: MssqlClientConfig) -> Effect[MssqlClientService, SqlError, Scope | Reactivity]:
    """A client on a pool of connections; it closes with the scope."""
    pool = _pool.make(
        connect_options(config),
        config.parameter_types,
        min_connections=DEFAULT_MIN_CONNECTIONS
        if config.min_connections is None
        else config.min_connections,
        max_connections=config.max_connections or DEFAULT_MAX_CONNECTIONS,
        ttl=seconds_or(config.connection_ttl, DEFAULT_CONNECTION_TTL),
    )
    span_attributes = _span_attributes(config)

    def build(
        check_out: Effect[MssqlConnection, SqlError, Scope],
    ) -> Effect[MssqlClientService, SqlError, Reactivity]:
        acquirer = cast("Effect[Connection, SqlError, Scope]", check_out)
        connected = (
            scoped(
                acquirer.flat_map(
                    lambda conn: conn.execute_unprepared("SELECT 1", (), None)
                ).map_error(_connect_failed)
            )
            .timeout_or_else(
                seconds_or(config.connect_timeout, DEFAULT_CHECK_TIMEOUT), _connect_timed_out
            )
            .as_void()
        )
        transform_rows = (
            None
            if config.transform_result_names is None
            else default_transforms(config.transform_result_names).array
        )
        service = transaction_connection()

        def mssql(conn: Connection) -> MssqlConnection:
            return cast("MssqlConnection", conn)

        with_transaction = make_with_transaction(
            TransactionOptions(
                transaction_service=service,
                span_attributes=tuple(span_attributes),
                acquire_connection=lambda restore: restore(acquirer),
                begin=lambda conn, _statement: mssql(conn).begin,
                savepoint=lambda conn, depth: mssql(conn).savepoint(f"effect_sql_{depth}"),
                commit=lambda conn: mssql(conn).commit,
                rollback=lambda conn: mssql(conn).rollback(),
                rollback_savepoint=lambda conn, depth: mssql(conn).rollback(f"effect_sql_{depth}"),
            )
        )
        client = make_sql_client(
            driver="mssql",
            acquirer=acquirer,
            compiler=make_compiler(config.transform_query_names),
            transaction_service=service,
            span_attributes=span_attributes,
            transform_rows=transform_rows,
        )

        def finish(c: SqlClientService) -> MssqlClientService:
            fields = c.fields()
            fields["with_transaction"] = with_transaction
            return MssqlClientService(config=config, **fields)

        return connected.and_then(client.map(finish))

    return pool.flat_map(build)


def _contexts(client: MssqlClientService) -> Context[MssqlClient | SqlClient]:
    return Context.empty().add(MssqlClient, client).add(SqlClient, client)


def layer_from[E](
    acquire: Effect[MssqlClientService, E, Scope | Reactivity],
) -> Layer[MssqlClient | SqlClient, E]:
    """Provides the client ``acquire`` makes as ``MssqlClient`` and
    ``SqlClient``, with its own ``Reactivity``."""
    require_effect(acquire, "acquire")
    return layer_effect_context(acquire.map(_contexts)).pipe(provide(reactivity_layer))


def layer(config: MssqlClientConfig) -> Layer[MssqlClient | SqlClient, SqlError]:
    """Provides a client (``make``)."""
    return layer_from(make(config))


def layer_config(
    config: Config[MssqlClientConfig] | Mapping[str, Any],
) -> Layer[MssqlClient | SqlClient, ConfigError | SqlError]:
    """``layer`` with the config read from the ``ConfigProvider``: a
    ``Config`` of the whole config, or a mapping from field names to their
    ``Config`` (Effect's ``Config.Wrap``)::

        mssql.layer_config({
            "server": fx.config.string("MSSQL_SERVER"),
            "password": fx.config.redacted("MSSQL_PASSWORD"),
        })
    """
    read: Effect[MssqlClientConfig, ConfigError] = (
        config
        if isinstance(config, Config)
        else unwrap(config).map(lambda fields: MssqlClientConfig(**fields))
    )
    return layer_from(read.flat_map(make))


__all__ = [
    "MssqlClient",
    "MssqlClientService",
    "SqlError",
    "connect_options",
    "layer",
    "layer_config",
    "layer_from",
    "make",
    "make_compiler",
]
