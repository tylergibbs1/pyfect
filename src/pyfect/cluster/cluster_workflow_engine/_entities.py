"""The entities a cluster workflow engine runs workflows as: one per
workflow (``Workflow/<name>``: ``run``, ``deferred``, ``resume``,
``activity``), a partial one for a workflow not registered on this runner,
and the durable clock entity."""

from __future__ import annotations

import builtins
from collections.abc import Mapping
from datetime import datetime
from typing import Any, NotRequired, TypedDict, cast

from pyfect.cluster.cluster_schema import Dynamic, Persisted, Uninterruptible, WithTransaction
from pyfect.cluster.entity import Entity
from pyfect.cluster.envelope import Request
from pyfect.context import Context
from pyfect.encoding.schema_binary._undefined import Undefined
from pyfect.rpc import make as make_rpc
from pyfect.rpc._rpc import AnyRpc
from pyfect.schema import Any as AnySchema
from pyfect.schema import (
    Boolean,
    Bottom,
    Class,
    DateTimeUtcFromMillis,
    String,
    Struct,
    Union,
    ast,
    field,
)
from pyfect.schema import Exit as ExitSchema
from pyfect.workflow.workflow import Workflow, result_schema

type AnyWorkflow = Workflow[Any, Any, Any]

PAYLOAD_PARENT_KEY = "~effect/cluster/ClusterWorkflowEngine/payloadParentKey"

_ANY_DEFECT: Any = AnySchema
EXIT_UNKNOWN = ExitSchema(AnySchema, AnySchema, _ANY_DEFECT)
"""Effect's ``Schema.Exit(AnyOrVoid, AnyOrVoid, Schema.Any)``."""


def activity_primary_key(activity: str, attempt: int) -> str:
    return f"{activity}/{attempt}"


class ActivityPayload(Class, identifier="ActivityPayload"):
    name: str
    attempt: int
    withTransaction: bool = False

    def primary_key(self) -> str:
        return activity_primary_key(self.name, self.attempt)


class DeferredPayload(Class, identifier="DeferredPayload"):
    name: str
    exit: Any = field(EXIT_UNKNOWN)

    def primary_key(self) -> str:
        return self.name


class ResumePayload(Class, identifier="ResumePayload"):
    # Older persisted resume envelopes have an empty payload and use the empty key.
    childExecutionId: str | None = field(Union(String, Undefined), default=None)

    def primary_key(self) -> str:
        # Different children must not share an in-flight wake: the parent
        # may have already started another run when the next child finishes.
        return self.childExecutionId or ""


def _with_transaction(annotations: Context[Any], request: Request[Any]) -> Context[Any]:
    payload = cast("ActivityPayload", request.payload)
    return annotations.add(WithTransaction, True) if payload.withTransaction else annotations


ActivityRpc = (
    make_rpc(
        "activity",
        payload=ActivityPayload,
        success=result_schema(success=AnySchema, error=AnySchema),
    )
    .annotate(Persisted, True)
    .annotate(Dynamic, _with_transaction)
)

DeferredRpc = (
    make_rpc("deferred", payload=DeferredPayload, success=EXIT_UNKNOWN)
    .annotate(Persisted, True)
    .annotate(Uninterruptible, True)
)

ResumeRpc = (
    make_rpc("resume", payload=ResumePayload)
    .annotate(Persisted, True)
    .annotate(Uninterruptible, "server")
)


# --- the run payload: the workflow's payload with its parent ---------------------------


class Parent(TypedDict):
    workflowName: str
    executionId: str
    detached: NotRequired[bool]


_ParentSchema: Bottom[Any] = Union(
    Struct(
        Parent,
        workflowName=String,
        executionId=String,
        detached=cast("Any", Union(Boolean, Undefined)),
    ),
    Undefined,
)
"""Effect's ``Schema.optional(Schema.Struct(...))``: a union on the wire."""


class RunPayload(dict[str, object]):
    """A workflow's payload fields with the parent key; every run of an
    execution shares the empty primary key."""

    def primary_key(self) -> str:
        return ""

    @property
    def parent(self) -> Parent | None:
        return cast("Parent | None", self.get(PAYLOAD_PARENT_KEY))

    def without_parent(self) -> dict[str, object]:
        return {k: v for k, v in self.items() if k != PAYLOAD_PARENT_KEY}


