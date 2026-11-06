"""A PostgreSQL ``listen`` and a Redis ``subscribe`` hold at most
``capacity`` messages the program has not taken. One more fails the
subscription with an error saying it fell behind (as Redis itself drops a
subscriber whose output buffer is full) instead of growing memory without
limit while a publisher outpaces the program. Effect's queues here are
unbounded. Each test skips without its local server."""

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any, Never

import pytest
from oracle import _postgres, _redis

import pyfect as fx
from pyfect import testing
from pyfect.option import Some
from pyfect.queue import Dequeue

type Body = Callable[[], Generator[Any, Any, Any]]


def _drain[A, E](queue: Dequeue[A, E], limit: int) -> fx.Effect[tuple[list[A], E | None], Never]:
    """Take until the queue fails (or ``limit`` items, or a second passes
    without one)."""

    def body() -> Generator[Any, Any, tuple[list[A], E | None]]:
        taken: list[A] = []
        while len(taken) < limit:
            result = yield from queue.take().timeout_option(1).result()
            match result:
                case fx.Ok(Some(item)):
                    taken.append(item)
                case fx.Ok(None):
                    return taken, None
                case fx.Err(error):
                    return taken, error
                case _:
                    return taken, None
        return taken, None

    return fx.gen(body)


def test_a_pg_listener_that_falls_behind_fails_instead_of_growing() -> None:
    pytest.importorskip("psycopg")
    from pyfect.sql import pg
    from pyfect.sql.error import SqlError

    server = _postgres.server()

    def body():
        sql = yield from pg.PgClient()
        notes = yield from sql.listen("bounded_listen", capacity=5)
        for n in range(20):
            yield from sql.notify("bounded_listen", str(n))
        yield from fx.sleep(0.5)
        taken, error = yield from _drain(notes, 50)
        assert [note.payload for note in taken] == [str(n) for n in range(5)]
        assert isinstance(error, SqlError)
        assert "fell behind" in str(error)

    layer = pg.layer(pg.PgPoolConfig(url=server.url, max_connections=2))
    fx.run_blocking(testing.with_live(fx.scoped(fx.gen(body))).pipe(fx.provide(layer)).or_die())


def test_a_pg_listener_is_bounded_by_default() -> None:
    pytest.importorskip("psycopg")
    from pyfect.sql import pg

    server = _postgres.server()
    capacity = 1024

    def body():
        sql = yield from pg.PgClient()
        notes = yield from sql.listen("default_listen")
        yield from sql.unsafe(
            "SELECT pg_notify('default_listen', g::text) FROM generate_series(1, $1::int) g",
            [capacity + 100],
        )
        yield from fx.sleep(1)
        assert (yield from notes.size()) <= capacity

    layer = pg.layer(pg.PgPoolConfig(url=server.url, max_connections=2))
    fx.run_blocking(testing.with_live(fx.scoped(fx.gen(body))).pipe(fx.provide(layer)).or_die())


def _with_redis(body: Body) -> None:
    pytest.importorskip("redis")
    from pyfect.persistence import redis_py

    server = _redis.server()
    _redis.flush()
    program = testing.with_live(fx.scoped(fx.gen(body)))
    fx.run_blocking(program.pipe(fx.provide(redis_py.layer(server.url))).or_die())


def test_a_redis_subscriber_that_falls_behind_fails_instead_of_growing() -> None:
    from pyfect.persistence.redis import Redis, RedisError

    def body():
        redis = yield from Redis()
        messages = yield from redis.subscribe("bounded", capacity=5)
        yield from fx.sleep(0.2)
        for n in range(20):
            yield from redis.send("PUBLISH", "bounded", str(n))
        yield from fx.sleep(0.5)
        taken, error = yield from _drain(messages, 50)
        assert [message.message for message in taken] == [str(n) for n in range(5)]
        assert isinstance(error, RedisError)
        assert "fell behind" in str(error.cause)

    _with_redis(body)


def test_a_redis_subscription_is_bounded_by_default() -> None:
    from pyfect.persistence.redis import Redis

    capacity = 1024

    def body():
        redis = yield from Redis()
        messages = yield from redis.subscribe("default")
        yield from fx.sleep(0.2)
        yield from fx.for_each(
            range(capacity + 100),
            lambda n: redis.send("PUBLISH", "default", str(n)),
            concurrency=16,
        )
        yield from fx.sleep(1)
        assert (yield from messages.size()) <= capacity

    _with_redis(body)
