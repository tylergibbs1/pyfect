"""Ports of platform-node's ``test/cluster-integration/Workflow.test.ts`` on
the cluster harness (``_cluster_harness``), on SQLite and on the throwaway
PostgreSQL server where Effect uses PostgreSQL and MySQL. Each test's
docstring is the Effect test title, without its backend prefix.
"""

from __future__ import annotations

import functools
from collections.abc import Callable, Generator
from dataclasses import dataclass, field
from typing import Any, Never, TypedDict, cast

import pyfect as fx
from pyfect import exit as Exit
from pyfect import schema as S
from pyfect import testing
from pyfect.cluster import cluster_workflow_engine
from pyfect.cluster.cluster_schema import ABANDON_ANNOTATION
from pyfect.cluster.entity import CurrentRunnerAddress, Entity, Request
from pyfect.cluster.entity_id import EntityId
from pyfect.cluster.sharding import Sharding, ShardingService
from pyfect.latch import Latch
from pyfect.layer import Layer
from pyfect.persistence import persisted_queue as pq
from pyfect.result import Ok
from pyfect.rpc import make as make_rpc
from pyfect.scope import acquire_release
from pyfect.workflow import (
    Complete,
    Suspended,
    activity,
    durable_clock,
    durable_deferred,
    durable_queue,
    workflow,
)
from pyfect.workflow.durable_deferred import Token, TokenSchema
from pyfect.workflow.workflow_engine import WorkflowEngine

from ._cluster_harness import Cluster, ClusterDatabase, ClusterRunner, make

type Body = Generator[fx.Effect[Any, Any, Any], Any]


class IdPayload(TypedDict):
    id: str


Id = S.Struct(IdPayload)


def id_key(payload: IdPayload) -> str:
    return payload["id"]


def count(counts: dict[str, int], id: str) -> None:
    counts[id] = counts.get(id, 0) + 1


# --- EndToEnd ----------------------------------------------------------------------------


class EndToEndPayload(TypedDict):
    id: str
    value: float


EndToEndWorkflow = workflow.make(
    "ClusterIntegrationEndToEnd",
    payload=S.Struct(EndToEndPayload),
    success=S.Number,
    idempotency_key=lambda payload: payload["id"],
)


@dataclass
class EndToEndState:
    gate: Latch = field(default_factory=lambda: Latch(True))
    entered: Latch = field(default_factory=Latch)
    runs: dict[str, int] = field(default_factory=lambda: {})


end_to_end = EndToEndState()


def _end_to_end(payload: EndToEndPayload, _execution_id: str) -> fx.Effect[float, Never, Any]:
    @fx.gen
    def execute():
        count(end_to_end.runs, payload["id"])
        end_to_end.entered.open_unsafe()
        yield from end_to_end.gate.wait()
        return payload["value"] + 1

    return activity.make(name="EndToEnd", success=S.Number, execute=execute)


# --- Replay ------------------------------------------------------------------------------

ReplayGate = durable_deferred.make("ClusterIntegrationReplayGate", success=S.String)
ReplayWorkflow = workflow.make(
    "ClusterIntegrationReplay", payload=Id, success=S.String, idempotency_key=id_key
)
replay_runs: dict[str, int] = {}


def _replay(payload: IdPayload, _execution_id: str) -> fx.Effect[str, Never, Any]:
    @fx.gen
    def run():
        yield from activity.make(
            name="BeforeSuspension", execute=fx.sync(lambda: count(replay_runs, payload["id"]))
        )
        return (yield from ReplayGate.wait())

    return run


# --- Restart -----------------------------------------------------------------------------

RestartGate = durable_deferred.make("ClusterIntegrationRestartGate", success=S.String)
RestartWorkflow = workflow.make(
    "ClusterIntegrationRestart", payload=Id, success=S.String, idempotency_key=id_key
)

# --- RaceReplay --------------------------------------------------------------------------

RaceReplayGate = durable_deferred.make("ClusterIntegrationRaceReplayGate", success=S.String)
RaceReplayTail = durable_deferred.make("ClusterIntegrationRaceReplayTail", success=S.String)
RaceReplayWorkflow = workflow.make(
    "ClusterIntegrationRaceReplay", payload=Id, success=S.String, idempotency_key=id_key
)
race_replay_enters: dict[str, int] = {}


def _race_replay(payload: IdPayload, _execution_id: str) -> fx.Effect[str, Never, Any]:
    @fx.gen
    def run():
        enter = fx.sync(lambda: count(race_replay_enters, payload["id"])).and_then(fx.never)
        winner = yield from durable_deferred.race_all(
            name="ClusterIntegrationRaceReplay",
            success=S.String,
            error=S.Never,
            effects=[RaceReplayGate.wait(), enter],
        )
        tail = yield from RaceReplayTail.wait()
        return f"{winner}:{tail}"

    return run


# --- Compensation ------------------------------------------------------------------------

CompensationGate = durable_deferred.make("ClusterIntegrationCompensationGate")


