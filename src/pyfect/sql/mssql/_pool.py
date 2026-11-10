"""The pool of SQL Server connections (Effect's ``Pool.makeWithTTL`` in
``MssqlClient``): between ``min`` and ``max`` connections, each closed
``ttl`` after its creation.

A connection the driver ended is invalidated, so the pool closes and
replaces it; as in Effect, a checkout also checks for the end, which can
come before the pool knows the connection."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from typing import Any, Never

from pyfect._core import Effect, _Succeed, _Suspend
from pyfect._primitives import uninterruptible_mask
from pyfect.duration import Duration
from pyfect.exit import Exit, Success
from pyfect.pool import Pool
from pyfect.process._os import Latch
from pyfect.scope import Scope, add_finalizer, fork_scoped
from pyfect.sql.error import SqlError
from pyfect.sql.mssql import _tds
from pyfect.sql.mssql._connection import MssqlConnection
from pyfect.sql.mssql._driver import ConnectOptions, RawConnection
from pyfect.sql.mssql._worker import Worker
from pyfect.sql.mssql.error import catch
from pyfect.sql.mssql.types import ParameterTypes

_CONNECT = catch("Failed to connect", "connect", "connection")


class _PoolRef:
    """The pool, once made (its connections are made before it is)."""

    pool: Pool[MssqlConnection, SqlError] | None = None


def _close(raw: RawConnection, worker: Worker) -> Effect[None]:
    def close() -> None:
        try:
            raw.close()
        finally:
            worker.shutdown()

    return _Suspend(lambda: _Succeed(close()))


def _open(
    options: ConnectOptions, parameter_types: ParameterTypes, ref: _PoolRef
) -> Effect[MssqlConnection, SqlError, Scope]:
    """A connection, closed with the scope."""

    def start() -> Effect[MssqlConnection, SqlError, Scope]:
        worker = Worker()
        ended: Latch[None] = Latch(waits_for="event")

        def end() -> None:
            ended.set(None)

        # ``_tds.connect`` is looked up at each call, so tests can replace it.
        opened = worker.call(
            lambda: _tds.connect(options, end), _CONNECT, release=lambda raw: raw.close()
        )

        def stop_unless_opened(exit_: Exit[RawConnection, SqlError]) -> Effect[None]:
            if isinstance(exit_, Success):
                return _Succeed(None)
            return _Suspend(lambda: _Succeed(worker.shutdown()))

        def invalidate(connection: MssqlConnection) -> Effect[None]:
            pool = ref.pool
            return _Succeed(None) if pool is None else pool.invalidate(connection)

        def track(raw: RawConnection) -> Effect[MssqlConnection, Never, Scope]:
            connection = MssqlConnection(raw, worker, ended, parameter_types)
            watch = ended.wait().and_then(_Suspend(lambda: invalidate(connection)))
            return (
                add_finalizer(lambda _: _close(raw, worker))
                .and_then(fork_scoped(watch.interruptible()))
                .as_(connection)
            )

        return uninterruptible_mask(
            lambda restore: restore(opened).on_exit(stop_unless_opened).flat_map(track)
        )

    return _Suspend(start)


def make(
    options: ConnectOptions,
    parameter_types: ParameterTypes,
    *,
    min_connections: int,
    max_connections: int,
    ttl: Duration,
) -> Effect[Effect[MssqlConnection, SqlError, Scope], Never, Scope]:
    """A pool closed with the scope, as its checkout: a connection until the
    checkout's scope closes."""
    ref = _PoolRef()

    def build(pool: Pool[MssqlConnection, SqlError]) -> Effect[MssqlConnection, SqlError, Scope]:
        ref.pool = pool

        def check_out() -> Effect[MssqlConnection, SqlError, Scope]:
            def checked(connection: MssqlConnection) -> Effect[MssqlConnection, SqlError, Scope]:
                if connection.ended:
                    return pool.invalidate(connection).and_then(_Suspend(check_out))
                return _Succeed(connection)

            return pool.get().flat_map(checked)

        return _Suspend(check_out)

    pool: Effect[Pool[MssqlConnection, SqlError], Never, Any] = Pool.make_with_ttl(
        _open(options, parameter_types, ref),
        min=min_connections,
        max=max_connections,
        time_to_live=ttl,
        time_to_live_strategy="creation",
    )
    return pool.map(build)


__all__ = ["make"]
