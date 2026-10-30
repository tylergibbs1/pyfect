"""Effect's ``test/persistence/PersistedQueueSqlTest.ts`` (its
``suiteWith(it)``): the delayed-offer and claim-ownership checks each SQL
driver runs, as a class a test module subclasses with ``make_client``.

They run on the live clock, which the database shares on this host; the
claim titles keep the stores' lock refreshes on the TestClock (Effect's
``TestClock.withLive`` around the waits only). Durations are seconds.
"""

from __future__ import annotations

from collections.abc import Generator
from typing import Any, Literal

import pytest

import pyfect as fx
from pyfect import schedule, testing
from pyfect import schema as S
from pyfect.clock import now_nanos
from pyfect.duration import Duration
from pyfect.latch import Latch
from pyfect.persistence import persisted_queue as pq
from pyfect.sql import SqlClient

type Body = Any


def now_millis() -> Generator[Any, Any, int]:
    return (yield from now_nanos()) // 1_000_000


def make_queue(
    table_name: str, poll_interval: Duration = 0.01
) -> Generator[Any, Any, pq.PersistedQueue[str]]:
    store = yield from pq.make_store_sql(table_name=table_name, poll_interval=poll_interval)
    factory = yield from pq.make_factory.pipe(fx.provide_service(pq.PersistedQueueStore, store))
    return (yield from factory.make(name=table_name, schema=S.String))


def make_ownership_queue(table_name: str) -> Generator[Any, Any, pq.PersistedQueue[str]]:
    store = yield from pq.make_store_sql(
        table_name=table_name,
        poll_interval=0.1,
        lock_refresh_interval=0.1,
        lock_expiration=1,
    )
    factory = yield from pq.make_factory.pipe(fx.provide_service(pq.PersistedQueueStore, store))
    return (
        yield from factory.make(name=table_name, schema=S.String, retry_schedule=schedule.spaced(0))
    )


def _succeed[A](value: A, _meta: pq.Metadata) -> fx.Effect[A]:
    return fx.succeed(value)


class PersistedQueueSqlSuite:
    """``PersistedQueue SQL delays`` and ``PersistedQueue SQL claims``: a
    test module subclasses it as ``Test...`` with ``client``, the
    ``SqlClient`` layer for one test."""

    def client(self) -> fx.Layer[SqlClient, Any]:
        raise NotImplementedError

    def run(self, body: Body, *, live: bool = True) -> None:
        program = fx.scoped(fx.gen(body))
        if live:
            program = testing.with_live(program)
        testing.run_test(program.pipe(fx.provide(self.client())))

    # --- PersistedQueue SQL delays ------------------------------------------------------

    def test_never_delivers_a_delayed_offer_early_at_a_second_boundary(self) -> None:
        """PersistedQueue SQL delays / never delivers a delayed offer early at a second
        boundary"""

        def body():
            queue = yield from make_queue("effect_queue_delay_boundary")

            # offer mid-way through a wall-clock second, so a whole-second
            # database clock drops about half a second from the start of the
            # delay while a slow insert still lands in the same second
            while True:
                millis = (yield from now_millis()) % 1000
                if 500 <= millis < 600:
                    break
                yield from fx.sleep(0.01)

            offered_at = yield from now_millis()
            yield from queue.offer("delayed", delay=1)
            yield from queue.take(_succeed)
            assert (yield from now_millis()) - offered_at >= 1000

        self.run(body)

    def test_measures_the_delay_from_an_offer_made_inside_a_transaction(self) -> None:
        """PersistedQueue SQL delays / measures the delay from an offer made inside a
        transaction"""

        def body():
            sql = yield from SqlClient()
            queue = yield from make_queue("effect_queue_delay_transaction")

            # the transaction starts well before the offer
            def offer() -> Generator[Any, Any, int]:
                yield from fx.sleep(2)
                offered_at = yield from now_millis()
                yield from queue.offer("delayed", delay=3)
                return offered_at

            offered_at = yield from sql.with_transaction(fx.gen(offer))
            yield from queue.take(_succeed)
            assert (yield from now_millis()) - offered_at >= 3000

        self.run(body)

    def test_wakes_a_waiting_taker_once_an_offer_made_inside_a_transaction_commits(
        self,
    ) -> None:
        """PersistedQueue SQL delays / wakes a waiting taker once an offer made inside a
        transaction commits"""

        def body():
            sql = yield from SqlClient()
            # no test waits out this poll interval: only the offer's wake-up
            # can deliver the element
            queue = yield from make_queue("effect_queue_commit_wake", 3600)
            taken = yield from queue.take(_succeed).fork_scoped()

            # the transaction stays open after the offer, long enough for a
            # wake-up sent before the commit to find nothing
            yield from sql.with_transaction(queue.offer("committed").and_then(fx.sleep(0.5)))

            value = yield from taken.join().timeout_option(5)
            assert value == fx.Some("committed")

        self.run(body)

    # --- PersistedQueue SQL claims ------------------------------------------------------

    @pytest.mark.parametrize(
        ("settlement", "same_store"),
        [("failure", True), ("failure", False), ("success", True)],
        ids=["failure-same", "failure-other", "success-same"],
    )
    def test_a_stale_settlement_preserves_a_newer_claim(
        self, settlement: Literal["failure", "success"], same_store: bool
    ) -> None:
        """PersistedQueue SQL claims / a stale ${settlement} preserves a newer claim from
        ${sameStore ? "the same" : "another"} store"""

        def body():
            table_name = f"effect_queue_stale_{settlement}_{'same' if same_store else 'other'}"
            stale = yield from make_ownership_queue(table_name)
            queue = stale if same_store else (yield from make_ownership_queue(table_name))
            yield from stale.offer("job", id="job-1")

            a_taken = Latch()
            a_release = Latch()

            def a(_value: str, _meta: pq.Metadata) -> fx.Effect[None, str]:
                end: fx.Effect[None, str] = fx.fail("boom") if settlement == "failure" else fx.void
                return a_taken.open().and_then(a_release.wait()).and_then(end)

            a_fiber = yield from stale.take(a).fork_scoped()
            yield from testing.with_live(a_taken.wait().timeout(5))

            # refreshes stay paused on the TestClock while the live database
            # clock expires the lock, whole-second timestamps included
            yield from testing.with_live(fx.sleep(2.5))

            b_taken = Latch()

            def b(value: str, meta: pq.Metadata) -> fx.Effect[None]:
                assert value == "job"
                assert meta.attempts == 2
                return b_taken.open().and_then(fx.never)

            replacement = yield from queue.take(b).fork_scoped()
            yield from testing.with_live(b_taken.wait().timeout(5))

            # resume refreshes for the replacement before the stale settlement
            yield from (
                testing.with_live(fx.sleep(0.1))
                .and_then(testing.adjust(0.1))
                .forever()
                .fork_scoped()
            )
            yield from a_release.open()
            yield from a_fiber.await_exit()

            duplicate = yield from queue.take(
                lambda value, meta: fx.succeed((value, meta.id, meta.attempts))
            ).fork_scoped()
            # longer than lock_expiration: the stale settlement must neither
            # release the replacement nor unregister its lock refresh
            yield from testing.with_live(fx.sleep(1.5))
            assert duplicate.poll_unsafe() is None

            yield from replacement.interrupt()
            redelivered = yield from testing.with_live(duplicate.join().timeout(5))
            assert redelivered == ("job", "job-1", 2)

        self.run(body, live=False)
