"""Ports of Effect's ``sql-pg/test/PgPool.integration.test.ts`` and
``PgPool.in-process.test.ts``, against a throwaway local PostgreSQL
(``_postgres.pg_server``; skipped without one).

Adapted: the late-cancel tests route the pool through ``CancelGate``, a TCP
proxy that holds back cancel requests (Effect's ``LateCancelProxy`` is a
``stream`` factory; libpq sends its cancel to the same address). The
listener tests that Effect runs on a ``multiplex`` pool run on a plain
one: multiplexing is not ported (psycopg runs one statement at a time per
session). "reports a caller-owned connect failure instead of retrying
indefinitely" connects to a port that closes every connection; "fails a
checkout that waits on an exhausted pool past acquireTimeout" uses the real
server.

Omitted:
- "defaults multiplex concurrency to 32", "keeps a multiplexed stream's
  connection to itself", "honours a configured multiplex concurrency",
  "fails a multiplexed reservation that waits on a busy pipeline past
  acquireTimeout": multiplexing is not ported.
- "replaces a fatal session before the next pool.use query": a psycopg
  loader that fails raises from the fetch and leaves the session usable,
  so there is no fatal decode failure to replace.
- "retries a stale background acquisition rather than failing an unrelated
  checkout": needs a scripted server that answers some startups and stalls
  others (a ``stream`` factory).

Adapted: the "PgPool connection spans" tests hold each connect in a paused
``CancelGate`` (Effect's held-startup ``stream`` factory) for 40 ms of real
time (a ``TestClock`` adjustment waits for the held connect, on the SQL
loop thread, to finish), so the connect takes at least 40 ms and starts
when the pool opens the session, just after the statement's span.
"""
# pyright: reportPrivateUsage=false

import threading
import time
from collections.abc import Generator
from typing import Any

import pytest

pytest.importorskip("psycopg")

import pyfect as fx
from pyfect import scope, testing
from pyfect.cause import Interrupted
from pyfect.exit import Failure
from pyfect.scope import Scope
from pyfect.sql import pg
from pyfect.sql.client import SqlClient
from pyfect.sql.error import SqlError
from pyfect.sql.pg.connection import PgConnection, Result
from pyfect.sql.statement import SpanPropagationEnabled

from ._postgres import (
    CancelGate,
    ClosingListener,
    PgServer,
    wait_until_active,
    wait_until_advisory_lock,
)

_BLOCKED_STREAM = """
  SELECT n FROM generate_series(1, 1000) AS g(n)
  UNION ALL
  SELECT 1001::int4 AS n
  FROM (SELECT pg_advisory_xact_lock($1::int4)) AS blocked
"""

_LOCK = "SELECT pg_advisory_xact_lock($1::int4)"


def _config(server: PgServer, **fields: Any) -> pg.PgPoolConfig:
    return pg.PgPoolConfig(url=server.url, **fields)


def _connect(server: PgServer) -> fx.Effect[PgConnection, SqlError, Scope]:
    return pg.connection.make(pg.PgConnectionConfig(url=server.url))


def _wait_for(event: threading.Event) -> fx.Effect[None]:
    def body() -> Generator[Any, Any]:
        deadline = time.monotonic() + 5
        while not event.is_set():
            assert time.monotonic() < deadline, "timed out waiting for the cancel gate"
            yield from fx.sleep(0.01)

    return fx.gen(body)


def _pid(connection: PgConnection) -> int:
    return connection.process_id


# --- PgPool -------------------------------------------------------------------


@testing.live
def test_reuses_checked_out_connections(pg_server: PgServer):
    """reuses checked out connections"""
    pool = yield from pg.pool.make(_config(pg_server, max_connections=1))

    def checking_out():
        connection = yield from pool.get
        result = yield from connection.query("SELECT $1::int4 AS one", [1])
        assert result.rows == [{"one": 1}]
        return connection.process_id

    first = yield from fx.scoped(fx.gen(checking_out))
    second = yield from fx.scoped(fx.gen(checking_out))
    assert first == second


