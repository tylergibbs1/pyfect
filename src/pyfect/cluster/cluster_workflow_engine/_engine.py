"""The cluster workflow engine (Effect's ``ClusterWorkflowEngine.make``):
workflow executions, activities, deferred completions, resumes, interrupts
and durable clocks are persisted entity messages, so a durable workflow
survives the runner that started it."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import builtins
from collections.abc import Callable, Generator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from math import ceil
from typing import Any, Literal, Never, cast

from pyfect._catch import catch_tag
from pyfect._core import Effect, _WithFiber
from pyfect._fiber import Fiber
from pyfect._json_text import stringify
from pyfect.cause import Cause, Interrupt
from pyfect.cluster import _cluster_abandon as cluster_abandon
from pyfect.cluster._entity_activation import CurrentActivationScope
from pyfect.cluster.cluster_error import EntityNotAssignedToRunner, PersistenceError
from pyfect.cluster.cluster_schema import Dynamic, ShardGroup, WithTransaction
from pyfect.cluster.cluster_workflow_engine._entities import (
    ActivityPayload,
    AnyWorkflow,
    ClockEntity,
    ClockPayload,
    ClockRpc,
    DeferredPayload,
    DeferredRpc,
    Parent,
    ResumePayload,
    RunPayload,
    activity_primary_key,
    make_partial_workflow_entity,
    make_workflow_entity,
    run_payload,
    run_rpc_of,
    workflow_payload,
)
from pyfect.cluster.entity import CurrentAddress, Entity, EntityHandlers, EntityOptions, Request
from pyfect.cluster.entity_address import EntityAddress
from pyfect.cluster.entity_id import EntityId
from pyfect.cluster.entity_type import EntityType
from pyfect.cluster.envelope import Interrupt as InterruptEnvelope
from pyfect.cluster.envelope import Request as EnvelopeRequest
from pyfect.cluster.envelope import make_request
from pyfect.cluster.message import OutgoingEnvelope, OutgoingRequest
from pyfect.cluster.message_storage import MessageStorage, MessageStorageService
from pyfect.cluster.reply import with_exit_schema
from pyfect.cluster.sharding import Sharding, ShardingService
from pyfect.cluster.snowflake import Snowflake
from pyfect.context import Context
from pyfect.date_time import now
from pyfect.deferred import Deferred
from pyfect.duration import Seconds, to_millis
from pyfect.effect import (
    context,
    die,
    fail,
    fail_cause,
    from_exit,
    gen,
    never,
    provide_context,
    provide_service,
    service_option,
    succeed,
    suspend,
    sync,
    void,
)
from pyfect.exit import Exit, Failure, Success
from pyfect.logger import log_warning
from pyfect.rc_map import RcMap
from pyfect.rpc import wrap as rpc_wrap
from pyfect.rpc._rpc import AnyRpc, exit_schema
from pyfect.rpc.schema import ClientAbort
from pyfect.schedule import exponential, min, spaced
from pyfect.schema import decode_unknown_effect, decode_unknown_sync, to_codec_json
from pyfect.schema import to_json_schema_document as json_schema_document
from pyfect.scope import CloseableScope, Scope, scoped
from pyfect.semaphore import Semaphore
from pyfect.tracer import annotate_current_span, current_span
from pyfect.workflow._encoded import DeferredState, Encoded, Handler, make_deferred_state
from pyfect.workflow._encoded import make_unsafe as make_engine_unsafe
from pyfect.workflow._result import Result, Suspended
from pyfect.workflow._services import (
    WorkflowEngine,
    WorkflowEngineService,
    WorkflowInstance,
    WorkflowInstanceService,
)
from pyfect.workflow.activity import Activity, CurrentAttempt
from pyfect.workflow.durable_clock import DurableClock
from pyfect.workflow.durable_clock import make as make_clock
from pyfect.workflow.durable_deferred import DurableDeferred
from pyfect.workflow.durable_deferred import make as make_deferred
from pyfect.workflow.workflow import SuspendOnFailure, into_result

type WakeMode = Literal["explicit", "automatic"]
type ReplyEncoded = dict[str, Any]

INTERRUPT_SIGNAL: DurableDeferred[None, Never] = make_deferred("Workflow/InterruptSignal")

# Workflow state is durable, so an idle entity (completed or suspended) can be
# released quickly and is rebuilt from storage when the next message arrives.
# This keeps completed and suspended executions from holding
# ``max_resident_entities`` slots for the full ``entity_max_idle_time``.
ENTITY_MAX_IDLE_TIME = Seconds(10)

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

_retry_policy = min(exponential(0.2, 1.5), spaced(60))


def ensure_success[A](effect: Effect[A, Any, Any]) -> Effect[A, Never, Any]:
    """Retry ``effect`` until it succeeds. A cluster abandonment means this
    owner can no longer complete it, so retrying would only wait on a
    retired run: it is raised again as an annotated interrupt, so the
    activation can unwind and its shard can be released."""

    def retryable(cause: Cause[Any]) -> bool:
        return not cluster_abandon.is_cause(cause)

    def abandon(_: Cause[Any]) -> Effect[Never]:
        return cluster_abandon.interrupt

    return (
        effect.sandbox()
        .retry(schedule=_retry_policy, while_=retryable)
        .catch_if(cluster_abandon.is_cause, abandon)
        .or_die()
    )


def _retry_persistence[A](effect: Effect[A, Any, Any]) -> Effect[A, Never, Any]:
    return effect.retry(
        times=3,
        schedule=exponential(0.25),
        while_=lambda e: isinstance(e, PersistenceError),
    ).or_die()


def _is_suspended_reply(reply: ReplyEncoded) -> bool:
    exit = reply["exit"]
    return exit.get("_tag") == "Success" and exit["value"].get("_tag") == "Suspended"


def _is_failed_reply(reply: ReplyEncoded) -> bool:
    return _is_suspended_reply(reply) and reply["exit"]["value"].get("failed") is True


_decode_deferred_with_exit = decode_unknown_sync(
    to_codec_json(with_exit_schema(exit_schema(DeferredRpc)))
)


def _deferred_exit(reply: ReplyEncoded) -> Exit[Any, Any]:
    decoded = _decode_deferred_with_exit(reply)
    exit = decoded.exit
    return cast("Exit[Any, Any]", exit.value) if isinstance(exit, Success) else exit


def payload_shape(workflow: AnyWorkflow) -> str:
    """The JSON Schema of ``workflow``'s payload, for a warning."""
    try:
        document = json_schema_document(workflow.payload_schema)
        schema: dict[str, object] = dict(document.schema)
        definitions = document.definitions
        shown = schema if not definitions else {**schema, "$defs": definitions}
        return stringify(shown)
    except Exception:
        return "<unavailable>"


