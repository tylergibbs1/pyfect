"""Pools of PostgreSQL sessions (Effect's ``@effect/sql-pg`` ``PgPool``).

Sessions open as they are needed, up to ``max_connections``, and close
again down to ``min_connections`` after ``idle_timeout`` unused. A
checkout skips (and replaces) a session that died, outlived its
``connection_ttl``, or had a cancel PostgreSQL did not confirm. Every
checkout is exclusive.

With ``SpanPropagationEnabled`` (and span timing), a statement that waited
for a new session gets a ``db.connect`` child span covering the part of
the connect it waited for, with ``db.client.connection.connect_time_ms``.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Never

from pyfect._core import Effect, _Succeed, _Suspend, _WithFiber
from pyfect._fiber import Fiber
from pyfect._primitives import Restore, uninterruptible_mask
from pyfect._tracer_ref import CurrentTracer
from pyfect.clock import Clock, ClockService, monotonic
from pyfect.context import Context, Tag
from pyfect.duration import Duration, from_input_unsafe
from pyfect.effect import fail, provide_service, succeed, sync
from pyfect.exit import Failure, Success
from pyfect.pool import Pool, PoolStats
from pyfect.scope import CloseableScope, Scope, add_finalizer, scoped
from pyfect.sql.error import SqlError
from pyfect.sql.pg.config import PgPoolConfig
from pyfect.sql.pg.connection import PgConnection
from pyfect.sql.pg.connection import make as make_connection
from pyfect.sql.pg.error import connection_error
from pyfect.sql.statement import SpanPropagationEnabled
from pyfect.tracer._model import ExternalSpan, SpanRequest
from pyfect.tracer._refs import ParentSpan, TracerEnabled, TracerTimingEnabled

_VOID: Effect[None] = _Succeed(None)


class PgPoolService:
    """A pool of sessions.

    - ``get``: a session until the scope closes
    - ``reserve``: a pinned session until the scope closes (transactions
      and listeners)
    - ``use(f)``: a session for as long as ``f``'s effect runs
    - ``invalidate(connection)``: replace a session
    - ``stats``: a snapshot of session occupancy (sessions, not statements;
      a session that has just failed can show as idle until the pool
      removes it)
    """

    __slots__ = ("_check_out", "_hand_out", "_pool", "_slow_use", "config")

    def __init__(
        self,
        config: PgPoolConfig,
        pool: Pool[PgConnection, SqlError],
        check_out: Effect[PgConnection, SqlError, Scope],
        slow_use: Callable[[], bool],
        hand_out: Callable[[PgConnection], Effect[PgConnection]],
    ) -> None:
        self.config = config
        self._pool = pool
        self._check_out = check_out
        self._slow_use = slow_use
        self._hand_out = hand_out

    @property
    def get(self) -> Effect[PgConnection, SqlError, Scope]:
        """Checks out a session until the current scope closes, replacing
        one past its ``connection_ttl``. Fails with an ``SqlError`` when no
        session can be connected or ``acquire_timeout`` passes first."""
        return self._check_out

    @property
    def reserve(self) -> Effect[PgConnection, SqlError, Scope]:
        """``get``, pinned: the session is reserved for the connection
        given until the current scope closes (for transactions and
        listeners). Fails as ``get`` does."""
        return self._check_out.flat_map(lambda connection: connection.pin)

    def use[A, E, R](
        self, f: Callable[[PgConnection], Effect[A, E, R]]
    ) -> Effect[A, E | SqlError, R]:
        """Lends a session to ``f`` for as long as its effect runs and
        takes it back on any exit, without opening a scope; a lease that
        must outlive the effect (a stream, a transaction) takes ``get`` or
        ``reserve``. Fails with ``f``'s errors, or an ``SqlError`` as
        ``get`` does."""

        def body() -> Effect[A, E | SqlError, R]:
            if self._slow_use():
                return scoped(self._check_out.flat_map(f))
            return self._pool.use(lambda connection: self._hand_out(connection).flat_map(f))

        return _Suspend(body)

    def invalidate(self, connection: PgConnection) -> Effect[None]:
        """Removes ``connection``'s session so the pool can replace it;
        never fails. Fatal protocol and socket errors invalidate sessions
        on their own."""
        return self._pool.invalidate(connection.base)

    @property
    def stats(self) -> Effect[PoolStats]:
        """A snapshot of session occupancy; never fails. It counts
        sessions, not statements, and a session that has just failed can
        show as idle until the pool removes it."""
        return self._pool.stats()


class PgPool(Tag[PgPoolService], key="@effect/sql-pg/PgPool"):
    """The pool service."""


def _acquire_timed_out() -> Effect[Never, SqlError]:
    return fail(
        connection_error("PgPool: Timed out waiting for a pooled connection", "acquireConnection")
    )


def _with_timeout[A](
    effect: Effect[A, SqlError, Scope], timeout: Duration | None
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


class _Connects:
    """When each session's connect started and ended (on the pool's clock),
    until its first checkout reports it. The pool connects on its own
    fiber, where a span would have no statement parent."""

    __slots__ = ("_clock", "_opened")

    def __init__(self, clock: ClockService) -> None:
        self._clock = clock
        self._opened: dict[PgConnection, tuple[int, int]] = {}

    def timed[E](self, connect: Effect[PgConnection, E, Scope]) -> Effect[PgConnection, E, Scope]:
        """``connect``, recording its times until the session's first
        checkout or its close, whichever comes first (Effect's WeakMap)."""

        def body() -> Effect[PgConnection, E, Scope]:
            start = self._clock.now_nanos_unsafe()

            def opened(connection: PgConnection) -> Effect[PgConnection, Never, Scope]:
                self._opened[connection] = (start, self._clock.now_nanos_unsafe())

                def forget(_: object) -> Effect[None]:
                    return sync(lambda: self._opened.pop(connection, None)).as_(None)

                return add_finalizer(forget).as_(connection)

            return connect.flat_map(opened)

        return _Suspend(body)

    def hand_out(self, connection: PgConnection) -> Effect[PgConnection]:
        if connection not in self._opened:
            return _Succeed(connection)
        return _WithFiber(lambda fiber: self._report(fiber, connection).as_(connection))

    def _report(self, fiber: Fiber[Any, Any], connection: PgConnection) -> Effect[None]:
        start, end = self._opened.pop(connection)
        statement = fiber.get_ref(ParentSpan)
        # Without span timing the statement span has no start time.
        if (
            statement is None
            or isinstance(statement, ExternalSpan)
            or not fiber.get_ref(TracerEnabled)
            or not fiber.get_ref(SpanPropagationEnabled)
            or not fiber.get_ref(TracerTimingEnabled)
        ):
            return _VOID
        waited_from = statement.status.start_time
        if end < waited_from:
            return _VOID
        span = fiber.get_ref(CurrentTracer).span(
            SpanRequest(
                name="db.connect",
                parent=statement,
                annotations=Context.empty(),
                links=[],
                start_time=max(start, waited_from),
                kind="client",
                root=False,
                sampled=statement.sampled,
            )
        )
        span.attribute("db.system.name", "postgresql")
        span.attribute("db.client.connection.connect_time_ms", (end - start) / 1e6)
        span.end(end, Success(None))
        return _VOID


def make(config: PgPoolConfig) -> Effect[PgPoolService, SqlError, Scope]:
    """A pool; closing the scope closes every session."""
    return _WithFiber(lambda fiber: _make(config, _Connects(fiber.get_ref(Clock))))


def _check_out(
    pool: Pool[PgConnection, SqlError],
    expired: Callable[[PgConnection, float], bool],
    connects: _Connects,
) -> Effect[PgConnection, SqlError, Scope]:
    def checked(connection: PgConnection) -> Effect[PgConnection, SqlError, Scope]:
        def at(now: float) -> Effect[PgConnection, SqlError, Scope]:
            if expired(connection, now):
                again = _Suspend(lambda: _check_out(pool, expired, connects))
                return pool.invalidate(connection).and_then(again)
            return succeed(connection)

        return monotonic().flat_map(at)

    return pool.get().flat_map(checked).flat_map(connects.hand_out)


def _make(config: PgPoolConfig, connects: _Connects) -> Effect[PgPoolService, SqlError, Scope]:
    ttl = None if config.connection_ttl is None else from_input_unsafe(config.connection_ttl)
    timeout = None if config.acquire_timeout is None else from_input_unsafe(config.acquire_timeout)
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

    acquire = connects.timed(make_connection(config)).tap(track)

    def expired(connection: PgConnection, now: float) -> bool:
        if connection.needs_retire:
            return True
        if ttl is None:
            return False
        if connection not in checked_out:
            checked_out.add(connection)
            return False
        return now - opened_at.get(connection, now) >= ttl.to_seconds()

    def slow_use() -> bool:
        return ttl is not None or timeout is not None or any(c.needs_retire for c in opened_at)

    def build(pool: Pool[PgConnection, SqlError]) -> PgPoolService:
        holder.append(pool)
        check_out = _Suspend(lambda: _check_out(pool, expired, connects))
        return PgPoolService(
            config, pool, _with_timeout(check_out, timeout), slow_use, connects.hand_out
        )

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
