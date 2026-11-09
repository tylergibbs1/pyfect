"""Typed durable workflows (Effect's ``effect/workflow/Workflow``)::

    Order = workflow.make(
        "Order",
        payload=S.Struct(OrderPayload),
        success=S.String,
        error=S.String,
        idempotency_key=lambda order: order["id"],
    )
    OrderLive = Order.to_layer(lambda order, execution_id: charge(order))

    receipt = yield from Order.execute({"id": "o-1", "amount": 10})

A workflow has a tag, schemas for its payload, success and error, and an
idempotency key: the execution id is a digest of the tag and the key, so
executing the same payload again joins the same execution. Inside the
handler, activities (``activity.make``) run once and are replayed,
``durable_deferred`` / ``durable_clock`` suspend the run until a value or
a time comes, and ``with_compensation`` undoes a step if the workflow
fails later.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Generator, Mapping
from typing import Any, Literal, Never, cast, overload

from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect._primitives import uninterruptible_mask
from pyfect._wire_codec import Const, wire_codec
from pyfect._wire_codec import key as wire_key
from pyfect.cause import Cause, Interrupt, from_reasons
from pyfect.cause import die as die_cause
from pyfect.context import Context, Reference, TagLike
from pyfect.effect import context, fail_cause, gen, interrupt, provide_context, succeed
from pyfect.effect import suspend as suspend_effect
from pyfect.exit import Exit, Failure, Success
from pyfect.layer import Layer, effect_discard
from pyfect.schedule import Schedule
from pyfect.schema import (
    Boolean,
    Bottom,
    Codec,
    Defect,
    StructSchema,
    TaggedClass,
    TaggedError,
    Union,
    ast,
)
from pyfect.schema import Cause as CauseSchema
from pyfect.schema import Class as SchemaClass
from pyfect.schema import Exit as ExitSchema
from pyfect.schema import Never as NeverSchema
from pyfect.schema import Null as NullSchema
from pyfect.scope import CloseableScope, Scope, scoped
from pyfect.tracer import annotate_current_span
from pyfect.workflow._crypto import make_hash_digest
from pyfect.workflow._result import Complete, Result, Suspended, is_result
from pyfect.workflow._services import WorkflowEngine, WorkflowInstance, WorkflowInstanceService
from pyfect.workflow._suspension import suspend as suspend_run
from pyfect.workflow._suspension import with_pending_activity, wrap_activity_result

type _C[T] = Codec[T, Any, Never, Never]


class CaptureDefects(Reference[bool], key="effect/workflow/Workflow/CaptureDefects"):
    """A workflow annotation: defects are part of its result (the
    default, ``True``), or, with ``False``, fail the execution itself."""

    @classmethod
    def default(cls) -> bool:
        return True


class SuspendOnFailure(Reference[bool], key="effect/workflow/Workflow/SuspendOnFailure"):
    """A workflow annotation: with ``True``, a failure suspends the
    execution, to be replayed by ``resume`` (default ``False``)."""

    @classmethod
    def default(cls) -> bool:
        return False


def _js_length(text: str) -> int:
    """``text.length`` in JavaScript: UTF-16 code units, so ids match
    Effect's."""
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