@testing.live
def test_uses_a_connection_once_when_its_ttl_is_zero(pg_server: PgServer):
    """uses a connection once when its TTL is zero"""
    pool = yield from pg.pool.make(_config(pg_server, connection_ttl=0, max_connections=1))
    checkout = fx.scoped(pool.get.map(_pid)).timeout(1)
    first = yield from checkout
    second = yield from checkout
    assert first != second


@testing.live
def test_streams_rows_incrementally_and_cancels_on_early_abort(pg_server: PgServer):
    """streams rows incrementally and cancels on early abort"""
    pool = yield from pg.pool.make(_config(pg_server))
    connection = yield from pool.get
    rows = yield from connection.stream(
        "SELECT n FROM generate_series(1, $1::int4) AS g(n)", [1000]
    ).run_collect()
    assert len(rows) == 1000
    assert rows[0] == {"n": 1}
    assert rows[999] == {"n": 1000}
    aborted = (
        yield from connection.stream("SELECT n FROM generate_series(1, 5000) AS g(n)")
        .take(5)
        .run_collect()
    )
    assert aborted == [{"n": 1}, {"n": 2}, {"n": 3}, {"n": 4}, {"n": 5}]
    result = yield from connection.query(
        "SELECT pg_backend_pid()::int4 AS pid, $1::text AS after", ["ok"]
    )
    assert result.rows == [{"pid": connection.process_id, "after": "ok"}]


@testing.live
def test_acquires_a_multiplexed_listener_after_registration(pg_server: PgServer):
    """acquires a multiplexed listener after registration"""
    pool = yield from pg.pool.make(_config(pg_server, max_connections=2))
    listener = yield from pool.reserve
    notifications = yield from listener.listen("test_channel")
    notifier = yield from pool.get
    assert listener.process_id != notifier.process_id
    yield from notifier.query("SELECT pg_notify($1, $2)", ["test_channel", "hello"])
    notification = yield from notifications.take()
    assert notification.channel == "test_channel"
    assert notification.payload == "hello"
    assert notification.process_id == notifier.process_id


@testing.live
def test_does_not_hand_on_a_listener_registered_through_a_released_pin(pg_server: PgServer):
    """does not hand on a listener registered through a released pin"""
    pool = yield from pg.pool.make(_config(pg_server, max_connections=1))
    pin_scope = fx.CloseableScope()
    listen_scope = fx.CloseableScope()
    pinned = yield from pool.reserve.pipe(fx.provide_service(Scope, pin_scope))
    yield from pinned.listen("released_pin_listener").pipe(fx.provide_service(Scope, listen_scope))
    yield from pin_scope.close(fx.Success(None))
    yield from listen_scope.close(fx.Success(None))
    channels = yield from fx.scoped(
        pool.reserve.flat_map(
            lambda connection: connection.query("SELECT pg_listening_channels() AS channel")
        )
    )
    assert channels.rows == []


@testing.live
def test_reports_listener_registration_failure_during_acquisition(pg_server: PgServer):
    """reports listener registration failure during acquisition"""
    pool = yield from pg.pool.make(_config(pg_server, max_connections=1))
    connection = yield from pool.get
    yield from connection.query("BEGIN")
    yield from connection.query("SELECT * FROM effect_missing_relation").flip()
    error = yield from connection.listen("test_channel").flip()
    assert isinstance(error, SqlError)
    # A failed acquisition must release the connection pin.
    yield from connection.query("ROLLBACK")
    result = yield from connection.query("SELECT 1 AS one")
    assert result.rows == [{"one": 1}]


@testing.live
def test_preserves_the_server_error_when_a_listener_backend_is_terminated(pg_server: PgServer):
    """preserves the server error when a listener backend is terminated"""
    pool = yield from pg.pool.make(_config(pg_server, max_connections=1))
    listener = yield from pool.reserve
    notifications = yield from listener.listen("terminated_listener")
    consumer = yield from scope.fork_scoped(notifications.take())
    terminator = yield from _connect(pg_server)
    yield from terminator.query("SELECT pg_terminate_backend($1)", [listener.process_id])
    error = yield from consumer.join().flip()
    assert isinstance(error, SqlError)
    assert getattr(error.reason.cause, "sqlstate", None) == "57P01"
    assert (yield from listener.query("SELECT 1").flip()) is error