@dataclass(slots=True, eq=False)
class _ActivationState:
    workflow_name: str
    execution_id: str
    results: dict[str, Exit[Any, Any]]
    # Every run forks its scope from here, so runs that suspended keep their
    # resources and durable finalizers until the execution finishes.
    scope: CloseableScope
    instances: set[WorkflowInstanceService] = field(default_factory=set[WorkflowInstanceService])


@dataclass(slots=True, eq=False)
class _CurrentRun:
    request: Request[Any]
    instance: WorkflowInstanceService
    # Activity awaits must wake the run after suspension without preempting it.
    activity_awaits: dict[str, int]


@dataclass(frozen=True, slots=True)
class _ActivityEntry:
    activity: Activity[Any, Any, Any]
    context: Context[Any]


class ClusterEngine:
    """The state of one cluster workflow engine and its ``Encoded``
    operations."""

    def __init__(
        self,
        sharding: ShardingService,
        storage: MessageStorageService,
        clients: RcMap[str, Callable[[str], Any], Never],
        clients_partial: RcMap[str, Callable[[str], Any], Never],
        holder: dict[str, ClusterEngine],
    ) -> None:
        self.sharding = sharding
        self.storage = storage
        self.clients = clients
        self.clients_partial = clients_partial
        holder["engine"] = self
        self.workflows: dict[str, AnyWorkflow] = {}
        self.entities: dict[str, builtins.type[Entity]] = {}
        self.partial_entities: dict[str, builtins.type[Entity]] = {}
        self.activities: dict[str, _ActivityEntry] = {}
        self.interrupted_activities: set[str] = set()
        self.deferred_state: DeferredState = make_deferred_state()
        # Rebuilds share an activation; overlapping activations have separate
        # results. Removed once the activation has closed its runs.
        self.pending_by_activation: dict[int, tuple[CloseableScope, _ActivationState]] = {}
        self.service: WorkflowEngineService = make_engine_unsafe(
            Encoded(
                register=self.register,
                execute=self.execute,
                poll=self.poll,
                interrupt=lambda workflow, execution_id: self.interrupt(
                    workflow, execution_id
                ).as_void(),
                interrupt_unsafe=self.interrupt_unsafe,
                resume=lambda workflow, execution_id: ensure_success(
                    self.resume(workflow, execution_id, "explicit")
                ),
                activity_execute=self.activity_execute,
                deferred_result=self.deferred_result,
                deferred_done=self.deferred_done,
                schedule_clock=self.schedule_clock,
                await_complete=self.await_complete,
            )
        )

    # --- entities and addresses ----------------------------------------------------------

    def ensure_entity(self, workflow: AnyWorkflow) -> builtins.type[Entity]:
        entity = self.entities.get(workflow.tag)
        if entity is None:
            entity = make_workflow_entity(workflow)
            self.workflows[workflow.tag] = workflow
            self.entities[workflow.tag] = entity
        return entity

    def ensure_partial_entity(self, workflow_name: str) -> builtins.type[Entity]:
        entity = self.partial_entities.get(workflow_name)
        if entity is None:
            entity = make_partial_workflow_entity(workflow_name)
            self.partial_entities[workflow_name] = entity
        return entity

    def entity_address_for(
        self, workflow: AnyWorkflow, entity_type: str, execution_id: str
    ) -> EntityAddress:
        entity_id = EntityId(execution_id)
        shard_group = workflow.annotations.get(ShardGroup)(entity_id)
        return EntityAddress(
            entity_type=EntityType(entity_type),
            entity_id=entity_id,
            shard_id=self.sharding.get_shard_id(entity_id, shard_group),
        )

    def run_address(self, workflow: AnyWorkflow, execution_id: str) -> EntityAddress:
        return self.entity_address_for(workflow, f"Workflow/{workflow.tag}", execution_id)

    def activation_state(self, activation: CloseableScope | None) -> _ActivationState | None:
        if activation is None:
            return None
        entry = self.pending_by_activation.get(id(activation))
        return entry[1] if entry is not None and entry[0] is activation else None

    def current_state(self) -> Effect[_ActivationState | None]:
        return service_option(CurrentActivationScope).map(
            lambda found: None if found is None else self.activation_state(found.value)
        )

    # --- storage ------------------------------------------------------------------------

    def send_discard(
        self, rpc: AnyRpc, address: EntityAddress, payload: object
    ) -> Effect[None, Any]:
        def body() -> Generator[Effect[Any, Any, Any], Any]:
            span = yield from current_span().or_die()
            envelope = make_request(
                request_id=(yield from self.sharding.get_snowflake),
                address=address,
                tag=rpc.tag,
                payload=payload,
                trace_id=span.trace_id,
                span_id=span.span_id,
                sampled=span.sampled,
            )
            message = OutgoingRequest(
                envelope=envelope,
                context=Context.empty(),
                last_received_reply=None,
                rpc=rpc,
                respond=lambda _: void,
                annotations=rpc.annotations.get(Dynamic)(rpc.annotations, envelope),
            )
            yield from self.sharding.send_outgoing(message, True)

        return gen(body)

    def request_id_for(
        self, workflow: AnyWorkflow, entity_type: str, execution_id: str, tag: str, id: str
    ) -> Effect[Snowflake | None, PersistenceError]:
        address = self.entity_address_for(workflow, entity_type, execution_id)
        return self.storage.request_id_for_primary_key(address=address, tag=tag, id=id)

    def reply_for_request_id(self, request_id: Snowflake) -> Effect[ReplyEncoded | None, Any]:
        def last(replies: list[Any]) -> ReplyEncoded | None:
            if replies and replies[-1].get("_tag") == "WithExit":
                return cast("ReplyEncoded", replies[-1])
            return None

        return self.storage.replies_for_unfiltered([request_id]).map(last)

    def request_reply(
        self, workflow: AnyWorkflow, entity_type: str, execution_id: str, tag: str, id: str
    ) -> Effect[ReplyEncoded | None, Any]:
        def found(request_id: Snowflake | None) -> Effect[ReplyEncoded | None, Any]:
            if request_id is None:
                return succeed(None)
            return self.reply_for_request_id(request_id)

        return self.request_id_for(workflow, entity_type, execution_id, tag, id).flat_map(found)

    def run_reply(
        self, workflow: AnyWorkflow, execution_id: str
    ) -> Effect[ReplyEncoded | None, Any]:
        return self.request_reply(workflow, f"Workflow/{workflow.tag}", execution_id, "run", "")

    def reset_activity_attempt(
        self,
        workflow: AnyWorkflow,
        execution_id: str,
        activity: Activity[Any, Any, Any],
        attempt: int,
    ) -> Effect[None]:
        def body() -> Generator[Effect[Any, Any, Any], Any]:
            request_id = yield from self.request_id_for(
                workflow,
                f"Workflow/{workflow.tag}",
                execution_id,
                "activity",
                activity_primary_key(activity.name, attempt),
            )
            if request_id is None:
                return
            yield from self.sharding.reset(request_id)

        return gen(body).retry(times=3, schedule=exponential(0.25)).or_die()

    def clear_clock(self, workflow: AnyWorkflow, execution_id: str) -> Effect[None, Any]:
        address = self.entity_address_for(workflow, ClockEntity.type, execution_id)
        return self.storage.clear_address(address)

    def resume(self, workflow: AnyWorkflow, execution_id: str, mode: WakeMode) -> Effect[None, Any]:
        def body() -> Generator[Effect[Any, Any, Any], Any]:
            reply = yield from self.run_reply(workflow, execution_id)
            if reply is None or not _is_suspended_reply(reply):
                return
            # Replies without ``failed`` retain automatic wakes for compatibility.
            if mode == "automatic" and _is_failed_reply(reply):
                return
            reset = yield from self.sharding.reset(
                Snowflake(int(reply["requestId"])),
                expected_reply_id=Snowflake(int(reply["id"])),
            )
            if not reset:
                return (yield from fail(RuntimeError("Failed to reset workflow run")))
            yield from self.sharding.poll_storage

        return gen(body)

    def interrupt_pending(self, instance: WorkflowInstanceService) -> Effect[bool]:
        """Whether a persisted interrupt is pending for ``instance``:
        activations load it when they start, so this reads only memory."""

        def check(state: _ActivationState | None) -> bool:
            return (
                state is not None
                and state.workflow_name == instance.workflow.tag
                and state.execution_id == instance.execution_id
                and INTERRUPT_SIGNAL.name in state.results
            )

        return self.current_state().map(check)

    def send_resume_parent(self, parent: Parent, child_execution_id: str) -> Effect[None, Any]:
        def body() -> Generator[Effect[Any, Any, Any], Any]:
            workflow_name = parent["workflowName"]
            request_id = yield from self.request_id_for(
                self.workflows[workflow_name],
                f"Workflow/{workflow_name}",
                parent["executionId"],
                "resume",
                child_execution_id,
            )
            if request_id is None:
                make_client = yield from self.clients_partial.get(workflow_name)
                client: Any = make_client(parent["executionId"])
                discard: Effect[None, Any] = client.resume.discard(
                    ResumePayload(childExecutionId=child_execution_id)
                )
                return (yield from discard)
            reply = yield from self.reply_for_request_id(request_id)
            if reply is None:
                return
            yield from self.sharding.reset(request_id)

        return scoped(gen(body))

    def await_run_reply(
        self,
        workflow: AnyWorkflow,
        request: EnvelopeRequest[Any],
        is_settled: Callable[[ReplyEncoded], bool],
    ) -> Effect[bool, Any]:
        """Wait for the run's next reply, subscribing before reading
        storage, so a reply cannot fall between the read and the
        subscription: ``True`` when the stored reply already settles the
        wait, ``False`` when a new reply arrived."""

        def body() -> Generator[Effect[Any, Any, Any], Any, bool]:
            waiter: Fiber[None, Any] = yield from self.storage.register_reply_handler(
                OutgoingRequest(
                    envelope=request,
                    context=Context.empty(),
                    rpc=run_rpc_of(self.ensure_entity(workflow)),
                    last_received_reply=None,
                    respond=lambda _: void,
                    annotations=Context.empty(),
                )
            ).fork_scoped(start_immediately=True)
            reply = yield from self.reply_for_request_id(request.request_id)
            if reply is not None and is_settled(reply):
                return True
            yield from waiter.join()
            return False

        return scoped(gen(body))

    def wait_for_run_reply(self, workflow: AnyWorkflow, request: Request[Any]) -> Effect[None]:
        """A child or deferred may complete while a run is still unwinding:
        wait for the run's reply, so the wake cannot fall between the run's
        last read and its suspended reply."""

        def on_cause(cause: Cause[Any]) -> Effect[None, Any]:
            if cluster_abandon.is_cause(cause):
                return cluster_abandon.interrupt
            return fail_cause(cause)

        return cast(
            "Effect[None]",
            self.await_run_reply(workflow, request, lambda _: True)
            .as_void()
            .pipe(catch_tag(EntityNotAssignedToRunner, lambda _: cluster_abandon.interrupt))
            .catch_cause(on_cause),
        )

    def await_complete(self, workflow: AnyWorkflow, execution_id: str) -> Effect[None]:
        """Wake an external caller once its run publishes a reply other than
        ``Suspended``. Replies are only observed on the runner that saves
        them, so callers on other runners, and any failure here, leave
        delivery to the caller's retry schedule."""

        def body() -> Generator[Effect[Any, Any, Any], Any]:
            address = self.run_address(workflow, execution_id)
            if not self.sharding.has_shard_id(address.shard_id):
                return (yield from never)
            request_id = yield from self.storage.request_id_for_primary_key(
                address=address, tag="run", id=""
            )
            if request_id is None:
                return (yield from never)
            request = make_request(
                request_id=request_id, address=address, tag="run", payload=RunPayload()
            )
            # A replay that suspends again re-arms the wait, so it does not
            # spend a step of the caller's retry schedule.
            settled = False
            while not settled:
                settled = yield from self.await_run_reply(
                    workflow, request, lambda reply: not _is_suspended_reply(reply)
                )

        return gen(body).catch_cause(lambda _: never)

    def interrupt(self, workflow: AnyWorkflow, execution_id: str) -> Effect[Snowflake | None]:
        def body() -> Generator[Effect[Any, Any, Any], Any, Snowflake | None]:
            self.ensure_entity(workflow)
            request_id = yield from self.request_id_for(
                workflow, f"Workflow/{workflow.tag}", execution_id, "run", ""
            )
            if request_id is None:
                return None
            reply = yield from self.reply_for_request_id(request_id)
            if reply is not None and not _is_suspended_reply(reply):
                return None
            yield from self.service.deferred_done(
                INTERRUPT_SIGNAL,
                workflow_name=workflow.tag,
                execution_id=execution_id,
                deferred_name=INTERRUPT_SIGNAL.name,
                exit=Success(None),
            )
            return request_id

        return _retry_persistence(gen(body))

    def interrupt_unsafe(self, workflow: AnyWorkflow, execution_id: str) -> Effect[None]:
        def body() -> Generator[Effect[Any, Any, Any], Any]:
            request_id = yield from self.interrupt(workflow, execution_id)
            if request_id is None:
                return
            entity = self.ensure_entity(workflow)
            envelope = InterruptEnvelope(
                id=(yield from self.sharding.get_snowflake),
                address=self.run_address(workflow, execution_id),
                request_id=request_id,
            )
            yield from self.sharding.send_outgoing(
                OutgoingEnvelope(envelope=envelope, rpc=run_rpc_of(entity)), False
            ).or_die()

        return gen(body)

    # --- registration -------------------------------------------------------------------

    def register(self, workflow: AnyWorkflow, execute: Handler, /) -> Effect[None, Never, Scope]:
        def body() -> Effect[None, Never, Scope]:
            existing = self.workflows.get(workflow.tag)
            registration = self.sharding.register_entity(
                self.ensure_entity(workflow),
                gen(lambda: self._build_handlers(workflow, execute)),
                # Alongside the run, let deferred handlers briefly acquire a
                # permit to fork their wake and return an asynchronous reply.
                EntityOptions(concurrency=2, max_idle_time=ENTITY_MAX_IDLE_TIME),
            )
            if existing is None or existing is workflow:
                return registration
            return log_warning(
                f'Workflow "{workflow.tag}" is already registered with payload shape '
                f"{payload_shape(existing)}; ignoring duplicate definition with payload "
                f"shape {payload_shape(workflow)}"
            ).and_then(registration)

        return suspend(body)

    def _load_activation(
        self, workflow: AnyWorkflow, execution_id: str, activation: CloseableScope
    ) -> Generator[Effect[Any, Any, Any], Any, _ActivationState]:
        pending = self.activation_state(activation)
        if pending is not None:
            return pending
        results: dict[str, Exit[Any, Any]] = {}
        # A new owner must see an interrupt persisted before it took over.
        # Publish the cache only once loaded, so a retried build repeats a
        # failed lookup.
        interrupt = yield from self.request_reply(
            workflow,
            f"Workflow/{workflow.tag}",
            execution_id,
            "deferred",
            INTERRUPT_SIGNAL.name,
        ).or_die()
        if interrupt is not None:
            results[INTERRUPT_SIGNAL.name] = _deferred_exit(interrupt)
        pending = _ActivationState(workflow.tag, execution_id, results, CloseableScope())
        key = id(activation)

        def forget() -> None:
            entry = self.pending_by_activation.get(key)
            if entry is not None and entry[1] is pending:
                del self.pending_by_activation[key]

        yield from activation.add_finalizer(
            lambda _: self.close_runs(pending, abandoned=True).and_then(sync(forget))
        )
        self.pending_by_activation[key] = (activation, pending)
        return pending

    def close_runs(self, state: _ActivationState, *, abandoned: bool) -> Effect[None]:
        """Close the scopes retained by suspended runs. The latest run
        already closed its own scope with its real exit, so earlier
        finalizers observe success and skip superseded compensations.
        Abandonment releases owner-local resources without running durable
        finalizers, so the run can replay elsewhere."""

        def run() -> Effect[None]:
            scope = state.scope
            if abandoned:
                for instance in state.instances:
                    instance.abandoned = True
            state.instances.clear()
            state.scope = CloseableScope()
            return scope.close(Success(None))

        return suspend(run)

    def _build_handlers(
        self, workflow: AnyWorkflow, execute: Handler
    ) -> Generator[Effect[Any, Any, Any], Any, EntityHandlers[Any, Any]]:
        address = yield from CurrentAddress()
        execution_id = str(address.entity_id)
        activation = yield from CurrentActivationScope()
        pending = yield from self._load_activation(workflow, execution_id, activation)
        return _Handlers(
            self,
            workflow=workflow,
            execute=execute,
            execution_id=execution_id,
            activation=activation,
            pending=pending,
        ).build()

    # --- execution ----------------------------------------------------------------------

    def execute(
        self,
        workflow: AnyWorkflow,
        /,
        *,
        execution_id: str,
        payload: object,
        discard: bool,
        parent: WorkflowInstanceService | None,
        detached: bool,
    ) -> Effect[Result[Any, Any] | None]:
        self.ensure_entity(workflow)
        parent_key: Parent | None = None
        if parent is not None:
            # A detached child keeps its parent for observability only.
            parent_key = Parent(workflowName=parent.workflow.tag, executionId=parent.execution_id)
            if detached:
                parent_key["detached"] = True
        run = run_payload(workflow, payload, parent_key)

        def call(make_client: Callable[[str], Any]) -> Effect[Any, Any]:
            client = make_client(execution_id)
            return client.run.discard(run) if discard else client.run(run)

        return scoped(self.clients.get(workflow.tag).flat_map(call).or_die())

    def poll(self, workflow: AnyWorkflow, execution_id: str) -> Effect[Result[Any, Any] | None]:
        def body() -> Generator[Effect[Any, Any, Any], Any, Result[Any, Any] | None]:
            entity = self.ensure_entity(workflow)
            schema = to_codec_json(exit_schema(run_rpc_of(entity)))
            reply = yield from self.run_reply(workflow, execution_id)
            if reply is None:
                return None
            exit = yield from decode_unknown_effect(schema)(reply["exit"])
            return (yield from from_exit(cast("Exit[Result[Any, Any], Any]", exit)))

        return gen(body).or_die()

    def activity_execute(
        self, activity: Activity[Any, Any, Any], attempt: int
    ) -> Effect[Result[Any, Any], Never, WorkflowInstance]:
        def body() -> Generator[Effect[Any, Any, Any], Any, Result[Any, Any]]:
            services = yield from context()
            instance = services.get_unsafe(WorkflowInstance)
            yield from annotate_current_span("executionId", instance.execution_id)
            activity_id = f"{instance.execution_id}/{activity.name}"
            # A pending interrupt replays only to rebuild compensations, so it
            # must not run new activities. Finalizers run once ``interrupted``
            # is set.
            if not instance.interrupted and (yield from self.interrupt_pending(instance)):
                reply = yield from self.request_reply(
                    instance.workflow,
                    f"Workflow/{instance.workflow.tag}",
                    instance.execution_id,
                    "activity",
                    activity_primary_key(activity.name, attempt),
                ).or_die()
                # Suspend so ``on_exit`` applies the interrupt to the run.
                if reply is None or _is_suspended_reply(reply):
                    return Suspended()
            make_client = yield from self.clients_partial.get(instance.workflow.tag)
            client: Any = make_client(instance.execution_id)
            while True:
                if activity_id not in self.activities:
                    self.activities[activity_id] = _ActivityEntry(activity, services)
                call: Effect[Result[Any, Any], Any] = client.activity(
                    ActivityPayload(
                        name=activity.name,
                        attempt=attempt,
                        withTransaction=activity.annotations.get(WithTransaction),
                    )
                )
                result = yield from call.or_die()
                # If the activity has suspended and did not execute, resume it
                # by resetting the attempt and executing it again.
                if isinstance(result, Suspended) and (
                    activity_id in self.activities or activity_id in self.interrupted_activities
                ):
                    yield from self.reset_activity_attempt(
                        instance.workflow, instance.execution_id, activity, attempt
                    )
                    continue
                self.activities.pop(activity_id, None)
                return result

        return cast("Effect[Result[Any, Any], Never, WorkflowInstance]", scoped(gen(body)))

    def deferred_result(
        self, deferred: DurableDeferred[Any, Any]
    ) -> Effect[Exit[Any, Any] | None, Never, WorkflowInstance]:
        def body() -> Generator[Effect[Any, Any, Any], Any, Exit[Any, Any] | None]:
            instance = yield from WorkflowInstance()
            state = yield from self.current_state()
            # Captured contexts can cross workflow boundaries. Never use another
            # execution's completion, even if its deferred has the same name.
            if (
                state is not None
                and state.workflow_name == instance.workflow.tag
                and state.execution_id == instance.execution_id
            ):
                found = state.results.get(deferred.name)
                if found is not None:
                    return found
            reply = yield from self.request_reply(
                instance.workflow,
                f"Workflow/{instance.workflow.tag}",
                instance.execution_id,
                "deferred",
                deferred.name,
            )
            return None if reply is None else _deferred_exit(reply)

        return cast(
            "Effect[Exit[Any, Any] | None, Never, WorkflowInstance]",
            _retry_persistence(gen(body)),
        )

    def deferred_done(
        self, *, workflow_name: str, execution_id: str, deferred_name: str, exit: Exit[Any, Any]
    ) -> Effect[None]:
        def body() -> Generator[Effect[Any, Any, Any], Any]:
            found = yield from service_option(WorkflowInstance)
            # Activities run with their own instance, so their completions
            # still wake a run that suspended before reaching the await. An
            # interrupt must wake the run even when it signals itself.
            if (
                found is not None
                and found.value.execution_id == execution_id
                and deferred_name != INTERRUPT_SIGNAL.name
            ):
                found.value.completed_deferreds.add(deferred_name)
            workflow = self.workflows.get(workflow_name)
            payload = DeferredPayload(name=deferred_name, exit=exit)
            if workflow is not None:
                address = self.entity_address_for(
                    workflow, f"Workflow/{workflow_name}", execution_id
                )
                return (yield from self.send_discard(DeferredRpc, address, payload).or_die())
            make_client = yield from self.clients_partial.get(workflow_name)
            yield from make_client(execution_id).deferred.discard(payload).or_die()

        return scoped(gen(body))

    def schedule_clock(
        self, workflow: AnyWorkflow, execution_id: str, clock: DurableClock
    ) -> Effect[None]:
        def send(at: Any) -> Effect[None, Any]:
            millis = (at - _EPOCH) / timedelta(milliseconds=1) + to_millis(clock.duration)
            wake_up = _EPOCH + timedelta(milliseconds=ceil(millis))
            payload = ClockPayload(name=clock.name, workflowName=workflow.tag, wakeUp=wake_up)
            address = self.entity_address_for(workflow, ClockEntity.type, execution_id)
            return self.send_discard(ClockRpc, address, payload)

        return now().flat_map(send).or_die()