class CompensationError(S.TaggedError, identifier="ClusterIntegrationCompensationError"):
    id: str


CompensationWorkflow = workflow.make(
    "ClusterIntegrationCompensation",
    payload=Id,
    error=CompensationError,
    idempotency_key=id_key,
)
compensation_runs: dict[str, int] = {}


def _compensation(payload: IdPayload, _execution_id: str) -> fx.Effect[None, Any, Any]:
    id = payload["id"]

    @fx.gen
    def run():
        yield from activity.make(
            name="ClusterIntegrationCompensationRegistered",
            success=S.String,
            execute=fx.succeed(id),
        ).pipe(
            CompensationWorkflow.with_compensation(
                lambda _value, _cause: fx.sync(lambda: count(compensation_runs, id))
            )
        )
        yield from CompensationGate.wait()
        return (yield from fx.fail(CompensationError(id=id)))

    return run


# --- SuspendFailure ----------------------------------------------------------------------

SuspendFailureGate = durable_deferred.make("ClusterIntegrationSuspendFailureGate")
SuspendFailureWorkflow = workflow.make(
    "ClusterIntegrationSuspendFailure", payload=Id, idempotency_key=id_key
).annotate(workflow.SuspendOnFailure, True)
suspend_failures: set[str] = set()


def _suspend_failure(payload: IdPayload, _execution_id: str) -> fx.Effect[None, Never, Any]:
    id = payload["id"]

    @fx.gen
    def run():
        yield from SuspendFailureGate.wait()
        return (
            yield from activity.make(
                name="ClusterIntegrationSuspendFailure",
                execute=fx.sync(lambda: suspend_failures.add(id)).and_then(
                    fx.die(RuntimeError("suspend after owner loss"))
                ),
            )
        )

    return run


# --- RaceBoundary ------------------------------------------------------------------------

RaceBoundaryGateA = durable_deferred.make("ClusterIntegrationRaceBoundaryGateA", success=S.String)
RaceBoundaryGateB = durable_deferred.make("ClusterIntegrationRaceBoundaryGateB", success=S.String)
RaceBoundaryWorkflow = workflow.make(
    "ClusterIntegrationRaceBoundary", payload=Id, success=S.String, idempotency_key=id_key
)


@dataclass
class RaceBoundaryState:
    commit_started: Latch = field(default_factory=Latch)
    commit: Latch = field(default_factory=Latch)
    runs: dict[str, int] = field(default_factory=lambda: {})


race_boundary = RaceBoundaryState()


def _race_boundary(payload: IdPayload, _execution_id: str) -> fx.Effect[str, Never, Any]:
    count(race_boundary.runs, payload["id"])
    state = race_boundary
    return durable_deferred.race_all(
        name="ClusterIntegrationRaceBoundary",
        success=S.String,
        error=S.Never,
        effects=[RaceBoundaryGateA.wait(), RaceBoundaryGateB.wait()],
    ).ensuring(fx.sync(state.commit_started.open_unsafe).and_then(state.commit.wait()))


# --- Retry -------------------------------------------------------------------------------


class RetryError(S.TaggedError, identifier="ClusterIntegrationRetryError"):
    attempt: int


class RetryPayload(TypedDict):
    id: str
    succeed: bool


RetryWorkflow = workflow.make(
    "ClusterIntegrationRetry",
    payload=S.Struct(RetryPayload),
    success=S.Int,
    error=RetryError,
    idempotency_key=lambda payload: payload["id"],
)
retry_attempts: dict[str, list[int]] = {}


def _retry(payload: RetryPayload, _execution_id: str) -> fx.Effect[int, RetryError, Any]:
    @fx.gen
    def execute():
        attempt = yield from activity.CurrentAttempt()
        retry_attempts.setdefault(payload["id"], []).append(attempt)
        if payload["succeed"] and attempt == 3:
            return attempt
        return (yield from fx.fail(RetryError(attempt=attempt)))

    made = activity.make(name="Retry", success=S.Int, error=RetryError, execute=execute)
    return made.pipe(activity.retry(times=2))


# --- Clock -------------------------------------------------------------------------------

ClockWorkflow = workflow.make(
    "ClusterIntegrationClock", payload=Id, success=S.Number, idempotency_key=id_key
)


def _clock(_payload: IdPayload, _execution_id: str) -> fx.Effect[float, Never, Any]:
    return durable_clock.sleep(
        name="RestartSleep", duration="1 second", in_memory_threshold=0
    ).and_then(fx.clock.current_time_millis())


# --- Queue -------------------------------------------------------------------------------

Queue = durable_queue.make(
    name="ClusterIntegrationQueue", payload=Id, success=S.String, idempotency_key=id_key
)
QueueWorkflow = workflow.make(
    "ClusterIntegrationQueue", payload=Id, success=S.String, idempotency_key=id_key
)


@dataclass
class QueueState:
    worker_gate: Latch = field(default_factory=Latch)
    runs: dict[str, int] = field(default_factory=lambda: {})


