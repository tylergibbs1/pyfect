"""The libSQL client (Effect's ``@effect/sql-libsql`` ``LibsqlClient``): an
``SqlClient`` with SQLite's SQL on one SDK client.

On a local database statements and transactions take turns: a statement
outside a transaction holds the client until it is done, and a transaction
from its ``BEGIN`` until it commits or rolls back. Remote statements and
transactions overlap, each on a stream of its own. ``BeginTransaction`` is ignored:
transactions begin in ``write`` mode (``BEGIN IMMEDIATE``). Streams are
not supported.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Never, Unpack, cast

from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect._primitives import Restore
from pyfect.config import Config, ConfigError, unwrap
from pyfect.context import Context, Tag
from pyfect.effect import succeed
from pyfect.layer import Layer, provide
from pyfect.layer import effect_context as layer_effect_context
from pyfect.reactivity import Reactivity
from pyfect.reactivity import layer as reactivity_layer
from pyfect.scope import Scope, acquire_release
from pyfect.semaphore import Semaphore
from pyfect.sql import _loop
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
from pyfect.sql.error import SqlError, classify_sqlite_error
from pyfect.sql.libsql._connection import ClientConnection, OpenTransaction
from pyfect.sql.libsql._local import LocalClient
from pyfect.sql.libsql._targets import RemoteTarget, Target
from pyfect.sql.libsql.config import LibsqlClientConfig, LibsqlLiveConfig
from pyfect.sql.libsql.sdk import LibsqlSdk, ManagedSdk
from pyfect.sql.statement import default_transforms, make_compiler_sqlite


class LibsqlClientService(SqlClientService):
    """A libSQL client: an ``SqlClientService``, its config and the SDK
    client it runs on."""

    __slots__ = ("config", "sdk")

    config: LibsqlClientConfig | LibsqlLiveConfig
    sdk: LibsqlSdk

    def __init__(
        self,
        *,
        config: LibsqlClientConfig | LibsqlLiveConfig,
        sdk: LibsqlSdk,
        **fields: Unpack[ClientFields],
    ) -> None:
        super().__init__(**fields)
        self.config = config
        self.sdk = sdk


class LibsqlClient(Tag[LibsqlClientService], key="@effect/sql-libsql/LibsqlClient"):
    """The libSQL client service."""


def _catch(message: str, operation: str) -> Callable[[BaseException], SqlError]:
    return lambda cause: SqlError(
        reason=classify_sqlite_error(cause, message=message, operation=operation)
    )


def _open(target: Target) -> Effect[ManagedSdk]:
    """The SDK client for ``target``. A local database that cannot be
    opened is a defect, as ``createClient`` throws in Effect."""
    if isinstance(target, RemoteTarget):
        from pyfect.sql.libsql._hrana import RemoteClient

        remote: ManagedSdk = RemoteClient(target)
        return succeed(remote)
    opened = _loop.call(
        lambda: LocalClient.open(target),
        _catch("Failed to open database", "connect"),
        waits_for="work",
    )
    return opened.map(lambda client: cast("ManagedSdk", client)).or_die()


def _close(sdk: ManagedSdk) -> Effect[None]:
    return _loop.call(sdk.close, _catch("Failed to close", "close"), waits_for="work").or_die()


def _sdk(config: LibsqlClientConfig | LibsqlLiveConfig) -> Effect[LibsqlSdk, Never, Scope]:
    if isinstance(config, LibsqlLiveConfig):
        return succeed(config.live_client)
    managed = acquire_release(_open(config.target), lambda sdk, _: _close(sdk))
    return managed.map(lambda sdk: cast("LibsqlSdk", sdk))


def _savepoint(statement: str) -> Callable[[Connection, int], Effect[None, SqlError]]:
    def run(conn: Connection, depth: int) -> Effect[None, SqlError]:
        return conn.execute_raw(f"{statement} effect_sql_{depth};", ()).as_void()

    return run


def _commit(conn: Connection) -> Effect[None, SqlError]:
    return cast("OpenTransaction", conn).commit()


def _rollback(conn: Connection) -> Effect[None, SqlError]:
    return cast("OpenTransaction", conn).rollback()


def _no_begin(_conn: Connection, _statement: str | None) -> Effect[None, SqlError]:
    # The transaction began when its connection was acquired.
    return succeed(None)


def make(
    config: LibsqlClientConfig | LibsqlLiveConfig,
) -> Effect[LibsqlClientService, Never, Scope | Reactivity]:
    """A client on ``config``'s database; one it opened closes with the
    scope."""
    service = transaction_connection()
    transform_rows = (
        None
        if config.transform_result_names is None
        else default_transforms(config.transform_result_names).array
    )
    span_attributes: list[tuple[str, object]] = [
        *config.span_attributes.items(),
        ("db.system.name", "sqlite"),
    ]

    def build(sdk: LibsqlSdk) -> Effect[LibsqlClientService, Never, Reactivity]:
        connection = ClientConnection(sdk)
        # Remote transports run each statement and transaction on a stream of
        # its own. A local client may own a single connection that it refuses
        # to lend while a transaction holds it, so take turns on it instead.
        permit: Effect[None, Never, Scope] = (
            succeed(None) if sdk.protocol in {"http", "ws"} else Semaphore(1).take_scoped(1)
        )

        def acquire_transaction(restore: Restore) -> Effect[Connection, SqlError, Scope]:
            # Runs masked: only the wait for the permit is interruptible, so
            # a BEGIN the SDK started always ends in a commit or rollback.
            began: Effect[Connection, SqlError] = connection.begin_transaction()
            return restore(permit).and_then(began)

        # Outside a transaction, hold the permit until the statement's scope
        # closes, so no other fiber can begin a transaction while it runs.
        lease: Effect[Connection, SqlError, Scope] = permit.as_(connection)
        with_transaction = make_with_transaction(
            TransactionOptions(
                transaction_service=service,
                span_attributes=tuple(span_attributes),
                acquire_connection=acquire_transaction,
                begin=_no_begin,
                savepoint=_savepoint("SAVEPOINT"),
                release_savepoint=_savepoint("RELEASE SAVEPOINT"),
                rollback_savepoint=_savepoint("ROLLBACK TO SAVEPOINT"),
                commit=_commit,
                rollback=_rollback,
            )
        )
        client = make_sql_client(
            driver="libsql",
            acquirer=lease,
            compiler=make_compiler_sqlite(config.transform_query_names),
            transaction_service=service,
            span_attributes=span_attributes,
            transform_rows=transform_rows,
        )

        def service_of(c: SqlClientService) -> LibsqlClientService:
            fields = c.fields()
            fields["with_transaction"] = with_transaction
            return LibsqlClientService(config=config, sdk=sdk, **fields)

        return client.map(service_of)

    return _sdk(config).flat_map(build)


def _contexts(client: LibsqlClientService) -> Context[LibsqlClient | SqlClient]:
    return Context.empty().add(LibsqlClient, client).add(SqlClient, client)


def layer_from[E](
    acquire: Effect[LibsqlClientService, E, Scope | Reactivity],
) -> Layer[LibsqlClient | SqlClient, E]:
    """Provides the client ``acquire`` makes as ``LibsqlClient`` and
    ``SqlClient``, with its own ``Reactivity``."""
    require_effect(acquire, "acquire")
    return layer_effect_context(acquire.map(_contexts)).pipe(provide(reactivity_layer))


def layer(config: LibsqlClientConfig | LibsqlLiveConfig) -> Layer[LibsqlClient | SqlClient]:
    """Provides a client (``make``)."""
    return layer_from(make(config))


def layer_config(
    config: Config[LibsqlClientConfig] | Config[LibsqlLiveConfig] | Mapping[str, Any],
) -> Layer[LibsqlClient | SqlClient, ConfigError]:
    """``layer`` with the config read from the ``ConfigProvider``: a
    ``Config`` of the whole config, or a mapping from ``LibsqlClientConfig``
    field names to their ``Config`` (Effect's ``Config.Wrap``)::

        libsql.layer_config({"url": fx.config.string("LIBSQL_URL")})
    """
    read: Effect[LibsqlClientConfig | LibsqlLiveConfig, ConfigError] = (
        config
        if isinstance(config, Config)
        else unwrap(config).map(lambda fields: LibsqlClientConfig(**fields))
    )
    return layer_from(read.flat_map(make))


__all__ = ["LibsqlClient", "LibsqlClientService", "layer", "layer_config", "layer_from", "make"]
