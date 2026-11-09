"""Named steps of a workflow whose results the engine stores (Effect's
``effect/workflow/Activity``)::

    charge = activity.make(
        name="charge",
        success=S.String,
        error=S.String,
        execute=payments.charge(order),
    )
    charge_id = yield from charge

An activity is an effect. Run inside a workflow, it runs once: its exit
is stored (encoded by its schemas), and a replay of the workflow gets the
stored exit back instead of running it again. An activity interrupted
from outside is retried (up to 10 times, exponential from 400 ms, at most
10 s apart; ``interrupt_retry_policy`` changes that).

Only completed results are stored: an activity that suspends (waiting on
a child workflow or a durable clock) runs again when the workflow
replays, so its side effects before the suspension must be idempotent.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Generator, Sequence
from typing import Any, Never, Protocol, TypeVar, cast, overload

from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect._effect_base import Step
from pyfect._fiber import Fiber
from pyfect.cause import Cause
from pyfect.context import Context, Reference, TagLike
from pyfect.effect import die, fail, fail_cause, from_exit, gen, provide_service, suspend
from pyfect.schedule import Metadata as ScheduleMetadata
from pyfect.schedule import Schedule, exponential, min, spaced
from pyfect.schema import (
    Codec,
    Defect,
    ExitSchema,
    Union,
    encode_unknown_effect,
    to_codec_json,
)
from pyfect.schema import Exit as ExitOf
from pyfect.schema import Never as NeverSchema
from pyfect.schema import Null as NullSchema
from pyfect.schema import Unknown as UnknownSchema
from pyfect.schema._data import DefectCodec
from pyfect.scope import Scope
from pyfect.tracer import annotate_current_span
from pyfect.workflow._crypto import make_hash_digest
from pyfect.workflow._result import Suspended
from pyfect.workflow._services import WorkflowEngine, WorkflowInstance
from pyfect.workflow._suspension import suspend as suspend_run
from pyfect.workflow._suspension import wrap_activity_result

T = TypeVar("T")


class _ExactBottom(Protocol[T]):
    def make(self, input: T, /) -> T: ...


class Exactly(Protocol[T]):
    """A schema of exactly ``T`` values. Its ``make`` takes and gives ``T``,
    so ``T`` is fixed by the schema and an effect passed beside it is
    checked against it, whichever argument comes first
    (``research/typing/workflow_2_exact_schemas.py``). Schemas of results
    must need no services; this protocol cannot check that."""

    def __codec__(self) -> _ExactBottom[T]: ...


def codec_of[T](schema: Exactly[T]) -> Codec[T, Any, Never, Never]:
    """The schema as a ``Codec`` (it is one: ``Exactly`` only checks it)."""
    return cast("Codec[T, Any, Never, Never]", schema)


class CurrentAttempt(Reference[int], key="effect/workflow/Activity/CurrentAttempt"):
    """The attempt of the activity running now, from 1 (set by
    ``retry``)."""

    @classmethod
    def default(cls) -> int:
        return 1


type InterruptRetryPolicy = Schedule[Any, Cause[Any], Any, Any]


def _interrupted_at_most_ten_times(meta: ScheduleMetadata[Any, Cause[Any]]) -> bool:
    return meta.attempt <= 10 and meta.input.has_interrupts


_interrupt_backoff: Schedule[Any, Cause[Any]] = min(
    exponential("400 millis", 1.5), spaced("10 seconds")
)

DEFAULT_INTERRUPT_RETRY_POLICY: InterruptRetryPolicy = _interrupt_backoff.while_(
    _interrupted_at_most_ten_times
)
"""Exponential from 400 ms, at most 10 s apart, while the activity was
interrupted, at most 10 times."""


class Activity[A, E, R](Effect[A, E, R | WorkflowEngine | WorkflowInstance]):
    """A workflow step succeeding with ``A``, failing with ``E`` and needing
    ``R``. Make one with ``make``."""

    __slots__ = (
        "_options",
        "_run",
        "annotations",
        "error_schema",
        "execute",
        "execute_encoded",
        "exit_schema",
        "exit_schema_partial",
        "name",
        "success_schema",
    )

    def __init__(
        self,
        *,
        name: str,
        success: Codec[A, Any, Never, Never],
        error: Codec[E, Any, Never, Never],
        execute: Effect[A, E, Any],
        interrupt_retry_policy: InterruptRetryPolicy,
        annotations: Context[Any],
    ) -> None:
        self.name = name
        self.success_schema = success
        self.error_schema = error
        self.annotations = annotations
        self._options = (execute, interrupt_retry_policy)
        success_json = to_codec_json(success)
        error_json = to_codec_json(error)
        self.exit_schema: ExitSchema[A, E, Any, Any, Never, Never] = ExitOf(
            success_json, error_json, Defect()
        )
        self.exit_schema_partial: ExitSchema[A, E, Any, Any, Never, Never] = ExitOf(
            success_json, error_json, cast("DefectCodec[Never, Never]", UnknownSchema)
        )
        without_interrupt = _retry_on_interrupt(name, interrupt_retry_policy, execute)
        self.execute: Effect[A, E, R | Scope | WorkflowEngine | WorkflowInstance] = (
            without_interrupt
        )
        encode_error = encode_unknown_effect(error_json)
        encode_success = encode_unknown_effect(success_json)
        self.execute_encoded: Effect[object, object, Any] = without_interrupt.match_effect(
            on_failure=lambda e: encode_error(e).or_die().flat_map(fail),
            on_success=lambda a: encode_success(a).or_die(),
        )
        self._run = _make_execute(self)

    def __repr__(self) -> str:
        return f"Activity({self.name!r})"

    def _step(self, fiber: Fiber[Any, Any]) -> Step:
        return self._run

    def _with_annotations(self, annotations: Context[Any]) -> Activity[A, E, R]:
        execute, policy = self._options
        return Activity(
            name=self.name,
            success=self.success_schema,
            error=self.error_schema,
            execute=execute,
            interrupt_retry_policy=policy,
            annotations=annotations,
        )

    def annotate[S, X](self, tag: TagLike[S, X], value: S) -> Activity[A, E, R]:
        return self._with_annotations(self.annotations.add(tag, value))

    def annotate_merge(self, annotations: Context[Any]) -> Activity[A, E, R]:
        return self._with_annotations(self.annotations.merge(annotations))


def _retry_on_interrupt[A, E, R](
    name: str, policy: InterruptRetryPolicy, effect: Effect[A, E, R]
) -> Effect[A, E, R | WorkflowInstance]:
    def with_instance(instance: Any) -> Effect[A, E, R]:
        def exhausted(cause: Cause[E]) -> Effect[Never, E]:
            if cause.has_interrupts and not instance.suspended:
                return die(
                    RuntimeError(f'Activity "{name}" interrupted and retry attempts exhausted')
                )
            return fail_cause(cause)

        # A suspension interrupts the body on purpose: it is a suspended
        # result, never retried.
        return (
            effect.sandbox()
            .retry(schedule=policy, while_=lambda _: not instance.suspended)
            .catch_all(exhausted)
        )

    return WorkflowInstance().flat_map(with_instance)


def _make_execute[A, E](activity: Activity[A, E, Any]) -> Effect[A, E, Any]:
    def body() -> Generator[Effect[Any, Any, Any], Any, A]:
        engine = yield from WorkflowEngine()
        instance = yield from WorkflowInstance()
        attempt = yield from CurrentAttempt()
        yield from annotate_current_span({"executionId": instance.execution_id})
        result = yield from wrap_activity_result(
            engine.activity_execute(activity, attempt), lambda r: isinstance(r, Suspended)
        )
        if isinstance(result, Suspended):
            if result.failed:
                instance.failed = True
            return (yield from suspend_run(instance))
        return (yield from from_exit(result.exit))

    return gen(body).with_span(activity.name, capture_stack_trace=False)


# An omitted ``success`` is ``None`` and an omitted ``error`` none, so
# ``execute`` must then succeed with ``None`` / never fail: inferring ``A``
# from ``execute`` alone let ``execute=fx.succeed(5)`` type-check and die
# encoding 5 as ``None``. Each case comes twice: without the first, an
# ``execute`` needing nothing beyond the workflow's own services leaves
# ``R`` unsolved (Unknown, not its default).
@overload
def make(
    *,
    name: str,
    execute: Effect[None, Never, WorkflowEngine | WorkflowInstance | Scope],
    success: None = None,
    error: None = None,
    interrupt_retry_policy: InterruptRetryPolicy | None = None,
    annotations: Context[Any] | None = None,
) -> Activity[None, Never, Never]: ...
@overload
def make[R](
    *,
    name: str,
    execute: Effect[None, Never, R | WorkflowEngine | WorkflowInstance | Scope],
    success: None = None,
    error: None = None,
    interrupt_retry_policy: InterruptRetryPolicy | None = None,
    annotations: Context[Any] | None = None,
) -> Activity[None, Never, R]: ...
@overload
def make[A](
    *,
    name: str,
    execute: Effect[A, Never, WorkflowEngine | WorkflowInstance | Scope],
    success: Exactly[A],
    error: None = None,
    interrupt_retry_policy: InterruptRetryPolicy | None = None,
    annotations: Context[Any] | None = None,
) -> Activity[A, Never, Never]: ...
@overload
def make[A, R](
    *,
    name: str,
    execute: Effect[A, Never, R | WorkflowEngine | WorkflowInstance | Scope],
    success: Exactly[A],
    error: None = None,
    interrupt_retry_policy: InterruptRetryPolicy | None = None,
    annotations: Context[Any] | None = None,
) -> Activity[A, Never, R]: ...
@overload
def make[E](
    *,
    name: str,
    execute: Effect[None, E, WorkflowEngine | WorkflowInstance | Scope],
    success: None = None,
    error: Exactly[E],
    interrupt_retry_policy: InterruptRetryPolicy | None = None,
    annotations: Context[Any] | None = None,
) -> Activity[None, E, Never]: ...
@overload
def make[E, R](
    *,
    name: str,
    execute: Effect[None, E, R | WorkflowEngine | WorkflowInstance | Scope],
    success: None = None,
    error: Exactly[E],
    interrupt_retry_policy: InterruptRetryPolicy | None = None,
    annotations: Context[Any] | None = None,
) -> Activity[None, E, R]: ...
@overload
def make[A, E](
    *,
    name: str,
    execute: Effect[A, E, WorkflowEngine | WorkflowInstance | Scope],
    success: Exactly[A],
    error: Exactly[E],
    interrupt_retry_policy: InterruptRetryPolicy | None = None,
    annotations: Context[Any] | None = None,
) -> Activity[A, E, Never]: ...
@overload
def make[A, E, R](
    *,
    name: str,
    execute: Effect[A, E, R | WorkflowEngine | WorkflowInstance | Scope],
    success: Exactly[A],
    error: Exactly[E],
    interrupt_retry_policy: InterruptRetryPolicy | None = None,
    annotations: Context[Any] | None = None,
) -> Activity[A, E, R]: ...
def make[A = None, E = Never, R = Never](
    *,
    name: str,
    execute: Effect[A, E, R | WorkflowEngine | WorkflowInstance | Scope],
    success: Exactly[A] | None = None,
    error: Exactly[E] | None = None,
    interrupt_retry_policy: InterruptRetryPolicy | None = None,
    annotations: Context[Any] | None = None,
) -> Activity[A, E, R]:
    """An activity named ``name`` (unique within its workflow) running
    ``execute``. ``success`` defaults to ``None`` (Effect's ``Void``),
    ``error`` to none; ``execute`` is checked against them."""
    require_effect(execute, "execute")
    return Activity(
        name=name,
        success=cast("Codec[A, Any, Never, Never]", NullSchema)
        if success is None
        else codec_of(success),
        error=cast("Codec[E, Any, Never, Never]", NeverSchema)
        if error is None
        else codec_of(error),
        execute=execute,
        interrupt_retry_policy=(
            DEFAULT_INTERRUPT_RETRY_POLICY
            if interrupt_retry_policy is None
            else interrupt_retry_policy
        ),
        annotations=Context.empty() if annotations is None else annotations,
    )


class _Retry:
    __slots__ = ("options",)

    def __init__(self, options: dict[str, Any]) -> None:
        self.options = options

    def __call__[A, E, R](self, effect: Effect[A, E, R]) -> Effect[A, E, R]:
        options = self.options

        def body() -> Effect[A, E, R]:
            attempt = 1

            def next_attempt() -> Effect[A, E, R]:
                nonlocal attempt
                current = attempt
                attempt += 1
                return effect.pipe(provide_service(CurrentAttempt, current))

            return suspend(next_attempt).retry(**options)

        return suspend(body)


def retry(
    *,
    times: int | None = None,
    while_: Callable[[Any], bool] | None = None,
    until: Callable[[Any], bool] | None = None,
) -> _Retry:
    """``Effect.retry`` (for ``.pipe``) that sets ``CurrentAttempt`` for each
    attempt, so an activity made inside gets a name and an idempotency key
    per attempt."""
    options: dict[str, Any] = {}
    if times is not None:
        options["times"] = times
    if while_ is not None:
        options["while_"] = while_
    if until is not None:
        options["until"] = until
    return _Retry(options)


def idempotency_key(
    name: str, *, include_attempt: bool = False
) -> Effect[str, Never, WorkflowInstance]:
    """A key unique to the current execution and ``name`` (and the attempt,
    with ``include_attempt``), for idempotent calls to other systems."""

    def body() -> Generator[Effect[Any, Never, Any], Any, str]:
        instance = yield from WorkflowInstance()
        key = instance.execution_id
        if include_attempt:
            attempt = yield from CurrentAttempt()
            key += f"-{attempt}"
        key += f"-{name}"
        return (yield from make_hash_digest(key))

    return gen(body)


def race_all[A, E, R](
    name: str, activities: Sequence[Activity[A, E, R]]
) -> Effect[A, E, R | WorkflowEngine | WorkflowInstance]:
    """Race ``activities`` durably: the first to succeed wins (or the last
    failure), and a replay gets the same winner."""
    from pyfect.workflow import durable_deferred

    if not activities:
        raise ValueError("race_all needs at least one activity")
    return durable_deferred.race_all(
        name=f"Activity/{name}",
        success=Union(*(a.success_schema for a in activities)),
        error=Union(*(a.error_schema for a in activities)),
        effects=activities,
    )


__all__ = [
    "DEFAULT_INTERRUPT_RETRY_POLICY",
    "Activity",
    "CurrentAttempt",
    "Exactly",
    "InterruptRetryPolicy",
    "codec_of",
    "idempotency_key",
    "make",
    "race_all",
    "retry",
]
