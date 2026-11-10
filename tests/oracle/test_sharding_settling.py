"""Ports of the "Sharding assignment settling" cases of Effect's
``test/cluster/Sharding.test.ts``: with ``runner_join_debounce``, runners
that join are added to the shard assignments only once the healthy runners
have settled, so each shard is handed off once. Each test's docstring is the
Effect test title."""

from __future__ import annotations

import copy
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field, replace
from typing import Any, Never

import pyfect as fx
from pyfect import exit as Exit
from pyfect import testing
from pyfect.clock import Clock
from pyfect.cluster import (
    message_storage,
    runner_health,
    runners,
    sharding,
    sharding_config,
    snowflake,
)
from pyfect.cluster.cluster_error import EntityNotAssignedToRunner, PersistenceError
from pyfect.cluster.entity_id import EntityId
from pyfect.cluster.machine_id import MachineId
from pyfect.cluster.message import Outgoing, codec_for_json
from pyfect.cluster.runner import Runner
from pyfect.cluster.runner_address import RunnerAddress
from pyfect.cluster.runner_storage import RunnerStorage, RunnerStorageService
from pyfect.cluster.runners import Runners, RunnersTransport
from pyfect.cluster.shard_id import ShardId
from pyfect.cluster.shard_id import make as shard
from pyfect.context import Context
from pyfect.duration import Duration, millis
from pyfect.layer import Layer
from pyfect.scope import CloseableScope, Scope, fork_in

from ._cluster_entities import TestEntity

_shards = [shard("default", i + 1) for i in range(24)]


def _joiner(port: int) -> Runner:
    return Runner(address=RunnerAddress(host="localhost", port=port), groups=("default",), weight=1)


def _void(*_: object) -> fx.Effect[None]:
    return fx.void


type Membership = list[tuple[Runner, bool]]


def _membership_storage(membership: Membership) -> RunnerStorageService:
    """Runner membership the test controls; the local runner joins on
    registration."""

    def register(runner: Runner, _healthy: bool) -> fx.Effect[MachineId, PersistenceError]:
        def run() -> MachineId:
            membership.append((runner, True))
            return MachineId(1)

        return fx.sync(run)

    def grant(_address: RunnerAddress, shards: Iterable[ShardId]) -> fx.Effect[list[ShardId]]:
        return fx.succeed(list(shards))

    return RunnerStorageService(
        get_runners=fx.sync(lambda: list(membership)),
        register=register,
        unregister=_void,
        set_runner_health=_void,
        acquire=grant,
        refresh=grant,
        release=_void,
        release_all=_void,
    )


def _config(port: int, **changes: Any) -> Layer[sharding_config.ShardingConfig]:
    defaults: dict[str, Any] = {
        "runner_address": RunnerAddress(host="localhost", port=port),
        "shards_per_group": len(_shards),
        "entity_termination_timeout": millis(0),
        "refresh_assignments_interval": millis(100),
    }
    return sharding_config.layer(replace(sharding_config.DEFAULTS, **(defaults | changes)))


@dataclass(frozen=True)
class _Change:
    at: float
    owned: str


@dataclass(eq=False)
class _Recorder:
    """The local runner's changes to the shards it owns, with the time
    since it started."""

    service: sharding.ShardingService
    clock: Any
    started_at: float
    history: list[_Change] = field(default_factory=list[_Change])
    current: str = ""

    def advance(self, millis: int) -> fx.Effect[None]:
        @fx.gen
        def run():
            for _ in range(0, millis, 10):
                yield from testing.adjust("10 millis")
                owned = ",".join(str(s) for s in _shards if self.service.has_shard_id(s))
                if owned == self.current:
                    continue
                self.current = owned
                now = self.clock.current_time_millis_unsafe()
                self.history.append(_Change(now - self.started_at, owned))

        return run