queue_state = QueueState()


def _queue_item(payload: IdPayload) -> fx.Effect[str]:
    def process() -> str:
        count(queue_state.runs, payload["id"])
        return f"processed:{payload['id']}"

    return fx.sync(process)


queue_worker_layer: Layer[Any, Any, Any] = fx.layer.effect_discard(
    # The test replaces the gate, so read it when the worker starts.
    fx.suspend(lambda: queue_state.worker_gate.wait())  # noqa: PLW0108
    .and_then(Queue.make_worker(_queue_item))
    .fork_scoped()
)

# --- Interrupt ---------------------------------------------------------------------------

InterruptGate = durable_deferred.make("ClusterIntegrationInterruptGate")
InterruptWorkflow = workflow.make("ClusterIntegrationInterrupt", payload=Id, idempotency_key=id_key)

# --- ShutdownActivity --------------------------------------------------------------------

ShutdownActivityWorkflow = workflow.make(
    "ClusterIntegrationShutdownActivity", payload=Id, success=S.String, idempotency_key=id_key
)
ShutdownSuspendActivityWorkflow = workflow.make(
    "ClusterIntegrationShutdownSuspendActivity",
    payload=Id,
    success=S.String,
    idempotency_key=id_key,
).annotate(workflow.SuspendOnFailure, True)


@dataclass
class ActivityHandoffState:
    ready: Latch = field(default_factory=Latch)
    start: Latch = field(default_factory=Latch)
    fault_armed: bool = False
    persisted: Latch = field(default_factory=Latch)
    fault_release: Latch = field(default_factory=lambda: Latch(True))
    runs: dict[str, int] = field(default_factory=lambda: {})
    compensations: set[str] = field(default_factory=set[str])
    resource_events: dict[str, list[str]] = field(default_factory=lambda: {})


handoff = ActivityHandoffState()


def reset_activity_handoff_state(id: str, *, fault_release_open: bool = True) -> None:
    handoff.ready = Latch()
    handoff.start = Latch()
    handoff.fault_armed = False
    handoff.persisted = Latch()
    handoff.fault_release = Latch(fault_release_open)
    handoff.runs.pop(id, None)
    handoff.compensations.discard(id)
    handoff.resource_events[id] = []


def _abandon_current() -> fx.Effect[Never]:
    """Interrupt the current fiber as abandoned (Effect's
    ``ClusterSchema.Abandon.annotation``)."""

    def abandon(fiber: Any) -> fx.Effect[Never]:
        def register(_resume: Callable[[fx.Effect[Never]], None]) -> None:
            fiber.interrupt_as_unsafe(fiber.id, ABANDON_ANNOTATION)

        return fx.callback(register).interruptible()

    return fx.current_fiber().flat_map(abandon)


def _shutdown_activity(target: workflow.Workflow[IdPayload, str, Never]) -> Any:
    def handler(payload: IdPayload, _execution_id: str) -> fx.Effect[str, Never, Any]:
        id = payload["id"]

        def event(name: str) -> fx.Effect[None]:
            return fx.sync(lambda: handoff.resource_events[id].append(name))

        def ran() -> str:
            count(handoff.runs, id)
            return f"completed:{id}"

        @fx.gen
        def run():
            yield from fx.succeed(id).pipe(
                target.with_compensation(
                    lambda _value, _cause: fx.sync(lambda: handoff.compensations.add(id))
                )
            )
            yield from acquire_release(event("acquire"), lambda _v, _e: event("release")).pipe(
                workflow.provide_scope
            )
            handoff.ready.open_unsafe()
            yield from handoff.start.wait()
            return (
                yield from activity.make(
                    name="ShutdownActivity", success=S.String, execute=fx.sync(ran)
                )
            )

        return run

    return handler


shutdown_activity_layer: Layer[Any, Any, Any] = ShutdownActivityWorkflow.to_layer(
    _shutdown_activity(ShutdownActivityWorkflow)
)
shutdown_suspend_activity_layer: Layer[Any, Any, Any] = ShutdownSuspendActivityWorkflow.to_layer(
    _shutdown_activity(ShutdownSuspendActivityWorkflow)
)


class _FaultyActivityClient:
    """A workflow entity client whose next ``activity`` call, while
    ``handoff.fault_armed``, is sent as a discard and then abandoned, as a
    runner shutting down does with a persisted request."""

    def __init__(self, client: Any) -> None:
        self._client = client

    def __getattr__(self, name: str) -> Any:
        return getattr(self._client, name)

    def activity(self, payload: Any, **options: Any) -> fx.Effect[Any, Any]:
        method = self._client.activity
        if not handoff.fault_armed:
            return method(payload, **options)
        handoff.fault_armed = False
        state = handoff

        # Mirror sendOutgoing's persisted abandon branch during a runner
        # shutdown: accept the durable request, then interrupt the caller
        # because this runner can never observe the reply.
        def persisted(_: object) -> fx.Effect[None]:
            return state.persisted.open().as_void()

        sent: fx.Effect[None, Any] = method.discard(payload, **options)
        return sent.tap(persisted).and_then(state.fault_release.wait()).and_then(_abandon_current())