@testing.live
def test_returns_a_multiplexed_reservation_to_shared_circulation(pg_server: PgServer):
    """returns a multiplexed reservation to shared circulation"""
    pool = yield from pg.pool.make(_config(pg_server, max_connections=1))
    reserve = fx.scoped(pool.reserve.map(_pid))
    get = fx.scoped(pool.get.map(_pid))
    first = yield from reserve
    assert (yield from get) == first
    assert (yield from reserve) == first
    assert (yield from get) == first


@testing.live
def test_interrupt_cancels_an_in_flight_query(pg_server: PgServer):
    """interrupt cancels an in-flight query"""
    pool = yield from pg.pool.make(_config(pg_server, max_connections=1))
    blocker = yield from _connect(pg_server)
    observer = yield from _connect(pg_server)

    def interrupting():
        connection = yield from pool.get
        yield from blocker.query("BEGIN")
        yield from blocker.query(_LOCK, [connection.process_id])
        fiber = yield from scope.fork_scoped(connection.query(_LOCK, [connection.process_id]))
        yield from wait_until_advisory_lock(observer, connection.process_id)
        yield from connection.interrupt
        error = yield from fiber.join().flip()
        assert isinstance(error, SqlError)
        assert error.reason._tag == "StatementTimeoutError"
        return connection.process_id

    first = yield from fx.scoped(fx.gen(interrupting).ensuring(blocker.query("ROLLBACK").ignore()))
    second = yield from fx.scoped(pool.get.map(_pid))
    assert second == first


@testing.live
def test_replaces_a_session_whose_pin_is_released_with_a_statement_in_flight(
    pg_server: PgServer,
):
    """replaces a session whose pin is released with a statement in flight"""
    pool = yield from pg.pool.make(_config(pg_server, max_connections=1))
    blocker = yield from _connect(pg_server)
    observer = yield from _connect(pg_server)
    pin_scope = fx.CloseableScope()
    pinned = yield from pool.reserve.pipe(fx.provide_service(Scope, pin_scope))

    def leaking():
        yield from blocker.query("BEGIN")
        yield from blocker.query(_LOCK, [pinned.process_id])
        leaked = yield from scope.fork_scoped(pinned.query(_LOCK, [pinned.process_id]))
        yield from wait_until_advisory_lock(observer, pinned.process_id)
        yield from pin_scope.close(fx.Success(None))
        # Freeing the lock lets the leaked statement finish if it still has a session.
        yield from blocker.query("ROLLBACK")
        assert isinstance((yield from leaked.await_exit()), fx.Failure)
        dead = yield from pinned.base.query("SELECT 1").flip()
        assert (
            dead.reason.message == "PgConnection: Pinned connection released with work outstanding"
        )

    yield from fx.gen(leaking).ensuring(blocker.query("ROLLBACK").ignore())

    def next_session():
        connection = yield from pool.reserve
        result = yield from connection.query("SELECT 1 AS ok")
        return connection.process_id, result.rows

    pid, rows = yield from fx.scoped(fx.gen(next_session))
    assert pid != pinned.process_id
    assert rows == [{"ok": 1}]


def _interrupt_with_late_cancel(
    pool: pg.PgPoolService,
    gate: CancelGate,
    blocker: PgConnection,
    observer: PgConnection,
) -> fx.Effect[int, Any]:
    """Interrupt a query blocked on a lock, then let it finish before the
    cancel reaches PostgreSQL; gives the session's process id."""

    def body():
        connection = yield from pool.get
        yield from blocker.query("BEGIN")
        yield from blocker.query(_LOCK, [connection.process_id])
        query = yield from scope.fork_scoped(connection.query(_LOCK, [connection.process_id]))
        yield from wait_until_advisory_lock(observer, connection.process_id)
        interruption = yield from scope.fork_scoped(query.interrupt())
        yield from _wait_for(gate.intercepted)
        yield from blocker.query("COMMIT")
        yield from interruption.join()
        return connection.process_id

    return fx.scoped(fx.gen(body).ensuring(blocker.query("ROLLBACK").ignore()))


