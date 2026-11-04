"""Ports of platform-node's ``test/cluster-integration/Entity.test.ts`` on
the cluster harness (``_cluster_harness``), on SQLite and on the throwaway
PostgreSQL server where Effect uses PostgreSQL and MySQL. Each test's
docstring is the Effect test title, without its backend prefix.

Adapted, with the reason:
- "retains frozen advisory locks until the session closes" runs on
  PostgreSQL only: SQLite has no advisory locks (its locks are rows, which
  "transfers frozen row locks after expiry" covers).
- "assigns annotated entities only to runners in their shard group", "runs
  one singleton and migrates it after owner death" and "keeps
  EntityResource alive during movement and releases it explicitly" run on
  both backends (Effect runs them on PostgreSQL only).
- "transfers frozen row locks after expiry" waits for the client to read
  the runners again before it sends: the new owner can take the lock up to
  a ``refresh_assignments_interval`` before the client stops routing to
  the frozen runner, which still serves requests (its sockets are open and
  its lock refresh waits), so Effect's test races there too.
"""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass, field
from typing import Any, TypedDict

import pytest

import pyfect as fx
from pyfect import exit as Exit
from pyfect import schema as S
from pyfect import testing
from pyfect.cluster import entity_resource, singleton
from pyfect.cluster.cluster_error import MailboxFull
from pyfect.cluster.cluster_schema import Persisted, ShardGroup
from pyfect.cluster.entity import CurrentAddress, CurrentRunnerAddress, Entity, Request
from pyfect.cluster.entity_id import EntityId
from pyfect.cluster.runner_address import RunnerAddress
from pyfect.context import Context
from pyfect.latch import Latch
from pyfect.layer import Layer
from pyfect.rpc import fork
from pyfect.rpc import make as make_rpc
from pyfect.scope import Scope, acquire_release

from ._cluster_harness import Cluster, ClusterDatabase, ClusterRunner, MessageCounts, make

type Body = Generator[fx.Effect[Any, Any, Any], Any]


def address_string(address: RunnerAddress) -> str:
    return f"{address.host}:{address.port}"


def now_millis() -> fx.Effect[float]:
    return fx.clock.now().map(lambda seconds: seconds * 1000)


class EntityRequest(S.Class, identifier="ClusterEntityRequest"):
    id: str
    sequence: float

    def primary_key(self) -> str:
        return self.id


class StateReplyFields(TypedDict):
    generation: int
    runner: str
    value: int


StateReply = S.Struct(StateReplyFields)


class StateEntity(
    Entity, type="ClusterIntegrationState", rpc_annotations=Context.make(Persisted, True)
):
    increment = make_rpc("Increment", payload=EntityRequest, success=StateReply)
    ordered = make_rpc("Ordered", payload=EntityRequest, success=S.Number)


@dataclass
class OrderState:
    gate: Latch = field(default_factory=lambda: Latch(True))
    entered: Latch = field(default_factory=Latch)
    order: list[float] = field(default_factory=lambda: [])


order_state = OrderState()
generations: dict[str, int] = {}


def reset_order() -> None:
    vars(order_state).update(vars(OrderState(gate=Latch())))


@fx.gen
def _state_handlers():
    address = yield from CurrentAddress()
    runner = yield from CurrentRunnerAddress()
    entity_id = str(address.entity_id)
    generation = generations.get(entity_id, 0) + 1
    generations[entity_id] = generation
    value = [0]

    def increment(_: Request[EntityRequest]) -> fx.Effect[StateReplyFields]:
        def run() -> StateReplyFields:
            value[0] += 1
            return {"generation": generation, "runner": address_string(runner), "value": value[0]}

        return fx.sync(run)

    def ordered(request: Request[EntityRequest]) -> fx.Effect[float]:
        @fx.gen
        def run():
            state = order_state
            state.order.append(request.payload.sequence)
            if request.payload.sequence == 1:
                state.entered.open_unsafe()
                yield from state.gate.wait()
            return request.payload.sequence

        return run

    return (
        StateEntity.handlers()
        .handle(StateEntity.increment)(increment)
        .handle(StateEntity.ordered)(ordered)
    )


state_entity_layer = StateEntity.to_layer_effect(_state_handlers, max_idle_time=1)


class MailboxEntity(Entity, type="ClusterIntegrationMailbox"):
    hold = make_rpc("Hold", payload=EntityRequest, success=S.Number)


@dataclass
class MailboxState:
    gate: Latch = field(default_factory=lambda: Latch(True))
    entered: Latch = field(default_factory=Latch)