class _Handlers:
    """The handlers of one workflow entity activation (Effect's
    ``register`` build)."""

    def __init__(
        self,
        engine: ClusterEngine,
        *,
        workflow: AnyWorkflow,
        execute: Handler,
        execution_id: str,
        activation: CloseableScope,
        pending: _ActivationState,
    ) -> None:
        self.engine = engine
        self.workflow = workflow
        self.execute = execute
        self.execution_id = execution_id
        self.activation = activation
        self.pending = pending
        # Retain awaited names through reply persistence, including
        # suspension. Replays reuse the request id but track a fresh set of
        # awaits.
        self.current_run: _CurrentRun | None = None
        # Concurrent automatic wakes share one wait for the current run to
        # publish its reply. Explicit wakes cannot be dropped, because an
        # automatic wake skips the reset of a failure suspension, so they
        # wait outside the gate. Operator resume does not use the gate.
        self.resume_gate = Semaphore(1)

    def build(self) -> EntityHandlers[Any, Any]:
        entity = self.engine.ensure_entity(self.workflow)
        rpcs = entity.rpcs
        handlers: Any = entity.handlers()
        handlers = handlers.handle(rpcs["run"])(self.run)
        handlers = handlers.handle(rpcs["activity"])(self.activity)
        handlers = handlers.handle(rpcs["deferred"])(self.deferred)
        handlers = handlers.handle(rpcs["resume"])(self.resume)
        return cast("EntityHandlers[Any, Any]", handlers)

    def wait_for_current_run_reply(self) -> Effect[None]:
        return suspend(
            lambda: (
                void
                if self.current_run is None
                else self.engine.wait_for_run_reply(self.workflow, self.current_run.request)
            )
        )

    def resume_current_run(self, mode: WakeMode) -> Effect[None]:
        engine = self.engine
        if mode == "explicit":
            return ensure_success(
                self.wait_for_current_run_reply().and_then(
                    engine.resume(self.workflow, self.execution_id, mode)
                )
            )
        # Release the gate before reset can start another run, so later
        # completions can wake that replay.
        return ensure_success(
            self.resume_gate.with_permits_if_available(self.wait_for_current_run_reply()).flat_map(
                lambda waited: (
                    void
                    if waited is None
                    else engine.resume(self.workflow, self.execution_id, mode)
                )
            )
        )

    def run(self, request: Request[RunPayload]) -> Effect[Any, Any, Any]:
        engine = self.engine
        workflow = self.workflow
        execution_id = self.execution_id
        pending = self.pending
        # Each run gets a fresh scope under the activation's parent, so
        # replays rebuild compensations while suspended runs keep theirs.
        instance = WorkflowInstanceService.initial(
            workflow, execution_id, scope=pending.scope.fork_unsafe()
        )
        pending.instances.add(instance)
        self.current_run = _CurrentRun(request, instance, {})
        parent = request.payload.parent
        suspend_on_failure = workflow.annotations.get_unsafe(SuspendOnFailure)

        def on_run_exit(exit: Exit[Any, Any]) -> Effect[None, Never, Any]:
            # An annotated cluster abandonment means this owner can no longer
            # finish the run. Do not resume the parent, but still allow a
            # pending durable interrupt to take effect.
            instance.abandoned = instance.abandoned or (
                isinstance(exit, Failure) and cluster_abandon.is_cause(exit.cause)
            )
            if instance.abandoned:
                instance.suspended = False
            if (
                not instance.suspended
                and not instance.abandoned
                and not (suspend_on_failure and isinstance(exit, Failure))
            ):
                resume_parent: Effect[None] = (
                    ensure_success(engine.send_resume_parent(parent, execution_id))
                    if parent is not None and not parent.get("detached", False)
                    else void
                )
                if isinstance(exit, Success) or not exit.cause.has_interrupts_only:
                    return resume_parent

                # ``interrupt_unsafe`` cuts the run off without a result and its
                # replay applies the interrupt. Retain the scope like a
                # suspended run, so ``close_runs`` supersedes it and only the
                # final run's compensations observe the interrupt.
                def after_interrupt(found: Exit[Any, Any] | None) -> Effect[None]:
                    if found is None:
                        return resume_parent
                    instance.suspended = True
                    return void

                return engine.service.deferred_result(INTERRUPT_SIGNAL).flat_map(after_interrupt)

            def apply_interrupt(found: Exit[Any, Any] | None) -> Effect[None]:
                if found is None:
                    return void
                instance.suspended = False
                instance.interrupted = True
                return (
                    engine.clear_clock(workflow, execution_id)
                    .ignore()
                    .and_then(_WithFiber(lambda fiber: fiber.interrupt().interruptible()))
                )

            return engine.service.deferred_result(INTERRUPT_SIGNAL).flat_map(apply_interrupt)

        def close(exit: Exit[Result[Any, Any], Any]) -> Effect[None]:
            if isinstance(exit, Success) and isinstance(exit.value, Suspended):
                return void
            return engine.close_runs(pending, abandoned=instance.abandoned)

        body = into_result(
            self.execute(workflow_payload(workflow, request.payload), execution_id).on_exit(
                on_run_exit
            )
        ).on_exit(close)
        return engine.deferred_state.track_run(instance, body).pipe(
            # Request middleware and local callers may carry another entity's context.
            provide_service(CurrentActivationScope, self.activation)
        )

    def activity(self, request: Request[ActivityPayload]) -> Effect[Any, Any, Any]:
        engine = self.engine
        payload = request.payload
        activity_id = f"{self.execution_id}/{payload.name}"
        current = self.current_run
        instance = WorkflowInstanceService.initial(
            self.workflow,
            self.execution_id,
            awaited_deferreds=None if current is None else current.activity_awaits,
        )
        engine.interrupted_activities.discard(activity_id)
        entry = engine.activities.get(activity_id)
        if entry is None:
            # Replay may never register a losing race activity. Answer it
            # without waiting; a later registration can reset this reply.
            return rpc_wrap(fork=True)(succeed(Suspended()))
        services = (
            entry.context.add(WorkflowInstance, instance)
            .add(CurrentActivationScope, self.activation)
            .add(CurrentAttempt, payload.attempt)
        )

        def on_cause(cause: Cause[Any]) -> Effect[Result[Any, Any], Any]:
            # Store interrupts as suspensions only when the client asked.
            if any(
                isinstance(reason, Interrupt) and ClientAbort in reason.annotations
                for reason in cause.reasons
            ):
                engine.interrupted_activities.add(activity_id)
                return succeed(Suspended())
            return fail_cause(cause)

        def forget() -> None:
            engine.activities.pop(activity_id, None)

        effect = (
            into_result(entry.activity.execute_encoded.pipe(provide_context(services)))
            .catch_cause(on_cause)
            .pipe(provide_service(WorkflowInstance, instance))
            .pipe(provide_service(CurrentAttempt, payload.attempt))
            .ensuring(sync(forget))
        )
        return rpc_wrap(fork=True, uninterruptible=True)(effect)

    def deferred(self, request: Request[DeferredPayload]) -> Effect[Any, Any, Any]:
        payload = request.payload
        name = payload.name
        self.pending.results[name] = payload.exit
        mode: WakeMode = "explicit" if name == INTERRUPT_SIGNAL.name else "automatic"
        engine = self.engine

        # Await registers before reading the cache. If this run has not
        # registered yet, a later await will see the result just stored.
        # Check when the wake runs and skip preemption too: interrupting a
        # later await would require waiting for its reply before reset. A
        # run completing its own deferred also reads it from the cache when
        # it awaits later, unless an activity is already parked on it. A run
        # only reads ``INTERRUPT_SIGNAL`` while suspending, so an interrupt
        # always waits for the current run's reply before it resets the run.
        def wake() -> Effect[None]:
            current = self.current_run
            if (
                current is not None
                and mode == "automatic"
                and name not in current.instance.awaited_deferreds
            ):
                if name in current.activity_awaits:
                    # Hold an activity wake until the run has published its reply.
                    return self.resume_current_run(mode)
                if name in current.instance.completed_deferreds:
                    return void
                return ensure_success(engine.resume(self.workflow, self.execution_id, mode))
            return engine.deferred_state.deferred_done(self.execution_id, name).and_then(
                self.resume_current_run(mode)
            )

        # An asynchronous reply releases the RPC concurrency permit while the
        # wake waits; the pending request still occupies mailbox capacity.
        # The activation owns the wake so it survives handler rebuilds, but
        # activation shutdown still interrupts it for durable redelivery.
        reply = Deferred[Any, Any]()
        return (
            reply.into(suspend(wake).as_(payload.exit))
            .fork_in(self.activation, start_immediately=True)
            .as_(reply)
        )

    def resume(self, _: Request[ResumePayload]) -> Effect[Any, Any, Any]:
        return rpc_wrap(fork=True, uninterruptible=True)(self.resume_current_run("automatic"))


