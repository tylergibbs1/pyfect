"""The cron schedule check (``_cron_schedule``) relaxes Effect's strict
schedule exactly as wide as the recorded lock events allow (pyfect-only)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from pyfect.cluster.cluster_cron import CronPayload
from pyfect.cluster.entity_address import EntityAddress
from pyfect.cluster.entity_id import EntityId
from pyfect.cluster.entity_type import EntityType
from pyfect.cluster.shard_id import ShardId
from pyfect.cron import parse_unsafe
from pyfect.date_time import format_iso

from ._cluster_harness import StorageEvents
from ._cron_schedule import Tick, check_schedule, tick

every_second = parse_unsafe("* * * * * *", "UTC")
NAME = "schedule"
EXECUTOR_SHARD = ShardId(group="default", id=3)
OTHER_SHARD = ShardId(group="default", id=4)


class Script:
    """Storage events and runs of the cron ``NAME``'s executor, in the
    order the calls are made."""

    def __init__(self) -> None:
        self.events = StorageEvents()
        self.ticks: list[Tick] = []
        self._ids: dict[int, int] = {}

    @staticmethod
    def instant(second: int) -> str:
        return format_iso(datetime(2026, 1, 1, 0, 0, second, tzinfo=UTC))

    def save(self, second: int) -> None:
        request_id = 1000 + second
        self._ids[second] = request_id
        address = EntityAddress(
            shard_id=EXECUTOR_SHARD,
            entity_type=EntityType(f"ClusterCron/{NAME}"),
            entity_id=EntityId("executor"),
        )
        payload = CronPayload(date_time=datetime.fromisoformat(self.instant(second)), executor=True)
        self.events.saved(request_id, address, payload)

    def run(self, second: int, runner: str = "a") -> None:
        self.ticks.append(tick(0, runner, self.instant(second)))

    def reply(self, second: int) -> None:
        self.events.replied_to(self._ids[second])

    def abandon(self, second: int, runner: str = "a") -> None:
        self.events.abandoned(runner, [self._ids[second]])

    def acquire(self, shard: ShardId = EXECUTOR_SHARD, runner: str = "b") -> None:
        self.events.acquired(runner, [shard])

    def done(self, second: int) -> None:
        self.save(second)
        self.run(second)
        self.reply(second)

    def check(self) -> str:
        _, path = check_schedule(every_second, self.ticks, self.events, name=NAME, label="unit")
        return path


def test_runs_in_order_once_each_are_strict():
    script = Script()
    for second in range(4):
        script.done(second)
    assert script.check() == "strict"


def test_a_run_abandoned_in_flight_may_run_again():
    script = Script()
    script.done(0)
    script.save(1)
    script.run(1)
    script.abandon(1)
    script.run(1, "b")
    script.reply(1)
    script.done(2)
    assert script.check().startswith(f"relaxed: repeat {Script.instant(1)} after abandoned")


def test_a_run_in_flight_when_its_shard_is_acquired_may_run_again():
    script = Script()
    script.save(0)
    script.run(0)
    script.acquire()
    script.run(0, "b")
    script.reply(0)
    script.done(1)
    assert script.check().startswith(f"relaxed: repeat {Script.instant(0)} after acquired")


def test_a_repeat_with_no_lock_event_fails():
    script = Script()
    script.done(0)
    script.run(0)
    script.done(1)
    with pytest.raises(AssertionError, match="ran again with no lock event"):
        script.check()


def test_a_repeat_of_an_instant_another_event_freed_fails():
    script = Script()
    script.save(0)
    script.run(0)
    script.save(1)
    script.run(1)
    script.abandon(1)
    script.run(0)
    with pytest.raises(AssertionError, match="ran again with no lock event"):
        script.check()


def test_a_repeat_whose_reply_was_stored_before_the_event_fails():
    script = Script()
    script.done(0)
    script.acquire()
    script.run(0, "b")
    with pytest.raises(AssertionError, match="ran again with no lock event"):
        script.check()


def test_a_repeat_of_a_run_that_began_after_the_event_fails():
    script = Script()
    script.done(0)
    script.save(1)
    script.acquire()
    script.run(1, "b")
    script.run(1, "b")
    with pytest.raises(AssertionError, match="ran again with no lock event"):
        script.check()


def test_a_repeat_after_another_shard_is_acquired_fails():
    script = Script()
    script.save(0)
    script.run(0)
    script.acquire(OTHER_SHARD)
    script.run(0, "b")
    with pytest.raises(AssertionError, match="ran again with no lock event"):
        script.check()


def test_a_second_chain_after_a_move_may_run_out_of_order():
    script = Script()
    script.done(0)
    script.save(1)
    script.acquire()
    script.done(5)
    for second in range(1, 5):
        script.done(second)
    assert script.check() == (
        f"relaxed: reorder {Script.instant(0)} -> {Script.instant(5)} after a move; "
        f"reorder {Script.instant(5)} -> {Script.instant(1)} after a move"
    )


def test_a_reorder_before_the_move_fails():
    script = Script()
    script.done(0)
    script.done(2)
    script.acquire()
    script.done(1)
    with pytest.raises(AssertionError, match="with no move before it"):
        script.check()


def test_an_acquisition_before_the_first_run_is_not_a_move():
    script = Script()
    script.acquire()
    script.done(0)
    script.done(2)
    script.done(1)
    with pytest.raises(AssertionError, match="with no move before it"):
        script.check()


def test_a_skipped_instant_fails_even_after_a_move():
    script = Script()
    script.done(0)
    script.acquire()
    script.done(2)
    with pytest.raises(AssertionError, match="was skipped"):
        script.check()


def test_each_repeat_needs_its_own_event():
    script = Script()
    script.save(0)
    script.run(0)
    script.abandon(0)
    script.run(0)
    script.run(0)
    with pytest.raises(AssertionError, match="ran again with no lock event"):
        script.check()


def test_repeats_each_after_an_event_are_counted():
    script = Script()
    script.save(0)
    script.run(0)
    script.abandon(0)
    script.run(0)
    script.abandon(0)
    script.run(0)
    script.reply(0)
    assert script.check() == f"relaxed: repeat {Script.instant(0)} after abandoned on a (x2)"