mailbox_state = MailboxState()


def _hold(request: Request[EntityRequest]) -> fx.Effect[float]:
    state = mailbox_state
    return (
        fx.sync(state.entered.open_unsafe).and_then(state.gate.wait()).as_(request.payload.sequence)
    )


mailbox_entity_layer = MailboxEntity.to_layer(
    MailboxEntity.handlers().handle(MailboxEntity.hold)(_hold), mailbox_capacity=1
)


class GroupEntity(
    Entity,
    type="ClusterIntegrationSpecialGroup",
    annotations=Context.make(ShardGroup, lambda _: "special"),
):
    runner = make_rpc("Runner", success=S.String)


@fx.gen
def _group_handlers():
    runner = yield from CurrentRunnerAddress()
    return GroupEntity.handlers().handle(GroupEntity.runner)(
        lambda _: fx.succeed(address_string(runner))
    )


group_entity_layer = GroupEntity.to_layer_effect(_group_handlers)


class ResourceEntity(Entity, type="ClusterIntegrationResource"):
    get = make_rpc("Get", success=S.Number)
    close = make_rpc("Close")


resource_state = {"acquired": 0, "released": 0}


def _acquire_resource() -> fx.Effect[int, Any, Any]:
    @fx.gen
    def acquire():
        close_scope = yield from entity_resource.CloseScope()

        def take() -> int:
            resource_state["acquired"] += 1
            return resource_state["acquired"]

        def release(_value: int, _exit: Any) -> fx.Effect[None]:
            def run() -> None:
                resource_state["released"] += 1

            return fx.sync(run)

        return (
            yield from acquire_release(fx.sync(take), release).pipe(
                fx.provide_service(Scope, close_scope)
            )
        )

    return acquire


@fx.gen
def _resource_handlers():
    resource = yield from entity_resource.make(_acquire_resource())
    return (
        ResourceEntity.handlers()
        .handle(ResourceEntity.close)(lambda _: resource.close)
        .handle(ResourceEntity.get)(lambda _: fx.scoped(resource.get))
    )


resource_entity_layer = ResourceEntity.to_layer_effect(_resource_handlers)


class RegistrationEntity(Entity, type="ClusterIntegrationRegistration"):
    runner = make_rpc("Runner", success=S.String).annotate(Persisted, True)


@fx.gen
def _registration_handlers():
    runner = yield from CurrentRunnerAddress()
    return RegistrationEntity.handlers().handle(RegistrationEntity.runner)(
        lambda _: fx.succeed(address_string(runner))
    )


registration_entity_layer = RegistrationEntity.to_layer_effect(_registration_handlers)

standard_entities: Layer[Any, Any, Any] = fx.layer.merge(
    state_entity_layer, mailbox_entity_layer, resource_entity_layer
)


def find_ids_by_runner(
    cluster: Cluster, runners: list[ClusterRunner]
) -> fx.Effect[dict[int, tuple[ClusterRunner, str]]]:
    """An entity id of ``StateEntity`` owned by each of ``runners``, by
    runner index."""

    @fx.gen
    def find():
        found: dict[int, tuple[ClusterRunner, str]] = {}
        for index in range(2000):
            if len(found) == len(runners):
                break
            id = f"entity-{index}"
            owner = yield from cluster.owner_of_entity(StateEntity, id)
            if owner is not None and owner in runners and owner.index not in found:
                found[owner.index] = (owner, id)
        assert len(found) == len(runners)
        return found

    return find


def run(body: Any) -> fx.Effect[None, Any]:
    return fx.scoped(fx.gen(body))


class Receiver(Entity, type="ClusterIntegrationShutdownReplyReceiver"):
    ping = make_rpc("Ping").annotate(Persisted, True)


class Sender(Entity, type="ClusterIntegrationShutdownReplySender"):
    arm = make_rpc("Arm").annotate(Persisted, False)


