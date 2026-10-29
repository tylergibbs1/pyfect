"""``PersistedQueue`` behavior Effect's suites leave unpinned, on the
memory, SQLite and Redis stores (Redis skipped without a local server),
with expected values printed by Effect under Node (memory store), and
store failures and options read as Effect reads them."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
from oracle import _persisted_queue_suite as suite
from oracle import _redis

import pyfect as fx
from pyfect import schedule
from pyfect import schema as S
from pyfect.duration import Seconds
from pyfect.latch import Latch
from pyfect.persistence import persisted_queue as pq
from pyfect.sql import sqlite
from pyfect.sql.client import SqlClient, SqlClientService
from pyfect.sql.error import SqlError

type StoreLayer = Callable[[Path], fx.Layer[pq.PersistedQueueStore, Any, Any]]


def _memory(_tmp_path: Path) -> fx.Layer[pq.PersistedQueueStore, Any, Any]:
    return pq.layer_store_memory


def _sqlite(tmp_path: Path) -> fx.Layer[pq.PersistedQueueStore, Any, Any]:
    client = sqlite.layer(sqlite.SqliteClientConfig(filename=str(tmp_path / "test.db")))
    return pq.layer_store_sql(poll_interval=0.01).pipe(fx.provide(client))


def _redis_store(_tmp_path: Path) -> fx.Layer[pq.PersistedQueueStore, Any, Any]:
    pytest.importorskip("redis")
    from pyfect.persistence import redis_py

    server = _redis.server()
    _redis.flush()
    return pq.layer_store_redis(poll_interval=0.01).pipe(fx.provide(redis_py.layer(server.url)))


_STORES = pytest.mark.parametrize(
    "store",
    [
        pytest.param(_memory, id="memory"),
        pytest.param(_sqlite, id="sqlite"),
        pytest.param(_redis_store, id="redis"),
    ],
)


@_STORES
@pytest.mark.filterwarnings("ignore::pyfect.testing.ClockNotAdvancedWarning")
def test_an_interrupted_take_does_not_count_its_attempt(tmp_path: Path, store: StoreLayer) -> None:
    """Two interrupted deliveries leave both attempts of ``max_attempts=2``
    to the failures that follow, and then the element is dead (Effect
    prints ``[["held",1],["held",1],1,2,"waiting"]``)."""
    seen: list[object] = []

    def held(_value: str, meta: pq.Metadata) -> fx.Effect[None]:
        seen.append(("held", meta.attempts))
        return fx.never

    def body():
        queue = yield from pq.make(
            name="q", schema=S.String, max_attempts=2, retry_schedule=schedule.spaced(0)
        )
        yield from queue.offer("a")
        for _ in range(2):
            taken = Latch()
            fiber = yield from queue.take(
                lambda value, meta, taken=taken: taken.open().and_then(held(value, meta))
            ).fork_scoped()
            yield from fx.testing.with_live(taken.wait().timeout(5))
            yield from fiber.interrupt()
        fail = queue.take(lambda _v, meta: fx.fail(meta.attempts)).flip()
        seen.append((yield from fail))
        seen.append((yield from fail))
        last = yield from queue.take(lambda _v, meta: fx.succeed(meta.attempts)).fork_scoped()
        yield from fx.testing.with_live(fx.sleep(0.2))
        seen.append("waiting" if last.unsafe_poll() is None else "delivered")

    suite.run(store(tmp_path), body)
    assert seen == [("held", 1), ("held", 1), 1, 2, "waiting"]


def _sqlite_without_table(tmp_path: Path) -> fx.Layer[Any, Any, Any]:
    """A SQLite queue store whose table was dropped after its migrations,
    so every statement on it fails."""
    client = sqlite.layer(sqlite.SqliteClientConfig(filename=str(tmp_path / "test.db")))

    def drop(sql: SqlClientService) -> fx.Effect[object, Any]:
        return sql("DROP TABLE effect_queue")

    store = pq.layer_store_sql(poll_interval=0.01)
    dropped = fx.layer.effect_discard(SqlClient().flat_map(drop))
    return fx.layer.merge(store, dropped).pipe(fx.provide(client))


def test_a_failed_sql_offer_or_cleanup_fails_with_a_persisted_queue_error(tmp_path: Path) -> None:
    """A store statement that fails gives a ``PersistedQueueError`` whose
    ``cause`` is the database error, not a defect."""
    errors: list[pq.PersistedQueueError | S.SchemaError] = []

    def body():
        queue = yield from pq.make(name="q", schema=S.String)
        store = yield from pq.PersistedQueueStore()
        errors.append((yield from queue.offer("a").flip()))
        cleanup = store.cleanup(time_to_live=Seconds(1), failed_time_to_live=Seconds(1))
        errors.append((yield from cleanup.flip()))

    suite.run(_sqlite_without_table(tmp_path), body)
    assert all(isinstance(error, pq.PersistedQueueError) for error in errors)
    assert [error.message for error in errors if isinstance(error, pq.PersistedQueueError)] == [
        "Failed to offer element to persisted queue",
        "Failed to clean up persisted queue",
    ]
    assert all(
        isinstance(error, pq.PersistedQueueError) and isinstance(error.cause, SqlError)
        for error in errors
    )


@pytest.mark.filterwarnings("ignore::pyfect.testing.ClockNotAdvancedWarning")
def test_a_zero_sql_lock_expiration_means_the_default(tmp_path: Path) -> None:
    """Effect reads its store intervals with ``options.x ? x : default``, so
    a zero ``lock_expiration`` is the two-minute default, not a lock that
    lapses at once: a crashed worker's fresh claim is not taken over."""
    client = sqlite.layer(sqlite.SqliteClientConfig(filename=str(tmp_path / "test.db")))
    store = pq.layer_store_sql(poll_interval=0.01, lock_expiration=0)
    exits: list[fx.Exit[int, Any]] = []

    def body():
        queue = yield from pq.make(name="q", schema=S.String)
        id = yield from queue.offer("a")
        sql = (yield from SqlClient()).without_transforms()
        # a worker claimed the element and crashed
        yield from sql(
            "UPDATE effect_queue SET acquired_by = 'dead', acquired_at = CURRENT_TIMESTAMP, "
            "attempts = 1 WHERE id = {}",
            id,
        )
        taken = queue.take(lambda _v, meta: fx.succeed(meta.attempts)).timeout(3)
        exits.append((yield from fx.testing.with_live(taken).exit()))

    suite.run(store.pipe(fx.layer.provide_merge(client)), body)
    assert not isinstance(exits[0], fx.exit.Success)


