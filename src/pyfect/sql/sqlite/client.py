"""The SQLite client on the standard library's ``sqlite3`` (Effect's
``@effect/sql-sqlite-node`` ``SqliteClient``).

Each client opens one connection, on a worker thread of its own, and
shares it between fibers: statements wait for it in turn, and a
transaction holds it until it ends.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Never, Unpack
from warnings import deprecated

from pyfect._core import Effect, _Suspend, _WithFiber
from pyfect.clock import Clock, sleep
from pyfect.config import Config, ConfigError, unwrap
from pyfect.context import Context, Tag
from pyfect.duration import Duration, to_millis
from pyfect.layer import Layer, provide
from pyfect.layer import effect_context as layer_effect_context
from pyfect.reactivity import Reactivity
from pyfect.reactivity import layer as reactivity_layer
from pyfect.scope import Scope, acquire_release, scoped
from pyfect.semaphore import Semaphore
from pyfect.sql.client import ClientFields, SqlClient, SqlClientService, make_sqlite_acquirers
from pyfect.sql.client import make as make_client
from pyfect.sql.error import LockTimeoutError, SqlError
from pyfect.sql.sqlite._connection import (
    BackupMetadata,
    RunResult,
    SqliteConnection,
    open_connection,
)
from pyfect.sql.statement import RecordUpdateHelper, default_transforms, make_compiler_sqlite

_MAX_BUSY_TIMEOUT = 2_147_483_647
_WAL_RETRY = 0.01


@dataclass(frozen=True, slots=True, kw_only=True)
class SqliteClientConfig:
    """How to open the database.

    - ``filename``: a path, or ``":memory:"``
    - ``readonly``: open it read-only (and start transactions with a plain
      ``BEGIN``; otherwise ``BEGIN IMMEDIATE``)
    - ``prepare_cache_size``: how many prepared statements to keep
    - ``disable_wal``: keep the journal mode; otherwise switch to WAL
    - ``busy_timeout``: how long SQLite waits on a locked database
      (5 seconds; infinite is clamped to SQLite's maximum). The wait
      happens on the connection's thread, not a fiber's.
    - ``span_attributes``: added to every statement's span
    - ``transform_result_names`` / ``transform_query_names``: rename
      result columns / identifiers (``fx.case`` has the usual ones)
    """

    filename: str
    readonly: bool = False
    prepare_cache_size: int = 200
    disable_wal: bool = False
    busy_timeout: Duration = 5.0
    span_attributes: Mapping[str, object] = field(default_factory=dict[str, object])
    transform_result_names: Callable[[str], str] | None = None
    transform_query_names: Callable[[str], str] | None = None

    def __post_init__(self) -> None:
        if self.prepare_cache_size < 0:
            raise ValueError(f"prepare_cache_size must be >= 0, got {self.prepare_cache_size}")


class SqliteClientService(SqlClientService):
    """A SQLite client: a ``SqlClientService`` that can also back up the
    database and load extensions. ``update_values`` is not supported."""

    __slots__ = ("config", "connection")

    config: SqliteClientConfig
    connection: SqliteConnection

    def __init__(
        self,
        *,
        config: SqliteClientConfig,
        connection: SqliteConnection,
        **fields: Unpack[ClientFields],
    ) -> None:
        super().__init__(**fields)
        self.config = config
        self.connection = connection

    def backup(self, destination: str) -> Effect[BackupMetadata, SqlError]:
        """Copy the database to the file ``destination``."""
        conn = self.connection
        return scoped(self.reserve.flat_map(lambda _: conn.backup(destination)))

    def load_extension(self, path: str) -> Effect[None, SqlError]:
        conn = self.connection
        return scoped(self.reserve.flat_map(lambda _: conn.load_extension(path)))

    @staticmethod
    @deprecated("update_values is not supported by SQLite")
    def update_values(value: Sequence[Mapping[str, object]], alias: str) -> RecordUpdateHelper:
        """Not supported by SQLite: a type error (Effect's ``never``), and a
        ``TypeError`` when called anyway."""
        raise TypeError("update_values is not supported by SQLite")


class SqliteClient(Tag[SqliteClientService], key="@effect/sql-sqlite-node/SqliteClient"):
    """The SQLite client service."""


def _busy_timeout_millis(timeout: Duration) -> int:
    millis = to_millis(timeout)
    if math.isinf(millis):
        return _MAX_BUSY_TIMEOUT
    return min(_MAX_BUSY_TIMEOUT, max(0, round(millis)))


def _enable_wal(conn: SqliteConnection, busy_timeout: int) -> Effect[None, SqlError]:
    """Switch to WAL. That can fail with ``SQLITE_BUSY`` without waiting
    for the busy handler, so retry every 10 ms until ``busy_timeout`` has
    passed, each attempt waiting at most the time left."""

    def body(fiber: Any) -> Effect[None, SqlError]:
        clock = fiber.get_ref(Clock)
        deadline = clock.monotonic_nanos_unsafe() + busy_timeout * 1_000_000

        def remaining() -> int:
            return max(0, (deadline - clock.monotonic_nanos_unsafe()) // 1_000_000)

        def retry(error: SqlError) -> Effect[None, SqlError]:
            return sleep(_WAL_RETRY).and_then(_Suspend(attempt))

        def attempt() -> Effect[None, SqlError]:
            return (
                conn.exec_config(f"PRAGMA busy_timeout = {remaining()}")
                .and_then(conn.exec_config("PRAGMA journal_mode = WAL"))
                .catch_if(
                    lambda e: isinstance(e.reason, LockTimeoutError) and remaining() > 0, retry
                )
            )

        return attempt().and_then(conn.exec_config(f"PRAGMA busy_timeout = {busy_timeout}"))

    return _WithFiber(body)


def make(config: SqliteClientConfig) -> Effect[SqliteClientService, SqlError, Scope | Reactivity]:
    """Open the database and build a client on it; the connection closes
    with the scope."""
    compiler = make_compiler_sqlite(config.transform_query_names)
    transform_rows = (
        None
        if config.transform_result_names is None
        else default_transforms(config.transform_result_names).array
    )
    busy_timeout = _busy_timeout_millis(config.busy_timeout)

    def configure(conn: SqliteConnection) -> Effect[SqliteConnection, SqlError]:
        setup = conn.exec_config(f"PRAGMA busy_timeout = {busy_timeout}")
        if not config.disable_wal and not config.readonly:
            setup = setup.and_then(_enable_wal(conn, busy_timeout))
        return setup.as_(conn)

    opened = acquire_release(
        open_connection(
            config.filename,
            readonly=config.readonly,
            prepare_cache_size=config.prepare_cache_size,
        ),
        lambda conn, _: conn.close(),
    ).flat_map(configure)

    def build(conn: SqliteConnection) -> Effect[SqliteClientService, Never, Reactivity]:
        acquirers = make_sqlite_acquirers(
            connection=_Suspend(lambda: _succeed(conn)),
            semaphore=Semaphore(1),
            is_transaction=lambda c: c.is_transaction(),
        )
        client = make_client(
            driver="sqlite-node",
            acquirer=acquirers.acquirer,
            borrower=acquirers.borrower,
            compiler=compiler,
            transaction_acquirer=acquirers.transaction_acquirer,
            on_commit_failure=acquirers.on_commit_failure,
            is_transaction=acquirers.is_transaction,
            release_savepoint=lambda name: f"RELEASE SAVEPOINT {name}",
            begin_transaction="BEGIN" if config.readonly else "BEGIN IMMEDIATE",
            span_attributes=[*config.span_attributes.items(), ("db.system.name", "sqlite")],
            transform_rows=transform_rows,
        )
        return client.map(
            lambda c: SqliteClientService(config=config, connection=conn, **c.fields())
        )

    return opened.flat_map(build)


def _succeed[A](value: A) -> Effect[A]:
    from pyfect.effect import succeed

    return succeed(value)


def _contexts(
    client: SqliteClientService,
) -> Context[SqliteClient | SqlClient]:
    return Context.empty().add(SqliteClient, client).add(SqlClient, client)


def layer(config: SqliteClientConfig) -> Layer[SqliteClient | SqlClient, SqlError]:
    """Provides the client as ``SqliteClient`` and ``SqlClient``, with its
    own ``Reactivity``."""
    return layer_effect_context(make(config).map(_contexts)).pipe(provide(reactivity_layer))


def layer_config(
    config: Config[SqliteClientConfig] | Mapping[str, Any],
) -> Layer[SqliteClient | SqlClient, ConfigError | SqlError]:
    """``layer`` with the config read from the ``ConfigProvider``: a
    ``Config`` of the whole config, or a mapping from field names to their
    ``Config`` (Effect's ``Config.Wrap``)::

        sqlite.layer_config({"filename": fx.config.string("DATABASE_PATH")})
    """
    read: Effect[SqliteClientConfig, ConfigError] = (
        config
        if isinstance(config, Config)
        else unwrap(config).map(lambda fields: SqliteClientConfig(**fields))
    )
    client = read.flat_map(make).map(_contexts)
    return layer_effect_context(client).pipe(provide(reactivity_layer))


__all__ = [
    "BackupMetadata",
    "RunResult",
    "SqlError",
    "SqliteClient",
    "SqliteClientConfig",
    "SqliteClientService",
    "SqliteConnection",
    "layer",
    "layer_config",
    "make",
]
