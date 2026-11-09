"""Ports of the "Sharding defect recovery" cases of Effect's
``test/cluster/Sharding.test.ts``, and of the mailbox-size cases that drive
an ``EntityManager`` directly over Effect's ``BlockedRebuildSharding``. Each
test's docstring is the Effect test title. The "replays a durable caller
parked on a queued request when its target closes" cases of this group are
in ``test_sharding_restart``.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Never, TypedDict

import pyfect as fx
from pyfect import exit as Exit
from pyfect import metric, schedule, testing
from pyfect import schema as S
from pyfect.cluster import _entity_manager as entity_manager
from pyfect.cluster import _entity_reaper, cluster_metrics, sharding, snowflake
from pyfect.cluster.cluster_schema import Persisted
from pyfect.cluster.entity import Entity, EntityHandlers, Request
from pyfect.cluster.entity_address import EntityAddress
from pyfect.cluster.entity_id import EntityId
from pyfect.cluster.entity_type import EntityType
from pyfect.cluster.envelope import make_request
from pyfect.cluster.message import IncomingRequestLocal
from pyfect.cluster.message_storage import NOOP, MemoryDriver
from pyfect.cluster.runner_address import RunnerAddress
from pyfect.cluster.shard_id import ShardId
from pyfect.cluster.shard_id import make as shard
from pyfect.context import Context
from pyfect.deferred import Deferred
from pyfect.duration import Seconds
from pyfect.layer import Layer
from pyfect.rpc import make as make_rpc
from pyfect.scope import CloseableScope, Scope

from ._sharding_fixtures import make_config, patched, series, unregistered


class IdPayload(TypedDict):
    id: str


class DefectRecoveryEntity(Entity, type="DefectRecovery"):
    run = make_rpc("run", payload=S.Struct(IdPayload), success=S.String).annotate(Persisted, True)


def _defect_recovery_sharding(entity_layer: Layer[Never, Never, Any]) -> Layer[Any]:
    return entity_layer.pipe(fx.layer.provide_merge(unregistered()))


defect_retry_policy = schedule.spaced("1 millis")
"""Restarts after 1ms, so tests only advance the clock as far as a restart
needs instead of waking every background Sharding loop along the way."""

blocked_rebuild_sharding = (
    fx.layer.merge(_entity_reaper.layer, snowflake.layer_generator)
    .pipe(lambda layer: fx.layer.merge(layer, make_config(entity_termination_timeout=Seconds(1))))
    .pipe(fx.layer.provide_merge(unregistered()))
)
"""The directly driven ``EntityManager`` waits up to 1000ms for its entities
to end."""


def _advance_until[A, E, R](effect: fx.Effect[A, E, R]) -> fx.Effect[A, E, R]:
    """Steps the test clock until ``effect`` completes."""
    return effect.race_first(testing.adjust("1 millis").forever())


class _Generations:
    """Counts handler builds. Building the ``blocked`` generation waits until
    ``acquired`` completes, holding the entity in replacement acquisition."""

    def __init__(self, blocked: int | None = None) -> None:
        self.count = 0
        self.blocked = blocked
        self.acquiring = Deferred[None, Never]()
        self.acquired = Deferred[None, Never]()

    @property
    def next(self) -> fx.Effect[int]:
        @fx.gen
        def run():
            self.count += 1
            generation = self.count
            if generation == self.blocked:
                yield from self.acquiring.succeed(None)
                yield from self.acquired.wait()
            return generation

        return run


def _owns_every_shard(_: ShardId) -> bool:
    return True


class _AdmitAll:
    def admit_unsafe(self) -> bool:
        return True

    def release_unsafe(self) -> None:
        pass


def _manager_options(
    service: sharding.ShardingService, **changes: Any
) -> entity_manager.ManagerOptions:
    return entity_manager.ManagerOptions(
        sharding=service,
        storage=NOOP,
        runner_address=RunnerAddress(host="localhost", port=1234),
        residency=_AdmitAll(),
        abandon_undelivered=lambda _address, _keep: fx.void,
        **changes,
    )


def _local_run(
    service: sharding.ShardingService, address: EntityAddress
) -> fx.Effect[IncomingRequestLocal]:
    @fx.gen
    def make():
        return IncomingRequestLocal(
            envelope=make_request(
                request_id=(yield from service.get_snowflake),
                address=address,
                tag="run",
                payload=None,
            ),
            last_sent_reply=None,
            annotations=Context.empty(),
            respond=lambda _: fx.void,
        )

    return make


def _address(entity: type[Entity], shard_id: ShardId, entity_id: str) -> EntityAddress:
    return EntityAddress(
        shard_id=shard_id, entity_type=EntityType(entity.type), entity_id=EntityId(entity_id)
    )


class _BlockedRebuild:
    """An ``EntityManager`` driven directly: its first request defects, and
    the replacement handlers stay in acquisition until ``acquired``."""

    def __init__(
        self,
        manager: entity_manager.EntityManager,
        shard_id: ShardId,
        send: fx.Effect[None, Any],
        attempts: list[int],
        acquired: Deferred[None, Never],
    ) -> None:
        self.manager = manager
        self.shard_id = shard_id
        self.send = send
        self.attempts = attempts
        self.acquired = acquired


class DefectRecoveryShutdownEntity(Entity, type="DefectRecoveryShutdown"):
    run = make_rpc("run")


def _start_blocked_rebuild(entity_id: str) -> fx.Effect[_BlockedRebuild, Any, Any]:
    @fx.gen
    def start():
        generations = _Generations(2)
        attempts = [0]
        e = DefectRecoveryShutdownEntity

        def run(_: Request[None]) -> fx.Effect[None]:
            def defect() -> fx.Effect[None]:
                attempts[0] += 1
                return fx.die(RuntimeError("restart"))

            return fx.suspend(defect)

        service = yield from sharding.Sharding()
        manager = yield from entity_manager.make(
            e,
            generations.next.as_(e.handlers().handle(e.run)(run)),
            _manager_options(
                service, max_idle_time=None, defect_retry_policy=schedule.spaced("1 millis")
            ),
        )
        id_ = EntityId(entity_id)
        shard_id = service.get_shard_id(id_, "default")
        address = _address(e, shard_id, entity_id)
        send = _local_run(service, address).flat_map(manager.send_local)
        yield from testing.adjust("1 millis")
        yield from send
        yield from testing.adjust("10 millis")
        yield from generations.acquiring.wait()
        return _BlockedRebuild(manager, shard_id, send, attempts, generations.acquired)

    return start


@testing.effect
def test_restarts_again_when_a_replayed_request_defects_synchronously():
    """restarts again when a replayed request defects synchronously"""
    e = DefectRecoveryEntity
    generations = _Generations()
    attempts = [0]

    def run(request: Request[IdPayload]) -> fx.Effect[str]:
        def step() -> fx.Effect[str]:
            attempts[0] += 1
            if attempts[0] <= 3:
                return fx.die(RuntimeError("repeated defect"))
            return fx.succeed(request.payload["id"])

        return fx.suspend(step)

    entity_layer: Layer[Never, Never, Any] = e.to_layer_effect(
        generations.next.as_(e.handlers().handle(e.run)(run)),
        defect_retry_policy=defect_retry_policy,
    )

    @fx.gen
    def body():
        client = (yield from e.client())("repeated")
        work = yield from client.run({"id": "request"}).fork()
        assert (yield from _advance_until(work.join())) == "request"
        assert attempts[0] == 4
        assert generations.count == 4

    yield from body.pipe(fx.provide(_defect_recovery_sharding(entity_layer)))


@testing.effect
def test_replays_unfinished_requests_before_arrivals_during_acquisition():
    """replays unfinished requests before arrivals during acquisition"""
    e = DefectRecoveryEntity
    generations = _Generations(2)
    fail = Deferred[None, Never]()
    both_started = Deferred[None, Never]()
    started = [0]
    calls: list[tuple[int, str]] = []
    completed: list[str] = []
    third_request_id = Deferred[Any, Never]()

    def handlers(generation: int) -> EntityHandlers[Any, Never]:
        @fx.fn
        def run(request: Request[IdPayload]):
            id_ = request.payload["id"]
            if id_ == "third":
                yield from third_request_id.succeed(request.request_id)
            calls.append((generation, id_))
            if generation == 1:
                started[0] += 1
                if started[0] == 2:
                    yield from both_started.succeed(None)
                yield from fail.wait()
                return (yield from fx.die(RuntimeError("initial defect")))
            if generation == 2 and id_ == "first":
                return (yield from fx.die(RuntimeError("replay defect")))
            completed.append(id_)
            return id_

        return e.handlers().handle(e.run)(run)

    entity_layer: Layer[Never, Never, Any] = e.to_layer_effect(
        generations.next.map(handlers),
        concurrency="unbounded",
        defect_retry_policy=defect_retry_policy,
    )

    @fx.gen
    def body():
        client = (yield from e.client())("arrivals")
        first = yield from client.run({"id": "first"}).fork()
        second = yield from client.run({"id": "second"}).fork()
        yield from both_started.wait()
        yield from fail.succeed(None)
        yield from _advance_until(generations.acquiring.wait())
        third = yield from client.run({"id": "third"}).fork()
        yield from testing.adjust("1 millis")
        yield from generations.acquired.succeed(None)
        yield from _advance_until(fx.for_each([first, second, third], lambda f: f.join()))
        assert (yield from first.join()) == "first"
        assert (yield from second.join()) == "second"
        assert (yield from third.join()) == "third"
        assert next(call for call in calls if call[0] == 2) == (2, "first")
        # A request still waiting for its first dispatch is not replayed as well
        assert len([call for call in calls if call[1] == "third"]) == 1
        request_id = yield from third_request_id.wait()
        driver = yield from MemoryDriver()
        replies = yield from driver.encoded.replies_for([str(request_id)]).or_die()
        exits: list[Any] = [reply.get("exit") for reply in replies if reply["_tag"] == "WithExit"]
        assert {"_tag": "Success", "value": "third"} in exits
        assert sorted(completed) == ["first", "second", "third"]
        assert generations.count == 3

    yield from body.pipe(fx.provide(_defect_recovery_sharding(entity_layer)))


@testing.effect
def test_finishes_shutdown_when_replacement_acquisition_completes():
    """finishes shutdown when replacement acquisition completes"""

    @fx.gen
    def body():
        blocked = yield from _start_blocked_rebuild("shutdown")
        shutdown = yield from blocked.manager.interrupt_shard(blocked.shard_id).fork()
        yield from testing.adjust("1 millis")
        assert (yield from blocked.manager.active_entity_count) == 0
        yield from blocked.acquired.succeed(None)
        yield from testing.adjust("1 millis")
        completed = shutdown.poll_unsafe()
        # Let a broken implementation's termination timeout finish before asserting.
        yield from testing.adjust("1 second")
        assert completed == Exit.succeed(None)
        assert blocked.attempts[0] == 1, "shutdown must not replay application requests"

    yield from fx.scoped(body).pipe(fx.provide(blocked_rebuild_sharding))


@testing.effect
def test_interrupts_a_queued_arrival_when_shutdown_starts_during_replacement_acquisition():
    """interrupts a queued arrival when shutdown starts during replacement acquisition"""

    @fx.gen
    def body():
        blocked = yield from _start_blocked_rebuild("shutdown-queued")
        # Arrives while the replacement handlers are still being built, so it
        # queues behind the replay of unfinished requests.
        queued = yield from blocked.send.fork()
        yield from testing.adjust("1 millis")
        assert queued.poll_unsafe() is None
        yield from blocked.manager.interrupt_shard(blocked.shard_id).fork()
        yield from testing.adjust("1 millis")
        assert (yield from blocked.manager.active_entity_count) == 0
        # The queued request must be refused as soon as the activation is
        # retired, without waiting for the replacement handlers.
        exit = queued.poll_unsafe()
        assert exit is not None, "queued arrival must not wait for replacement acquisition"
        assert isinstance(exit, Exit.Failure) and exit.cause.has_interrupts, (
            "queued arrival must be interrupted"
        )
        yield from blocked.acquired.succeed(None)

    yield from fx.scoped(body).pipe(fx.provide(blocked_rebuild_sharding))


class DuplicateEntityIdEntity(Entity, type="DuplicateEntityId"):
    run = make_rpc("run")


@testing.effect
def test_interrupts_an_entity_whose_id_is_also_active_on_a_shard_that_was_interrupted_first():
    """interrupts an entity whose id is also active on a shard that was interrupted first"""
    e = DuplicateEntityIdEntity
    stopped = [0]

    def stop(_: Exit.Exit[Any, Any]) -> fx.Effect[None]:
        def run() -> None:
            stopped[0] += 1

        return fx.sync(run)

    @fx.gen
    def body():
        service = yield from sharding.Sharding()
        manager = yield from entity_manager.make(
            e,
            fx.add_finalizer(stop).as_(e.handlers().handle(e.run)(lambda _: fx.void)),
            # both shards belong to this runner
            _manager_options(patched(service, has_shard_id=_owns_every_shard), max_idle_time=None),
        )

        def activate(shard_id: ShardId) -> fx.Effect[None, Any]:
            return _local_run(service, _address(e, shard_id, "duplicate")).flat_map(
                manager.send_local
            )

        default_shard = shard("default", 1)
        workflow_shard = shard("workflow", 1)
        yield from testing.adjust("1 millis")
        yield from activate(default_shard)
        yield from activate(workflow_shard)
        yield from testing.adjust("1 millis")

        interrupt_workflow = yield from manager.interrupt_shard(workflow_shard).fork()
        yield from testing.adjust("1 second")
        assert interrupt_workflow.poll_unsafe() == Exit.succeed(None)
        assert stopped[0] == 1
        interrupt_default = yield from manager.interrupt_shard(default_shard).fork()
        yield from testing.adjust("1 second")
        assert interrupt_default.poll_unsafe() == Exit.succeed(None)
        assert stopped[0] == 2

    yield from fx.scoped(body).pipe(fx.provide(blocked_rebuild_sharding))


# --- mailbox sizes over a directly driven EntityManager ----------------------------------


def _mailbox_max_manager(
    type_: str, handler: fx.Effect[None]
) -> fx.Effect[Callable[[ShardId], fx.Effect[None, Any]], Never, Any]:
    """Owns every shard, so one entity id can be resident on several shards
    at once. Gives a function sending a ``run`` request to entity "1" on a
    given shard."""
    entity: Any = type(type_, (Entity,), {"run": make_rpc("run")}, type=type_)

    @fx.gen
    def make():
        service = yield from sharding.Sharding()
        manager = yield from entity_manager.make(
            entity,
            fx.succeed(entity.handlers().handle(entity.run)(_constant(handler))),
            _manager_options(patched(service, has_shard_id=_owns_every_shard), max_idle_time=None),
        )

        def send(shard_id: ShardId) -> fx.Effect[None, Any]:
            return _local_run(service, _address(entity, shard_id, "1")).flat_map(manager.send_local)

        return send

    return make


def _constant(handler: fx.Effect[None]) -> Callable[[Request[None]], fx.Effect[None]]:
    return lambda _: handler


def _mailbox_size_max(registry: dict[Any, Any]) -> list[tuple[Any, Any]]:
    return [
        (attributes, state.value)
        for attributes, state in series(registry, cluster_metrics.entity_mailbox_size_max.id)
    ]


@testing.effect
def test_reports_the_largest_mailbox_size_across_entities_sharing_an_id_on_different_shards():
    """reports the largest mailbox size across entities sharing an id on different shards"""
    registry: dict[Any, Any] = {}

    @fx.gen
    def body():
        release = yield from Deferred[None, Never].make()
        send = yield from _mailbox_max_manager("MailboxMaxDuplicateId", release.wait())
        yield from testing.adjust("1 millis")
        yield from send(shard("default", 1))
        yield from send(shard("default", 1))
        yield from send(shard("workflow", 1))
        yield from testing.adjust("1 millis")

        # Let the entities drain when the test scope closes, even if the
        # assertion fails
        def check() -> None:
            assert _mailbox_size_max(registry) == [({"type": "MailboxMaxDuplicateId"}, 2)]

        yield from fx.sync(check).ensuring(release.succeed(None))

    yield from (
        fx.scoped(body)
        .pipe(fx.provide(blocked_rebuild_sharding))
        .pipe(fx.provide_service(metric.MetricRegistry, registry))
    )


@testing.effect
def test_keeps_reporting_the_largest_mailbox_size_until_entities_drain_on_shutdown():
    """keeps reporting the largest mailbox size until entities drain on shutdown"""
    registry: dict[Any, Any] = {}

    @fx.gen
    def body():
        release = yield from Deferred[None, Never].make()
        scope = CloseableScope()
        send = yield from _mailbox_max_manager("MailboxMaxDrain", release.wait()).pipe(
            fx.provide_service(Scope, scope)
        )
        yield from testing.adjust("1 millis")
        assert _mailbox_size_max(registry) == [({"type": "MailboxMaxDrain"}, 0)]

        yield from send(shard("default", 1))
        yield from testing.adjust("1 millis")
        closing = yield from scope.close(Exit.succeed(None)).fork()
        # Stay within the termination timeout, so the entity is still draining
        yield from testing.adjust("1 millis")

        def check() -> None:
            assert _mailbox_size_max(registry) == [({"type": "MailboxMaxDrain"}, 1)]

        yield from fx.sync(check).ensuring(release.succeed(None))
        yield from closing.join()
        assert _mailbox_size_max(registry) == []

    yield from (
        fx.scoped(body)
        .pipe(fx.provide(blocked_rebuild_sharding))
        .pipe(fx.provide_service(metric.MetricRegistry, registry))
    )