class _ActivityHandoffSharding:
    def __init__(self, sharding: ShardingService) -> None:
        self._sharding = sharding

    def __getattr__(self, name: str) -> Any:
        return getattr(self._sharding, name)

    def make_client(self, entity: type[Entity], /) -> fx.Effect[Callable[[str], Any]]:
        def wrap(make_client: Callable[[str], Any]) -> Callable[[str], Any]:
            return lambda entity_id: _FaultyActivityClient(make_client(entity_id))

        return self._sharding.make_client(entity).map(wrap)


activity_handoff_sharding_layer: Layer[Any, Never, Any] = fx.layer.effect(
    Sharding,
    Sharding().map(lambda sharding: cast("ShardingService", _ActivityHandoffSharding(sharding))),
)

shutdown_activity_entities: Layer[Any, Any, Any] = (
    fx.layer.merge(shutdown_activity_layer, shutdown_suspend_activity_layer)
    .pipe(fx.layer.provide(fx.layer.effect(WorkflowEngine, cluster_workflow_engine.make())))
    .pipe(fx.layer.provide(activity_handoff_sharding_layer))
    .or_die()
)

# --- DeferredControl ---------------------------------------------------------------------


class CompletePayload(TypedDict):
    token: Token
    value: str


Complete_ = S.Struct(CompletePayload, token=TokenSchema)


class DeferredControl(Entity, type="ClusterIntegrationDeferredControl"):
    complete_deferred = make_rpc("CompleteDeferred", payload=Complete_, success=S.String)
    complete_race_boundary_deferred = make_rpc(
        "CompleteRaceBoundaryDeferred", payload=Complete_, success=S.String
    )


@fx.gen
def _deferred_control():
    runner = yield from CurrentRunnerAddress()
    address = f"{runner.host}:{runner.port}"

    def complete(
        deferred: durable_deferred.DurableDeferred[str, Never],
    ) -> Callable[[Request[CompletePayload]], fx.Effect[str, Never, Any]]:
        def handle(request: Request[CompletePayload]) -> fx.Effect[str, Never, Any]:
            return deferred.succeed(
                token=request.payload["token"], value=request.payload["value"]
            ).as_(address)

        return handle

    return (
        DeferredControl.handlers()
        .handle(DeferredControl.complete_deferred)(complete(RestartGate))
        .handle(DeferredControl.complete_race_boundary_deferred)(complete(RaceBoundaryGateB))
    )


_workflow_layers: list[Layer[Any, Any, Any]] = [
    EndToEndWorkflow.to_layer(_end_to_end),
    ReplayWorkflow.to_layer(_replay),
    RestartWorkflow.to_layer(lambda _payload, _id: RestartGate.wait()),
    RaceReplayWorkflow.to_layer(_race_replay),
    CompensationWorkflow.to_layer(_compensation),
    SuspendFailureWorkflow.to_layer(_suspend_failure),
    RaceBoundaryWorkflow.to_layer(_race_boundary),
    RetryWorkflow.to_layer(_retry),
    ClockWorkflow.to_layer(_clock),
    QueueWorkflow.to_layer(lambda payload, _id: Queue.process({"id": payload["id"]})),
    queue_worker_layer,
    InterruptWorkflow.to_layer(lambda _payload, _id: InterruptGate.wait()),
    DeferredControl.to_layer_effect(_deferred_control),
]


def _merge(left: Layer[Any, Any, Any], right: Layer[Any, Any, Any]) -> Layer[Any, Any, Any]:
    return fx.layer.merge(left, right)


workflows = functools.reduce(_merge, _workflow_layers)


def entities(prefix: str) -> Layer[Any, Any, Any]:
    queue = pq.layer.pipe(
        fx.layer.provide_merge(
            pq.layer_store_sql(
                table_name=f"{prefix}_workflow_queue",
                poll_interval="100 millis",
                lock_refresh_interval="500 millis",
                lock_expiration="1750 millis",
            )
        )
    )
    return (
        workflows.pipe(fx.layer.provide(queue))
        .pipe(fx.layer.provide(cluster_workflow_engine.layer))
        .or_die()
    )


# --- helpers -----------------------------------------------------------------------------


def with_workflow[A, E](cluster: Cluster, effect: fx.Effect[A, E, Any]) -> fx.Effect[A, E]:
    return effect.pipe(fx.provide_service(WorkflowEngine, cluster.workflow_engine))


def wait_for_suspended(
    cluster: Cluster, target: workflow.Workflow[Any, Any, Any], execution_id: str
) -> fx.Effect[None, Any]:
    return cluster.wait_until(
        f"{target.tag}/{execution_id} did not suspend",
        with_workflow(
            cluster,
            target.poll(execution_id).map(lambda result: isinstance(result, Suspended)),
        ),
    )


