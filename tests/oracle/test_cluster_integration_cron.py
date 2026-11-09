"""Ports of platform-node's ``test/cluster-integration/ClusterCron.test.ts``
on the cluster harness (``_cluster_harness``), on SQLite and on the
throwaway PostgreSQL server where Effect uses PostgreSQL and MySQL. Each
test's docstring is the Effect test title, without its backend prefix.
"""

from __future__ import annotations

import builtins
from collections.abc import Callable, Generator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, cast

import pyfect as fx
from pyfect import testing
from pyfect.cluster import cluster_cron
from pyfect.cluster.cluster_cron import CurrentScheduledTime
from pyfect.cluster.cluster_schema import ShardGroup
from pyfect.cluster.entity import CurrentRunnerAddress, Entity
from pyfect.context import Context
from pyfect.cron import Cron, parse_unsafe
from pyfect.cron import next as cron_next
from pyfect.date_time import format_iso
from pyfect.latch import Latch

from ._cluster_harness import ClusterDatabase, make

type Body = Generator[fx.Effect[Any, Any, Any], Any]

every_second = parse_unsafe("* * * * * *", "UTC")
test_config = {"shards_per_group": 12}


@dataclass(frozen=True)
class Tick:
    at: float
    runner: str
    scheduled: str


def now_millis() -> fx.Effect[float]:
    return fx.clock.current_time_millis()


def millis_of(iso: str) -> float:
    return datetime.fromisoformat(iso).timestamp() * 1000


def record_tick(ticks: list[Tick]) -> fx.Effect[bool, Any, Any]:
    """Record a tick with its runner and scheduled instant; whether it is
    the first."""

    @fx.gen
    def record():
        runner = yield from CurrentRunnerAddress()
        scheduled = yield from CurrentScheduledTime()
        at = yield from now_millis()
        is_first = not ticks
        ticks.append(Tick(at, f"{runner.host}:{runner.port}", format_iso(scheduled)))
        return is_first

    return record


def cron_probe(name: str, shard_group: str = "default") -> builtins.type[Entity]:
    """An entity class at the address of the cron ``name``'s singleton and
    runs, for asking which runner owns them."""

    def group(_: Any) -> str:
        return shard_group

    return cast(
        "builtins.type[Entity]",
        builtins.type(
            f"Probe[{name}]",
            (Entity,),
            {},
            type=f"ClusterCron/{name}",
            annotations=Context.make(ShardGroup, group),
        ),
    )


def next_scheduled(cron: Cron, after: str | float) -> str:
    start = (
        datetime.fromisoformat(after)
        if isinstance(after, str)
        else datetime.fromtimestamp(after / 1000, UTC)
    )
    return format_iso(cron_next(cron, start).astimezone(UTC))


def assert_scheduled_from_execution_time(cron: Cron, ticks: list[Tick], start: int = 1) -> None:
    for index in range(start, len(ticks)):
        assert ticks[index].scheduled == next_scheduled(cron, ticks[index - 1].at)


def assert_scheduled_from_previous(cron: Cron, ticks: list[Tick]) -> None:
    for index in range(1, len(ticks)):
        assert ticks[index].scheduled == next_scheduled(cron, ticks[index - 1].scheduled)


def run(body: Callable[[], Body]) -> fx.Effect[None, Any]:
    return fx.scoped(fx.gen(body))


@testing.live(timeout="1 minute")
def test_runs_once_per_scheduled_instant_and_continues_after_failure(
    cluster_db: ClusterDatabase,
):
    """runs once per scheduled instant and continues after failure"""
    backend = cluster_db.backend

    def body() -> Body:
        ticks: list[Tick] = []
        attempts = {"failing": 0, "successful": 0}
        # Record ticks only once the assignments are stable, as the
        # calculation test below holds its executions: while the runners
        # start, the singleton can move and schedule a second chain, and the
        # first run, on a moving shard, can then run after a later one.
        armed = [False]

        def record() -> fx.Effect[None, Any, Any]:
            return record_tick(ticks).as_void() if armed[0] else fx.void

        def failing() -> fx.Effect[None, str]:
            attempts["failing"] += 1
            if attempts["failing"] == 1:
                return fx.fail("expected cron failure")
            attempts["successful"] += 1
            return fx.void

        cron = cluster_cron.make(
            name=f"basic-{backend}", cron=every_second, execute=fx.suspend(record)
        )
        failing_cron = cluster_cron.make(
            name=f"failure-{backend}", cron=every_second, execute=fx.suspend(failing)
        )
        cluster = yield from make(
            cluster_db, config=test_config, entities=fx.layer.merge(cron, failing_cron)
        )
        yield from cluster.start(3)
        yield from cluster.wait_for_stable_assignments()
        armed[0] = True
        yield from cluster.wait_until(
            "The cron jobs did not continue through four scheduled instants",
            fx.sync(lambda: len(ticks) >= 4 and attempts["failing"] >= 4),
        )

        first_four = ticks[:4]
        assert len({tick.scheduled for tick in first_four}) == len(first_four)
        assert_scheduled_from_execution_time(every_second, first_four)
        assert attempts["successful"] == attempts["failing"] - 1

    yield from run(body)