@testing.live(timeout=60)
def test_interrupts_an_unroutable_reply_during_runner_shutdown(cluster_db: ClusterDatabase):
    """interrupts an unroutable reply during runner shutdown without hanging teardown"""

    def body() -> Body:
        finalizer_entered, send_reply = Latch(), Latch()
        request_exit: list[Exit.Exit[Any, Any]] = []

        @fx.gen
        def sender_handlers():
            receiver = yield from Receiver.client()
            scope = yield from Scope()

            @fx.gen
            def finalize():
                finalizer_entered.open_unsafe()
                yield from send_reply.wait()
                request_exit.append((yield from receiver("unroutable").ping().exit()))

            yield from scope.add_finalizer(lambda _: finalize.uninterruptible())
            return Sender.handlers().handle(Sender.arm)(lambda _: fx.void)

        entities = fx.layer.merge(
            Receiver.to_layer(Receiver.handlers().handle(Receiver.ping)(lambda _: fx.void)),
            Sender.to_layer_effect(sender_handlers),
        )
        cluster = yield from make(cluster_db, entities=entities)
        [runner] = yield from cluster.start(1, assigned_shard_groups=("default",))
        yield from cluster.wait_for_stable_assignments()
        sender = yield from cluster.get_client(Sender)
        yield from sender("sender").arm()

        stopping = yield from cluster.stop(runner).fork(start_immediately=True)
        yield from cluster.wait_until(
            "The shutdown reply finalizer did not start", finalizer_entered.wait().as_(True)
        )
        send_reply.open_unsafe()
        yield from stopping.join()

        # The request is durable, so the caller is interrupted rather than
        # failed: the send is not an error, this runner just cannot observe
        # the reply.
        assert len(request_exit) == 1
        exit = request_exit[0]
        assert isinstance(exit, Exit.Failure)
        assert exit.cause.has_interrupts_only

    yield from run(body)


def _discard_entities(persisted: bool) -> tuple[Layer[Any, Any, Any], Latch, Latch, list[Any]]:
    finalizer_entered, send_discard = Latch(), Latch()
    discard_exit: list[Exit.Exit[Any, Any]] = []

    class DiscardReceiver(Entity, type="ClusterIntegrationShutdownDiscardReceiver"):
        ping = make_rpc("Ping").annotate(Persisted, persisted)

    class DiscardSender(Entity, type="ClusterIntegrationShutdownDiscardSender"):
        arm = make_rpc("Arm").annotate(Persisted, False)

    @fx.gen
    def sender_handlers():
        receiver = yield from DiscardReceiver.client()
        scope = yield from Scope()

        @fx.gen
        def finalize():
            finalizer_entered.open_unsafe()
            yield from send_discard.wait()
            discard_exit.append((yield from receiver("unroutable").ping.discard().exit()))

        yield from scope.add_finalizer(lambda _: finalize.uninterruptible())
        return DiscardSender.handlers().handle(DiscardSender.arm)(lambda _: fx.void)

    entities = fx.layer.merge(
        DiscardReceiver.to_layer(
            DiscardReceiver.handlers().handle(DiscardReceiver.ping)(lambda _: fx.void)
        ),
        DiscardSender.to_layer_effect(sender_handlers),
    )
    return entities, finalizer_entered, send_discard, [discard_exit, DiscardSender]


@pytest.mark.parametrize(
    "preemptive_shutdown", [False, True], ids=["preemptive=false", "preemptive=true"]
)
@pytest.mark.parametrize("persisted", [False, True], ids=["persisted=false", "persisted=true"])
@testing.live(timeout=60)
def test_sends_an_outgoing_discard_from_a_shutdown_finalizer_without_deadlocking(
    cluster_db: ClusterDatabase, persisted: bool, preemptive_shutdown: bool
):
    """sends an outgoing discard from a shutdown finalizer without deadlocking (persisted=${persisted}, preemptive=${preemptiveShutdown})"""  # noqa: E501

    def body() -> Body:
        entities, finalizer_entered, send_discard, extra = _discard_entities(persisted)
        discard_exit, sender_entity = extra
        cluster = yield from make(
            cluster_db, entities=entities, config={"preemptive_shutdown": preemptive_shutdown}
        )
        [runner] = yield from cluster.start(1, assigned_shard_groups=("default",))
        yield from cluster.wait_for_stable_assignments()
        sender = yield from cluster.get_client(sender_entity)
        yield from sender("sender").arm()

        stopping = yield from cluster.stop(runner).fork(start_immediately=True)
        yield from cluster.wait_until(
            "The shutdown discard finalizer did not start", finalizer_entered.wait().as_(True)
        )
        send_discard.open_unsafe()
        yield from stopping.join()

        assert len(discard_exit) == 1
        assert isinstance(discard_exit[0], Exit.Success)

    yield from run(body)


class ReplayEntity(Entity, type="ClusterIntegrationFatalReplay"):
    hold = make_rpc("Hold").annotate(Persisted, True)
    crash = make_rpc("Crash", success=S.Number).annotate(Persisted, True)