def wait_for_complete(
    cluster: Cluster, target: workflow.Workflow[Any, Any, Any], execution_id: str
) -> fx.Effect[Complete[Any, Any], Any]:
    found: list[Complete[Any, Any]] = []

    def check(result: Any) -> bool:
        if not isinstance(result, Complete):
            return False
        found.append(cast("Complete[Any, Any]", result))
        return True

    return cluster.wait_until(
        f"{target.tag}/{execution_id} did not complete",
        with_workflow(cluster, target.poll(execution_id).map(check)),
    ).map(lambda _: found[-1])


def restart(cluster: Cluster) -> fx.Effect[list[ClusterRunner], Any, Any]:
    @fx.gen
    def run():
        running = [runner for runner in cluster.runners if runner.state() == "running"]
        yield from fx.for_each(running, cluster.kill, concurrency="unbounded")
        replacements = yield from cluster.start(3)
        yield from cluster.wait_for_stable_assignments()
        return replacements

    return run


def workflow_owner(cluster: Cluster, execution_id: str) -> ClusterRunner | None:
    shard = cluster.client_sharding.get_shard_id(EntityId(execution_id), "default")
    owners = cluster.owners_of_shard(shard)
    return owners[0] if owners else None


def find_control_on_another_runner(
    cluster: Cluster, workflow_runner: ClusterRunner
) -> fx.Effect[tuple[str, ClusterRunner]]:
    @fx.gen
    def find():
        for index in range(2000):
            id = f"control-{index}"
            owner = yield from cluster.owner_of_entity(DeferredControl, id)
            if owner is not None and owner is not workflow_runner:
                return id, owner
        raise AssertionError("Could not route deferred control to another runner")

    return find


def address_of(runner: ClusterRunner) -> str:
    return f"{runner.address.host}:{runner.address.port}"


def run(body: Callable[[], Body]) -> fx.Effect[None, Any]:
    return fx.scoped(fx.gen(body))


def started(
    cluster_db: ClusterDatabase, layer: Any = entities, **options: Any
) -> Generator[fx.Effect[Any, Any, Any], Any, Cluster]:
    cluster = yield from make(cluster_db, entities=layer, **options)
    yield from cluster.start(3)
    yield from cluster.wait_for_stable_assignments()
    return cluster


# --- tests -------------------------------------------------------------------------------


@testing.live(timeout="1 minute")
def test_executes_end_to_end_and_deduplicates_concurrent_callers(cluster_db: ClusterDatabase):
    """executes end to end and deduplicates concurrent callers"""
    id = f"{cluster_db.backend}-end-to-end"

    def body() -> Body:
        end_to_end.gate = Latch()
        end_to_end.entered = Latch()
        cluster = yield from started(cluster_db)

        payload: EndToEndPayload = {"id": id, "value": 41}
        first = yield from with_workflow(cluster, EndToEndWorkflow.execute(payload)).fork(
            start_immediately=True
        )
        yield from cluster.wait_until(
            "The end-to-end activity did not start", end_to_end.entered.wait().as_(True)
        )
        second = yield from with_workflow(cluster, EndToEndWorkflow.execute(payload)).fork(
            start_immediately=True
        )
        end_to_end.gate.open_unsafe()

        assert (yield from first.join()) == 42
        assert (yield from second.join()) == 42
        assert end_to_end.runs[id] == 1

    yield from run(body)


@testing.live(timeout="1 minute")
def test_replays_completed_activities_after_the_owner_dies(cluster_db: ClusterDatabase):
    """replays completed activities after the owner dies"""
    id = f"{cluster_db.backend}-replay"

    def body() -> Body:
        cluster = yield from started(cluster_db)
        execution_id = yield from with_workflow(
            cluster, ReplayWorkflow.execute({"id": id}, discard=True)
        )
        yield from wait_for_suspended(cluster, ReplayWorkflow, execution_id)
        assert replay_runs[id] == 1

        owner = workflow_owner(cluster, execution_id)
        assert owner is not None
        yield from cluster.kill(owner)
        yield from cluster.wait_for_stable_assignments()
        token = ReplayGate.token_from_execution_id(
            workflow=ReplayWorkflow, execution_id=execution_id
        )
        yield from with_workflow(cluster, ReplayGate.succeed(token=token, value="resumed"))
        result = yield from wait_for_complete(cluster, ReplayWorkflow, execution_id)

        assert result.exit == Exit.succeed("resumed")
        assert replay_runs[id] == 1

    yield from run(body)