def _build_runner(membership: Membership, **config: Any) -> fx.Effect[_Recorder, Never, Scope]:
    layer = (
        sharding.layer.pipe(
            fx.layer.provide(fx.layer.succeed(RunnerStorage, _membership_storage(membership)))
        )
        .pipe(fx.layer.provide(runner_health.layer_noop))
        .pipe(fx.layer.provide(runners.layer_noop))
        .pipe(
            fx.layer.provide(
                fx.layer.merge(message_storage.layer_memory, snowflake.layer_generator)
            )
        )
        .pipe(fx.layer.provide(_config(1234, **config)))
    )

    @fx.gen
    def run():
        context: Context[Any] = yield from layer.build()
        clock = yield from Clock()
        service = context.get_unsafe(sharding.Sharding)
        return _Recorder(service, clock, clock.current_time_millis_unsafe())

    return run


def _staggered_joins(**config: Any) -> fx.Effect[list[_Change]]:
    """One runner, then three more joining 1.5 seconds apart."""

    @fx.gen
    def run():
        membership: Membership = []
        recorder = yield from _build_runner(membership, **config)
        yield from recorder.advance(1500)
        for port in (5001, 5002, 5003):
            membership.append((_joiner(port), True))
            yield from recorder.advance(1500)
        yield from recorder.advance(10_000)
        return recorder.history

    return fx.scoped(run)