# --- the durable clock entity -----------------------------------------------------------


def _clock_handlers() -> Generator[Effect[Any, Any, Any], Any, EntityHandlers[Any, Any]]:
    engine = yield from WorkflowEngine()
    address = yield from CurrentAddress()
    execution_id = str(address.entity_id)

    def run(request: Request[ClockPayload]) -> Effect[None]:
        deferred = make_clock(name=request.payload.name, duration=0).deferred
        return ensure_success(
            engine.deferred_done(
                deferred,
                workflow_name=request.payload.workflowName,
                execution_id=execution_id,
                deferred_name=deferred.name,
                exit=Success(None),
            )
        )

    return ClockEntity.handlers().handle(ClockEntity.run)(run)


clock_entity_layer = ClockEntity.to_layer_effect(
    gen(_clock_handlers), max_idle_time=ENTITY_MAX_IDLE_TIME
)


def make() -> Effect[WorkflowEngineService, Never, Sharding | MessageStorage | Scope]:
    """A ``WorkflowEngineService`` backed by cluster sharding and message
    storage (Effect's ``ClusterWorkflowEngine.make``)."""

    def body() -> Generator[Effect[Any, Any, Any], Any, WorkflowEngineService]:
        sharding = yield from Sharding()
        storage = yield from MessageStorage()
        holder: dict[str, ClusterEngine] = {}

        def lookup(workflow_name: str) -> Effect[Callable[[str], Any]]:
            engine = holder["engine"]
            entity = engine.entities.get(workflow_name)
            if entity is None:
                return die(RuntimeError(f"Workflow {workflow_name} not registered"))
            return engine.clients_partial.invalidate(workflow_name).and_then(
                cast("Effect[Callable[[str], Any]]", entity.client())
            )

        def lookup_partial(workflow_name: str) -> Effect[Callable[[str], Any]]:
            engine = holder["engine"]
            entity = engine.entities.get(workflow_name) or engine.ensure_partial_entity(
                workflow_name
            )
            return cast("Effect[Callable[[str], Any]]", entity.client())

        clients = yield from RcMap.make(lookup, idle_time_to_live=300)
        clients_partial = yield from RcMap.make(lookup_partial, idle_time_to_live=300)
        return ClusterEngine(sharding, storage, clients, clients_partial, holder).service

    return cast(
        "Effect[WorkflowEngineService, Never, Sharding | MessageStorage | Scope]", gen(body)
    )


__all__ = [
    "ENTITY_MAX_IDLE_TIME",
    "INTERRUPT_SIGNAL",
    "ClusterEngine",
    "clock_entity_layer",
    "ensure_success",
    "make",
    "payload_shape",
]