class Workflow[P, A, E]:
    """A durable workflow taking a ``P`` payload, succeeding with ``A`` and
    failing with ``E``. Make one with ``make``."""

    __slots__ = (
        "annotations",
        "error_schema",
        "idempotency_key",
        "payload_schema",
        "success_schema",
        "suspended_retry_schedule",
        "tag",
    )

    def __init__(
        self,
        tag: str,
        *,
        payload_schema: _C[P],
        success_schema: _C[A],
        error_schema: _C[E],
        idempotency_key: Callable[[P], str],
        annotations: Context[Any],
        suspended_retry_schedule: Schedule[Any, Any, Any, Any] | None,
    ) -> None:
        self.tag = tag
        self.payload_schema = payload_schema
        self.success_schema = success_schema
        self.error_schema = error_schema
        self.idempotency_key = idempotency_key
        self.annotations = annotations
        self.suspended_retry_schedule = suspended_retry_schedule

    def __repr__(self) -> str:
        return f"Workflow({self.tag!r})"

    def _with_annotations(self, annotations: Context[Any]) -> Workflow[P, A, E]:
        return Workflow(
            self.tag,
            payload_schema=self.payload_schema,
            success_schema=self.success_schema,
            error_schema=self.error_schema,
            idempotency_key=self.idempotency_key,
            annotations=annotations,
            suspended_retry_schedule=self.suspended_retry_schedule,
        )

    def annotate[S, T](self, tag: TagLike[S, T], value: S) -> Workflow[P, A, E]:
        """A copy with ``tag`` annotated (``SuspendOnFailure``, ...)."""
        return self._with_annotations(self.annotations.add(tag, value))

    def annotate_merge(self, annotations: Context[Any]) -> Workflow[P, A, E]:
        return self._with_annotations(self.annotations.merge(annotations))

    def _execution_id_of(self, payload: object) -> Effect[str]:
        key = self.idempotency_key(payload)  # pyright: ignore[reportArgumentType]
        return make_hash_digest(f"{_js_length(self.tag)}:{self.tag}:{key}")

    @overload
    def execute(
        self, payload: P, *, discard: Literal[True], detached: bool = False
    ) -> Effect[str, Never, WorkflowEngine]: ...
    @overload
    def execute(
        self, payload: P, *, discard: Literal[False] = False
    ) -> Effect[A, E, WorkflowEngine]: ...
    def execute(
        self, payload: P, *, discard: bool = False, detached: bool = False
    ) -> Effect[Any, Any, WorkflowEngine]:
        """Run the workflow with ``payload`` and wait for its result. A
        caller outside any workflow retries a suspended execution on the
        workflow's ``suspended_retry_schedule``.

        ``discard=True`` gives the execution id without waiting; the child
        stays linked to its parent workflow for completion wakes and
        interruption, unless ``detached=True`` too. Do not wait for a
        detached execution later: executing the same payload joins it,
        but its completion does not wake the waiting workflow."""

        def body() -> Effect[Any, Any, WorkflowEngine]:
            made = self.payload_schema.__codec__().make(payload)

            def run_on(execution_id: str) -> Effect[Any, Any, WorkflowEngine]:
                return annotate_current_span("executionId", execution_id).and_then(
                    WorkflowEngine().flat_map(
                        lambda engine: engine.execute(
                            self,
                            execution_id=execution_id,
                            payload=made,
                            discard=discard,
                            detached=detached,
                            suspended_retry_schedule=self.suspended_retry_schedule,
                        )
                    )
                )

            run = suspend_effect(lambda: self._execution_id_of(made)).flat_map(run_on)
            # Count the child with its parent before its id is computed, so
            # a sibling that suspends first waits for it to be dispatched.
            return run if discard else with_pending_activity(run)

        return suspend_effect(body).with_span(f"{self.tag}.execute", capture_stack_trace=False)

    def poll(self, execution_id: str) -> Effect[Result[A, E] | None, Never, WorkflowEngine]:
        """The result of the execution so far: ``None`` while it has none."""
        return (
            WorkflowEngine()
            .flat_map(lambda engine: engine.poll(self, execution_id))
            .with_span(
                f"{self.tag}.poll",
                attributes={"executionId": execution_id},
                capture_stack_trace=False,
            )
        )

    def interrupt(self, execution_id: str) -> Effect[None, Never, WorkflowEngine]:
        """Interrupt the execution: it ends at its next suspension, running
        its compensations and finalizers."""
        return (
            WorkflowEngine()
            .flat_map(lambda engine: engine.interrupt(self, execution_id))
            .with_span(
                f"{self.tag}.interrupt",
                attributes={"executionId": execution_id},
                capture_stack_trace=False,
            )
        )

    def resume(self, execution_id: str) -> Effect[None, Never, WorkflowEngine]:
        """Replay a suspended execution (also one suspended by
        ``SuspendOnFailure``)."""
        return (
            WorkflowEngine()
            .flat_map(lambda engine: engine.resume(self, execution_id))
            .with_span(
                f"{self.tag}.resume",
                attributes={"executionId": execution_id},
                capture_stack_trace=False,
            )
        )

    # The first overload solves a handler needing only the workflow's own
    # services; the second alone would leave ``R`` Unknown.
    @overload
    def to_layer(
        self,
        execute: Callable[[P, str], Effect[A, E, WorkflowEngine | WorkflowInstance | Scope]],
    ) -> Layer[Never, Never, WorkflowEngine]: ...
    @overload
    def to_layer[R](
        self,
        execute: Callable[[P, str], Effect[A, E, R | WorkflowEngine | WorkflowInstance | Scope]],
    ) -> Layer[Never, Never, R | WorkflowEngine]: ...
    def to_layer[R](
        self,
        execute: Callable[[P, str], Effect[A, E, R | WorkflowEngine | WorkflowInstance | Scope]],
    ) -> Layer[Never, Never, R | WorkflowEngine]:
        """The layer registering ``execute(payload, execution_id)`` as the
        workflow's handler; it runs with the layer's services."""
        return effect_discard(
            WorkflowEngine().flat_map(lambda engine: engine.register(self, execute))
        )

    def execution_id(self, payload: P) -> Effect[str]:
        """The execution id ``payload`` runs under."""
        return suspend_effect(
            lambda: self._execution_id_of(self.payload_schema.__codec__().make(payload))
        )

    @overload
    def with_compensation[B, EB, RB, R2 = Never](
        self,
        effect: Effect[B, EB, RB],
        compensation: Callable[[B, Cause[E]], Effect[object, Never, R2]],
        /,
    ) -> Effect[B, EB, RB | R2 | WorkflowInstance | Scope]: ...
    @overload
    def with_compensation[R2 = Never](
        self, compensation: Callable[[Any, Cause[E]], Effect[object, Never, R2]], /
    ) -> _Compensate[R2]: ...
    def with_compensation(self, *args: Any) -> Any:
        """``with_compensation(effect, compensation)`` (or curried, for
        ``.pipe``): when the whole workflow fails, run
        ``compensation(value, cause)`` with ``effect``'s value. Only
        top-level steps of the workflow are compensated, not effects
        nested inside an activity."""
        if len(args) == 2:
            return with_compensation(args[0], args[1])
        return _Compensate(args[0])


