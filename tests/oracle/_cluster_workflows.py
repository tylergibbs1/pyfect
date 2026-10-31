"""The workflows and helpers of Effect's
``test/cluster/ClusterWorkflowEngine.test.ts``."""

from __future__ import annotations

from collections.abc import Callable, Generator
from dataclasses import replace
from datetime import datetime
from typing import Any, Never, TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.cluster import (
    cluster_workflow_engine,
    message_storage,
    runner_health,
    runner_storage,
    runners,
    sharding,
    sharding_config,
)
from pyfect.cluster.cluster_schema import Persisted
from pyfect.cluster.entity import Entity
from pyfect.cluster.entity_address import EntityAddress
from pyfect.cluster.entity_id import EntityId
from pyfect.cluster.entity_type import EntityType
from pyfect.cluster.message_storage import (
    MemoryDriver,
    MemoryDriverService,
    MessageStorage,
    MessageStorageService,
)
from pyfect.cluster.sharding import Sharding
from pyfect.cluster.sharding_config import ShardingConfigService
from pyfect.context import Tag
from pyfect.date_time import now
from pyfect.duration import Seconds
from pyfect.rpc import make as make_rpc
from pyfect.rpc._rpc import exit_schema
from pyfect.scope import Scope
from pyfect.workflow import Complete, Suspended, activity, durable_clock, durable_deferred, workflow
from pyfect.workflow.workflow import SuspendOnFailure, result_schema
from pyfect.workflow.workflow_engine import WorkflowEngine, WorkflowInstance

type FlagMap = dict[str, bool | int | float | str]


class Flags(Tag[FlagMap], key="Flags"):
    pass


flags_layer = fx.layer.sync(Flags, dict)


class Empty(TypedDict):
    pass


class IdPayload(TypedDict):
    id: str


class EmailPayload(TypedDict):
    to: str
    id: str


EMPTY = S.Struct(Empty)
ID = S.Struct(IdPayload)


def config(**overrides: Any) -> ShardingConfigService:
    return replace(
        sharding_config.DEFAULTS,
        **{
            "shards_per_group": 300,
            "available_shard_groups": ("default", "workflow"),
            "assigned_shard_groups": ("default", "workflow"),
            "entity_mailbox_capacity": 10,
            "entity_termination_timeout": Seconds(0),
            "entity_message_poll_interval": Seconds(5),
            "send_retry_interval": Seconds(0.1),
            **overrides,
        },
    )


def make_test_workflow_engine(
    *,
    config_overrides: dict[str, Any] | None = None,
    sharding_layer: fx.Layer[Any, Never, Any] | None = None,
    storage_layer: fx.Layer[Any, Never, Any] | None = None,
) -> fx.Layer[Any, Never, Never]:
    """Effect's ``makeTestWorkflowEngine``."""
    return (
        cluster_workflow_engine.layer.pipe(
            fx.layer.provide_merge(sharding.layer if sharding_layer is None else sharding_layer)
        )
        .pipe(fx.layer.provide(runners.layer_noop))
        .pipe(
            fx.layer.provide_merge(
                message_storage.layer_memory if storage_layer is None else storage_layer
            )
        )
        .pipe(fx.layer.provide(runner_storage.layer_memory))
        .pipe(fx.layer.provide(runner_health.layer_noop))
        .pipe(fx.layer.provide(sharding_config.layer(config(**(config_overrides or {})))))
    )


def poll_until(
    wf: workflow.Workflow[Any, Any, Any],
    execution_id: str,
    tag: type[Complete[Any, Any]] | type[Suspended],
) -> Generator[Any, Any, Any]:
    service = yield from Sharding()
    result = yield from wf.poll(execution_id)
    for _ in range(2000):
        if isinstance(result, tag):
            break
        yield from fx.yield_now()
        yield from testing.adjust(0.001)
        yield from service.poll_storage
        result = yield from wf.poll(execution_id)
    assert isinstance(result, tag), f"workflow must reach {tag.__name__}"
    return result


def advance_until(
    ready: Callable[[], bool], message: str, step: float = 0.001, rounds: int = 2000
) -> Generator[Any, Any]:
    for _ in range(rounds):
        if ready():
            break
        yield from testing.adjust(step)
    assert ready(), message