@testing.live(timeout="90 seconds")
def test_calculates_the_next_run_from_the_previous_instant_or_the_current_time(
    cluster_db: ClusterDatabase,
):
    """calculates the next run from the previous instant or the current time"""
    backend = cluster_db.backend

    def body() -> Body:
        previous_ticks: list[Tick] = []
        current_ticks: list[Tick] = []
        gate = Latch()
        # Hold an execution only once the assignments are stable, as a held
        # execution on a moving shard would keep that shard from being released.
        state = {"armed": False, "entered": 0}

        def blocked_execution(ticks: list[Tick]) -> fx.Effect[None, Any, Any]:
            @fx.gen
            def execute():
                if not state["armed"]:
                    return
                if (yield from record_tick(ticks)):
                    state["entered"] += 1
                    yield from gate.wait()

            return execute.uninterruptible()

        previous_cron = cluster_cron.make(
            name=f"previous-{backend}",
            cron=every_second,
            calculate_next_run_from_previous=True,
            execute=blocked_execution(previous_ticks),
        )
        current_cron = cluster_cron.make(
            name=f"current-{backend}", cron=every_second, execute=blocked_execution(current_ticks)
        )
        cluster = yield from make(
            cluster_db, config=test_config, entities=fx.layer.merge(previous_cron, current_cron)
        )
        yield from cluster.start(3)
        yield from cluster.wait_for_stable_assignments()
        state["armed"] = True
        yield from cluster.wait_until(
            "Both cron executions did not enter their first run",
            fx.sync(lambda: state["entered"] == 2),
        )
        blocked_at = yield from now_millis()
        yield from cluster.wait_until(
            "The cron executions were not held across several scheduled instants",
            now_millis().map(lambda now: now >= blocked_at + 3200),
            5,
        )
        gate.open_unsafe()
        yield from cluster.wait_until(
            "The cron jobs did not resume after their first execution",
            fx.sync(lambda: len(previous_ticks) >= 4 and len(current_ticks) >= 4),
            12,
        )

        previous_second = millis_of(previous_ticks[1].scheduled)
        current_second = millis_of(current_ticks[1].scheduled)
        assert_scheduled_from_previous(every_second, previous_ticks)
        assert_scheduled_from_execution_time(every_second, current_ticks, 2)
        assert previous_ticks[1].at - previous_second >= 2000
        assert current_ticks[1].at - current_second <= 1000

    yield from run(body)


@testing.live(timeout="90 seconds")
def test_catches_up_or_skips_stale_runs_and_preserves_the_schedule_across_restart(
    cluster_db: ClusterDatabase,
):
    """catches up or skips stale runs and preserves the schedule across restart"""
    backend = cluster_db.backend

    def body() -> Body:
        catch_up_ticks: list[Tick] = []
        skip_ticks: list[Tick] = []
        catch_up_cron = cluster_cron.make(
            name=f"catch-up-{backend}",
            cron=every_second,
            calculate_next_run_from_previous=True,
            execute=record_tick(catch_up_ticks).as_void(),
        )
        skip_cron = cluster_cron.make(
            name=f"skip-stale-{backend}",
            cron=every_second,
            calculate_next_run_from_previous=True,
            skip_if_older_than="500 millis",
            execute=record_tick(skip_ticks).as_void(),
        )
        cluster = yield from make(
            cluster_db, config=test_config, entities=fx.layer.merge(catch_up_cron, skip_cron)
        )
        runners = yield from cluster.start(3)
        yield from cluster.wait_for_stable_assignments()
        yield from cluster.wait_until(
            "The cron schedules did not start",
            fx.sync(lambda: len(catch_up_ticks) >= 2 and len(skip_ticks) >= 2),
        )
        for runner in runners:
            yield from cluster.kill(runner)
        catch_up_before = len(catch_up_ticks)
        skip_before = len(skip_ticks)
        last_scheduled_before_restart = catch_up_ticks[catch_up_before - 1].scheduled
        stopped_at = yield from now_millis()
        yield from cluster.wait_until(
            "The cluster downtime window did not elapse",
            now_millis().map(lambda now: now >= stopped_at + 3200),
            5,
        )
        assert len(catch_up_ticks) == catch_up_before
        assert len(skip_ticks) == skip_before

        yield from cluster.start(3)
        yield from cluster.wait_for_stable_assignments()

        def differs() -> bool:
            caught_up = len(catch_up_ticks) - catch_up_before
            skipped = len(skip_ticks) - skip_before
            return caught_up >= 3 and caught_up >= skipped + 2

        yield from cluster.wait_until(
            "The restarted cluster did not expose the catch-up and stale-skip difference",
            fx.sync(differs),
            15,
        )
        yield from cluster.wait_until(
            "The stale-skipping cron did not resume",
            fx.sync(lambda: len(skip_ticks) > skip_before),
        )

        first_catch_up = catch_up_ticks[catch_up_before]
        first_after_skip = skip_ticks[skip_before]
        assert first_catch_up.scheduled == next_scheduled(
            every_second, last_scheduled_before_restart
        )
        assert first_catch_up.at - millis_of(first_catch_up.scheduled) >= 2000
        assert first_after_skip.at - millis_of(first_after_skip.scheduled) <= 750
        assert_scheduled_from_previous(every_second, catch_up_ticks)

    yield from run(body)


