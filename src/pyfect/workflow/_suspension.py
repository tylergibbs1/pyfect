"""Suspending a workflow run, and the count of in-flight activities that a
suspension waits for (Effect's ``Workflow.suspend`` /
``wrapActivityResult``)."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any, Literal, Never

from pyfect._core import Effect, _Callback, _WithFiber
from pyfect._effect_args import require_effect
from pyfect._fiber import Fiber
from pyfect.context import Context, Tag
from pyfect.effect import context, gen, provide_service, succeed, sync, yield_now
from pyfect.exit import Exit, Success
from pyfect.scope import acquire_use_release
from pyfect.workflow._result import Suspended
from pyfect.workflow._services import WorkflowInstance, WorkflowInstanceService


def suspend(instance: WorkflowInstanceService) -> Effect[Never]:
    """Mark ``instance`` suspended and interrupt the current fiber, so the
    run stops until it is resumed."""

    def register(fiber: Fiber[Any, Any]) -> Effect[Never]:
        def park(_resume: Callable[[Effect[Never]], None]) -> None:
            instance.suspended = True
            fiber.interrupt_as_unsafe(fiber.id)

        return _Callback(park)

    return _WithFiber(register).interruptible()


class _Registration:
    __slots__ = ("instance", "state")

    def __init__(self, instance: WorkflowInstanceService) -> None:
        self.instance = instance
        self.state: Literal["pending", "adopted", "released"] = "pending"


class _PendingActivityRegistration(
    Tag[_Registration], key="effect/workflow/Workflow/PendingActivityRegistration"
):
    pass


def _register(instance: WorkflowInstanceService) -> _Registration:
    state = instance.activity_state
    if state.count == 0:
        state.latch.close_unsafe()
    state.count += 1
    return _Registration(instance)


def _adopt(ctx: Context[Any], instance: WorkflowInstanceService) -> _Registration | None:
    found = ctx.get_option(_PendingActivityRegistration)
    if found is None or found.value.instance is not instance:
        return None
    pending = found.value
    if pending.state != "pending":
        raise RuntimeError(
            "Workflow.wrapActivityResult: pending child registration has already been consumed"
        )
    pending.state = "adopted"
    return pending


def _release(registration: _Registration) -> None:
    if registration.state == "released":
        return
    registration.state = "released"
    state = registration.instance.activity_state
    state.count -= 1
    if state.count == 0:
        state.latch.open_unsafe()


def _wait_for_zero(instance: WorkflowInstanceService) -> Effect[None]:
    def body() -> Generator[Effect[Any], Any]:
        state = instance.activity_state
        while True:
            if state.count > 0:
                yield from state.latch.wait()
                yield from yield_now()
                continue
            yield from yield_now()
            if state.count == 0:
                return

    return gen(body)


def wrap_activity_result[A, E, R](
    effect: Effect[A, E, R], is_suspend: Callable[[A], bool]
) -> Effect[A, E, R | WorkflowInstance]:
    """Run ``effect`` as an in-flight activity of the current run. When it
    succeeds with a value ``is_suspend`` accepts, wait for the run's other
    in-flight activities to finish (or suspend) before going on, so a
    suspension never cuts short a sibling's work. A ``Suspended`` result's
    cause is added to the run's."""
    require_effect(effect, "effect")

    def with_context(ctx: Context[Any]) -> Effect[A, E, R]:
        instance = ctx.get_unsafe(WorkflowInstance)

        def release(registration: _Registration, ex: Exit[A, E]) -> Effect[None]:
            _release(registration)
            suspended = isinstance(ex, Success) and is_suspend(ex.value)
            if isinstance(ex, Success) and isinstance(ex.value, Suspended):
                value_cause = ex.value.cause
                if value_cause is not None:
                    instance.cause = (
                        value_cause if instance.cause is None else instance.cause + value_cause
                    )
            if suspended and instance.activity_state.count > 0:
                return _wait_for_zero(instance)
            return succeed(None)

        return acquire_use_release(
            sync(lambda: _adopt(ctx, instance) or _register(instance)),
            lambda _: effect,
            release,
        )

    return context().flat_map(with_context)


def with_pending_activity[A, E, R](effect: Effect[A, E, R]) -> Effect[A, E, R]:
    """Count ``effect`` (a child workflow's execution) as in flight before
    any of it runs; ``wrap_activity_result`` adopts the registration once
    the execution is dispatched."""
    require_effect(effect, "effect")

    def with_context(ctx: Context[Any]) -> Effect[A, E, R]:
        found = ctx.get_option(WorkflowInstance)
        if found is None:
            return effect
        instance = found.value
        return acquire_use_release(
            sync(lambda: _register(instance)),
            lambda registration: effect.pipe(
                provide_service(_PendingActivityRegistration, registration)
            ),
            lambda registration, _: sync(lambda: _release(registration)),
        )

    return context().flat_map(with_context)


__all__ = ["suspend", "with_pending_activity", "wrap_activity_result"]