@testing.live(timeout=60)
def test_rebuilds_an_entity_after_a_fatal_defect_and_replays_in_flight_requests(
    cluster_db: ClusterDatabase,
):
    """rebuilds an entity after a fatal defect and replays in-flight requests"""

    def body() -> Body:
        first_attempt_entered, replay_entered = Latch(), Latch()
        replay_gate, replay_completed = Latch(), Latch()
        counts = {"builds": 0, "replay_attempts": 0}

        def build() -> Any:
            counts["builds"] += 1
            generation = counts["builds"]

            @fx.gen
            def hold_body():
                counts["replay_attempts"] += 1
                if counts["replay_attempts"] == 1:
                    first_attempt_entered.open_unsafe()
                else:
                    replay_entered.open_unsafe()
                yield from replay_gate.wait()
                replay_completed.open_unsafe()

            return (
                ReplayEntity.handlers()
                .handle(ReplayEntity.crash)(
                    lambda _: (
                        fx.die(RuntimeError("fatal replay defect"))
                        if generation == 1
                        else fx.succeed(generation)
                    )
                )
                .handle(ReplayEntity.hold)(lambda _: fork(hold_body))
            )

        entities: Layer[Any, Any, Any] = ReplayEntity.to_layer_effect(fx.sync(build))
        cluster = yield from make(cluster_db, entities=entities)
        yield from cluster.start(1)
        yield from cluster.wait_for_stable_assignments()
        client = yield from cluster.get_client(ReplayEntity)

        held = yield from client("replay").hold().fork(start_immediately=True)
        yield from cluster.wait_until(
            "The in-flight request did not start before the defect",
            first_attempt_entered.wait().as_(True),
        )
        generation = yield from client("replay").crash()
        yield from cluster.wait_until(
            "The in-flight request was not replayed after the defect",
            replay_entered.wait().as_(True),
        )
        replay_gate.open_unsafe()
        yield from cluster.wait_until(
            "The replayed request did not complete", replay_completed.wait().as_(True)
        )
        yield from held.join()

        assert generation == 2
        assert counts["builds"] == 2
        assert counts["replay_attempts"] == 2

    yield from run(body)


class StuckEntity(Entity, type="ClusterIntegrationStuckReassignment"):
    run_ = make_rpc("Run", success=S.Number).annotate(Persisted, False)


# Effect v4.0.6 fails this test too (its cluster-integration Entity.test.ts, run
# under Node on pg and mysql: the same error). The port passed only while the RPC
# server registered a handler after its first step, which ended drains at once.
_FAILS_IN_EFFECT = pytest.mark.xfail(strict=True, reason="fails the same way in Effect v4.0.6")


@_FAILS_IN_EFFECT
@testing.live(timeout=60)
def test_force_interrupts_a_stuck_handler_after_the_graceful_termination_timeout(
    cluster_db: ClusterDatabase,
):
    """force-interrupts a stuck handler after the graceful termination timeout"""

    def body() -> Body:
        handler_entered, handler_interrupted = Latch(), Latch()
        state = {"attempts": 0, "block": True}

        def run_handler(_: Request[None]) -> fx.Effect[int]:
            def start() -> fx.Effect[int]:
                state["attempts"] += 1
                attempt = state["attempts"]
                if not state["block"]:
                    return fx.succeed(attempt)
                handler_entered.open_unsafe()
                return fx.never.on_interrupt(handler_interrupted.open().as_void())

            return fx.suspend(start)

        entities = StuckEntity.to_layer(
            StuckEntity.handlers().handle(StuckEntity.run_)(run_handler)
        )
        cluster = yield from make(
            cluster_db,
            entities=entities,
            config={
                "entity_termination_timeout": fx.duration.Seconds(0.1),
                "preemptive_shutdown": False,
            },
        )
        yield from cluster.start(2)
        yield from cluster.wait_for_stable_assignments()
        owner = yield from cluster.owner_of_entity(StuckEntity, "stuck")
        assert owner is not None
        client = yield from cluster.get_client(StuckEntity)
        request = yield from client("stuck").run_().fork(start_immediately=True)
        yield from cluster.wait_until(
            "The stuck handler did not start", handler_entered.wait().as_(True)
        )
        state["block"] = False

        stopping = yield from cluster.stop(owner).fork(start_immediately=True)
        yield from cluster.wait_until(
            "The stuck handler was not force-interrupted after the graceful timeout",
            handler_interrupted.wait().as_(True),
        )
        yield from stopping.join()
        yield from cluster.wait_until(
            "The stopped runner did not reassign the stuck entity",
            cluster.owner_of_entity(StuckEntity, "stuck").map(
                lambda next: next is not None and next is not owner
            ),
        )

        assert (yield from request.join()) == 2
        assert state["attempts"] == 2

    yield from run(body)


