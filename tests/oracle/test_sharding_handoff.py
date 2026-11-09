"""Ports of the "Sharding shard handoff", "Sharding singleton cancellation"
and "Sharding persisted sends to a shard awaiting its lock" groups of
Effect's ``test/cluster/Sharding.test.ts``, over Effect's ``FailoverStorage``
(``_failover_storage``) and its singleton reassignment storage. Each test's
docstring is the Effect test title."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import math
from collections.abc import Callable, Iterable
from dataclasses import dataclass, replace
from typing import Any, Never, cast

import pyfect as fx
from pyfect import exit as Exit
from pyfect import metric, testing
from pyfect._fiber import Fiber
from pyfect.clock import Clock
from pyfect.cluster import (
    _interruptors as active_teardown,
)
from pyfect.cluster import (
    cluster_metrics,
    message_storage,
    runner_health,
    runners,
    sharding,
    sharding_config,
    snowflake,
)
from pyfect.cluster.cluster_schema import Persisted
from pyfect.cluster.entity import Entity, EntityOptions
from pyfect.cluster.entity_address import EntityAddress
from pyfect.cluster.entity_id import EntityId
from pyfect.cluster.entity_type import EntityType
from pyfect.cluster.machine_id import MachineId
from pyfect.cluster.message_storage import MemoryDriver, MemoryDriverService
from pyfect.cluster.runner import Runner
from pyfect.cluster.runner_address import RunnerAddress
from pyfect.cluster.runner_storage import RunnerStorage, RunnerStorageService
from pyfect.cluster.shard_id import ShardId
from pyfect.cluster.shard_id import make as shard
from pyfect.context import Context
from pyfect.deferred import Deferred
from pyfect.duration import Seconds
from pyfect.latch import Latch
from pyfect.layer import Layer
from pyfect.logger import LogLevel, format_json
from pyfect.rpc import make as make_rpc
from pyfect.scope import CloseableScope, Scope

from . import _cluster_entities as entities
from ._cluster_entities import TestEntity, test_entity_no_state, test_entity_state_layer
from ._failover_storage import FailoverState, failover_storage_layer

EntityState = entities.TestEntityState

_runner_address = RunnerAddress(host="localhost", port=1234)
_all_shards = [shard("default", 1), shard("default", 2)]
_VOID = Exit.succeed(None)


class GatedTeardownEntity(Entity, type="GatedTeardownEntity"):
    activate = make_rpc("Activate").annotate(Persisted, False)


def _config(**changes: Any) -> Layer[sharding_config.ShardingConfig]:
    return sharding_config.layer(
        replace(sharding_config.DEFAULTS, runner_address=_runner_address, **changes)
    )


# --- the shard handoff fixtures ----------------------------------------------------------------


def _close(scope: CloseableScope, _exit: Exit.Exit[Any, Any]) -> fx.Effect[None]:
    return scope.close(_VOID)


_make_owned_scope = fx.acquire_release(fx.sync(CloseableScope), _close)


def _open_gate(gate: Latch, _exit: Exit.Exit[Any, Any]) -> fx.Effect[bool]:
    return gate.open()


# Open teardown gates before closing scopes, including on assertion failure.
_make_gate = fx.acquire_release(fx.sync(Latch), _open_gate)


@fx.fn
def _advance_until(done: Callable[[], bool]):
    for _ in range(100):
        if done():
            break
        yield from testing.adjust("10 millis")
    assert done()


def _releasing_gauge(registry: dict[Any, Any]) -> int | None:
    """The releasing-shards gauge of the registry the runner was built with."""
    for snapshot in metric.snapshot_unsafe(Context.make(metric.MetricRegistry, registry)):
        if snapshot.id == "effect_cluster_shards_releasing":
            assert isinstance(snapshot.state, metric.GaugeState)
            return int(cast(metric.GaugeState[int], snapshot.state).value)
    return None


@dataclass(slots=True, eq=False)
class _Built:
    context: Context[Any]
    scope: CloseableScope
    sharding: sharding.ShardingService


def _build_sharding(
    state: FailoverState, existing_scope: CloseableScope | None = None, **config: Any
) -> fx.Effect[_Built, Never, Scope]:
    defaults: dict[str, Any] = {
        "shards_per_group": 2,
        "entity_termination_timeout": Seconds(0),
        "entity_message_poll_interval": Seconds(0.01),
        "refresh_assignments_interval": Seconds(0.01),
    }
    layer = (
        sharding.layer.pipe(fx.layer.provide(failover_storage_layer(state)))
        .pipe(fx.layer.provide(runner_health.layer_noop))
        .pipe(fx.layer.provide(runners.layer_noop))
        .pipe(fx.layer.provide(message_storage.layer_memory))
        .pipe(fx.layer.provide(snowflake.layer_generator))
        .pipe(fx.layer.provide(_config(**(defaults | config))))
    )

    @fx.gen
    def run():
        scope = existing_scope if existing_scope is not None else (yield from _make_owned_scope)
        context: Context[Any] = yield from layer.build_with_scope(scope)
        return _Built(context, scope, context.get_unsafe(sharding.Sharding))

    return run


def _warning_logger(
    warnings: list[tuple[float, str]], on_error: Callable[[Any], None] | None = None
) -> fx.Effect[fx.Logger[None]]:
    @fx.gen
    def run():
        clock = yield from Clock()

        def log(options: Any) -> None:
            if on_error is not None and options.log_level == LogLevel.ERROR:
                on_error(options)
            if options.log_level != LogLevel.WARN:
                return
            output = format_json.log(options)
            if "releas" in output.lower():
                warnings.append((clock.current_time_millis_unsafe(), output))

        return fx.Logger.make(log)

    return run


def _with_loggers[A, E, R](
    effect: fx.Effect[A, E, R], logger: fx.Logger[None]
) -> fx.Effect[A, E, R]:
    return effect.pipe(fx.provide(fx.logger.layer([logger])))


def _now_millis() -> fx.Effect[float]:
    return fx.clock.current_time_millis()


def _gated_handlers(gate: Latch) -> fx.Effect[Any, Never, Scope]:
    handlers = GatedTeardownEntity.handlers().handle(GatedTeardownEntity.activate)(
        lambda _: fx.void
    )
    return fx.add_finalizer(lambda _: gate.wait()).as_(handlers)


# --- Sharding shard handoff ------------------------------------------------------------------


@testing.effect
def test_warns_about_pending_entities_and_singletons_and_reacquires_only_after_teardown():  # noqa: PLR0915
    """warns about pending entities and singletons and reacquires only after teardown"""
    state = FailoverState()
    registry: dict[Any, Any] = {}

    @fx.gen
    def body():  # noqa: PLR0915
        registration_scope = yield from _make_owned_scope
        clock = yield from Clock()
        warnings: list[tuple[float, str]] = []
        unhealthy_at: list[float] = []

        def on_error(options: Any) -> None:
            if "unhealthy" in str(options.message) and not unhealthy_at:
                unhealthy_at.append(clock.current_time_millis_unsafe())

        logger = yield from _warning_logger(warnings, on_error)
        built = yield from _with_loggers(
            _build_sharding(
                state,
                shards_per_group=1,
                shard_lock_expiration=Seconds(0.3),
                shard_lock_refresh_interval=Seconds(1),
                # Keep 30 seconds of polling cheap
                entity_message_poll_interval=Seconds(0.1),
            ),
            logger,
        ).pipe(fx.provide_service(metric.MetricRegistry, registry))
        service = built.sharding
        # These finalizers run before either scope closes, even on assertion
        # failure.
        entity_gate = yield from _make_gate
        singleton_gate = yield from _make_gate
        started = Latch()
        stopped = Latch()
        shard_id = shard("default", 1)
        yield from _advance_until(lambda: service.has_shard_id(shard_id))
        yield from service.register_entity(
            GatedTeardownEntity, _gated_handlers(entity_gate), EntityOptions()
        ).pipe(fx.provide_service(Scope, registration_scope))
        make_client = yield from GatedTeardownEntity.client().pipe(fx.provide(built.context))
        yield from make_client("1").activate()
        yield from service.register_singleton(
            "StalledReleaseSingleton",
            started.open()
            .and_then(singleton_gate.wait())
            .uninterruptible()
            .ensuring(stopped.open()),
            None,
        ).pipe(fx.provide_service(Scope, registration_scope))
        yield from started.wait()
        yield from _advance_until(lambda: any(call.shards for call in state.refresh_calls))
        acquires_before_outage = len(state.acquire_calls)

        def assert_still_blocked() -> None:
            assert not service.has_shard_id(shard_id)
            assert len(state.acquire_calls) == acquires_before_outage
            assert len(state.release_all_calls) == 0

        state.blackholed = True
        yield from testing.adjust("201 millis")
        assert not service.has_shard_id(shard_id)
        assert warnings == [], "a brief release must not warn"
        state.blackholed = False
        # Storage recovers, but uninterruptible work must still prevent release.
        yield from testing.adjust("1 second")
        assert_still_blocked()
        assert not stopped.is_open()
        first_warnings = list(warnings)
        blocked_shards = cluster_metrics.shards.value_unsafe(Context.empty()).value
        blocked_releasing = _releasing_gauge(registry)
        # The entity stops, so the next warning names only the singleton.
        yield from entity_gate.open()
        yield from testing.adjust(
            Seconds((first_warnings[0][0] + 29_999 - clock.current_time_millis_unsafe()) / 1000)
        )
        warnings_before_repeat = list(warnings)
        assert_still_blocked()
        yield from testing.adjust("1 millis")
        warnings_at_repeat = list(warnings)
        assert_still_blocked()

        yield from singleton_gate.open()
        yield from _advance_until(lambda: service.has_shard_id(shard_id))
        assert stopped.is_open()
        assert len(state.release_all_calls) == 1
        assert state.release_all_calls[0].completed
        reacquires = state.acquire_calls[acquires_before_outage:]
        assert len(reacquires) > 0
        assert all(call.completed_release_alls == 1 for call in reacquires)
        recovered_releasing = _releasing_gauge(registry)
        warnings_at_recovery = list(warnings)
        yield from testing.adjust("30 seconds")
        assert warnings == warnings_at_recovery, "the release monitor must stop after recovery"

        # Assert diagnostics last so the red test also exercises safe recovery.
        assert len(first_warnings) == 1, "a prolonged forced release must warn once by expiration"
        # The forced release starts once the acquisition loop wakes, after the
        # loss.
        assert first_warnings[0][0] - unhealthy_at[0] >= 300, (
            "the first warning must not precede expiration"
        )
        assert "default:1" in first_warnings[0][1]
        assert "GatedTeardownEntity" in first_warnings[0][1]
        assert "StalledReleaseSingleton" in first_warnings[0][1]
        assert warnings_before_repeat == first_warnings, (
            "warnings must not repeat before 30 seconds"
        )
        assert len(warnings_at_repeat) == 2, "a pending release must warn again after 30 seconds"
        assert warnings_at_repeat[1][0] - first_warnings[0][0] == 30_000
        assert "default:1" in warnings_at_repeat[1][1]
        assert "GatedTeardownEntity" not in warnings_at_repeat[1][1]
        assert "StalledReleaseSingleton" in warnings_at_repeat[1][1]
        assert warnings_at_recovery == warnings_at_repeat
        assert blocked_shards == 0
        assert blocked_releasing == 1, "the blocked shard must count as releasing"
        assert recovered_releasing == 0, "releasing must return to zero after recovery"

    yield from fx.scoped(body)


@testing.effect
def test_does_not_warn_when_forced_release_completes_before_the_warning_deadline():
    """does not warn when forced release completes before the warning deadline"""
    state = FailoverState(release_all_duration=0.05)

    @fx.gen
    def body():
        warnings: list[tuple[float, str]] = []
        logger = yield from _warning_logger(warnings)
        built = yield from _with_loggers(
            _build_sharding(
                state,
                shards_per_group=1,
                shard_lock_expiration=Seconds(0.3),
                shard_lock_refresh_interval=Seconds(1),
            ),
            logger,
        )

        def reset() -> None:
            state.release_all_duration = 0

        yield from fx.add_finalizer(lambda _: fx.sync(reset))
        service = built.sharding
        shard_id = shard("default", 1)
        yield from _advance_until(lambda: service.has_shard_id(shard_id))
        yield from _advance_until(lambda: any(call.shards for call in state.refresh_calls))
        state.blackholed = True
        yield from testing.adjust("201 millis")
        assert not service.has_shard_id(shard_id)
        state.blackholed = False
        yield from _advance_until(lambda: len(state.release_all_calls) > 0)
        assert not state.release_all_calls[0].completed
        yield from _advance_until(lambda: service.has_shard_id(shard_id))
        assert state.release_all_calls[0].completed
        yield from testing.adjust("900 millis")
        assert warnings == [], "a completed release must cancel its warning monitor"

    yield from fx.scoped(body)


@testing.effect
def test_warns_immediately_on_release_failure_and_throttles_retries_to_one_warning_per_30_seconds():
    """warns immediately on release failure and throttles retries to one warning per 30 seconds"""
    state = FailoverState(release_failures=math.inf)

    @fx.gen
    def body():
        warnings: list[tuple[float, str]] = []
        logger = yield from _warning_logger(warnings)
        built = yield from _with_loggers(
            _build_sharding(state, shards_per_group=1, shard_lock_refresh_interval=Seconds(0.1)),
            logger,
        )

        def reset() -> None:
            state.release_failures = 0

        yield from fx.add_finalizer(lambda _: fx.sync(reset))
        service = built.sharding
        yield from _advance_until(lambda: service.has_shard_id(_all_shards[0]))
        state.assign_self = False
        yield from _advance_until(lambda: len(state.release_calls) > 0)
        assert len(warnings) == 1, "the first failure must warn immediately"
        assert "release failed" in warnings[0][1]
        assert "default" in warnings[0][1]
        first_warning_at = warnings[0][0]
        first_attempts = len(state.release_calls)
        yield from testing.adjust(
            Seconds((first_warning_at + 29_999 - (yield from _now_millis())) / 1000)
        )
        assert len(warnings) == 1, "retries inside the throttle window must not warn"
        assert len(state.release_calls) > first_attempts, "storage retries must continue"
        yield from testing.adjust("1 millis")
        assert len(warnings) == 2, "a continuing failure must warn again after 30 seconds"
        assert warnings[1][0] - first_warning_at == 30_000
        state.release_failures = 0
        yield from testing.adjust("100 millis")
        completed_attempts = len(state.release_calls)
        yield from testing.adjust("30 seconds")
        assert len(state.release_calls) == completed_attempts
        assert len(warnings) == 2, "warnings must stop after release succeeds"

    yield from fx.scoped(body)


@testing.effect
def test_waits_for_entity_teardown_before_handing_off_without_acquiring_newly_freed_shards():
    """waits for entity teardown before handing off without acquiring newly freed shards"""
    held_shard, freed_shard = _all_shards
    state = FailoverState(acquire_denied=[freed_shard])

    @fx.gen
    def body():
        registration_scope = yield from _make_owned_scope
        # Keep assignments unchanged while a peer's lock becomes available.
        built = yield from _build_sharding(state, refresh_assignments_interval=Seconds(60))
        service = built.sharding
        gate = yield from _make_gate
        yield from _advance_until(lambda: service.has_shard_id(held_shard))
        yield from service.register_entity(
            GatedTeardownEntity, _gated_handlers(gate), EntityOptions()
        ).pipe(fx.provide_service(Scope, registration_scope))
        entity_id = 0
        while service.get_shard_id(EntityId(str(entity_id)), "default") != held_shard:
            entity_id += 1
        make_client = yield from GatedTeardownEntity.client().pipe(fx.provide(built.context))
        yield from make_client(str(entity_id)).activate()

        closing = yield from built.scope.close(_VOID).fork()
        yield from _advance_until(lambda: state.runner is None)
        acquires = len(state.acquire_calls)
        state.acquire_denied.clear()
        yield from testing.adjust("3 seconds")
        assert closing.poll_unsafe() is None
        assert state.runner is None
        assert state.acquire_calls[acquires:] == []
        assert state.release_calls == []
        assert state.release_all_calls == []

        yield from gate.open()
        yield from _advance_until(lambda: closing.poll_unsafe() is not None)
        assert closing.poll_unsafe() == _VOID
        assert state.release_calls == [held_shard]
        assert [call.releases for call in state.release_all_calls] == [1]

    yield from fx.scoped(body)


@testing.effect
def test_does_not_record_a_release_cancelled_when_shutdown_handoff_times_out():
    """does not record a release cancelled when shutdown handoff times out"""
    state = FailoverState(release_failures=math.inf)
    registry: dict[Any, Any] = {}
    config: dict[str, Any] = {
        "shards_per_group": 1,
        "shard_lock_refresh_interval": Seconds(0.1),
    }

    def release_duration() -> metric.HistogramState:
        return cluster_metrics.shard_release_duration.value_unsafe(
            Context.make(metric.MetricRegistry, registry)
        )

    @fx.gen
    def body():
        built = yield from _build_sharding(state, **config).pipe(
            fx.provide_service(metric.MetricRegistry, registry)
        )
        yield from _advance_until(lambda: built.sharding.has_shard_id(_all_shards[0]))
        before = release_duration()

        closing = yield from built.scope.close(_VOID).fork()
        yield from _advance_until(lambda: len(state.release_calls) > 0)
        yield from testing.adjust("50 millis")
        assert len(state.release_calls) > 1, "storage retries must continue"
        retrying_releasing = _releasing_gauge(registry)
        yield from _advance_until(lambda: closing.poll_unsafe() is not None)

        assert closing.poll_unsafe() == _VOID
        assert release_duration().count == before.count
        assert retrying_releasing == 1, "retries must not count a shard twice"

        # A new runner in the same registry must not report the abandoned
        # release.
        state.release_failures = 0
        restarted = yield from _build_sharding(state, **config).pipe(
            fx.provide_service(metric.MetricRegistry, registry)
        )
        assert _releasing_gauge(registry) == 0, "initialization must publish zero"
        yield from _advance_until(lambda: restarted.sharding.has_shard_id(_all_shards[0]))
        assert _releasing_gauge(registry) == 0

    yield from fx.scoped(body)


@testing.effect
def test_waits_for_singleton_teardown_before_handing_off_their_shards():
    """waits for singleton teardown before handing off their shards"""
    state = FailoverState()
    registry: dict[Any, Any] = {}

    @fx.gen
    def body():
        registration_scope = yield from _make_owned_scope
        running_registration_scope = yield from _make_owned_scope
        built = yield from _build_sharding(state).pipe(
            fx.provide_service(metric.MetricRegistry, registry)
        )
        service = built.sharding
        gate = yield from _make_gate
        yield from _advance_until(lambda: all(service.has_shard_id(s) for s in _all_shards))
        assert _releasing_gauge(registry) == 0, "initialization must publish zero"
        started = Latch()
        stopping = Latch()
        yield from service.register_singleton(
            "ClosingSingleton",
            started.open().and_then(
                fx.add_finalizer(lambda _: stopping.open().and_then(gate.wait()))
            ),
            None,
        ).pipe(fx.provide_service(Scope, registration_scope))
        yield from started.wait()
        # A singleton on the other shard that is still running at shutdown.
        closing_shard = service.get_shard_id(EntityId("ClosingSingleton"), "default")
        running_name = 0
        while service.get_shard_id(EntityId(f"Running{running_name}"), "default") == closing_shard:
            running_name += 1
        running_started = Latch()
        yield from service.register_singleton(
            f"Running{running_name}",
            running_started.open().and_then(fx.add_finalizer(lambda _: gate.wait())),
            None,
        ).pipe(fx.provide_service(Scope, running_registration_scope))
        yield from running_started.wait()
        yield from registration_scope.close(_VOID).fork()
        yield from stopping.wait()

        closing = yield from built.scope.close(_VOID).fork()
        yield from testing.adjust("100 millis")
        assert closing.poll_unsafe() is None
        assert state.release_calls == []
        assert state.release_all_calls == []
        tearing_down_releasing = _releasing_gauge(registry)

        # Each shard's first release attempt fails and is retried.
        state.release_failures = 2
        yield from gate.open()
        yield from _advance_until(lambda: len(state.release_calls) >= 2)
        retrying_releasing = _releasing_gauge(registry)
        yield from _advance_until(lambda: closing.poll_unsafe() is not None)
        assert closing.poll_unsafe() == _VOID
        assert [call.releases for call in state.release_all_calls] == [4]
        assert tearing_down_releasing == 2, "each shard waiting for teardown must count once"
        assert retrying_releasing == 2, "retries must not count a shard twice"
        assert _releasing_gauge(registry) == 0, "a completed handoff must publish zero"

    yield from fx.scoped(body)


@testing.effect
def test_closes_a_singleton_registration_whose_singleton_registered_another_singleton():
    """closes a singleton registration whose singleton registered another singleton"""
    state = FailoverState()

    # Await cleanup, but keep a regressed uninterruptible teardown bounded.
    def close_detached(scope: CloseableScope, _exit: Exit.Exit[Any, Any]) -> fx.Effect[None]:
        @fx.gen
        def run():
            closing = yield from scope.close(_VOID).fork_daemon()
            yield from _advance_until(lambda: closing.poll_unsafe() is not None)
            assert closing.poll_unsafe() == _VOID

        return run

    make_detached_scope = fx.acquire_release(fx.sync(CloseableScope), close_detached)

    @fx.gen
    def body():
        sharding_scope = yield from make_detached_scope
        registration_scope = yield from make_detached_scope
        built = yield from _build_sharding(state, sharding_scope)
        service = built.sharding
        yield from _advance_until(lambda: all(service.has_shard_id(s) for s in _all_shards))
        child_registered = Latch()
        yield from service.register_singleton(
            "ParentSingleton",
            service.register_singleton("ChildSingleton", fx.never, None)
            .and_then(child_registered.open())
            .as_void(),
            None,
        ).pipe(fx.provide_service(Scope, registration_scope))
        yield from child_registered.wait()

        closing = yield from registration_scope.close(_VOID).fork_daemon()
        yield from _advance_until(lambda: closing.poll_unsafe() is not None)
        assert closing.poll_unsafe() == _VOID

    yield from fx.scoped(body)


# --- Sharding singleton cancellation -----------------------------------------------------------


@dataclass(slots=True, eq=False)
class _SingletonStorageState:
    assign_self: bool = True
    runner: Runner | None = None


_singleton_other_runner = Runner(
    address=RunnerAddress(host="localhost", port=5678),
    groups=("singleton",),
    # With these fixed addresses, the weighted ring moves singleton:1 to this
    # runner. The ownership assertions below guard that fixture assumption.
    weight=1000,
)


def _singleton_storage(state: _SingletonStorageState) -> RunnerStorageService:
    def get_runners() -> list[tuple[Runner, bool]]:
        if state.runner is None:
            return []
        if state.assign_self:
            return [(state.runner, True)]
        return [(state.runner, True), (_singleton_other_runner, True)]

    def register(runner: Runner, _healthy: bool) -> fx.Effect[MachineId]:
        def run() -> MachineId:
            state.runner = runner
            return MachineId(1)

        return fx.sync(run)

    def granted(_address: RunnerAddress, shard_ids: Iterable[ShardId]) -> fx.Effect[list[ShardId]]:
        return fx.sync(lambda: list(shard_ids))

    return RunnerStorageService(
        register=register,
        unregister=lambda _address: fx.void,
        get_runners=fx.sync(get_runners),
        set_runner_health=lambda _address, _healthy: fx.void,
        acquire=granted,
        refresh=granted,
        release=lambda _address, _shard_id: fx.void,
        release_all=lambda _address: fx.void,
    )


def _singleton_reassignment_sharding(state: _SingletonStorageState) -> Layer[Any]:
    """Keep the destination shard local while only the singleton shard moves
    away."""
    return (
        test_entity_no_state.pipe(fx.layer.provide_merge(sharding.layer))
        .pipe(fx.layer.provide(runner_health.layer_noop))
        .pipe(fx.layer.provide(fx.layer.sync(RunnerStorage, lambda: _singleton_storage(state))))
        .pipe(fx.layer.provide_merge(test_entity_state_layer))
        .pipe(fx.layer.provide(runners.layer_noop))
        .pipe(fx.layer.provide_merge(message_storage.layer_memory))
        .pipe(
            fx.layer.provide(
                _config(
                    entity_mailbox_capacity=10,
                    available_shard_groups=("default", "singleton"),
                    assigned_shard_groups=("default", "singleton"),
                    shards_per_group=1,
                    entity_termination_timeout=Seconds(0),
                    entity_message_poll_interval=Seconds(0.01),
                    refresh_assignments_interval=Seconds(0.01),
                    send_retry_interval=Seconds(0.01),
                )
            )
        )
    )


_singleton_shard = shard("singleton", 1)
_destination_shard = shard("default", 1)


@fx.fn
def _wait_for_singleton_ownership(service: sharding.ShardingService, owned: bool):
    for _ in range(100):
        if service.has_shard_id(_singleton_shard) == owned:
            return
        yield from testing.adjust("10 millis")
    assert service.has_shard_id(_singleton_shard) == owned


def _journal_interrupts(driver: MemoryDriverService) -> int:
    return len([e for e in driver.encoded.journal if e["_tag"] == "Interrupt"])


@testing.effect
def test_cancels_explicitly_but_abandons_a_singleton_child_rpc_on_reassignment():
    """cancels explicitly but abandons a singleton child RPC on reassignment"""
    storage_state = _SingletonStorageState()

    @fx.gen
    def body():
        service = yield from sharding.Sharding()
        driver = yield from MemoryDriver()
        entity_state = yield from EntityState()
        # Acquire clients outside the singleton context; children must use
        # caller identity.
        make_client = yield from TestEntity.client()
        explicit_client = make_client("explicit-singleton-target")
        reassignment_client = make_client("singleton-target")
        child_ready = yield from Deferred[Fiber[None, Any], Never].make()
        run_reassignment = yield from Deferred[None, Never].make()
        stopped = yield from Deferred[None, Never].make()
        yield from _wait_for_singleton_ownership(service, True)

        @fx.gen
        def singleton():
            child = yield from explicit_client.never().fork(start_immediately=True)
            yield from child_ready.succeed(child)
            yield from run_reassignment.wait()
            yield from reassignment_client.never().fork(start_immediately=True)
            yield from fx.never

        yield from service.register_singleton(
            "rpc-caller", singleton.ensuring(stopped.succeed(None)), "singleton"
        )
        yield from entity_state.envelopes.take()
        yield from (yield from child_ready.wait()).interrupt()
        yield from testing.adjust("1 millis")
        assert service.has_shard_id(_singleton_shard)
        assert _journal_interrupts(driver) == 1, "explicit child cancellation must persist"
        yield from entity_state.interrupts.take()

        yield from run_reassignment.succeed(None)
        yield from entity_state.envelopes.take()
        storage_state.assign_self = False
        yield from _wait_for_singleton_ownership(service, False)
        yield from stopped.wait()
        yield from testing.adjust("1 millis")
        assert service.has_shard_id(_destination_shard), "Sharding and the destination stay alive"
        assert _journal_interrupts(driver) == 1, "reassignment must not add a durable cancellation"
        assert entity_state.interrupts.size_unsafe() == 0

    yield from fx.scoped(body).pipe(fx.provide(_singleton_reassignment_sharding(storage_state)))


@testing.effect
def test_bounds_singleton_teardown_to_interruption_finalization_not_inherited_context():
    """bounds singleton teardown to interruption finalization, not inherited context"""
    storage_state = _SingletonStorageState()

    @fx.gen
    def body():
        service = yield from sharding.Sharding()
        driver = yield from MemoryDriver()
        entity_state = yield from EntityState()
        client = (yield from TestEntity.client())("finalizer-target")
        # Both clients are acquired before singleton execution. Keep the
        # survivor on a separate local entity so the preserved finalizer RPC
        # cannot block it.
        survivor_client = (yield from TestEntity.client())("survivor-target")
        outer_scope = yield from Scope()
        run_later = yield from Deferred[None, Never].make()
        survivor_ready = yield from Deferred[Fiber[None, Any], Never].make()
        finalizing = yield from Deferred[None, Never].make()
        finish = yield from Deferred[None, Never].make()
        stopped = yield from Deferred[None, Never].make()
        yield from _wait_for_singleton_ownership(service, True)

        @fx.gen
        def singleton():
            # This fiber inherits singleton identity but outlives its local run.
            survivor = yield from (
                run_later.wait()
                .and_then(survivor_client.never())
                .fork_in(outer_scope, start_immediately=True)
            )
            yield from survivor_ready.succeed(survivor)
            yield from fx.never

        @fx.gen
        def finalizer():
            # Cancellation during finalization is still shard teardown.
            child = yield from client.never().interruptible().fork(start_immediately=True)
            yield from entity_state.envelopes.take()
            yield from child.interrupt()
            yield from finalizing.succeed(None)
            yield from finish.wait()

        yield from service.register_singleton(
            "finalizer-caller",
            singleton.ensuring(finalizer).ensuring(stopped.succeed(None)),
            "singleton",
        )
        survivor = yield from survivor_ready.wait()
        # Release the finalizer barrier even if a setup assertion fails.
        yield from fx.add_finalizer(lambda _: finish.succeed(None))
        storage_state.assign_self = False
        yield from _wait_for_singleton_ownership(service, False)
        yield from finalizing.wait()
        during_finalization = _journal_interrupts(driver)
        probe = EntityAddress(
            shard_id=_singleton_shard,
            entity_type=EntityType("singleton-teardown-probe"),
            entity_id=EntityId("probe"),
        )
        assert active_teardown.is_active(probe), "tracking must remain active through finalization"
        yield from finish.succeed(None)
        yield from stopped.wait()
        yield from testing.adjust("10 millis")
        assert not active_teardown.is_active(probe), "teardown must release its shard tracking"

        # Do not let inherited identity suppress a later explicit
        # cancellation.
        yield from run_later.succeed(None)
        yield from entity_state.envelopes.take()
        yield from survivor.interrupt()
        yield from testing.adjust("1 millis")
        assert _journal_interrupts(driver) - during_finalization == 1
        assert service.has_shard_id(_destination_shard)
        assert during_finalization == 0, "teardown must include singleton finalizers"

    yield from fx.scoped(body).pipe(fx.provide(_singleton_reassignment_sharding(storage_state)))


# --- Sharding persisted sends to a shard awaiting its lock ---------------------------------------


def _pending_lock_sharding(state: FailoverState) -> Layer[Any]:
    return (
        test_entity_no_state.pipe(fx.layer.provide_merge(sharding.layer))
        .pipe(fx.layer.provide(failover_storage_layer(state)))
        .pipe(fx.layer.provide(runner_health.layer_noop))
        .pipe(fx.layer.provide_merge(test_entity_state_layer))
        .pipe(fx.layer.provide(runners.layer_noop))
        .pipe(fx.layer.provide(message_storage.layer_memory))
        .pipe(
            fx.layer.provide(
                _config(
                    shards_per_group=1,
                    entity_message_poll_interval=Seconds(0.01),
                    refresh_assignments_interval=Seconds(0.01),
                    send_retry_interval=Seconds(0.01),
                )
            )
        )
    )


@testing.effect
def test_persists_a_discard_send_and_delivers_it_once_the_shard_lock_is_acquired():
    """persists a discard send and delivers it once the shard lock is acquired"""
    storage_state = FailoverState(lock_held_elsewhere=True)

    @fx.gen
    def body():
        entity_state = yield from EntityState()
        service = yield from sharding.Sharding()
        shard_id = service.get_shard_id(EntityId("1"), "default")
        while not storage_state.acquire_calls:
            yield from testing.adjust("10 millis")
        client = (yield from TestEntity.client())("1")
        send = yield from client.get_user.discard({"id": 1}).fork(start_immediately=True)
        yield from testing.adjust("100 millis")
        assert send.poll_unsafe() == _VOID, "a discard send returns once persisted"
        assert entity_state.envelopes.size_unsafe() == 0, "delivery must wait for the shard lock"

        storage_state.lock_held_elsewhere = False
        while not service.has_shard_id(shard_id):
            yield from testing.adjust("10 millis")
        yield from service.poll_storage
        yield from testing.adjust("10 millis")
        assert entity_state.envelopes.size_unsafe() == 1

    yield from fx.scoped(body).pipe(fx.provide(_pending_lock_sharding(storage_state)))
