"""Ports of the ``PersistedQueue`` suites of Effect's
``platform-node/test/NodeRedis.integration.test.ts`` on ``redis_py``
(Effect's ``NodeRedis``), against the throwaway Redis server of
``_redis`` (skipped without one), emptied before each test: the
``PersistedQueueTest`` suite (``_persisted_queue_suite``) on
``layer_store_redis`` with short intervals (``PersistedQueue
(NodeRedis)``), and the queue titles of the file's ``PersistedQueue
(NodeRedis)`` suite. Its other titles are in ``test_redis_py.py``.

Each test's docstring is the Effect test title. The redis-py client's
calls run on its own thread, so these tests wait on the wall clock.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Generator
from typing import Any, TypedDict

import pytest

pytest.importorskip("redis")

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.persistence import persisted_queue as pq
from pyfect.persistence import redis_py
from pyfect.persistence.redis import Redis, RedisError

from . import _persisted_queue_suite as suite
from . import _redis

pytestmark = pytest.mark.filterwarnings("ignore::pyfect.testing.ClockNotAdvancedWarning")


class RedisItem(TypedDict):
    n: float


REDIS_ITEM = S.Struct(RedisItem)


@pytest.fixture(autouse=True)
def _flushed() -> None:
    _redis.flush()


def _redis_layer() -> fx.Layer[Redis | redis_py.RedisPy, RedisError]:
    return redis_py.layer(_redis.server().url)


class TestPersistedQueueRedis(suite.PersistedQueueSuite):
    """PersistedQueue (NodeRedis)"""

    def make_layer(self) -> fx.Layer[pq.PersistedQueueStore, Any, Any]:
        # short intervals so the periodic reset runs while the suite's takes
        # are in flight
        return pq.layer_store_redis(poll_interval=0.05, lock_refresh_interval=0.1).pipe(
            fx.provide(_redis_layer())
        )


# --- PersistedQueue (NodeRedis) ---------------------------------------------------------


def _run(body: Callable[[], Generator[Any, Any]], *, live: bool = False) -> None:
    store = pq.layer_store_redis().pipe(fx.provide(_redis_layer()))
    services = fx.layer.merge(_redis_layer(), pq.layer.pipe(fx.layer.provide_merge(store)))
    program = fx.scoped(fx.gen(body))
    if live:
        program = testing.with_live(program)
    testing.run_test(program.pipe(fx.provide(services)).or_die())


def test_moves_exhausted_elements_to_the_failed_list() -> None:
    """PersistedQueue (NodeRedis) / moves exhausted elements to the failed list"""

    def body():
        redis = yield from Redis()
        queue_name = "test-redis-failed"
        queue = yield from pq.make(name=queue_name, schema=REDIS_ITEM, max_attempts=1)
        id = yield from queue.offer({"n": 42})
        error = yield from queue.take(lambda _v, _m: fx.fail("boom")).flip()
        assert error == "boom"

        failed = yield from redis.send("LRANGE", f"effectq:{queue_name}:failed", "0", "-1")
        assert isinstance(failed, list)
        assert len(failed) == 1
        failed_item = json.loads(str(failed[0]))
        assert failed_item["id"] == id
        assert failed_item["element"] == {"n": 42}
        assert failed_item["attempts"] == 1

        pending = yield from redis.send("HLEN", f"effectq:{queue_name}:pending")
        assert pending == 0

    _run(body)


def _crash_store(prefix: str) -> fx.Effect[pq.PersistedQueueStoreService, Any, Any]:
    return pq.make_store_redis(
        prefix=prefix, poll_interval=0.05, lock_refresh_interval=0.1, lock_expiration=1
    )


def _factory_queue(
    store: pq.PersistedQueueStoreService, name: str, **opts: Any
) -> Generator[Any, Any, pq.PersistedQueue[RedisItem]]:
    factory = yield from pq.make_factory.pipe(fx.provide_service(pq.PersistedQueueStore, store))
    return (yield from factory.make(name=name, schema=REDIS_ITEM, **opts))


def test_recovers_elements_from_crashed_workers() -> None:
    """PersistedQueue (NodeRedis) / recovers elements from crashed workers"""

    def body():
        prefix = "effectq-crash:"
        store = yield from _crash_store(prefix)
        queue = yield from _factory_queue(store, "crash-recovery")
        redis = yield from Redis()

        # simulate a worker that claimed the element and then crashed: the
        # element sits in the pending hash with a consumed attempt and no lock
        yield from redis.send(
            "HSET",
            f"{prefix}crash-recovery:pending",
            "crashed",
            json.dumps({"id": "crashed", "element": {"n": 1}}, separators=(",", ":")),
        )
        yield from redis.send("HSET", f"{prefix}crash-recovery:attempts", "crashed", "1")

        result = yield from queue.take(lambda value, meta: fx.succeed((value["n"], meta.attempts)))
        assert result == (1, 2)

    _run(body, live=True)


def test_dead_letters_elements_from_workers_that_crashed_on_the_final_attempt() -> None:
    """PersistedQueue (NodeRedis) / dead-letters elements from workers that crashed on the
    final attempt"""

    def body():
        prefix = "effectq-crash-exhausted:"
        store = yield from _crash_store(prefix)
        queue = yield from _factory_queue(store, "crash-exhausted", max_attempts=1)
        redis = yield from Redis()

        # the final attempt was claimed by a worker that crashed, so no
        # finalizer will ever settle this element
        yield from redis.send(
            "HSET",
            f"{prefix}crash-exhausted:pending",
            "crashed",
            json.dumps({"id": "crashed", "element": {"n": 1}}, separators=(",", ":")),
        )
        yield from redis.send("HSET", f"{prefix}crash-exhausted:attempts", "crashed", "1")

        # an active taker runs the periodic reset that dead-letters such
        # elements instead of redelivering them
        fiber = yield from queue.take(lambda value, _m: fx.succeed(value)).fork_scoped()
        yield from fx.sleep(1)

        failed = yield from redis.send("LRANGE", f"{prefix}crash-exhausted:failed", "0", "-1")
        assert isinstance(failed, list)
        assert len(failed) == 1
        failed_item = json.loads(str(failed[0]))
        assert failed_item["id"] == "crashed"
        assert failed_item["element"] == {"n": 1}
        assert failed_item["attempts"] == 1
        assert "Lock expired after final attempt" in failed_item["lastFailure"]

        pending = yield from redis.send("HLEN", f"{prefix}crash-exhausted:pending")
        assert int(str(pending)) == 0
        assert fiber.poll_unsafe() is None

    _run(body, live=True)