class _RunPayloadShape:
    """A ``ClassShape`` decoding the workflow payload's fields and the
    parent key into a ``RunPayload``."""

    __slots__ = ("_built", "payload_fields")

    def __init__(self, payload_fields: ast.Objects) -> None:
        self.payload_fields = payload_fields
        self._built: tuple[ast.Objects, ast.AST] | None = None

    def _build(self) -> tuple[ast.Objects, ast.AST]:
        if self._built is None:
            parent = ast.PropertySignature(PAYLOAD_PARENT_KEY, _ParentSchema.ast, optional=True)
            fields = ast.Objects(
                (*self.payload_fields.properties, parent),
                self.payload_fields.index_signatures,
                checks=self.payload_fields.checks,
            )
            self._built = (fields, fields.flip().to_type())
        return self._built

    @property
    def cls(self) -> builtins.type:
        return RunPayload

    @property
    def fields(self) -> ast.Objects:
        return self._build()[0]

    @property
    def encoded(self) -> ast.AST:
        return self._build()[1]

    @property
    def checks(self) -> None:
        return None

    def construct(self, values: dict[object, object]) -> object:
        return RunPayload(cast("dict[str, object]", values))

    def values_of(self, instance: object) -> dict[object, object]:
        return dict[object, object](cast("RunPayload", instance).items())


def _payload_fields(workflow: AnyWorkflow) -> ast.Objects:
    node = workflow.payload_schema.__codec__().ast
    if isinstance(node, ast.Objects) and node.encoding is None:
        return node
    if isinstance(node, ast.Class):
        return node.shape.fields
    raise TypeError(
        f"the payload of the workflow {workflow.tag!r} must be a struct or a schema class"
    )


def run_payload_schema(workflow: AnyWorkflow) -> Bottom[RunPayload, Mapping[str, object]]:
    node: Any = ast.Class(_RunPayloadShape(_payload_fields(workflow)))
    return Bottom(node)


def run_payload(workflow: AnyWorkflow, payload: object, parent: Parent | None) -> RunPayload:
    """The run payload of a decoded workflow ``payload``."""
    node = workflow.payload_schema.__codec__().ast
    if isinstance(node, ast.Class):
        values: dict[str, object] = {str(k): v for k, v in node.shape.values_of(payload).items()}
    else:
        values = dict(cast("Mapping[str, object]", payload))
    if parent is not None:
        values[PAYLOAD_PARENT_KEY] = parent
    return RunPayload(values)


def workflow_payload(workflow: AnyWorkflow, payload: RunPayload) -> object:
    """The workflow's own payload from a run payload."""
    values = payload.without_parent()
    node = workflow.payload_schema.__codec__().ast
    if isinstance(node, ast.Class):
        return node.shape.construct(cast("dict[object, object]", values))
    return cast("object", values)


# --- the entities ------------------------------------------------------------------------


def make_workflow_entity(workflow: AnyWorkflow) -> builtins.type[Entity]:
    run = (
        make_rpc(
            "run",
            payload=run_payload_schema(workflow),
            success=result_schema(success=workflow.success_schema, error=workflow.error_schema),
        )
        .annotate(Persisted, True)
        .annotate(Uninterruptible, True)
    )
    return builtins.type(
        f"Workflow[{workflow.tag}]",
        (Entity,),
        {"run": run, "deferred": DeferredRpc, "resume": ResumeRpc, "activity": ActivityRpc},
        type=f"Workflow/{workflow.tag}",
        annotations=workflow.annotations,
    )


def make_partial_workflow_entity(workflow_name: str) -> builtins.type[Entity]:
    return builtins.type(
        f"Workflow[{workflow_name}]",
        (Entity,),
        {"deferred": DeferredRpc, "resume": ResumeRpc, "activity": ActivityRpc},
        type=f"Workflow/{workflow_name}",
    )


def run_rpc_of(entity: builtins.type[Entity]) -> AnyRpc:
    return entity.rpcs["run"]


class ClockPayload(Class, identifier="Workflow/DurableClock/Run"):
    name: str
    workflowName: str
    wakeUp: datetime = field(DateTimeUtcFromMillis)

    def primary_key(self) -> str:
        return self.name

    def deliver_at(self) -> datetime:
        return self.wakeUp


ClockRpc = (
    make_rpc("run", payload=ClockPayload).annotate(Persisted, True).annotate(Uninterruptible, True)
)


class ClockEntity(Entity, type="Workflow/-/DurableClock"):
    run = ClockRpc


__all__ = [
    "EXIT_UNKNOWN",
    "PAYLOAD_PARENT_KEY",
    "ActivityPayload",
    "ActivityRpc",
    "AnyWorkflow",
    "ClockEntity",
    "ClockPayload",
    "ClockRpc",
    "DeferredPayload",
    "DeferredRpc",
    "Parent",
    "ResumePayload",
    "ResumeRpc",
    "RunPayload",
    "activity_primary_key",
    "make_partial_workflow_entity",
    "make_workflow_entity",
    "run_payload",
    "run_payload_schema",
    "run_rpc_of",
    "workflow_payload",
]
