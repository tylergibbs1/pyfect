"""Releasing a pin while work through it is under way: pyfect's psycopg
session layer (Effect's PgClient has none), against a throwaway local
PostgreSQL (``_postgres.pg_server``; skipped without one)."""

import pytest

pytest.importorskip("psycopg")

import pyfect as fx
from pyfect import testing
from pyfect.scope import Scope
from pyfect.sql import pg

from ._postgres import PgServer


@testing.live
def test_releasing_a_pin_while_a_stream_opens_closes_the_session(pg_server: PgServer):
    connection = yield from pg.connection.make(pg.PgConnectionConfig(url=pg_server.url))
    pin_scope = fx.CloseableScope()
    pinned = yield from connection.pin.pipe(fx.provide_service(Scope, pin_scope))
    # Runs up to its first wait: parked while psycopg opens the stream.
    streaming = yield from (
        pinned.stream("SELECT generate_series(1, 3) AS n")
        .run_collect()
        .fork(start_immediately=True)
    )
    assert streaming.poll_unsafe() is None
    yield from pin_scope.close(fx.Success(None))
    # The stream was work through the pin, so the release closes the session
    # rather than hand it on with the stream still reading from it.
    assert connection.is_dead
    assert isinstance((yield from streaming.await_exit()), fx.Failure)


@testing.live
def test_releasing_a_pin_while_a_listener_subscribes_closes_the_session(pg_server: PgServer):
    connection = yield from pg.connection.make(pg.PgConnectionConfig(url=pg_server.url))
    pin_scope = fx.CloseableScope()
    pinned = yield from connection.pin.pipe(fx.provide_service(Scope, pin_scope))
    listen_scope = fx.CloseableScope()
    listening = yield from (
        pinned.listen("released_while_subscribing")
        .pipe(fx.provide_service(Scope, listen_scope))
        .fork(start_immediately=True)
    )
    assert listening.poll_unsafe() is None
    yield from pin_scope.close(fx.Success(None))
    assert connection.is_dead
    assert isinstance((yield from listening.await_exit()), fx.Failure)
    yield from listen_scope.close(fx.Success(None))