def poll_storage_until(ready: Callable[[], bool], message: str) -> Generator[Any, Any]:
    """``poll_storage`` signals the storage loop; it does not await processing."""
    service = yield from Sharding()
    for _ in range(2000):
        if ready():
            break
        yield from service.poll_storage
        yield from testing.adjust(0.001)
    assert ready(), message


def requests_of(driver: MemoryDriverService) -> list[Any]:
    return list(driver.encoded.requests.values())


def wait_for_clock(driver: MemoryDriverService, name: str) -> Generator[Any, Any]:
    def persisted() -> bool:
        return any(
            entry.envelope["_tag"] == "Request"
            and entry.envelope["address"]["entityType"] == "Workflow/-/DurableClock"
            and entry.envelope["payload"]["name"] == name
            for entry in requests_of(driver)
        )

    yield from poll_storage_until(persisted, f"durable clock {name} must be persisted")


test_workflow_engine = make_test_workflow_engine()


# --- EmailWorkflow -----------------------------------------------------------------------


class SendEmailError(S.TaggedError, identifier="SendEmailError"):
    message: str


EmailWorkflow = workflow.make(
    "EmailWorkflow",
    payload=S.Struct(EmailPayload),
    error=SendEmailError,
    idempotency_key=lambda payload: payload["id"],
)

EmailTrigger = durable_deferred.make("EmailTrigger", success=S.String)


def _email(payload: EmailPayload, _: str):
    @fx.gen
    def body():
        flags = yield from Flags()

        def finalizer(_: Any) -> fx.Effect[None]:
            return fx.sync(lambda: flags.__setitem__("finalizer", True))

        yield from fx.add_finalizer(finalizer)

        @fx.gen
        def send():
            attempt = yield from activity.CurrentAttempt()
            if attempt != 5:
                return (
                    yield from fx.fail(
                        SendEmailError(
                            message=f"Failed to send email for {payload['id']} on attempt {attempt}"
                        )
                    )
                )

        def compensation(_: Any, __: Any) -> fx.Effect[None]:
            return fx.sync(lambda: flags.__setitem__("compensation", True))

        yield from (
            activity.make(name="SendEmail", error=SendEmailError, execute=send)
            .pipe(EmailWorkflow.with_compensation(compensation))
            .pipe(activity.retry(times=5))
        )

        if payload["to"] == "compensation":
            return (yield from fx.fail(SendEmailError(message="Compensation triggered")))

        @fx.gen
        def sleep_then_now():
            # suspended inside Activity
            yield from durable_clock.sleep(name="Some sleep", duration=10, in_memory_threshold=0)
            return (yield from now())

        result = yield from activity.make(
            name="Sleep", success=S.DateTimeUtc, execute=sleep_then_now
        )
        # test serialization from Activity
        assert isinstance(result, datetime)

        yield from EmailTrigger.token()

        def caught(_: Any) -> fx.Effect[None]:
            flags["catchCause"] = True
            return fx.void

        # suspended outside Activity
        yield from (
            EmailTrigger.wait()
            .catch_cause(caught)
            .ensuring(fx.sync(lambda: flags.__setitem__("ensuring", True)))
        )

    return body


email_workflow_layer = EmailWorkflow.to_layer(_email)


# --- Parent and child --------------------------------------------------------------------

ParentWorkflow = workflow.make(
    "ParentWorkflow", payload=ID, idempotency_key=lambda payload: payload["id"]
)
ChildWorkflow = workflow.make(
    "ChildWorkflow", payload=ID, idempotency_key=lambda payload: payload["id"]
)
ChildDeferred = durable_deferred.make("ChildDeferred")


def _parent(payload: IdPayload, _: str):
    @fx.gen
    def body():
        flags = yield from Flags()
        instance = yield from WorkflowInstance()

        def finalizer(_: Any) -> fx.Effect[None]:
            return fx.sync(lambda: flags.__setitem__("parent-suspended", instance.suspended))

        yield from fx.add_finalizer(finalizer)
        yield from ChildWorkflow.execute({"id": payload["id"]})
        flags["parent-end"] = True

    return body