def _late_cancel_pool(gate: CancelGate):
    return pg.pool.make(pg.PgPoolConfig(url=gate.url, max_connections=1))


def _released(gate: CancelGate) -> fx.Effect[None]:
    return fx.sync(gate.release)


@testing.live
def test_replaces_a_pooled_session_after_an_unconfirmed_query_cancel(
    pg_server: PgServer, cancel_gate: CancelGate
):
    """replaces a pooled session after an unconfirmed query cancel"""
    pool = yield from _late_cancel_pool(cancel_gate)
    blocker = yield from _connect(pg_server)
    observer = yield from _connect(pg_server)

    def body():
        first = yield from _interrupt_with_late_cancel(pool, cancel_gate, blocker, observer)
        second = yield from fx.scoped(pool.get.map(_pid))
        assert second != first
        cancel_gate.release()
        yield from _wait_for(cancel_gate.delivered)

    yield from fx.gen(body).ensuring(_released(cancel_gate))


@testing.live
def test_replaces_a_session_before_pool_use_after_an_unconfirmed_query_cancel(
    pg_server: PgServer, cancel_gate: CancelGate
):
    """replaces a session before pool.use after an unconfirmed query cancel"""
    pool = yield from _late_cancel_pool(cancel_gate)
    blocker = yield from _connect(pg_server)
    observer = yield from _connect(pg_server)

    def body():
        first = yield from _interrupt_with_late_cancel(pool, cancel_gate, blocker, observer)
        second = yield from pool.use(lambda connection: fx.succeed(connection.process_id))
        assert second != first
        cancel_gate.release()
        yield from _wait_for(cancel_gate.delivered)

    yield from fx.gen(body).ensuring(_released(cancel_gate))


@testing.live
def test_protects_an_active_pool_use_query_from_a_late_cancel(
    pg_server: PgServer, cancel_gate: CancelGate
):
    """protects an active pool.use query from a late cancel"""
    pool = yield from _late_cancel_pool(cancel_gate)
    blocker = yield from _connect(pg_server)
    observer = yield from _connect(pg_server)
    started = yield from fx.Queue[int].unbounded()
    lock_acquired = yield from fx.Queue[None].unbounded()

    def body():
        yield from _interrupt_with_late_cancel(pool, cancel_gate, blocker, observer)

        def following(connection: PgConnection) -> Generator[Any, Any, Result]:
            yield from started.offer(connection.process_id)
            yield from lock_acquired.take()
            return (
                yield from connection.query(
                    "SELECT 1 AS after FROM pg_advisory_xact_lock($1::int4)",
                    [connection.process_id],
                )
            )

        follow_up = yield from scope.fork_scoped(
            pool.use(lambda connection: fx.gen(lambda: following(connection)))
        )
        follow_up_pid = yield from started.take()
        yield from blocker.query("BEGIN")
        yield from blocker.query(_LOCK, [follow_up_pid])
        yield from lock_acquired.offer(None)
        yield from wait_until_advisory_lock(observer, follow_up_pid)
        cancel_gate.release()
        yield from _wait_for(cancel_gate.delivered)
        yield from blocker.query("COMMIT")
        result = yield from follow_up.join()
        assert result.rows == [{"after": 1}]

    yield from fx.gen(body).ensuring(
        _released(cancel_gate).and_then(blocker.query("ROLLBACK")).ignore()
    )


