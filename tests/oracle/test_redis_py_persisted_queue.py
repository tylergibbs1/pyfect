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
from pyfect.latch import Latch
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
        return pq.layer_store_redis(
            poll_interval="50 millis", lock_refresh_interval="100 millis"
        ).pipe(fx.provide(_redis_layer()))


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
        prefix=prefix,
        poll_interval="50 millis",
        lock_refresh_interval="100 millis",
        lock_expiration="1 second",
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
        yield from fx.sleep("1 second")

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


def test_a_settlement_from_a_recovered_claim_leaves_the_newer_claim_alone() -> None:
    """Effect 4.1.2's ``makeStoreRedis``: settlements are fenced on the
    acquisition's lock, so a handler whose lapsed claim another worker
    recovered and re-claimed cannot release that newer claim."""

    def body():
        prefix = "effectq-fenced:"
        name = "fenced"
        # worker a never renews its lock; worker b resets lapsed locks often
        a = yield from pq.make_store_redis(
            prefix=prefix,
            poll_interval="50 millis",
            lock_refresh_interval="1 hour",
            lock_expiration="500 millis",
        )
        b = yield from pq.make_store_redis(
            prefix=prefix, poll_interval="50 millis", lock_refresh_interval="100 millis"
        )
        queue_a = yield from _factory_queue(a, name)
        queue_b = yield from _factory_queue(b, name)
        redis = yield from Redis()
        id = yield from queue_a.offer({"n": 1})

        taken_a = Latch()
        gate_a = Latch()
        settled_a = yield from queue_a.take(
            lambda _v, _m: taken_a.open().and_then(gate_a.wait())
        ).fork_scoped()
        yield from taken_a.wait()

        taken_b = Latch()
        gate_b = Latch()
        settled_b = yield from queue_b.take(
            lambda _v, meta: taken_b.open().and_then(gate_b.wait()).as_(meta.attempts)
        ).fork_scoped()
        yield from taken_b.wait()

        yield from gate_a.open()
        yield from settled_a.join()
        assert (yield from redis.send("HEXISTS", f"{prefix}{name}:pending", id)) == 1

        yield from gate_b.open()
        assert (yield from settled_b.join()) == 2
        assert (yield from redis.send("HEXISTS", f"{prefix}{name}:pending", id)) == 0

    _run(body, live=True)


# --- PersistedQueue (NodeRedis): claim ownership -------------------------------------


def _ownership_queue(
    prefix: str, lock_refresh_interval: str
) -> Generator[Any, Any, pq.PersistedQueue[RedisItem]]:
    store = yield from pq.make_store_redis(
        prefix=prefix,
        poll_interval="50 millis",
        lock_expiration="1 second",
        lock_refresh_interval=lock_refresh_interval,
    )
    return (yield from _factory_queue(store, "ownership"))


def _live_sleep(duration: str) -> fx.Effect[None]:
    return testing.with_live(fx.sleep(duration))


def _metadata(_value: RedisItem, metadata: pq.Metadata) -> fx.Effect[pq.Metadata]:
    return fx.succeed(metadata)


def test_success_after_lease_expiry_but_before_reset_is_not_redelivered() -> None:
    """PersistedQueue (NodeRedis) / success after lease expiry but before reset is not
    redelivered"""

    def body():
        # Neither refresh nor reset can run again before this handler succeeds.
        queue = yield from _ownership_queue("effectq-late-success:", "1 hour")
        yield from queue.offer({"n": 42}, id="order-1")

        def handle(_value: RedisItem, metadata: pq.Metadata) -> fx.Effect[None]:
            assert metadata.attempts == 1
            # Redis owns the lease clock; let it expire without another claimant.
            return fx.sleep("1100 millis")

        yield from queue.take(handle)

        # Only now allow recovery to run: a recorded success must leave no work.
        recovery = yield from _ownership_queue("effectq-late-success:", "100 millis")
        duplicate = yield from recovery.take(_metadata).fork_scoped()
        yield from fx.sleep("1500 millis")
        assert duplicate.poll_unsafe() is None

    _run(body, live=True)


def test_renews_an_expired_lease_before_recovery_revokes_ownership() -> None:
    """PersistedQueue (NodeRedis) / renews an expired lease before recovery revokes
    ownership"""

    def body():
        queue = yield from _ownership_queue("effectq-late-renewal:", "100 millis")
        # Stagger the timers: renewal is due at 100ms, reset at 150ms.
        yield from testing.adjust("50 millis")
        yield from queue.offer({"n": 42}, id="order-1")
        taken = Latch()
        finish = Latch()
        claim = yield from queue.take(
            lambda _v, _m: taken.open().and_then(finish.wait())
        ).fork_scoped()
        yield from taken.wait()
        yield from _live_sleep("1100 millis")
        # Only renewal runs, after Redis has expired the lease. Give its I/O
        # time to complete before introducing a recovery worker.
        yield from testing.adjust("50 millis")
        yield from _live_sleep("100 millis")
        recovery = yield from testing.with_live(
            fx.gen(lambda: _ownership_queue("effectq-late-renewal:", "100 millis"))
        )
        duplicate = yield from testing.with_live(recovery.take(_metadata)).fork_scoped()
        yield from _live_sleep("400 millis")
        assert duplicate.poll_unsafe() is None
        yield from finish.open()
        yield from claim.join()
        yield from _live_sleep("1500 millis")
        assert duplicate.poll_unsafe() is None

    _run(body)