@testing.live(timeout="90 seconds")
def test_resumes_deferred_workflows_across_a_whole_cluster_restart_from_another_runner(
    cluster_db: ClusterDatabase,
):
    """resumes deferred workflows across a whole-cluster restart from another runner"""
    id = f"{cluster_db.backend}-restart"

    def body() -> Body:
        cluster = yield from started(cluster_db)
        execution_id = yield from with_workflow(
            cluster, RestartWorkflow.execute({"id": id}, discard=True)
        )
        yield from wait_for_suspended(cluster, RestartWorkflow, execution_id)
        yield from restart(cluster)

        owner = workflow_owner(cluster, execution_id)
        assert owner is not None
        control_id, control_owner = yield from find_control_on_another_runner(cluster, owner)
        control = yield from cluster.get_client(DeferredControl)
        token = RestartGate.token_from_execution_id(
            workflow=RestartWorkflow, execution_id=execution_id
        )
        completed_by = yield from control(control_id).complete_deferred(
            {"token": token, "value": "after-restart"}
        )
        assert completed_by == address_of(control_owner)

        result = yield from wait_for_complete(cluster, RestartWorkflow, execution_id)
        assert result.exit == Exit.succeed("after-restart")

    yield from run(body)


@testing.live(timeout="1 minute")
def test_wakes_a_durable_deferred_race_all_and_replays_the_winner_after_owner_death(
    cluster_db: ClusterDatabase,
):
    """wakes a DurableDeferred raceAll and replays the winner after owner death"""
    id = f"{cluster_db.backend}-race-replay"

    def body() -> Body:
        cluster = yield from started(cluster_db)
        execution_id = yield from with_workflow(
            cluster, RaceReplayWorkflow.execute({"id": id}, discard=True)
        )
        yield from cluster.wait_until(
            "The durable race did not start",
            fx.sync(lambda: race_replay_enters.get(id, 0) > 0),
        )

        race_token = RaceReplayGate.token_from_execution_id(
            workflow=RaceReplayWorkflow, execution_id=execution_id
        )
        yield from with_workflow(cluster, RaceReplayGate.succeed(token=race_token, value="winner"))
        yield from wait_for_suspended(cluster, RaceReplayWorkflow, execution_id)
        entries_before_kill = race_replay_enters.get(id)

        owner = workflow_owner(cluster, execution_id)
        assert owner is not None
        yield from cluster.kill(owner)
        yield from cluster.wait_for_stable_assignments()

        tail_token = RaceReplayTail.token_from_execution_id(
            workflow=RaceReplayWorkflow, execution_id=execution_id
        )
        yield from with_workflow(
            cluster, RaceReplayTail.succeed(token=tail_token, value="after-owner-death")
        )
        result = yield from wait_for_complete(cluster, RaceReplayWorkflow, execution_id)

        assert result.exit == Exit.succeed("winner:after-owner-death")
        assert race_replay_enters.get(id) == entries_before_kill

    yield from run(body)


@testing.live(timeout="90 seconds")
def test_runs_compensation_and_suspend_on_failure_after_the_owner_is_lost(
    cluster_db: ClusterDatabase,
):
    """runs compensation and SuspendOnFailure after the owner is lost"""
    compensation_id = f"{cluster_db.backend}-compensation-owner-loss"
    suspend_id = f"{cluster_db.backend}-suspend-owner-loss"

    def body() -> Body:
        cluster = yield from started(cluster_db)
        compensation_execution_id = yield from with_workflow(
            cluster, CompensationWorkflow.execute({"id": compensation_id}, discard=True)
        )
        suspend_execution_id = yield from with_workflow(
            cluster, SuspendFailureWorkflow.execute({"id": suspend_id}, discard=True)
        )
        yield from wait_for_suspended(cluster, CompensationWorkflow, compensation_execution_id)
        yield from wait_for_suspended(cluster, SuspendFailureWorkflow, suspend_execution_id)

        compensation_owner = workflow_owner(cluster, compensation_execution_id)
        suspend_owner = workflow_owner(cluster, suspend_execution_id)
        assert compensation_owner is not None
        assert suspend_owner is not None
        owners = [compensation_owner]
        if suspend_owner is not compensation_owner:
            owners.append(suspend_owner)
        for owner in owners:
            yield from cluster.kill(owner)
        yield from cluster.wait_for_stable_assignments()

        compensation_token = CompensationGate.token_from_execution_id(
            workflow=CompensationWorkflow, execution_id=compensation_execution_id
        )
        yield from with_workflow(
            cluster, CompensationGate.succeed(token=compensation_token, value=None)
        )
        compensation_result = yield from wait_for_complete(
            cluster, CompensationWorkflow, compensation_execution_id
        )
        assert isinstance(compensation_result.exit, Exit.Failure)
        failure = compensation_result.exit.cause.find_error()
        assert isinstance(failure, Ok)
        assert isinstance(failure.value, CompensationError)
        assert compensation_runs[compensation_id] == 1

        suspend_token = SuspendFailureGate.token_from_execution_id(
            workflow=SuspendFailureWorkflow, execution_id=suspend_execution_id
        )
        yield from with_workflow(
            cluster, SuspendFailureGate.succeed(token=suspend_token, value=None)
        )
        yield from cluster.wait_until(
            "SuspendOnFailure did not run after the workflow owner was lost",
            fx.sync(lambda: suspend_id in suspend_failures),
        )
        yield from wait_for_suspended(cluster, SuspendFailureWorkflow, suspend_execution_id)

    yield from run(body)


