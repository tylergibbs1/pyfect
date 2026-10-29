"""Effect's ``test/persistence/PersistedQueueTest.ts``: the suite each
``PersistedQueueStore`` runs (its ``suiteWith(name, layer, ...)``), as a
class a test module subclasses with the store's ``layer``.

Durations are seconds. ``TestClock.adjust`` is ``testing.adjust``;
``Effect.sleep(...).pipe(TestClock.withLive)`` is a live sleep of that
many seconds times the class's ``live`` (1 for the stores that run on real
time; 0 for the memory store, which only reads the test clock, so its
suite takes no wall time: a live sleep of 0 is a yield). Each test builds
the layer afresh, where Effect's ``it.layer`` shares one store and clock
across the suite; every title uses queues of its own, as in Effect.
"""

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any, ClassVar, TypedDict

import pyfect as fx
from pyfect import schedule, testing
from pyfect import schema as S
from pyfect.duration import Seconds
from pyfect.latch import Latch
from pyfect.persistence import persisted_queue as pq

type Body = Callable[[], Generator[Any, Any]]


class Item(TypedDict):
    n: int


ITEM = S.Struct(Item, n=S.BigInt)


class Text(TypedDict):
    s: str


TEXT = S.Struct(Text)

LONE_SURROGATE = "\ud83d"
"""``"😀".slice(0, 1)``: the high half of a surrogate pair, alone."""


def run(layer: fx.Layer[Any, Any, Any], body: Body) -> None:
    testing.run_test(
        fx.scoped(fx.gen(body)).pipe(fx.provide(pq.layer.pipe(fx.layer.provide_merge(layer))))
    )


def live_sleep(seconds: float) -> fx.Effect[None]:
    return testing.with_live(fx.sleep(seconds))


