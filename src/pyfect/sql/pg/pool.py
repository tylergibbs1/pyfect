"""Pools of PostgreSQL sessions (Effect's ``@effect/sql-pg`` ``PgPool``).

Sessions open as they are needed, up to ``max_connections``, and close
again down to ``min_connections`` after ``idle_timeout`` unused. A
checkout skips (and replaces) a session that died, outlived its
``connection_ttl``, or had a cancel PostgreSQL did not confirm. Every
checkout is exclusive.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Never

from pyfect._core import Effect, _Suspend
from pyfect._primitives import Restore, uninterruptible_mask
from pyfect.clock import monotonic
from pyfect.context import Tag
from pyfect.duration import to_seconds
from pyfect.effect import fail, provide_service, succeed, sync
from pyfect.exit import Failure
from pyfect.pool import Pool
from pyfect.scope import CloseableScope, Scope, add_finalizer, scoped
from pyfect.sql.error import SqlError
from pyfect.sql.pg.config import PgPoolConfig
from pyfect.sql.pg.connection import PgConnection
from pyfect.sql.pg.connection import make as make_connection
from pyfect.sql.pg.error import connection_error


class PgPoolService:
    """A pool of sessions.

    - ``get``: a session until the scope closes
    - ``reserve``: a pinned session until the scope closes (transactions
      and listeners)
    - ``use(f)``: a session for as long as ``f``'s effect runs
    - ``invalidate(connection)``: replace a session
    """

    __slots__ = ("_check_out", "_pool", "_slow_use", "config")

    def __init__(
        self,
        config: PgPoolConfig,
        pool: Pool[PgConnection, SqlError],
        check_out: Effect[PgConnection, SqlError, Scope],
        slow_use: Callable[[], bool],
    ) -> None:
        self.config = config
        self._pool = pool
        self._check_out = check_out
        self._slow_use = slow_use

    @property
    def get(self) -> Effect[PgConnection, SqlError, Scope]:
        return self._check_out

    @property
    def reserve(self) -> Effect[PgConnection, SqlError, Scope]:
        return self._check_out.flat_map(lambda connection: connection.pin)

    def use[A, E, R](
        self, f: Callable[[PgConnection], Effect[A, E, R]]
    ) -> Effect[A, E | SqlError, R]:
        def body() -> Effect[A, E | SqlError, R]:
            if self._slow_use():
                return scoped(self._check_out.flat_map(f))
            return self._pool.use(f)

        return _Suspend(body)

    def invalidate(self, connection: PgConnection) -> Effect[None]:
        return self._pool.invalidate(connection.base)


class PgPool(Tag[PgPoolService], key="@effect/sql-pg/PgPool"):
    """The pool service."""


def _acquire_timed_out() -> Effect[Never, SqlError]:
    return fail(
        connection_error("PgPool: Timed out waiting for a pooled connection", "acquireConnection")
    )


def _with_timeout[A](
    effect: Effect[A, SqlError, Scope], timeout: float | None
) -> Effect[A, SqlError, Scope]:
    """Bound ``effect``; it runs in a child scope, so a lease it took
    before timing out goes back at once."""
    if timeout is None:
        return effect

    def body(restore: Restore) -> Effect[A, SqlError, Scope]:
        def in_child(child: CloseableScope) -> Effect[A, SqlError]:
            bounded = effect.pipe(provide_service(Scope, child)).timeout_or_else(
                timeout, _acquire_timed_out
            )
            return restore(bounded).on_error(lambda cause: child.close(Failure(cause)))

        return Scope().flat_map(lambda parent: parent.fork()).flat_map(in_child)

    return uninterruptible_mask(body)


def make(config: PgPoolConfig) -> Effect[PgPoolService, SqlError, Scope]:
    """A pool; closing the scope closes every session."""
    ttl = None if config.connection_ttl is None else to_seconds(config.connection_ttl)
    timeout = None if config.acquire_timeout is None else to_seconds(config.acquire_timeout)
    opened_at: dict[PgConnection, float] = {}
    checked_out: set[PgConnection] = set()
    holder: list[Pool[PgConnection, SqlError]] = []

    def track(connection: PgConnection) -> Effect[None, Never, Scope]:
        def forget(_: object) -> Effect[None]:
            def run() -> None:
                opened_at.pop(connection, None)
                checked_out.discard(connection)

            return sync(run)

        def opened(now: float) -> Effect[None, Never, Scope]:
            opened_at[connection] = now
            connection.on_retire(lambda: holder[0].invalidate(connection))
            return add_finalizer(forget)

        return monotonic().flat_map(opened)

    acquire = make_connection(config).tap(track)

    def expired(connection: PgConnection, now: float) -> bool:
        if connection.needs_retire:
            return True
        if ttl is None:
            return False
        if connection not in checked_out:
            checked_out.add(connection)
            return False
        return now - opened_at.get(connection, now) >= ttl

    def check_out() -> Effect[PgConnection, SqlError, Scope]:
        pool = holder[0]

        def checked(connection: PgConnection) -> Effect[PgConnection, SqlError, Scope]:
            def at(now: float) -> Effect[PgConnection, SqlError, Scope]:
                if expired(connection, now):
                    return pool.invalidate(connection).and_then(_Suspend(check_out))
                return succeed(connection)

            return monotonic().flat_map(at)

        return pool.get().flat_map(checked)

    def slow_use() -> bool:
        return ttl is not None or timeout is not None or any(c.needs_retire for c in opened_at)

    def build(pool: Pool[PgConnection, SqlError]) -> PgPoolService:
        holder.append(pool)
        return PgPoolService(config, pool, _with_timeout(_Suspend(check_out), timeout), slow_use)

    pool: Effect[Pool[PgConnection, SqlError], Never, Any] = Pool.make_with_ttl(
        acquire,
        min=config.min_connections,
        max=config.max_connections,
        time_to_live=config.idle_timeout,
        time_to_live_strategy="usage",
    )
    return pool.map(build)


__all__ = [
    "PgPool",
    "PgPoolService",
    "SqlError",
    "make",
]