def _child(_payload: IdPayload, _: str):
    @fx.gen
    def body():
        flags = yield from Flags()
        flags["child-token"] = yield from ChildDeferred.token()
        yield from ChildDeferred.wait()
        flags["child-end"] = True

    return body


parent_workflow_layer = ParentWorkflow.to_layer(_parent)
child_workflow_layer = ChildWorkflow.to_layer(_child)


# --- SuspendOnFailure, catchCause, defects -----------------------------------------------

SuspendOnFailureWorkflow = workflow.make(
    "SuspendOnFailureWorkflow", payload=ID, idempotency_key=lambda payload: payload["id"]
).annotate(SuspendOnFailure, True)


def _suspend_on_failure(_payload: IdPayload, _: str):
    @fx.gen
    def body():
        flags = yield from Flags()
        instance = yield from WorkflowInstance()

        def finalizer(_: Any) -> fx.Effect[None]:
            def record() -> None:
                flags["suspended"] = instance.suspended
                assert instance.cause is not None
                flags["cause"] = instance.cause.pretty()

            return fx.sync(record)

        yield from fx.add_finalizer(finalizer)
        yield from activity.make(name="fail", execute=fx.die(RuntimeError("boom")))

    return body


suspend_on_failure_workflow_layer = SuspendOnFailureWorkflow.to_layer(_suspend_on_failure)

CatchWorkflow = workflow.make(
    "CatchWorkflow", payload=ID, idempotency_key=lambda payload: payload["id"]
)


def _catch(_payload: IdPayload, _: str):
    @fx.gen
    def body():
        flags = yield from Flags()

        def log(cause: Any) -> Any:
            def run() -> fx.Effect[None]:
                flags["catch"] = True
                return fx.log(cause)

            return activity.make(name="log", execute=fx.suspend(run))

        yield from activity.make(name="fail", execute=fx.die(RuntimeError("boom"))).catch_cause(log)

    return body


catch_workflow_layer = CatchWorkflow.to_layer(_catch)

ErrorDefectWorkflow = workflow.make(
    "ErrorDefectWorkflow", payload=ID, idempotency_key=lambda payload: payload["id"]
)


class _BatchRequestError(Exception):
    def __init__(self) -> None:
        super().__init__("Batch request error: Request timed out")
        # A property JSON cannot hold (Effect's ``1n``).
        self.nonJson = 1


def _error_defect(_payload: IdPayload, _: str):
    return activity.make(name="raw-error-defect", execute=fx.die(_BatchRequestError()))


error_defect_workflow_layer = ErrorDefectWorkflow.to_layer(_error_defect)


# --- shared storage across runners -------------------------------------------------------


def make_shared_storage() -> fx.Effect[MessageStorageService, Never, Scope]:
    """Storage shared across runners, so a later runner sees the previous
    runner's residue."""
    return (
        message_storage.layer_memory.pipe(fx.layer.provide(sharding_config.layer_defaults))
        .build()
        .map(lambda ctx: ctx.get_unsafe(MessageStorage))
    )


def override_storage(storage: MessageStorageService, **overrides: Any) -> MessageStorageService:
    """Effect's ``{ ...storage, method: ... }``: ``storage`` with some
    methods replaced, sharing its reply handlers."""
    methods = {name: staticmethod(f) for name, f in overrides.items()}
    cls = type("OverriddenStorage", (MessageStorageService,), methods)
    return cls(storage.base, storage._handlers, storage._handlers_by_shard)  # pyright: ignore[reportPrivateUsage]


def storage_layer_of(storage: MessageStorageService) -> fx.Layer[MessageStorage]:
    return fx.layer.succeed(MessageStorage, storage)


def unanswered_activity_storage(storage: MessageStorageService) -> fx.Layer[MessageStorage]:
    """Preserve the unanswered request across runner teardown."""

    def save_reply(reply: Any) -> fx.Effect[None, Any]:
        return fx.never if reply.rpc.tag == "activity" else storage.save_reply(reply)

    return storage_layer_of(override_storage(storage, save_reply=save_reply))


class RecoveryActivityPayload(S.Class):
    name: str
    attempt: int
    withTransaction: bool

    def primary_key(self) -> str:
        return f"{self.name}/{self.attempt}"