class _Compensate[R2]:
    __slots__ = ("compensation",)

    def __init__(
        self, compensation: Callable[[Any, Cause[Any]], Effect[object, Never, R2]]
    ) -> None:
        self.compensation = compensation

    def __call__[B, EB, RB](
        self, effect: Effect[B, EB, RB]
    ) -> Effect[B, EB, RB | R2 | WorkflowInstance | Scope]:
        return with_compensation(effect, self.compensation)


@overload
def make[P: Mapping[str, object], A = None, E = Never](
    tag: str,
    *,
    payload: StructSchema[P, Never, Never],
    idempotency_key: Callable[[P], str],
    success: _C[A] | None = None,
    error: _C[E] | None = None,
    suspended_retry_schedule: Schedule[Any, Any, Any, Any] | None = None,
    annotations: Context[Any] | None = None,
) -> Workflow[P, A, E]: ...
@overload
def make[P: SchemaClass | TaggedClass | TaggedError, A = None, E = Never](
    tag: str,
    *,
    payload: type[P],
    idempotency_key: Callable[[P], str],
    success: _C[A] | None = None,
    error: _C[E] | None = None,
    suspended_retry_schedule: Schedule[Any, Any, Any, Any] | None = None,
    annotations: Context[Any] | None = None,
) -> Workflow[P, A, E]: ...
def make(
    tag: str,
    *,
    payload: _C[Any],
    idempotency_key: Callable[[Any], str],
    success: _C[Any] | None = None,
    error: _C[Any] | None = None,
    suspended_retry_schedule: Schedule[Any, Any, Any, Any] | None = None,
    annotations: Context[Any] | None = None,
) -> Workflow[Any, Any, Any]:
    """A workflow named ``tag``. ``payload`` is a struct schema or a
    schema class (Effect's ``Schema.Struct.Fields | AnyStructSchema``; any
    other schema raises ``TypeError``); ``success`` defaults to ``None``
    (Effect's ``Void``), ``error`` to none. ``idempotency_key(payload)``
    names the execution. ``suspended_retry_schedule`` is how a caller
    waiting outside any workflow polls a suspended execution (exponential
    from 200 ms, at most 30 s apart)."""
    payload_fields(tag, payload)
    return Workflow(
        tag,
        payload_schema=payload,
        success_schema=NullSchema if success is None else success,
        error_schema=NeverSchema if error is None else error,
        idempotency_key=idempotency_key,
        annotations=Context.empty() if annotations is None else annotations,
        suspended_retry_schedule=suspended_retry_schedule,
    )


