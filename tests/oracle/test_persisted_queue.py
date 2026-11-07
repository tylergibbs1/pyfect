"""Ports of Effect's ``test/persistence/PersistedQueue.test.ts``: the
``PersistedQueueTest`` suite (``_persisted_queue_suite``) on
``layer_store_memory`` (``PersistedQueue (memory)``), then the file's own
titles.

Each test's docstring is the Effect test title. Durations are seconds
(Effect's ``Schedule.exponential(1000)`` is ``exponential(1)``).
"""

from __future__ import annotations

from typing import Any

import pyfect as fx
from pyfect import schedule, testing
from pyfect.persistence import persisted_queue as pq

from . import _persisted_queue_suite as suite
from ._persisted_queue_suite import ITEM, Item


class TestPersistedQueueMemory(suite.PersistedQueueSuite):
    """PersistedQueue (memory)"""

    layer = pq.layer_store_memory
    live = 0.0


def _run(body: suite.Body) -> None:
    suite.run(pq.layer_store_memory, body)


# --- PersistedQueue.retrySchedule -----------------------------------------------------


def test_derives_growing_delays_from_the_persisted_attempt_count() -> None:
    """PersistedQueue.retrySchedule / derives growing delays from the persisted attempt count"""

    def body():
        queue = yield from pq.make(
            name="retry-schedule-state",
            schema=ITEM,
            retry_schedule=schedule.exponential("1 second"),
        )
        attempts: list[int] = []

        def fail(_value: Item, meta: pq.Metadata) -> fx.Effect[None, str]:
            attempts.append(meta.attempts)
            return fx.fail("boom")

        take_fail = queue.take(fail).flip()
        yield from queue.offer({"n": 1})

        # attempt 1 at t=0 schedules the retry for t=1s
        yield from take_fail

        fiber = yield from take_fail.fork_scoped()
        yield from testing.adjust("500 millis")
        assert fiber.poll_unsafe() is None
        yield from testing.adjust("500 millis")
        assert (yield from fiber.join()) == "boom"

        # attempt 2 failed at t=1s: the schedule must not restart at 1s, the
        # next delay is 2s
        fiber2 = yield from take_fail.fork_scoped()
        yield from testing.adjust("1500 millis")
        assert fiber2.poll_unsafe() is None
        yield from testing.adjust("600 millis")
        assert (yield from fiber2.join()) == "boom"

        assert attempts == [1, 2, 3]

    _run(body)


# --- PersistedQueue.layerCleanup ------------------------------------------------------


def test_prunes_completed_elements_on_the_configured_interval() -> None:
    """PersistedQueue.layerCleanup / prunes completed elements on the configured interval"""

    def body():
        queue = yield from pq.make(name="cleanup-layer", schema=ITEM)
        yield from queue.offer({"n": 1}, id="cleanup-layer-id")
        yield from queue.take(_succeed)

        yield from pq.layer_cleanup(interval="1 minute", time_to_live="1 hour").build()

        # within the ttl the id stays deduplicated
        yield from testing.adjust("2 minutes")
        yield from queue.offer({"n": 2}, id="cleanup-layer-id")
        fiber = yield from queue.take(_succeed).fork_scoped()
        yield from testing.adjust("1 second")
        assert fiber.poll_unsafe() is None

        # after the ttl a cleanup run prunes the entry and the id can be reused
        yield from testing.adjust("2 hours")
        yield from queue.offer({"n": 3}, id="cleanup-layer-id")
        yield from testing.adjust("1 second")
        assert (yield from fiber.join()) == {"n": 3}

    _run(body)


def _succeed[A](value: A, _meta: Any) -> fx.Effect[A]:
    return fx.succeed(value)