@testing.effect(timeout="30 seconds")
def test_hands_each_shard_off_once_for_a_bounded_burst_of_staggered_joins():
    """hands each shard off once for a bounded burst of staggered joins"""
    # By default, each join publishes a new assignment within its interval.
    immediate = yield from _staggered_joins()
    assert [int(change.at // 1500) for change in immediate] == [0, 1, 2, 3]

    settled = yield from _staggered_joins(runner_join_debounce=millis(2000))
    assert [change.owned for change in settled] == [immediate[0].owned, immediate[3].owned]
    # the initial assignment does not wait for the window
    assert settled[0].at < 1500
    # the last join at 4500ms is published once membership is quiet for the window
    assert 6500 <= settled[1].at < 7000


@testing.effect
def test_publishes_continuous_joins_within_four_settle_windows():
    """publishes continuous joins within four settle windows"""

    @fx.gen
    def body():
        membership: Membership = []
        recorder = yield from _build_runner(membership, runner_join_debounce=millis(2000))
        yield from recorder.advance(1000)
        # joins every 1000ms never leave membership quiet for the window
        for port in range(5001, 5013):
            membership.append((_joiner(port), True))
            yield from recorder.advance(1000)
        history = recorder.history
        assert len(history) >= 2
        # the first join at 1000ms is published by 1000 + 4 * 2000ms
        assert 9000 <= history[1].at < 9500

    yield from fx.scoped(body)


@testing.effect
def test_publishes_unhealthy_runners_immediately_while_joins_are_settling():
    """publishes unhealthy runners immediately while joins are settling"""

    @fx.gen
    def body():
        existing = _joiner(5001)
        membership: Membership = [(existing, True)]
        recorder = yield from _build_runner(membership, runner_join_debounce=millis(2000))
        yield from recorder.advance(1000)
        # a runner starting in an existing cluster takes its share without waiting
        assert len(recorder.history) == 1
        assert recorder.history[0].owned != ",".join(map(str, _shards))

        membership.append((_joiner(5002), True))
        yield from recorder.advance(1000)
        assert len(recorder.history) == 1, "the join should still be settling"

        membership[0] = (existing, False)
        yield from recorder.advance(500)
        assert len(recorder.history) == 2, "the unhealthy runner should be published immediately"

    yield from fx.scoped(body)


# --- a staggered cluster over shared membership and locks --------------------------------------


@dataclass(eq=False)
class _SharedCluster:
    membership: Membership = field(default_factory=list[tuple[Runner, bool]])
    locks: dict[str, RunnerAddress] = field(default_factory=dict[str, RunnerAddress])
    owners: dict[str, list[int]] = field(default_factory=dict[str, list[int]])
    """The ports of the runners that locked each shard, in order."""
    fail_get_runners: set[int] = field(default_factory=set[int])
    """Ports whose next membership read fails."""
    stall_get_runners: dict[int, int] = field(default_factory=dict[int, int])
    """Ports whose next membership read fails after the given milliseconds."""
    acquire_delays: dict[int, int] = field(default_factory=dict[int, int])
    """Ports whose next acquisition of any shards completes after the given
    milliseconds."""


def _shared_cluster_storage(cluster: _SharedCluster, port: int) -> RunnerStorageService:
    """One runner's view of shared membership and exclusive shard locks."""

    def is_owner(shard_id: ShardId, address: RunnerAddress) -> bool:
        return cluster.locks.get(str(shard_id)) == address

    def get_runners() -> fx.Effect[list[tuple[Runner, bool]], PersistenceError]:
        failed: fx.Effect[list[tuple[Runner, bool]], PersistenceError] = fx.fail(
            PersistenceError(cause="getRunners failed")
        )
        stall = cluster.stall_get_runners.pop(port, None)
        if stall is not None:
            return failed.delay(Duration(stall / 1000))
        if port in cluster.fail_get_runners:
            cluster.fail_get_runners.discard(port)
            return failed
        return fx.succeed(list(cluster.membership))

    def register(runner: Runner, _healthy: bool) -> fx.Effect[MachineId, PersistenceError]:
        def run() -> MachineId:
            cluster.membership.append((runner, True))
            return MachineId(port)

        return fx.sync(run)

    def unregister(address: RunnerAddress) -> fx.Effect[None, PersistenceError]:
        def run() -> None:
            for i, (runner, _) in enumerate(cluster.membership):
                if runner.address == address:
                    del cluster.membership[i]
                    return

        return fx.sync(run)

    def acquire(
        address: RunnerAddress, shard_ids: Iterable[ShardId]
    ) -> fx.Effect[list[ShardId], PersistenceError]:
        requested = list(shard_ids)

        def run() -> list[ShardId]:
            acquired: list[ShardId] = []
            for shard_id in requested:
                key = str(shard_id)
                if key in cluster.locks and not is_owner(shard_id, address):
                    continue
                cluster.locks[key] = address
                owners = cluster.owners.setdefault(key, [])
                if not owners or owners[-1] != address.port:
                    owners.append(address.port)
                acquired.append(shard_id)
            return acquired

        delay = cluster.acquire_delays.get(port)
        if delay is None or not requested:
            return fx.sync(run)
        del cluster.acquire_delays[port]
        return fx.sync(run).delay(Duration(delay / 1000))

    def refresh(
        address: RunnerAddress, shard_ids: Iterable[ShardId]
    ) -> fx.Effect[list[ShardId], PersistenceError]:
        requested = list(shard_ids)
        return fx.sync(lambda: [s for s in requested if is_owner(s, address)])

    def release(address: RunnerAddress, shard_id: ShardId) -> fx.Effect[None, PersistenceError]:
        def run() -> None:
            if is_owner(shard_id, address):
                del cluster.locks[str(shard_id)]

        return fx.sync(run)

    def release_all(address: RunnerAddress) -> fx.Effect[None, PersistenceError]:
        def run() -> None:
            for key, owner in list(cluster.locks.items()):
                if owner == address:
                    del cluster.locks[key]

        return fx.sync(run)

    return RunnerStorageService(
        get_runners=fx.suspend(get_runners),
        register=register,
        unregister=unregister,
        set_runner_health=_void,
        acquire=acquire,
        refresh=refresh,
        release=release,
        release_all=release_all,
    )


@dataclass(frozen=True)
class _ClusterResult:
    owners: dict[str, list[int]]
    locks: dict[str, int]
    routes: dict[str, list[int]]
    executions: dict[str, list[int]]
    running: dict[str, int]


def _staggered_cluster(  # noqa: PLR0915
    *,
    refresh_assignments_interval: float = 0.1,
    fail_refresh_during_joins: bool = False,
    stall_joiner_refresh: bool = False,
    slow_joiner_acquire: bool = False,
) -> fx.Effect[_ClusterResult]:
    """Runners A (1234) and Z (1240, assigned no shard groups) start
    together, then B, C and D join 1.5 seconds apart. Every runner shares
    membership and shard locks, A to D register a singleton on each shard,
    and Z routes a volatile request to an entity on each shard.

    ``fail_refresh_during_joins`` fails A's next membership read once C has
    joined, while joins are pending. ``stall_joiner_refresh`` delays B's next
    membership read after D has joined by 2.5 seconds, then fails it, so B's
    view is stale while A publishes. ``slow_joiner_acquire`` delays B's
    first acquisition by 7.6 seconds, so it completes after A publishes and
    while B has C and D pending."""
    cluster = _SharedCluster()
    if slow_joiner_acquire:
        cluster.acquire_delays[1235] = 7600
    # The ports Z routed each shard to, in order
    routes: dict[str, list[int]] = {}
    # The ports each shard's singleton started on, in order
    executions: dict[str, list[int]] = {}
    # The port each shard's singleton is running on
    running: dict[str, int] = {}

    def start_runner(
        scope: CloseableScope,
        port: int,
        runners_layer: Layer[Runners, Never, Any] = runners.layer_noop,
        **config: Any,
    ) -> fx.Effect[Context[Any]]:
        storage = _shared_cluster_storage(cluster, port)
        layer = (
            sharding.layer.pipe(fx.layer.provide(fx.layer.succeed(RunnerStorage, storage)))
            .pipe(fx.layer.provide(runner_health.layer_noop))
            .pipe(fx.layer.provide(runners_layer))
            .pipe(
                fx.layer.provide(
                    fx.layer.merge(message_storage.layer_memory, snowflake.layer_generator)
                )
            )
            .pipe(
                fx.layer.provide(
                    _config(
                        port,
                        refresh_assignments_interval=Duration(refresh_assignments_interval),
                        send_retry_interval=millis(100),
                        runner_join_debounce=millis(2000),
                        **config,
                    )
                )
            )
        )
        return layer.build_with_scope(scope)

    def record_route(_address: RunnerAddress, message: Outgoing) -> fx.Effect[None, Any]:
        """Records each routing attempt, then fails it so the request
        retries."""

        def run() -> fx.Effect[None, Any]:
            key = str(message.envelope.address.shard_id)
            history = routes.setdefault(key, [])
            if not history or history[-1] != _address.port:
                history.append(_address.port)
            return fx.fail(EntityNotAssignedToRunner(address=message.envelope.address))

        return fx.suspend(run)

    observer_runners = fx.layer.effect(
        Runners,
        runners.make(
            RunnersTransport(
                codec_for=codec_for_json,
                send=record_route,
                notify=_void,
                ping=_void,
                on_runner_unavailable=_void,
            )
        ),
    ).pipe(fx.layer.provide(snowflake.layer_generator))

    @fx.gen
    def run():
        scope = CloseableScope()
        runner_a = yield from start_runner(scope, 1234)
        observer = yield from start_runner(scope, 1240, observer_runners, assigned_shard_groups=())
        observer_sharding = observer.get_unsafe(sharding.Sharding)
        make_client = yield from TestEntity.client().pipe(
            fx.provide_service(sharding.Sharding, observer_sharding)
        )
        routed: set[str] = set()
        entity_id = 1
        while len(routed) < 24:
            key = str(observer_sharding.get_shard_id(EntityId(str(entity_id)), "default"))
            if key not in routed:
                routed.add(key)
                yield from fork_in(
                    make_client(str(entity_id)).get_user_volatile({"id": entity_id}), scope
                )
            entity_id += 1
        singletons: dict[str, str] = {}
        entity_id = 1
        while len(singletons) < 24:
            name = f"singleton-{entity_id}"
            key = str(observer_sharding.get_shard_id(EntityId(name), "default"))
            singletons.setdefault(key, name)
            entity_id += 1

        def singleton(key: str, port: int) -> fx.Effect[None]:
            def started() -> None:
                history = executions.setdefault(key, [])
                if not history or history[-1] != port:
                    history.append(port)
                running[key] = port

            def stopped() -> None:
                if running.get(key) == port:
                    del running[key]

            return fx.sync(started).and_then(fx.never).on_interrupt(fx.sync(stopped))

        @fx.fn
        def register_singletons(context: Context[Any], port: int):
            service = context.get_unsafe(sharding.Sharding)
            for key, name in singletons.items():
                yield from service.register_singleton(name, singleton(key, port), None).pipe(
                    fx.provide_service(Scope, scope)
                )

        yield from register_singletons(runner_a, 1234)

        yield from testing.adjust("1500 millis")
        for port in (1235, 1236, 1237):
            yield from register_singletons((yield from start_runner(scope, port)), port)
            if port == 1236 and fail_refresh_during_joins:
                yield from testing.adjust("200 millis")
                cluster.fail_get_runners.add(1234)
                yield from testing.adjust("1300 millis")
            else:
                yield from testing.adjust("1500 millis")
        if stall_joiner_refresh:
            cluster.stall_get_runners[1235] = 2500
        for _ in range(150):
            yield from testing.adjust("100 millis")

        # Exclude the handoffs made while shutting down, which waits on the test clock
        result = _ClusterResult(
            owners=copy.deepcopy(cluster.owners),
            locks={key: owner.port for key, owner in cluster.locks.items()},
            routes=copy.deepcopy(routes),
            executions=copy.deepcopy(executions),
            running=dict(running),
        )
        closing = yield from scope.close(Exit.succeed(None)).fork()
        while closing.poll_unsafe() is None:
            yield from testing.adjust("100 millis")
        return result

    return run


def _assert_single_handoffs(result: _ClusterResult, *, lock_churn: bool = False) -> None:
    """Every shard is locked by at most two runners in turn, its singleton
    runs on at most two runners in turn, and Z changes the runner it routes
    each shard to at most once. Each shard ends up locked by the runner Z
    routes it to, with its singleton running there. ``lock_churn`` allows a
    runner to lock a shard briefly without running anything on it."""
    assert len(result.owners) == 24
    assert any(len(owners) == 2 for owners in result.owners.values()), "no shard was handed off"
    if not lock_churn:
        for key, owners in result.owners.items():
            assert len(owners) <= 2, f"shard {key} was locked by {owners}"
    assert len(result.executions) == 24
    for key, executions in result.executions.items():
        assert len(executions) <= 2, f"shard {key} ran its singleton on {executions}"
        assert result.running.get(key) == result.locks.get(key), f"shard {key} runs its singleton"
    assert len(result.routes) == 24
    assert any(len(routes) == 2 for routes in result.routes.values()), "no shard was rerouted"
    for key, routes in result.routes.items():
        assert len(routes) <= 2, f"shard {key} was routed to {routes}"
        assert result.locks.get(key) == routes[-1], f"shard {key} is routed to {routes[-1]}"


def _single_handoffs(
    run: Callable[[], fx.Effect[_ClusterResult]], *, lock_churn: bool = False
) -> fx.Effect[None]:
    return run().map(lambda result: _assert_single_handoffs(result, lock_churn=lock_churn))


@testing.effect(timeout="30 seconds")
def test_hands_each_shard_off_once_across_a_staggered_cluster_startup():
    """hands each shard off once across a staggered cluster startup"""
    yield from _single_handoffs(_staggered_cluster)


@testing.effect(timeout="30 seconds")
def test_hands_each_shard_off_once_when_membership_refresh_fails_during_pending_joins():
    """hands each shard off once when membership refresh fails during pending joins"""
    yield from _single_handoffs(lambda: _staggered_cluster(fail_refresh_during_joins=True))


@testing.effect(timeout="30 seconds")
def test_hands_each_shard_off_once_when_runners_poll_membership_out_of_phase():
    """hands each shard off once when runners poll membership out of phase"""
    yield from _single_handoffs(lambda: _staggered_cluster(refresh_assignments_interval=3))


@testing.effect(timeout="30 seconds")
def test_hands_each_shard_off_once_when_a_joining_runners_membership_refresh_stalls():
    """hands each shard off once when a joining runner's membership refresh stalls"""
    yield from _single_handoffs(lambda: _staggered_cluster(stall_joiner_refresh=True))


@testing.effect(timeout="30 seconds")
def test_runs_each_singleton_on_one_new_runner_when_a_joining_runners_acquisition_is_slow():
    """runs each singleton on one new runner when a joining runner's acquisition is slow"""
    # B can still lock shards when its slow acquisition completes, but must
    # not run them while joins are pending
    yield from _single_handoffs(
        lambda: _staggered_cluster(refresh_assignments_interval=3, slow_joiner_acquire=True),
        lock_churn=True,
    )