def payload_fields(tag: str, payload: _C[Any]) -> ast.Objects:
    """The fields of the workflow ``tag``'s ``payload``: a struct with no
    encoding of its own, or a schema class. Raises ``TypeError`` otherwise."""
    node = payload.__codec__().ast
    if isinstance(node, ast.Objects) and node.encoding is None:
        return node
    if isinstance(node, ast.Class):
        return node.shape.fields
    raise TypeError(f"the payload of the workflow {tag!r} must be a struct or a schema class")


# --- running a workflow body -------------------------------------------------------------


# The first overloads of ``into_result`` and ``provide_scope`` solve a body
# needing only a scope; the second alone would leave ``R`` Unknown.
@overload
def into_result[A, E](
    effect: Effect[A, E, Scope],
) -> Effect[Result[A, E], Never, WorkflowInstance]: ...
@overload
def into_result[A, E, R](
    effect: Effect[A, E, R | Scope],
) -> Effect[Result[A, E], Never, R | WorkflowInstance]: ...
def into_result[A, E, R](
    effect: Effect[A, E, R | Scope],
) -> Effect[Result[A, E], Never, R | WorkflowInstance]:
    """Run ``effect`` as one run of the current workflow execution and give
    its ``Result``: ``Suspended`` when it suspended, else ``Complete``. A
    run interrupted from outside (not a workflow interrupt) fails with the
    interruption; with ``CaptureDefects`` off, a defect fails it too. The
    execution's scope closes once the result is ``Complete``."""
    require_effect(effect, "effect")

    def with_instance(instance: WorkflowInstanceService) -> Effect[Result[A, E], Never, R]:
        capture_defects = instance.workflow.annotations.get_unsafe(CaptureDefects)
        suspend_on_failure = instance.workflow.annotations.get_unsafe(SuspendOnFailure)

        # Run on a child, so an external interrupt can suspend the workflow.
        body: Effect[A, E, R | Scope] = (
            effect.fork(start_immediately=True)
            .flat_map(lambda fiber: fiber.join().on_interrupt(fiber.interrupt()))
            .interruptible()
        )
        if suspend_on_failure:

            def on_cause(cause: Cause[E]) -> Effect[Never, E]:
                if instance.abandoned or instance.interrupted:
                    return fail_cause(cause)
                instance.suspended = True
                # An ordinary suspension is a self-interrupt and ends up here too.
                if not cause.has_interrupts_only:
                    instance.failed = True
                    instance.cause = die_cause(cause.raisable())
                return interrupt()

            body = body.catch_cause(on_cause)

        def on_failure(cause: Cause[E]) -> Effect[Result[A, E]]:
            reasons = tuple(r for r in cause.reasons if not isinstance(r, Interrupt))
            interrupts_only = not reasons
            filtered: Cause[E] = cause if not reasons else from_reasons(reasons)
            abandoned = instance.abandoned and not instance.interrupted and interrupts_only
            instance.abandoned = abandoned
            if instance.suspended and interrupts_only and not abandoned:
                if instance.failed:
                    return succeed(Suspended(cause=instance.cause, failed=True))
                return succeed(Suspended(cause=instance.cause))
            if not instance.interrupted and interrupts_only:
                # An external interrupt ends the run without a result.
                return fail_cause(filtered)  # pyright: ignore[reportReturnType]
            if not capture_defects and cause.has_dies:
                return fail_cause(filtered)  # pyright: ignore[reportReturnType]
            return succeed(Complete(Failure(filtered)))

        def on_success(value: A) -> Effect[Result[A, E]]:
            return succeed(Complete(Success(value)))

        def close_scope(ex: Exit[Result[A, E], Never]) -> Effect[None]:
            scope = instance.scope
            if isinstance(ex, Failure):
                return scope.close(ex)
            if isinstance(ex.value, Complete):
                return scope.close(ex.value.exit)
            return succeed(None)

        return (
            scoped(body)
            .match_cause_effect(on_failure=on_failure, on_success=on_success)
            .on_exit(close_scope)
            .uninterruptible()
        )

    return WorkflowInstance().flat_map(with_instance)