@testing.live(timeout="1 minute")
def test_accepts_a_late_durable_race_completion_across_the_suspend_commit(
    cluster_db: ClusterDatabase,
):
    """accepts a late durable-race completion across the suspend commit"""
    id = f"{cluster_db.backend}-race-suspend-commit"

    def body() -> Body:
        race_boundary.commit_started = Latch()
        race_boundary.commit = Latch()
        state = race_boundary
        cluster = yield from started(cluster_db)
        execution_id = yield from with_workflow(
            cluster, RaceBoundaryWorkflow.execute({"id": id}, discard=True)
        )
        yield from cluster.wait_until(
            "The durable race did not reach its suspend commit",
            state.commit_started.wait().as_(True),
        )

        owner = workflow_owner(cluster, execution_id)
        assert owner is not None
        control_id, control_owner = yield from find_control_on_another_runner(cluster, owner)
        control = yield from cluster.get_client(DeferredControl)
        token = RaceBoundaryGateB.token_from_execution_id(
            workflow=RaceBoundaryWorkflow, execution_id=execution_id
        )
        completed_by = yield from control(control_id).complete_race_boundary_deferred(
            {"token": token, "value": "late-winner"}
        )
        assert completed_by == address_of(control_owner)

        kill_fiber = yield from cluster.kill(owner).fork(start_immediately=True)
        # The uninterruptible ensuring finalizer holds the scope's close here
        # until the commit latch opens, keeping the owner blocked mid-commit.
        state.commit.open_unsafe()
        yield from kill_fiber.join()
        yield from cluster.wait_for_stable_assignments()

        result = yield from wait_for_complete(cluster, RaceBoundaryWorkflow, execution_id)
        assert result.exit == Exit.succeed("late-winner")
        assert state.runs.get(id, 0) >= 2

    yield from run(body)


@testing.live(timeout="1 minute")
def test_applies_activity_retry_policy_and_preserves_the_exhausted_error(
    cluster_db: ClusterDatabase,
):
    """applies activity retry policy and preserves the exhausted error"""
    success_id = f"{cluster_db.backend}-retry-success"
    failure_id = f"{cluster_db.backend}-retry-failure"

    def body() -> Body:
        cluster = yield from started(cluster_db)
        assert (
            yield from with_workflow(
                cluster, RetryWorkflow.execute({"id": success_id, "succeed": True})
            )
        ) == 3
        error = yield from with_workflow(
            cluster, RetryWorkflow.execute({"id": failure_id, "succeed": False})
        ).flip()

        assert retry_attempts[success_id] == [1, 2, 3]
        assert retry_attempts[failure_id] == [1, 2, 3]
        assert isinstance(error, RetryError)
        assert error.attempt == 3

    yield from run(body)


@testing.live(timeout="90 seconds")
def test_wakes_a_durable_clock_after_a_whole_cluster_restart(cluster_db: ClusterDatabase):
    """wakes a durable clock after a whole-cluster restart"""
    id = f"{cluster_db.backend}-clock"

    def body() -> Body:
        cluster = yield from started(cluster_db)
        start = yield from fx.clock.current_time_millis()
        execution_id = yield from with_workflow(
            cluster, ClockWorkflow.execute({"id": id}, discard=True)
        )
        yield from wait_for_suspended(cluster, ClockWorkflow, execution_id)
        yield from restart(cluster)

        result = yield from wait_for_complete(cluster, ClockWorkflow, execution_id)
        assert isinstance(result.exit, Exit.Success)
        assert result.exit.value - start >= 900

    yield from run(body)


@testing.live(timeout="90 seconds")
def test_persists_queued_work_across_restart_and_consumes_it_once(cluster_db: ClusterDatabase):
    """persists queued work across restart and consumes it once"""
    id = f"{cluster_db.backend}-queue"

    def body() -> Body:
        queue_state.worker_gate = Latch()
        cluster = yield from started(cluster_db)
        execution_id = yield from with_workflow(
            cluster, QueueWorkflow.execute({"id": id}, discard=True)
        )
        yield from wait_for_suspended(cluster, QueueWorkflow, execution_id)
        yield from restart(cluster)
        queue_state.worker_gate.open_unsafe()

        result = yield from wait_for_complete(cluster, QueueWorkflow, execution_id)
        assert result.exit == Exit.succeed(f"processed:{id}")
        assert queue_state.runs[id] == 1

    yield from run(body)


@testing.live(timeout="90 seconds")
def test_persists_interruption_across_a_whole_cluster_restart(cluster_db: ClusterDatabase):
    """persists interruption across a whole-cluster restart"""
    id = f"{cluster_db.backend}-interrupt"

    def body() -> Body:
        cluster = yield from started(cluster_db)
        execution_id = yield from with_workflow(
            cluster, InterruptWorkflow.execute({"id": id}, discard=True)
        )
        yield from wait_for_suspended(cluster, InterruptWorkflow, execution_id)
        yield from with_workflow(cluster, InterruptWorkflow.interrupt(execution_id))
        yield from restart(cluster)

        result = yield from wait_for_complete(cluster, InterruptWorkflow, execution_id)
        assert isinstance(result.exit, Exit.Failure)
        assert result.exit.cause.has_interrupts

    yield from run(body)