class PersistedQueueSuite:
    """``PersistedQueue (${name})``: a test module subclasses it as
    ``Test...`` with the store's ``layer``."""

    layer: ClassVar[fx.Layer[pq.PersistedQueueStore, Any, Any]]
    live: ClassVar[float] = 1.0

    def make_layer(self) -> fx.Layer[pq.PersistedQueueStore, Any, Any]:
        """The store for one test (``layer``, unless a module builds a
        fresh database per test)."""
        return self.layer

    def run(self, body: Body) -> None:
        run(self.make_layer(), body)

    # --- the suite's helpers ----------------------------------------------------------

    def assert_not_delivered(self, fiber: fx.Fiber[Any, Any]) -> Generator[Any, Any]:
        """Advance the test clock one poll cycle, give real-time stores a
        moment, then check the forked take still waits."""
        yield from testing.adjust(1)
        yield from live_sleep(self.live)
        assert fiber.unsafe_poll() is None

    def await_delivery[A](self, fiber: fx.Fiber[A, Any]) -> Generator[Any, Any, A]:
        """Advance both clocks until the forked take completes, its
        acknowledgement included."""
        for _ in range(8):
            if fiber.unsafe_poll() is not None:
                break
            yield from testing.adjust(1)
            yield from live_sleep(0.7 * self.live)
        assert fiber.unsafe_poll() is not None
        return (yield from fiber.join())

    def advance_past_ttl(self) -> Generator[Any, Any]:
        """Move both clocks past a 1 second time to live."""
        yield from testing.adjust(2)
        yield from live_sleep(1.5 * self.live)

    # --- PersistedQueue (${name}) ------------------------------------------------------

    def test_offer_take(self) -> None:
        """offer + take"""

        def body():
            queue = yield from pq.make(name="test-queue-a", schema=ITEM)
            yield from queue.offer({"n": 42})

            def handle(value: Item, metadata: pq.Metadata) -> fx.Effect[None]:
                assert value["n"] == 42
                assert metadata.attempts == 1
                return fx.void

            yield from queue.take(handle)

        self.run(body)

    def test_delivers_lone_surrogates_without_losing_concurrent_elements(self) -> None:
        """delivers lone surrogates without losing concurrent elements"""

        def body():
            queue = yield from pq.make(name="test-queue-lone-surrogate-batch", schema=TEXT)
            yield from queue.offer({"s": LONE_SURROGATE})
            yield from queue.offer({"s": "ok"})
            fiber = yield from fx.all(
                queue.take(_succeed), queue.take(_succeed), concurrency=2
            ).fork_scoped()
            values = yield from self.await_delivery(fiber)
            assert sorted(v["s"] for v in values) == sorted([LONE_SURROGATE, "ok"])

        self.run(body)

    def test_delivers_elements_with_lone_surrogate_custom_ids(self) -> None:
        """delivers elements with lone-surrogate custom ids"""

        def body():
            queue = yield from pq.make(name="test-queue-lone-surrogate-custom-id", schema=ITEM)
            yield from queue.offer({"n": 42}, id=LONE_SURROGATE)
            fiber = yield from queue.take(_succeed).fork_scoped()
            assert (yield from self.await_delivery(fiber)) == {"n": 42}

        self.run(body)

    def test_cleanup_retains_failed_lone_surrogates_until_the_failed_ttl_releases_their_ids(
        self,
    ) -> None:
        """cleanup retains failed lone surrogates until the failed TTL releases their custom
        ids"""

        def body():
            store = yield from pq.PersistedQueueStore()
            queue = yield from pq.make(
                name="test-queue-lone-surrogate-failed-id", schema=TEXT, max_attempts=1
            )
            id = "lone-surrogate-failed-custom-id"
            yield from queue.offer({"s": LONE_SURROGATE}, id=id)
            failed = yield from queue.take(_boom).flip().fork_scoped()
            assert (yield from self.await_delivery(failed)) == "boom"

            # An unexpired dead letter must keep its custom id deduplicated.
            yield from store.cleanup(
                time_to_live=Seconds(1), failed_time_to_live=Seconds(30 * 86_400)
            )
            yield from queue.offer({"s": "duplicate"}, id=id)
            fiber = yield from queue.take(_succeed).fork_scoped()
            yield from self.assert_not_delivered(fiber)

            # Expiring that dead letter releases the id even with an opaque
            # surrogate payload.
            yield from self.advance_past_ttl()
            yield from store.cleanup(
                time_to_live=Seconds(30 * 86_400), failed_time_to_live=Seconds(1)
            )
            yield from queue.offer({"s": "reoffered"}, id=id)
            assert (yield from self.await_delivery(fiber)) == {"s": "reoffered"}

        self.run(body)

    def test_interrupt(self) -> None:
        """interrupt"""

        def body():
            queue = yield from pq.make(name="test-queue-b", schema=ITEM)
            yield from queue.offer({"n": 42})
            latch = Latch()

            def hold(_value: Item, _meta: pq.Metadata) -> fx.Effect[None]:
                return latch.open().and_then(fx.never)

            fiber = yield from queue.take(hold).fork_scoped()
            fiber2 = yield from queue.take(_succeed).fork_scoped()
            yield from latch.wait()

            # the second take really waits while the element is being processed
            yield from self.assert_not_delivered(fiber2)
            yield from fiber.interrupt()
            yield from testing.adjust(1)
            assert (yield from fiber2.join())["n"] == 42

        self.run(body)

    def test_failure(self) -> None:
        """failure"""

        def body():
            queue = yield from pq.make(
                name="test-queue-c", schema=ITEM, retry_schedule=schedule.spaced(0)
            )
            yield from queue.offer({"n": 42})
            assert (yield from queue.take(_boom).flip()) == "boom"

            def second(value: Item, meta: pq.Metadata) -> fx.Effect[Item]:
                assert meta.attempts == 2
                return fx.succeed(value)

            assert (yield from queue.take(second))["n"] == 42

        self.run(body)

    def test_delays_retries_with_the_retry_schedule(self) -> None:
        """delays retries with the retry schedule"""

        def body():
            queue = yield from pq.make(
                name="test-queue-retry-schedule",
                schema=ITEM,
                # MySQL and SQLite truncate retry timestamps to whole seconds:
                # leave room for that before the real-time check below.
                retry_schedule=schedule.spaced(2),
            )
            yield from queue.offer({"n": 42})
            assert (yield from queue.take(_boom).flip()) == "boom"
            fiber = yield from queue.take(_attempts).fork_scoped()

            # not redelivered before the retry delay elapses
            yield from testing.adjust(0.1)
            yield from live_sleep(0.1 * self.live)
            assert fiber.unsafe_poll() is None
            assert (yield from self.await_delivery(fiber)) == 2

        self.run(body)

    def test_delays_first_delivery_with_the_offer_delay(self) -> None:
        """delays first delivery with the offer delay"""

        def body():
            queue = yield from pq.make(name="test-queue-offer-delay", schema=ITEM)
            # SQL stores round to whole seconds, so keep the delay well clear
            # of the one second assert_not_delivered checks
            yield from queue.offer({"n": 42}, delay=3)

            def handle(value: Item, meta: pq.Metadata) -> fx.Effect[tuple[Item, int]]:
                return fx.succeed((value, meta.attempts))

            fiber = yield from queue.take(handle).fork_scoped()
            yield from self.assert_not_delivered(fiber)
            # the delay does not consume an attempt
            assert (yield from self.await_delivery(fiber)) == ({"n": 42}, 1)

        self.run(body)

    def test_delivers_zero_and_negative_offer_delays_immediately(self) -> None:
        """delivers zero and negative offer delays immediately"""

        def body():
            queue = yield from pq.make(name="test-queue-offer-delay-immediate", schema=ITEM)
            yield from queue.offer({"n": 1}, delay=0)
            yield from queue.offer({"n": 2}, delay=-5)
            first = yield from queue.take(_succeed)
            second = yield from queue.take(_succeed)
            assert sorted([first["n"], second["n"]]) == [1, 2]

        self.run(body)

    def test_an_infinite_offer_delay_writes_nothing(self) -> None:
        """an infinite offer delay writes nothing"""

        def body():
            queue = yield from pq.make(name="test-queue-offer-delay-infinite", schema=ITEM)
            id = yield from queue.offer({"n": 1}, id="infinite-delay-id", delay=float("inf"))
            assert id == "infinite-delay-id"
            generated_id = yield from queue.offer({"n": 2}, delay=float("inf"))
            assert generated_id

            # no dedupe record was written, so the id can be offered again
            yield from queue.offer({"n": 3}, id="infinite-delay-id")
            assert (yield from queue.take(_succeed)) == {"n": 3}

            fiber = yield from queue.take(_succeed).fork_scoped()
            yield from self.assert_not_delivered(fiber)

        self.run(body)

    def test_ignores_the_delay_of_a_duplicate_offer(self) -> None:
        """ignores the delay of a duplicate offer"""

        def body():
            queue = yield from pq.make(name="test-queue-offer-delay-duplicate", schema=ITEM)
            yield from queue.offer({"n": 1}, id="delayed-duplicate-id", delay=3)
            yield from queue.offer({"n": 2}, id="delayed-duplicate-id")

            # the undelayed duplicate does not make the element available early
            fiber = yield from queue.take(_succeed).fork_scoped()
            yield from self.assert_not_delivered(fiber)
            assert (yield from self.await_delivery(fiber)) == {"n": 1}

            fiber2 = yield from queue.take(_succeed).fork_scoped()
            yield from self.assert_not_delivered(fiber2)

        self.run(body)

    def test_idempotent_offer(self) -> None:
        """idempotent offer"""

        def body():
            queue = yield from pq.make(name="idempotent-offer", schema=ITEM)
            yield from queue.offer({"n": 42}, id="custom-id")
            yield from queue.offer({"n": 42}, id="custom-id")

            def check(value: Item, _meta: pq.Metadata) -> fx.Effect[None]:
                assert value["n"] == 42
                return fx.void

            yield from queue.take(check)
            fiber = yield from queue.take(check).fork_scoped()
            yield from self.assert_not_delivered(fiber)

        self.run(body)

    def test_deduplicates_custom_ids_independently_in_each_queue(self) -> None:
        """deduplicates custom ids independently in each queue"""

        def body():
            first = yield from pq.make(name="custom-id-first", schema=ITEM)
            second = yield from pq.make(name="custom-id-second", schema=ITEM)
            yield from first.offer({"n": 1}, id="shared-custom-id")
            yield from second.offer({"n": 2}, id="shared-custom-id")
            fiber = yield from second.take(_succeed).fork_scoped()
            assert (yield from self.await_delivery(fiber)) == {"n": 2}

        self.run(body)

    def test_does_not_redeliver_in_flight_elements(self) -> None:
        """does not redeliver in-flight elements"""

        def body():
            queue = yield from pq.make(name="test-queue-reset", schema=ITEM)
            yield from queue.offer({"n": 42})
            taken = Latch()
            release = Latch()
            fiber = yield from queue.take(
                lambda _v, _m: taken.open().and_then(release.wait())
            ).fork_scoped()
            yield from taken.wait()
            fiber2 = yield from queue.take(_succeed).fork_scoped()

            # let any periodic reset in the store run while the element is
            # still being processed
            yield from self.assert_not_delivered(fiber2)

            # after a successful take the element is not delivered again
            yield from release.open()
            yield from fiber.join()
            yield from self.assert_not_delivered(fiber2)
            yield from fiber2.interrupt()

        self.run(body)

    def test_stops_delivering_when_max_attempts_is_exhausted(self) -> None:
        """stops delivering when maxAttempts is exhausted"""

        def body():
            queue = yield from pq.make(
                name="test-queue-exhausted",
                schema=ITEM,
                max_attempts=1,
                retry_schedule=schedule.spaced(0),
            )
            yield from queue.offer({"n": 42})
            assert (yield from queue.take(_boom).flip()) == "boom"
            fiber = yield from queue.take(_succeed).fork_scoped()
            yield from self.assert_not_delivered(fiber)

        self.run(body)

    def test_dead_letters_elements_that_fail_to_decode(self) -> None:
        """dead-letters elements that fail to decode"""

        def body():
            store = yield from pq.PersistedQueueStore()
            queue = yield from pq.make(
                name="test-queue-decode-failure", schema=ITEM, retry_schedule=schedule.spaced(0)
            )
            yield from store.offer(
                name="test-queue-decode-failure",
                id="poison",
                element={"n": None},
                is_custom_id=True,
            )
            yield from queue.offer({"n": 42})

            # the poison element is marked as failed and skipped
            assert (yield from queue.take(_succeed)) == {"n": 42}

            # the poison element is not delivered again
            fiber = yield from queue.take(_succeed).fork_scoped()
            yield from self.assert_not_delivered(fiber)

        self.run(body)

    def test_cleanup_removes_expired_completed_elements(self) -> None:
        """cleanup removes expired completed elements"""

        def body():
            store = yield from pq.PersistedQueueStore()
            queue = yield from pq.make(name="test-queue-cleanup", schema=ITEM)
            yield from queue.offer({"n": 1}, id="cleanup-id")
            yield from queue.take(_succeed)

            # within the ttl the dedupe entry survives, so re-offers are ignored
            yield from store.cleanup(time_to_live=Seconds(30 * 86_400), failed_time_to_live=None)
            yield from queue.offer({"n": 2}, id="cleanup-id")
            fiber = yield from queue.take(_succeed).fork_scoped()
            yield from self.assert_not_delivered(fiber)

            # after the ttl the completed element and its dedupe entry go away
            yield from self.advance_past_ttl()
            yield from store.cleanup(time_to_live=Seconds(1), failed_time_to_live=None)
            yield from queue.offer({"n": 3}, id="cleanup-id")
            assert (yield from self.await_delivery(fiber)) == {"n": 3}

        self.run(body)

    def test_cleanup_removes_failed_elements_only_with_failed_time_to_live(self) -> None:
        """cleanup removes failed elements only with failedTimeToLive"""

        def body():
            store = yield from pq.PersistedQueueStore()
            queue = yield from pq.make(
                name="test-queue-cleanup-failed",
                schema=ITEM,
                max_attempts=1,
                retry_schedule=schedule.spaced(0),
            )
            yield from queue.offer({"n": 1}, id="failed-cleanup-id")
            assert (yield from queue.take(_boom).flip()) == "boom"

            # without failed_time_to_live the failed element is the dead
            # letter and is kept, so its id stays deduplicated
            yield from self.advance_past_ttl()
            yield from store.cleanup(time_to_live=Seconds(1), failed_time_to_live=None)
            yield from queue.offer({"n": 2}, id="failed-cleanup-id")
            fiber = yield from queue.take(_succeed).fork_scoped()
            yield from self.assert_not_delivered(fiber)

            # with failed_time_to_live the failed element and its dedupe entry go away
            yield from store.cleanup(
                time_to_live=Seconds(30 * 86_400), failed_time_to_live=Seconds(1)
            )
            yield from queue.offer({"n": 3}, id="failed-cleanup-id")
            assert (yield from self.await_delivery(fiber)) == {"n": 3}

        self.run(body)

    def test_cleanup_keeps_dedupe_entries_for_unprocessed_elements(self) -> None:
        """cleanup keeps dedupe entries for unprocessed elements"""

        def body():
            store = yield from pq.PersistedQueueStore()
            queue = yield from pq.make(name="test-queue-cleanup-pending", schema=ITEM)
            yield from queue.offer({"n": 1}, id="pending-cleanup-id")

            # an element older than the ttl that was never processed keeps its
            # dedupe entry, so the re-offer does not enqueue a duplicate
            yield from self.advance_past_ttl()
            yield from store.cleanup(time_to_live=Seconds(1), failed_time_to_live=None)
            yield from queue.offer({"n": 2}, id="pending-cleanup-id")
            assert (yield from queue.take(_succeed)) == {"n": 1}

            fiber = yield from queue.take(_succeed).fork_scoped()
            yield from self.assert_not_delivered(fiber)

        self.run(body)

    def test_processes_concurrent_elements_exactly_once_with_retries(self) -> None:
        """processes concurrent elements exactly once with retries"""

        def body():
            queue = yield from pq.make(
                name="test-queue-soak", schema=ITEM, retry_schedule=schedule.spaced(0)
            )
            total = 24
            deliveries: dict[int, int] = {}
            succeeded: set[int] = set()
            completed = Latch()
            yield from fx.for_each(range(total), lambda n: queue.offer({"n": n}), concurrency=8)

            def handle(value: Item, _meta: pq.Metadata) -> fx.Effect[None, str]:
                def run() -> fx.Effect[None, str]:
                    n = value["n"]
                    count = deliveries.get(n, 0) + 1
                    deliveries[n] = count
                    # every third element fails on its first delivery
                    if n % 3 == 0 and count == 1:
                        return fx.fail("transient")
                    succeeded.add(n)
                    if len(succeeded) == total:
                        completed.unsafe_open()
                    return fx.void

                return fx.suspend(run)

            worker = queue.take(handle).ignore().forever()
            for _ in range(3):
                yield from worker.fork_scoped()

            while not completed.is_open():
                yield from testing.adjust(1)
                yield from live_sleep(0.25 * self.live)

            assert len(succeeded) == total
            for n, count in deliveries.items():
                assert count == (2 if n % 3 == 0 else 1), f"deliveries for element {n}"

        self.run(body)


def _succeed[A](value: A, _meta: pq.Metadata) -> fx.Effect[A]:
    return fx.succeed(value)


def _boom(_value: object, _meta: pq.Metadata) -> fx.Effect[None, str]:
    return fx.fail("boom")


def _attempts(_value: object, meta: pq.Metadata) -> fx.Effect[int]:
    return fx.succeed(meta.attempts)