@testing.live(timeout=60)
def test_holds_persisted_messages_until_a_slow_entity_layer_registers(
    cluster_db: ClusterDatabase,
):
    """holds persisted messages until a slow entity layer registers"""
    backend = cluster_db.backend

    def body() -> Body:
        registration_gate = Latch()
        delayed_entities = registration_entity_layer.pipe(
            fx.layer.provide(fx.layer.effect_discard(registration_gate.wait()))
        )
        cluster = yield from make(
            cluster_db,
            entities=registration_entity_layer,
            config={
                "entity_message_poll_interval": fx.duration.Seconds(0.1),
                "entity_registration_timeout": fx.duration.Seconds(1),
                "send_retry_interval": fx.duration.Seconds(0.1),
                "shards_per_group": 4,
            },
        )
        yield from cluster.start(1, assigned_shard_groups=())
        starting = yield from cluster.start(1, entities=delayed_entities).fork(
            start_immediately=True
        )
        client = yield from cluster.get_client(RegistrationEntity)
        entity_id = f"{backend}-slow-registration"
        request = yield from client(entity_id).runner().fork(start_immediately=True)

        yield from cluster.wait_until(
            "The slow-registration request was not persisted",
            cluster.unprocessed_message_count.map(lambda count: count == 1),
        )
        deadline = (yield from now_millis()) + 1500
        yield from cluster.wait_until(
            "The slow-registration hold window did not elapse",
            now_millis().map(lambda now: now >= deadline),
            2,
        )
        assert (yield from cluster.message_counts()) == MessageCounts(0, 0, 1)

        registration_gate.open_unsafe()
        [runner] = yield from starting.join()
        yield from cluster.wait_for_entity_owner(RegistrationEntity, entity_id, runner)
        assert (yield from request.join()) == address_string(runner.address)
        assert (yield from cluster.message_counts()) == MessageCounts(0, 1, 0)

    yield from run(body)


@testing.live(timeout=60)
def test_defects_a_durable_request_whose_owner_never_registers_the_entity(
    cluster_db: ClusterDatabase,
):
    """defects a durable request whose owner never registers the entity"""
    backend = cluster_db.backend

    def body() -> Body:
        cluster = yield from make(
            cluster_db,
            entities=registration_entity_layer,
            config={
                "entity_message_poll_interval": fx.duration.Seconds(0.1),
                "entity_registration_timeout": fx.duration.Seconds(0.5),
                "send_retry_interval": fx.duration.Seconds(0.1),
                "shards_per_group": 4,
            },
        )
        yield from cluster.start(1, assigned_shard_groups=())
        [runner] = yield from cluster.start(1, entities=fx.layer.empty)
        entity_id = f"{backend}-missing-registration"
        yield from cluster.wait_for_entity_owner(RegistrationEntity, entity_id, runner)
        client = yield from cluster.get_client(RegistrationEntity)
        request = yield from client(entity_id).runner().fork(start_immediately=True)

        yield from cluster.wait_until(
            "The missing entity registration did not produce a stored defect",
            cluster.failed_message_count.map(lambda count: count == 1),
        )
        exit = yield from request.await_exit()
        assert isinstance(exit, Exit.Failure)
        assert f"Entity type '{RegistrationEntity.type}' not registered" in exit.cause.pretty()
        assert (yield from cluster.message_counts()) == MessageCounts(1, 0, 0)

    yield from run(body)