def test_revoked_ownership_cannot_settle_recovered_work_before_reacquisition() -> None:
    """PersistedQueue (NodeRedis) / revoked ownership cannot settle recovered work before
    reacquisition"""

    def body():
        # Store construction pauses renewal. Takes use live time so polling
        # and reset keep running even while this test's clock is stopped.
        queue = yield from _ownership_queue("effectq-revoked-owner:", "100 millis")
        yield from queue.offer({"n": 42}, id="order-1")
        taken = Latch()
        finish = Latch()
        stale = yield from testing.with_live(
            queue.take(lambda _v, _m: taken.open().and_then(finish.wait()))
        ).fork_scoped()
        yield from taken.wait()
        # Reset recovers the expired lease, but no taker can acquire it yet.
        yield from _live_sleep("1500 millis")
        yield from testing.adjust("100 millis")
        yield from _live_sleep("100 millis")
        yield from finish.open()
        yield from stale.join()

        def recovered_with(value: RedisItem, metadata: pq.Metadata) -> fx.Effect[Any]:
            return fx.succeed((value, metadata.id, metadata.attempts))

        recovered = yield from testing.with_live(queue.take(recovered_with))
        assert recovered == ({"n": 42}, "order-1", 2)
        duplicate = yield from testing.with_live(queue.take(_metadata)).fork_scoped()
        yield from _live_sleep("1500 millis")
        assert duplicate.poll_unsafe() is None

    _run(body)


def test_stale_interruption_does_not_release_a_replacement_or_decrement_its_attempts() -> None:
    """PersistedQueue (NodeRedis) / stale interruption does not release a replacement or
    decrement its attempts"""

    def body():
        a = yield from _ownership_queue("effectq-stale-interrupt:", "1 hour")
        b = yield from _ownership_queue("effectq-stale-interrupt:", "100 millis")
        yield from a.offer({"n": 42}, id="order-1")
        taken = Latch()
        stale = yield from a.take(lambda _v, _m: taken.open().and_then(fx.never)).fork_scoped()
        yield from taken.wait()
        replaced = Latch()

        def replace(_value: RedisItem, metadata: pq.Metadata) -> fx.Effect[None]:
            assert metadata.attempts == 2
            return replaced.open().and_then(fx.never)

        replacement = yield from b.take(replace).fork_scoped()
        yield from replaced.wait()
        yield from stale.interrupt()
        duplicate = yield from b.take(_metadata).fork_scoped()
        yield from fx.sleep("1500 millis")
        assert duplicate.poll_unsafe() is None
        yield from replacement.interrupt()
        assert (yield from duplicate.join()).attempts == 2

    _run(body, live=True)


def test_same_store_stale_success_preserves_the_replacement_and_its_refresh_registration() -> None:
    """PersistedQueue (NodeRedis) / same-store stale success preserves the replacement and its
    refresh registration"""

    def body():
        queue = yield from _ownership_queue("effectq-same-store:", "100 millis")
        yield from queue.offer({"n": 42}, id="order-1")
        a_taken = Latch()
        release_a = Latch()
        stale = yield from testing.with_live(
            queue.take(lambda _v, _m: a_taken.open().and_then(release_a.wait()))
        ).fork_scoped()
        yield from a_taken.wait()
        # Poll/reset use live time; only renewal stays paused until B takes.
        b_taken = Latch()

        def replace(_value: RedisItem, metadata: pq.Metadata) -> fx.Effect[None]:
            assert metadata.attempts == 2
            return b_taken.open().and_then(fx.never)

        replacement = yield from testing.with_live(queue.take(replace)).fork_scoped()
        yield from b_taken.wait()
        # Only the replacement can now renew. Keep ticking while Redis I/O
        # completes, including while testing the old finalizer below.
        yield from (
            _live_sleep("100 millis").and_then(testing.adjust("100 millis")).forever().fork_scoped()
        )
        yield from release_a.open()
        yield from stale.join()
        duplicate = yield from testing.with_live(queue.take(_metadata)).fork_scoped()
        # The old finalizer must not unregister the new acquisition's refresh.
        yield from _live_sleep("1500 millis")
        assert duplicate.poll_unsafe() is None
        yield from replacement.interrupt()
        assert (yield from duplicate.join()).attempts == 2

    _run(body)


def test_a_renewal_after_recovery_does_not_recreate_the_revoked_lock() -> None:
    """Effect 4.1.2's ``expireAll``: a lapsed lock is recreated only while its
    claim still owns the element, so a worker's renewal after a reset
    recovered the element leaves no lock behind."""

    def body():
        prefix = "effectq-revoked-renewal:"
        redis = yield from Redis()
        queue = yield from _ownership_queue(prefix, "100 millis")
        yield from queue.offer({"n": 42}, id="order-1")
        taken = Latch()
        finish = Latch()
        stale = yield from testing.with_live(
            queue.take(lambda _v, _m: taken.open().and_then(finish.wait()))
        ).fork_scoped()
        yield from taken.wait()
        # The lease lapses and the live-clock reset recovers the element.
        yield from _live_sleep("1500 millis")
        assert (yield from redis.send("HLEN", f"{prefix}ownership:owners")) == 0
        # Now the paused renewal runs for the revoked claim.
        yield from testing.adjust("100 millis")
        yield from _live_sleep("100 millis")
        assert (yield from redis.send("KEYS", f"{prefix}lock:*")) == []
        yield from finish.open()
        yield from stale.join()

    _run(body)