@testing.live(timeout="90 seconds")
def test_resumes_without_duplicate_or_missing_ticks_after_the_singleton_owner_dies(
    cluster_db: ClusterDatabase,
):
    """resumes without duplicate or missing ticks after the singleton owner dies"""
    backend = cluster_db.backend

    def body() -> Body:
        name = f"owner-failover-{backend}"
        ticks: list[Tick] = []
        cron = cluster_cron.make(
            name=name,
            cron=every_second,
            calculate_next_run_from_previous=True,
            execute=record_tick(ticks).as_void(),
        )
        cluster = yield from make(cluster_db, config=test_config, entities=cron)
        yield from cluster.start(3)
        yield from cluster.wait_for_stable_assignments()
        yield from cluster.wait_until(
            "The cron did not execute before failover", fx.sync(lambda: len(ticks) >= 2)
        )
        owner = yield from cluster.owner_of_entity(cron_probe(name), name)
        assert owner is not None
        yield from cluster.kill(owner)
        after_kill = len(ticks)
        yield from cluster.wait_until(
            "The cron did not resume after its singleton owner died",
            fx.sync(lambda: len(ticks) >= after_kill + 3),
            12,
        )
        yield from cluster.wait_for_stable_assignments()

        assert_scheduled_from_previous(every_second, ticks)
        assert len({tick.scheduled for tick in ticks}) == len(ticks)
        owner_address = f"{owner.address.host}:{owner.address.port}"
        assert all(tick.runner != owner_address for tick in ticks[after_kill:])

    yield from run(body)


@testing.live(timeout="1 minute")
def test_assigns_cron_singletons_and_executions_to_their_shard_groups(
    cluster_db: ClusterDatabase,
):
    """assigns cron singletons and executions to their shard groups"""
    backend = cluster_db.backend

    def body() -> Body:
        default_name = f"default-group-{backend}"
        special_name = f"special-group-{backend}"
        default_ticks: list[Tick] = []
        special_ticks: list[Tick] = []
        default_cron = cluster_cron.make(
            name=default_name, cron=every_second, execute=record_tick(default_ticks).as_void()
        )
        special_cron = cluster_cron.make(
            name=special_name,
            cron=every_second,
            shard_group="special",
            execute=record_tick(special_ticks).as_void(),
        )
        cluster = yield from make(
            cluster_db,
            config={"available_shard_groups": ("default", "special"), "shards_per_group": 12},
            entities=fx.layer.merge(default_cron, special_cron),
        )
        [default_runner] = yield from cluster.start(1, assigned_shard_groups=("default",))
        [special_runner] = yield from cluster.start(1, assigned_shard_groups=("special",))
        yield from cluster.wait_for_stable_assignments()
        yield from cluster.wait_until(
            "The shard-group cron jobs did not execute",
            fx.sync(lambda: len(default_ticks) >= 2 and len(special_ticks) >= 2),
        )

        default_owner = yield from cluster.owner_of_entity(cron_probe(default_name), default_name)
        special_owner = yield from cluster.owner_of_entity(
            cron_probe(special_name, "special"), special_name
        )
        assert default_owner is default_runner
        assert special_owner is special_runner
        default_address = f"{default_runner.address.host}:{default_runner.address.port}"
        special_address = f"{special_runner.address.host}:{special_runner.address.port}"
        assert all(tick.runner == default_address for tick in default_ticks)
        assert all(tick.runner == special_address for tick in special_ticks)

    yield from run(body)