@testing.live(timeout=60)
def test_routes_by_entity_id_isolates_state_and_preserves_mailbox_order(
    cluster_db: ClusterDatabase,
):
    """routes by entity id, isolates state, and preserves mailbox order"""
    backend = cluster_db.backend

    def body() -> Body:
        generations.clear()
        reset_order()
        cluster = yield from make(cluster_db, entities=standard_entities)
        runners = yield from cluster.start(3)
        yield from cluster.wait_for_stable_assignments()
        ids = yield from find_ids_by_runner(cluster, runners)
        client = yield from cluster.get_client(StateEntity)

        for runner, id in ids.values():
            first = yield from client(id).increment(EntityRequest(id=f"{id}-1", sequence=0))
            second = yield from client(id).increment(EntityRequest(id=f"{id}-2", sequence=0))
            assert first["runner"] == address_string(runner.address)
            assert second["runner"] == first["runner"]
            assert first["value"] == 1
            assert second["value"] == 2
            shard = yield from cluster.shard_of_entity(StateEntity, id)
            assert not cluster.client_sharding.has_shard_id(shard)

        ordered_id = next(iter(ids.values()))[1]
        state = order_state
        first_call = (
            yield from client(ordered_id)
            .ordered(EntityRequest(id=f"{backend}-ordered-1", sequence=1))
            .fork(start_immediately=True)
        )
        yield from cluster.wait_until(
            "The first ordered request did not start", state.entered.wait().as_(True)
        )
        second_call = (
            yield from client(ordered_id)
            .ordered(EntityRequest(id=f"{backend}-ordered-2", sequence=2))
            .fork(start_immediately=True)
        )
        state.gate.open_unsafe()
        assert (yield from first_call.join()) == 1
        assert (yield from second_call.join()) == 2
        assert state.order == [1, 2]

        assert len((yield from cluster.registrations())) == len(runners)

    yield from run(body)


@testing.live(timeout=60)
def test_reports_mailbox_saturation_and_revives_idle_entities_with_fresh_state(
    cluster_db: ClusterDatabase,
):
    """reports mailbox saturation and revives idle entities with fresh state"""
    backend = cluster_db.backend

    def body() -> Body:
        generations.clear()
        vars(mailbox_state).update(vars(MailboxState(gate=Latch())))
        state = mailbox_state
        cluster = yield from make(cluster_db, entities=standard_entities)
        yield from cluster.start(2)
        yield from cluster.wait_for_stable_assignments()

        mailbox = yield from cluster.get_client(MailboxEntity)
        held = (
            yield from mailbox("full")
            .hold(EntityRequest(id=f"{backend}-held", sequence=1))
            .fork(start_immediately=True)
        )
        yield from cluster.wait_until(
            "The mailbox request did not start", state.entered.wait().as_(True)
        )
        error = (
            yield from mailbox("full")
            .hold(EntityRequest(id=f"{backend}-rejected", sequence=2))
            .flip()
        )
        assert isinstance(error, MailboxFull)
        state.gate.open_unsafe()
        assert (yield from held.join()) == 1

        state_client = yield from cluster.get_client(StateEntity)
        first = yield from state_client("idle").increment(
            EntityRequest(id=f"{backend}-idle-1", sequence=0)
        )
        owner = yield from cluster.owner_of_entity(StateEntity, "idle")
        assert owner is not None
        yield from cluster.wait_until(
            "The idle entity was not reaped",
            owner.sharding.active_entity_count.map(lambda count: count == 0),
            12,
        )
        revived = yield from state_client("idle").increment(
            EntityRequest(id=f"{backend}-idle-2", sequence=0)
        )
        assert first["generation"] == 1
        assert revived["generation"] == 2
        assert revived["value"] == 1

    yield from run(body)


@_FAILS_IN_EFFECT
@testing.live(timeout=90)
def test_rebalances_on_runner_addition_graceful_stop_and_abrupt_death(
    cluster_db: ClusterDatabase,
):
    """rebalances on runner addition, graceful stop, and abrupt death"""
    backend = cluster_db.backend

    def body() -> Body:
        reset_order()
        state = order_state
        cluster = yield from make(cluster_db, entities=standard_entities)
        initial = yield from cluster.start(2)
        yield from cluster.wait_for_stable_assignments()
        before: dict[str, ClusterRunner | None] = {}
        for index in range(2000):
            id = f"moving-{index}"
            before[id] = yield from cluster.owner_of_entity(StateEntity, id)

        [added] = yield from cluster.start(1)
        assert added.index == 2
        yield from cluster.wait_for_stable_assignments()
        moved_id: str | None = None
        for id, old in before.items():
            if old is not added and (yield from cluster.owner_of_entity(StateEntity, id)) is added:
                moved_id = id
                break
        assert moved_id is not None
        client = yield from cluster.get_client(StateEntity)
        moved = yield from client(moved_id).increment(
            EntityRequest(id=f"{backend}-moved", sequence=0)
        )
        assert moved["runner"] == address_string(added.address)

        ids = yield from find_ids_by_runner(cluster, initial)
        stop_id = ids[initial[0].index][1]
        request = (
            yield from client(stop_id)
            .ordered(EntityRequest(id=f"{backend}-stop", sequence=1))
            .fork(start_immediately=True)
        )
        yield from cluster.wait_until(
            "The handover request did not start", state.entered.wait().as_(True)
        )
        stopping = yield from cluster.stop(initial[0]).fork(start_immediately=True)
        yield from cluster.wait_until(
            "The stopped runner did not hand over its entity",
            cluster.owner_of_entity(StateEntity, stop_id).map(
                lambda owner: owner is not None and owner is not initial[0]
            ),
        )
        state.gate.open_unsafe()
        assert (yield from request.join()) == 1
        yield from stopping.join()
        yield from cluster.wait_for_stable_assignments()

        kill_id = f"kill-{backend}"
        killed = yield from cluster.owner_of_entity(StateEntity, kill_id)
        assert killed is not None
        yield from cluster.kill(killed)
        reply = yield from client(kill_id).increment(
            EntityRequest(id=f"{backend}-kill", sequence=0)
        )
        assert reply["runner"] != address_string(killed.address)
        yield from cluster.wait_for_stable_assignments()
        assert (yield from cluster.message_counts()).unprocessed == 0

    yield from run(body)