@testing.live
def test_retires_an_idle_interrupted_session_before_pool_use(
    pg_server: PgServer, cancel_gate: CancelGate
):
    """retires an idle interrupted session before pool.use"""
    pool = yield from _late_cancel_pool(cancel_gate)
    observer = yield from _connect(pg_server)
    started = yield from fx.Queue[int].unbounded()

    def body():
        def interrupting():
            connection = yield from pool.get
            yield from connection.interrupt
            yield from _wait_for(cancel_gate.intercepted)
            return connection.process_id

        first = yield from fx.scoped(fx.gen(interrupting))

        def following(connection: PgConnection) -> Generator[Any, Any, Result]:
            yield from started.offer(connection.process_id)
            return (yield from connection.query("SELECT 1 AS after FROM pg_sleep(1)"))

        follow_up = yield from scope.fork_scoped(
            pool.use(lambda connection: fx.gen(lambda: following(connection)))
        )
        follow_up_pid = yield from started.take()
        assert follow_up_pid != first
        yield from wait_until_active(observer, follow_up_pid)
        cancel_gate.release()
        yield from _wait_for(cancel_gate.delivered)
        result = yield from follow_up.join()
        assert result.rows == [{"after": 1}]

    yield from fx.gen(body).ensuring(_released(cancel_gate))


@testing.live
def test_replaces_a_pooled_session_after_an_unconfirmed_stream_cancel(
    pg_server: PgServer, cancel_gate: CancelGate
):
    """replaces a pooled session after an unconfirmed stream cancel"""
    pool = yield from _late_cancel_pool(cancel_gate)
    blocker = yield from _connect(pg_server)

    def body():
        def streaming():
            connection = yield from pool.get
            yield from blocker.query("BEGIN")
            yield from blocker.query(_LOCK, [connection.process_id])
            rows = yield from scope.fork_scoped(
                connection.stream(_BLOCKED_STREAM, [connection.process_id]).take(1).run_collect()
            )
            yield from _wait_for(cancel_gate.intercepted)
            yield from blocker.query("COMMIT")
            assert (yield from rows.join()) == [{"n": 1}]
            return connection.process_id

        first = yield from fx.scoped(fx.gen(streaming).ensuring(blocker.query("ROLLBACK").ignore()))

        def replacing():
            replacement = yield from pool.get
            assert replacement.process_id != first
            query = yield from scope.fork_scoped(
                replacement.query("SELECT 1 AS after FROM pg_sleep(1)")
            )
            yield from wait_until_active(blocker, replacement.process_id)
            cancel_gate.release()
            yield from _wait_for(cancel_gate.delivered)
            result = yield from query.join()
            assert result.rows == [{"after": 1}]

        yield from fx.scoped(fx.gen(replacing))

    yield from fx.gen(body).ensuring(_released(cancel_gate))


@testing.live
def test_keeps_a_session_after_a_confirmed_stream_cancel(pg_server: PgServer):
    """keeps a session after a confirmed stream cancel"""
    pool = yield from pg.pool.make(_config(pg_server, max_connections=1))
    blocker = yield from _connect(pg_server)
    connection = yield from pool.get
    yield from blocker.query("BEGIN")
    yield from blocker.query(_LOCK, [connection.process_id])
    rows = yield from (
        connection.stream(_BLOCKED_STREAM, [connection.process_id]).take(1).run_collect().timeout(5)
    )
    assert rows == [{"n": 1}]
    result = yield from connection.query("SELECT pg_backend_pid()::int4 AS pid")
    assert result.rows == [{"pid": connection.process_id}]
    yield from blocker.query("ROLLBACK")


@testing.live
def test_keeps_a_held_session_after_an_unconfirmed_query_cancel(
    pg_server: PgServer, cancel_gate: CancelGate
):
    """keeps a held session after an unconfirmed query cancel"""
    pool = yield from _late_cancel_pool(cancel_gate)
    blocker = yield from _connect(pg_server)
    observer = yield from _connect(pg_server)

    def body():
        connection = yield from pool.get
        yield from blocker.query("BEGIN")
        yield from blocker.query(_LOCK, [connection.process_id])
        query = yield from scope.fork_scoped(connection.query(_LOCK, [connection.process_id]))
        yield from wait_until_advisory_lock(observer, connection.process_id)
        interruption = yield from scope.fork_scoped(query.interrupt())
        yield from _wait_for(cancel_gate.intercepted)
        yield from blocker.query("COMMIT")
        yield from interruption.join()
        before = yield from connection.query("SELECT pg_backend_pid()::int4 AS pid")
        assert before.rows == [{"pid": connection.process_id}]
        cancel_gate.release()
        yield from _wait_for(cancel_gate.delivered)
        after = yield from connection.query("SELECT pg_backend_pid()::int4 AS pid")
        assert after.rows == [{"pid": connection.process_id}]

    yield from fx.gen(body).ensuring(
        _released(cancel_gate).and_then(blocker.query("ROLLBACK")).ignore()
    )