# --- the workflow scope and compensation -------------------------------------------------

scope: Effect[CloseableScope, Never, WorkflowInstance] = WorkflowInstance().map(
    lambda instance: instance.scope
)
"""The execution's scope, closed only when the execution completes."""


@overload
def provide_scope[A, E](effect: Effect[A, E, Scope]) -> Effect[A, E, WorkflowInstance]: ...
@overload
def provide_scope[A, E, R](
    effect: Effect[A, E, R | Scope],
) -> Effect[A, E, R | WorkflowInstance]: ...
def provide_scope[A, E, R](effect: Effect[A, E, R | Scope]) -> Effect[A, E, R | WorkflowInstance]:
    """Run ``effect`` in the execution's scope: its resources last until the
    execution completes."""
    require_effect(effect, "effect")
    from pyfect.effect import provide_service

    return scope.flat_map(lambda s: effect.pipe(provide_service(Scope, s)))


def add_finalizer[R = Never](
    f: Callable[[Exit[Any, Any]], Effect[object, Never, R]],
) -> Effect[None, Never, WorkflowInstance | R]:
    """Run ``f(exit)`` when the execution completes, with the services in
    scope now. Unlike a finalizer of the body, it sees a workflow
    interrupt. A run abandoned for replay skips it."""

    def body() -> Generator[Effect[Any, Never, Any], Any]:
        instance = yield from WorkflowInstance()
        services = yield from context()

        def finalizer(ex: Exit[Any, Any]) -> Effect[object, Never, Any]:
            if instance.abandoned:
                return succeed(None)
            return f(ex).pipe(provide_context(services))

        yield from instance.scope.add_finalizer(finalizer)

    return gen(body)


def with_compensation[A, E, R, R2 = Never](
    effect: Effect[A, E, R],
    compensation: Callable[[A, Cause[Any]], Effect[object, Never, R2]],
) -> Effect[A, E, R | R2 | WorkflowInstance | Scope]:
    """Run ``effect``; if it succeeds and the whole workflow later fails,
    run ``compensation(value, cause)``. Only top-level steps of a workflow
    are compensated, not effects nested inside an activity."""
    require_effect(effect, "effect")

    def compensate(value: A) -> Effect[None, Never, WorkflowInstance | R2]:
        return add_finalizer(
            lambda ex: succeed(None) if isinstance(ex, Success) else compensation(value, ex.cause)
        )

    return uninterruptible_mask(lambda restore: restore(effect).tap(compensate))


def result_schema[A, E](
    *, success: Codec[A, Any, Any, Any], error: Codec[E, Any, Any, Any]
) -> Bottom[Result[A, E], Mapping[str, object]]:
    """The schema of a ``Result`` (Effect's ``Workflow.Result``): a
    ``Complete`` encoded as ``{"_tag": "Complete", "exit": ...}`` with an
    exit of ``success`` / ``error``, or a ``Suspended`` as
    ``{"_tag": "Suspended", "cause"?: ..., "failed"?: true}``."""
    complete: Bottom[Any, Mapping[str, object]] = wire_codec(
        cast("type[Any]", Complete),
        [
            Const("_tag", "Complete"),
            wire_key("exit", "exit", ExitSchema(success, error, Defect())),
        ],
        identifier="Workflow.Complete",
    )
    suspended = wire_codec(
        Suspended,
        [
            Const("_tag", "Suspended"),
            wire_key("cause", "cause", CauseSchema(NeverSchema, Defect()), optional=True),
            # Effect sets ``failed`` only when true; ``False`` is its unset value.
            wire_key("failed", "failed", Boolean, optional=True, unset=False),
        ],
        identifier="effect/workflow/Workflow/Suspended",
    )
    return cast("Bottom[Result[A, E], Mapping[str, object]]", Union(complete, suspended))


suspend = suspend_run
"""Mark the run suspended and interrupt the current fiber (Effect's
``Workflow.suspend``)."""

__all__ = [
    "CaptureDefects",
    "Complete",
    "Result",
    "SuspendOnFailure",
    "Suspended",
    "Workflow",
    "add_finalizer",
    "into_result",
    "is_result",
    "make",
    "payload_fields",
    "provide_scope",
    "result_schema",
    "scope",
    "suspend",
    "with_compensation",
    "wrap_activity_result",
]