@testing.live(timeout=60)
def test_transfers_frozen_row_locks_after_expiry(cluster_db: ClusterDatabase):
    """transfers frozen row locks after expiry"""
    backend = cluster_db.backend

    def body() -> Body:
        cluster = yield from make(cluster_db, entities=standard_entities, lock_mode="row")
        yield from cluster.start(2)
        yield from cluster.wait_for_stable_assignments()
        id = f"frozen-{backend}"
        old_owner = yield from cluster.owner_of_entity(StateEntity, id)
        assert old_owner is not None
        shard = yield from cluster.shard_of_entity(StateEntity, id)
        yield from cluster.freeze(old_owner)
        yield from cluster.wait_until(
            "The frozen runner's row lock did not expire",
            cluster.owner_of_entity(StateEntity, id).map(
                lambda owner: owner is not None and owner is not old_owner
            ),
            12,
        )
        yield from cluster.wait_for_client_sync()
        next_owner = yield from cluster.owner_of_entity(StateEntity, id)
        assert next_owner is not None
        assert cluster.owners_of_shard(shard) == [next_owner]
        client = yield from cluster.get_client(StateEntity)
        reply = yield from client(id).increment(EntityRequest(id=f"{backend}-freeze", sequence=0))
        assert reply["runner"] == address_string(next_owner.address)
        yield from cluster.kill(old_owner)

    yield from run(body)


@testing.live(timeout=60)
def test_retains_frozen_advisory_locks_until_the_session_closes(cluster_db: ClusterDatabase):
    """retains frozen advisory locks until the session closes"""
    backend = cluster_db.backend
    if backend != "pg":
        pytest.skip("SQLite has no advisory locks")

    def body() -> Body:
        cluster = yield from make(cluster_db, entities=standard_entities)
        yield from cluster.start(2)
        yield from cluster.wait_for_stable_assignments()
        id = f"frozen-advisory-{backend}"
        old_owner = yield from cluster.owner_of_entity(StateEntity, id)
        assert old_owner is not None
        shard = yield from cluster.shard_of_entity(StateEntity, id)
        yield from cluster.freeze(old_owner)
        deadline = (yield from now_millis()) + 3000
        yield from cluster.wait_until(
            "The advisory-lock observation window did not elapse",
            now_millis().map(lambda now: now >= deadline),
            5,
        )
        assert cluster.owners_of_shard(shard) == []
        assert cluster.owners_of_shard(shard, True) == [old_owner]
        yield from cluster.kill(old_owner)
        yield from cluster.wait_until(
            "The advisory lock was not handed over after its session closed",
            cluster.owner_of_entity(StateEntity, id).map(
                lambda owner: owner is not None and owner is not old_owner
            ),
        )

    yield from run(body)


@testing.live(timeout=60)
def test_assigns_annotated_entities_only_to_runners_in_their_shard_group(
    cluster_db: ClusterDatabase,
):
    """assigns annotated entities only to runners in their shard group"""

    def body() -> Body:
        entities = fx.layer.merge(state_entity_layer, group_entity_layer)
        cluster = yield from make(
            cluster_db,
            entities=entities,
            config={"available_shard_groups": ("default", "special"), "shards_per_group": 30},
        )
        [default_runner] = yield from cluster.start(1, assigned_shard_groups=("default",))
        [special_runner] = yield from cluster.start(1, assigned_shard_groups=("special",))
        yield from cluster.wait_for_stable_assignments()
        client = yield from cluster.get_client(GroupEntity)
        assert (yield from client("grouped").runner()) == address_string(special_runner.address)
        assert (yield from cluster.owner_of_entity(GroupEntity, "grouped")) is special_runner
        assert (yield from cluster.owner_of_entity(StateEntity, "default")) is default_runner

    yield from run(body)