@testing.live
def test_replaces_connections_that_die(pg_server: PgServer):
    """replaces connections that die"""
    pool = yield from pg.pool.make(_config(pg_server, max_connections=1))
    first = yield from fx.scoped(pool.get.map(_pid))
    terminator = yield from _connect(pg_server)
    yield from terminator.query("SELECT pg_terminate_backend($1)", [first])

    def checking():
        connection = yield from pool.get
        alive = isinstance((yield from connection.query("SELECT 1 AS one").exit()), fx.Success)
        return connection.process_id if alive and connection.process_id != first else None

    while True:
        replaced = yield from fx.scoped(fx.gen(checking))
        if replaced is not None:
            assert replaced != first
            break
        yield from fx.sleep(0.01)


@testing.live
def test_invalidates_a_reserved_connection(pg_server: PgServer):
    """invalidates a reserved connection"""
    pool = yield from pg.pool.make(_config(pg_server, max_connections=2))
    reserved = yield from pool.reserve
    yield from pool.invalidate(reserved)
    replacement = yield from pool.get
    assert replacement.process_id != reserved.process_id


@testing.live
def test_admits_a_waiting_checkout_when_a_reserved_connection_dies(pg_server: PgServer):
    """admits a waiting checkout when a reserved connection dies"""
    pool = yield from pg.pool.make(_config(pg_server, max_connections=1))
    reserved = yield from pool.reserve
    waiter = yield from scope.fork_scoped(
        fx.scoped(pool.get.flat_map(lambda connection: connection.query("SELECT 1 AS ok")))
    )
    yield from fx.sleep(0.01)
    # The reservation is still held when its connection dies, so nothing
    # returns the connection to the pool.
    yield from reserved.query("SELECT pg_terminate_backend(pg_backend_pid())").ignore()
    result = yield from waiter.join()
    assert result.rows == [{"ok": 1}]


@testing.live
def test_returns_a_borrowed_session_on_success_failure_and_interruption(pg_server: PgServer):
    """returns a borrowed session on success, failure, and interruption"""
    # A pool of one: a lease that is not returned hangs the next borrow.
    pool = yield from pg.pool.make(_config(pg_server, max_connections=1))
    ok = yield from pool.use(lambda connection: connection.query("SELECT 1 AS ok"))
    assert ok.rows == [{"ok": 1}]
    failed = yield from pool.use(lambda connection: connection.query("SELECT * FROM nope")).exit()
    assert isinstance(failed, fx.Failure)
    running = yield from scope.fork_scoped(
        pool.use(lambda connection: connection.query("SELECT pg_sleep(30)"))
    )
    yield from fx.sleep(0.01)
    yield from running.interrupt()
    again = yield from pool.use(lambda connection: connection.query("SELECT 2 AS ok"))
    assert again.rows == [{"ok": 2}]


@testing.live
def test_borrows_around_a_connection_that_has_to_be_replaced(pg_server: PgServer):
    """borrows around a connection that has to be replaced"""
    pool = yield from pg.pool.make(_config(pg_server, max_connections=1))
    first = yield from pool.use(
        lambda connection: connection.query("SELECT 1 AS ok").as_(connection.process_id)
    )
    yield from pool.use(
        lambda connection: connection.query("SELECT pg_terminate_backend(pg_backend_pid())")
    ).ignore()
    yield from fx.sleep(0.5)
    second = yield from pool.use(
        lambda connection: connection.query("SELECT 2 AS ok").as_(connection.process_id)
    )
    assert second != first