@testing.live(timeout="90 seconds")
def test_replays_a_persisted_activity_handoff_without_leaking_workflow_resources(
    cluster_db: ClusterDatabase,
):
    """replays a persisted activity handoff without leaking workflow resources"""
    backend = cluster_db.backend

    def body() -> Body:
        cluster = yield from started(cluster_db, shutdown_activity_entities)
        cases: list[tuple[str, workflow.Workflow[IdPayload, str, Never]]] = [
            ("default", ShutdownActivityWorkflow),
            ("suspend-on-failure", ShutdownSuspendActivityWorkflow),
        ]
        for suffix, target in cases:
            id = f"{backend}-shutdown-activity-{suffix}"
            reset_activity_handoff_state(id)
            execution_id = yield from with_workflow(
                cluster, target.execute({"id": id}, discard=True)
            )
            yield from cluster.wait_until(
                "The shutdown activity workflow did not start", handoff.ready.wait().as_(True)
            )

            handoff.fault_armed = True
            handoff.start.open_unsafe()

            result = yield from wait_for_complete(cluster, target, execution_id)
            assert handoff.persisted.is_open
            assert result.exit == Exit.succeed(f"completed:{id}")
            assert handoff.runs[id] == 1
            assert id not in handoff.compensations
            assert handoff.resource_events[id] == ["acquire", "release", "acquire", "release"]

    yield from run(body)


@testing.live(timeout="90 seconds")
def test_preserves_a_safe_interrupt_during_a_persisted_activity_handoff(
    cluster_db: ClusterDatabase,
):
    """preserves a safe interrupt during a persisted activity handoff"""
    id = f"{cluster_db.backend}-shutdown-activity-interrupt"

    def body() -> Body:
        reset_activity_handoff_state(id, fault_release_open=False)
        cluster = yield from started(cluster_db, shutdown_activity_entities)
        execution_id = yield from with_workflow(
            cluster, ShutdownActivityWorkflow.execute({"id": id}, discard=True)
        )
        yield from cluster.wait_until(
            "The shutdown activity workflow did not start", handoff.ready.wait().as_(True)
        )

        handoff.fault_armed = True
        yield from with_workflow(cluster, ShutdownActivityWorkflow.interrupt(execution_id))
        handoff.start.open_unsafe()
        yield from cluster.wait_until(
            "The shutdown activity request was not persisted", handoff.persisted.wait().as_(True)
        )
        yield from cluster.wait_until(
            "The shutdown activity request was not processed",
            fx.sync(lambda: handoff.runs.get(id) == 1),
        )
        handoff.fault_release.open_unsafe()

        result = yield from wait_for_complete(cluster, ShutdownActivityWorkflow, execution_id)
        assert isinstance(result.exit, Exit.Failure)
        assert result.exit.cause.has_interrupts
        assert id in handoff.compensations

    # ``body`` replaces the latch, so read it when the test ends.
    yield from run(body).ensuring(fx.sync(lambda: handoff.fault_release.open_unsafe()))  # noqa: PLW0108


@testing.live(timeout="90 seconds")
def test_recovers_a_persisted_activity_across_an_actual_owner_handoff(
    cluster_db: ClusterDatabase,
):
    """recovers a persisted activity across an actual owner handoff"""
    id = f"{cluster_db.backend}-shutdown-activity-handoff"

    def body() -> Body:
        reset_activity_handoff_state(id)
        layer = shutdown_activity_layer.pipe(
            fx.layer.provide(cluster_workflow_engine.layer)
        ).or_die()
        cluster = yield from started(
            cluster_db, layer, config={"entity_termination_timeout": fx.duration.seconds(0.1)}
        )
        execution_id = yield from with_workflow(
            cluster, ShutdownActivityWorkflow.execute({"id": id}, discard=True)
        )
        yield from cluster.wait_until(
            "The shutdown activity workflow did not start", handoff.ready.wait().as_(True)
        )

        owner = workflow_owner(cluster, execution_id)
        assert owner is not None
        stopping = yield from cluster.stop(owner).fork(start_immediately=True)
        handoff.start.open_unsafe()

        def handed_over() -> bool:
            next_owner = workflow_owner(cluster, execution_id)
            return next_owner is not None and next_owner is not owner

        yield from cluster.wait_until(
            "The shutdown activity workflow was not handed to another runner",
            fx.sync(handed_over),
        )

        result = yield from wait_for_complete(cluster, ShutdownActivityWorkflow, execution_id)
        yield from stopping.join()
        assert result.exit == Exit.succeed(f"completed:{id}")
        assert handoff.runs[id] == 1
        assert (yield from cluster.message_counts()).unprocessed == 0

    yield from run(body)