@testing.live(timeout=60)
def test_runs_one_singleton_and_migrates_it_after_owner_death(cluster_db: ClusterDatabase):
    """runs one singleton and migrates it after owner death"""

    def body() -> Body:
        counts = {"active": 0, "max_active": 0, "starts": 0}

        def start() -> None:
            counts["active"] += 1
            counts["starts"] += 1
            counts["max_active"] = max(counts["max_active"], counts["active"])

        def stop(_value: None, _exit: Any) -> fx.Effect[None]:
            def run_stop() -> None:
                counts["active"] -= 1

            return fx.sync(run_stop)

        singleton_layer = singleton.make(
            "cluster-integration-singleton", acquire_release(fx.sync(start), stop)
        )
        cluster = yield from make(
            cluster_db, entities=fx.layer.merge(state_entity_layer, singleton_layer)
        )
        runners = yield from cluster.start(3)
        yield from cluster.wait_for_stable_assignments()
        yield from cluster.wait_until(
            "The singleton did not start", fx.sync(lambda: counts["active"] == 1)
        )
        first_owner = yield from cluster.owner_of_entity(
            StateEntity, "cluster-integration-singleton"
        )
        assert first_owner in runners
        assert first_owner is not None
        yield from cluster.kill(first_owner)
        yield from cluster.wait_until(
            "The singleton did not migrate",
            fx.sync(lambda: counts["starts"] >= 2 and counts["active"] == 1),
        )
        owner = yield from cluster.owner_of_entity(StateEntity, "cluster-integration-singleton")
        assert owner is not first_owner
        assert counts["max_active"] == 1

    yield from run(body)


@testing.live(timeout=60)
def test_keeps_entity_resource_alive_during_movement_and_releases_it_explicitly(
    cluster_db: ClusterDatabase,
):
    """keeps EntityResource alive during movement and releases it explicitly"""

    def body() -> Body:
        resource_state["acquired"] = 0
        resource_state["released"] = 0
        cluster = yield from make(cluster_db, entities=resource_entity_layer)
        yield from cluster.start(2)
        yield from cluster.wait_for_stable_assignments()
        client = yield from cluster.get_client(ResourceEntity)
        assert (yield from client("resource").get()) == 1
        owner = yield from cluster.owner_of_entity(ResourceEntity, "resource")
        assert owner is not None
        yield from cluster.stop(owner)
        yield from cluster.wait_until(
            "The resource entity did not move",
            cluster.owner_of_entity(ResourceEntity, "resource").map(
                lambda next: next is not None and next is not owner
            ),
        )
        assert resource_state["released"] == 0
        assert (yield from client("resource").get()) == 2
        yield from client("resource").close()
        yield from cluster.wait_until(
            "The entity resource was not released",
            fx.sync(lambda: resource_state["released"] == 1),
        )

    yield from run(body)


@testing.live(timeout=60)
def test_isolates_clusters_with_different_table_prefixes(cluster_db: ClusterDatabase):
    """isolates clusters with different table prefixes"""
    backend = cluster_db.backend

    def body() -> Body:
        config = {"shards_per_group": 30}
        first = yield from make(cluster_db, entities=state_entity_layer, config=config)
        second = yield from make(cluster_db, entities=state_entity_layer, config=config)
        [first_runner] = yield from first.start(1)
        [second_runner] = yield from second.start(1)
        yield from first.wait_for_stable_assignments()
        yield from second.wait_for_stable_assignments()
        assert first.prefix != second.prefix
        first_rows = yield from first.registrations()
        second_rows = yield from second.registrations()
        assert [row["address"] for row in first_rows] == [address_string(first_runner.address)]
        assert [row["address"] for row in second_rows] == [address_string(second_runner.address)]
        first_client = yield from first.get_client(StateEntity)
        second_client = yield from second.get_client(StateEntity)
        first_reply = yield from first_client("same-id").increment(
            EntityRequest(id=f"{backend}-prefix-first", sequence=0)
        )
        second_reply = yield from second_client("same-id").increment(
            EntityRequest(id=f"{backend}-prefix-second", sequence=0)
        )
        assert first_reply["runner"] == address_string(first_runner.address)
        assert second_reply["runner"] == address_string(second_runner.address)

    yield from run(body)


__all__ = ["EntityId"]