# --- PgPool failed startup / acquireTimeout ------------------------------------


@testing.live
def test_reports_a_caller_owned_connect_failure_instead_of_retrying_indefinitely(
    closing_listener: ClosingListener,
):
    """reports a caller-owned connect failure instead of retrying indefinitely"""
    pool = yield from pg.pool.make(
        pg.PgPoolConfig(
            username="test", host="127.0.0.1", port=closing_listener.port, max_connections=1
        )
    )
    error = yield from pool.get.flip()
    assert error.reason._tag == "ConnectionError"
    assert error.reason.operation == "connect"
    assert closing_listener.connections == 1


@testing.effect
def test_fails_a_checkout_that_waits_on_an_exhausted_pool_past_acquire_timeout(
    pg_server: PgServer,
):
    """fails a checkout that waits on an exhausted pool past acquireTimeout"""

    def body():
        sql = yield from pg.make(_config(pg_server, max_connections=1, acquire_timeout=0.1))
        yield from sql.reserve
        statement = yield from sql("SELECT 1").flip().fork()
        transaction = yield from sql.with_transaction(sql("SELECT 1")).flip().fork()
        yield from testing.adjust(0.1)
        for fiber in (statement, transaction):
            error = yield from fiber.join()
            assert error.reason._tag == "ConnectionError"
            assert error.reason.operation == "acquireConnection"

    yield from fx.scoped(fx.gen(body)).pipe(fx.provide(fx.reactivity.layer))


def test_a_released_client_interrupts_naming_the_closed_pool(pg_server: PgServer) -> None:
    """pyfect: a ``SqlClient`` kept past its layer (``.pipe(provide(layer))``)
    interrupts as Effect's ``Pool.get`` does, and says the pool is closed."""

    @fx.fn
    def program():
        sql = yield from SqlClient().pipe(fx.provide(pg.client.layer(_config(pg_server))))
        return (yield from sql("SELECT 1").timeout(5).exit())

    exit_ = fx.run_blocking(scope.scoped(program()).or_die())
    assert isinstance(exit_, Failure) and exit_.cause.has_interrupts_only, exit_
    error = exit_.cause.squash()
    assert isinstance(error, Interrupted)
    assert "because the Pool is closed" in "\n".join(error.__notes__)


# --- PgPool connection spans --------------------------------------------------


def _recording() -> tuple[fx.tracer.Tracer, list[fx.tracer.NativeSpan]]:
    spans: list[fx.tracer.NativeSpan] = []

    def make(request: fx.tracer.SpanRequest) -> fx.tracer.NativeSpan:
        span = fx.tracer.NativeSpan(request)
        spans.append(span)
        return span

    return fx.tracer.Tracer(make), spans


def _accepted(gate: CancelGate, count: int) -> fx.Effect[None]:
    """Wait until ``gate`` took ``count`` connections."""

    def body() -> Generator[Any, Any]:
        deadline = time.monotonic() + 5
        while gate.accepted < count:
            assert time.monotonic() < deadline, "timed out waiting for a connect"
            yield from fx.sleep(0.001)

    return fx.gen(body)


def _first_checkout(
    gate: CancelGate,
    checkout: Any,
    *,
    acquire_timeout: float | None = None,
    propagate: bool = True,
    timing: bool = True,
) -> fx.Effect[tuple[list[fx.tracer.NativeSpan], fx.tracer.NativeSpan], Any]:
    """A statement whose checkout opens the pool's first session, the
    connect answered after 40 ms, then a second statement on that session."""
    tracer, spans = _recording()

    def body():
        pool = yield from pg.pool.make(
            pg.PgPoolConfig(url=gate.url, max_connections=1, acquire_timeout=acquire_timeout)
        )
        gate.pause()
        first = yield from fx.scoped(checkout(pool)).with_span("first statement").fork()
        yield from _accepted(gate, gate.accepted + 1)
        yield from fx.sleep(0.04)
        gate.resume()
        yield from first.join()
        yield from fx.scoped(pool.get).with_span("second statement")
        connects = [s for s in spans if s.name == "db.connect"]
        return connects, next(s for s in spans if s.name == "first statement")

    return (
        fx.scoped(fx.gen(body))
        .pipe(fx.provide_service(fx.tracer.TracerTimingEnabled, timing))
        .with_tracer(tracer)
        .pipe(fx.provide_service(SpanPropagationEnabled, propagate))
    )