def test_retry_delays_replay_the_schedule_on_simulated_time() -> None:
    """The schedule is replayed with time advanced by its own delays, so
    ``up_to(duration=2.5)`` over ``exponential(1)`` stops at the third
    failure and keeps its last delay: 1 s, 2 s, then 2 s again (not 4 s,
    as a replay that left the time at 0 would give)."""
    gaps: list[str] = []

    def body():
        queue = yield from pq.make(
            name="q",
            schema=S.String,
            retry_schedule=schedule.exponential(1).up_to(duration=2.5),
        )
        take_fail = queue.take(lambda _v, meta: fx.fail(meta.attempts)).flip()
        yield from queue.offer("a")
        yield from take_fail
        for delay in (1, 2, 2):
            fiber = yield from take_fail.fork_scoped()
            yield from fx.testing.adjust(delay - 0.1)
            early = fiber.unsafe_poll() is not None
            yield from fx.testing.adjust(0.1)
            on_time = fiber.unsafe_poll() is not None
            gaps.append(f"{delay}s early={early} on_time={on_time}")
            yield from fiber.join()

    suite.run(pq.layer_store_memory, body)
    assert gaps == [
        "1s early=False on_time=True",
        "2s early=False on_time=True",
        "2s early=False on_time=True",
    ]


@_STORES
@pytest.mark.filterwarnings("ignore::pyfect.testing.ClockNotAdvancedWarning")
def test_an_element_that_fails_to_decode_is_failed_at_once(
    tmp_path: Path, store: StoreLayer
) -> None:
    """A decode failure dead-letters the element on its first delivery
    instead of retrying it: a failed-entry cleanup frees its id at once, so
    the id can be offered again (a retried element would still be pending,
    and the new offer de-duplicated away)."""
    taken: list[object] = []

    def body():
        store_service = yield from pq.PersistedQueueStore()
        queue = yield from pq.make(
            name="q", schema=suite.ITEM, retry_schedule=schedule.spaced(3600)
        )
        yield from store_service.offer(
            name="q", id="poison", element={"n": None}, is_custom_id=True
        )
        yield from queue.offer({"n": 1})
        taken.append((yield from queue.take(_succeed)))
        # past the failure on both the test clock and the database's
        yield from fx.testing.adjust(1)
        yield from fx.testing.with_live(fx.sleep(1.1))
        yield from store_service.cleanup(
            time_to_live=Seconds(86_400), failed_time_to_live=Seconds(0)
        )
        yield from queue.offer({"n": 2}, id="poison")
        again = queue.take(_succeed).timeout(3)
        taken.append((yield from fx.testing.with_live(again)))

    suite.run(store(tmp_path), body)
    assert taken == [{"n": 1}, {"n": 2}]


def _succeed[A](value: A, _meta: pq.Metadata) -> fx.Effect[A]:
    return fx.succeed(value)