RecoveryActivityRpc = make_rpc(
    "activity",
    payload=RecoveryActivityPayload,
    success=result_schema(success=S.Any, error=S.Any),
).annotate(Persisted, True)


def send_unregistered_activity(workflow_name: str, execution_id: str) -> Generator[Any, Any, Any]:
    entity = type(
        "RecoveryEntity",
        (Entity,),
        {"activity": RecoveryActivityRpc},
        type=f"Workflow/{workflow_name}",
    )
    make_client = yield from entity.client()
    client: Any = make_client(execution_id)
    yield from client.activity.discard(
        RecoveryActivityPayload(name="loser", attempt=1, withTransaction=False)
    )
    service = yield from Sharding()
    storage = yield from MessageStorage()
    entity_id = EntityId(execution_id)
    request_id = yield from storage.request_id_for_primary_key(
        address=EntityAddress(
            entity_type=EntityType(entity.type),
            entity_id=entity_id,
            shard_id=service.get_shard_id(entity_id, "default"),
        ),
        tag="activity",
        id="loser/1",
    )
    assert request_id is not None
    return request_id


_recovery_exit = S.decode_unknown_sync(S.to_codec_json(exit_schema(RecoveryActivityRpc)))


def activity_reply(storage: MessageStorageService, request_id: Any) -> Generator[Any, Any, Any]:
    for _ in range(200):
        replies = yield from storage.replies_for_unfiltered([request_id])
        if replies and replies[-1]["_tag"] == "WithExit":
            return _recovery_exit(replies[-1]["exit"])
        yield from testing.adjust(0.001)
    raise AssertionError(
        "unregistered activity must receive a terminal Suspended reply without waiting for "
        "registration"
    )


def make_shared_memory() -> fx.Effect[
    tuple[MessageStorageService, MemoryDriverService], Never, Scope
]:
    """The shared memory storage and its driver."""
    return (
        message_storage.layer_memory.pipe(fx.layer.provide(sharding_config.layer_defaults))
        .build()
        .map(lambda ctx: (ctx.get_unsafe(MessageStorage), ctx.get_unsafe(MemoryDriver)))
    )


def next_step_activity(runs: list[str], label: str) -> activity.Activity[str, Never, Never]:
    def run() -> str:
        runs.append(label)
        return f"{label}:next"

    return activity.make(name="next-step", success=S.String, execute=fx.sync(run))


def expect_continues_beside_parked_sibling(
    name: str, body: fx.Effect[str, Never, Any]
) -> Generator[Any, Any]:
    """Run ``body`` and then a ``next-step`` activity beside a branch parked
    on an unrelated durable event. ``next-step`` must run before that event
    arrives, and exactly once. Deferred writes made by ``body`` are delayed
    to stand in for a persistence round trip."""
    wf = workflow.make(name, payload=EMPTY, success=S.String, idempotency_key=lambda _: "one")
    event = durable_deferred.make(f"{name}/Event")
    next_step_runs: list[str] = []

    def handler(_: Any, __: str):
        @fx.gen
        def run():
            engine = yield from WorkflowEngine()

            def deferred_done(deferred: Any, **done: Any) -> fx.Effect[None]:
                return engine.deferred_done(deferred, **done).delay(0.01)

            delayed = body.pipe(
                fx.provide_service(WorkflowEngine, replace(engine, deferred_done=deferred_done))
            )
            result, _ = yield from fx.all(
                delayed.flat_map(lambda value: next_step_activity(next_step_runs, value)),
                event.wait(),
                concurrency="unbounded",
            )
            return result

        return run

    context = (
        yield from wf.to_layer(handler)
        .pipe(fx.layer.provide_merge(make_test_workflow_engine()))
        .build()
    )

    @fx.gen
    def check():
        execution_id = yield from wf.execute({}, discard=True)
        yield from advance_until(
            lambda: len(next_step_runs) > 0, "next-step must run before the event", 0.01, 300
        )
        yield from event.succeed(
            token=event.token_from_execution_id(workflow=wf, execution_id=execution_id),
            value=None,
        )
        assert (yield from poll_until(wf, execution_id, Complete)) == Complete(
            fx.Success("timer:next")
        )
        assert next_step_runs == ["timer"]

    yield from check.pipe(fx.provide(context))