@testing.live
def test_reports_the_connect_a_statement_waited_for_under_its_span(cancel_gate: CancelGate):
    """PgPool connection spans / reports the connect a statement waited for under its span,
    only with propagation and timing"""

    def use(pool: pg.PgPoolService) -> fx.Effect[None, SqlError]:
        return pool.use(lambda _: fx.void)

    def reserve(pool: pg.PgPoolService) -> fx.Effect[PgConnection, SqlError, Scope]:
        return pool.reserve

    for checkout, acquire_timeout in ((use, None), (use, 1.0), (reserve, None)):
        connects, first = yield from _first_checkout(
            cancel_gate, checkout, acquire_timeout=acquire_timeout
        )
        assert len(connects) == 1
        (connect,) = connects
        assert connect.parent is first
        assert connect.status.start_time >= first.status.start_time
        connect_time = connect.attributes.get("db.client.connection.connect_time_ms")
        assert isinstance(connect_time, float)
        assert connect_time >= 40
        assert connect.attributes.get("db.system.name") == "postgresql"
        assert connect.kind == "client"
    connects, _ = yield from _first_checkout(cancel_gate, use, propagate=False)
    assert connects == []
    connects, _ = yield from _first_checkout(cancel_gate, use, timing=False)
    assert connects == []


@testing.live
def test_reports_no_connect_for_a_session_that_was_ready_before_the_statement(
    pg_server: PgServer,
):
    """PgPool connection spans / reports no connect for a session that was ready before the
    statement"""
    tracer, spans = _recording()

    def body():
        pool = yield from pg.pool.make(_config(pg_server, min_connections=1, max_connections=2))
        # The background session gives no signal when it is ready.
        yield from fx.sleep(0.2)

        def statements():
            yield from pool.get.with_span("ready statement")
            waiting = yield from fx.scoped(pool.get).with_span("waiting statement").fork()
            yield from waiting.join()

        yield from fx.scoped(fx.gen(statements))
        connects = [s for s in spans if s.name == "db.connect"]
        assert len(connects) == 1
        waiting = next(s for s in spans if s.name == "waiting statement")
        assert connects[0].parent is waiting

    yield from (
        fx.scoped(fx.gen(body))
        .with_tracer(tracer)
        .pipe(fx.provide_service(SpanPropagationEnabled, True))
    )


def _dead_sessions(url: object) -> int:
    import gc

    gc.collect()
    return sum(
        1
        for o in gc.get_objects()
        if isinstance(o, PgConnection) and o.config.url == url and o.is_dead
    )


@testing.live
def test_forgets_the_connect_of_a_session_closed_before_its_first_checkout(
    cancel_gate: CancelGate,
):
    """Effect keeps connect times in a WeakMap: a session the pool closes
    before anyone checked it out (here, opened for a checkout that timed
    out and then idle past ``idle_timeout``) is not kept alive by them."""

    def body():
        pool = yield from pg.pool.make(
            pg.PgPoolConfig(
                url=cancel_gate.url, max_connections=1, idle_timeout=0.05, acquire_timeout=0.05
            )
        )
        cancel_gate.pause()
        timed_out = yield from fx.scoped(pool.get).exit()
        assert isinstance(timed_out, Failure)
        cancel_gate.resume()
        yield from _accepted(cancel_gate, 1)
        # Long enough for the connect to land and the idle session to close.
        yield from fx.sleep(0.5)
        assert _dead_sessions(cancel_gate.url) == 0
        del pool

    yield from fx.scoped(fx.gen(body))
