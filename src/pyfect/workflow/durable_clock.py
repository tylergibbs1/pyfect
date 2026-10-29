"""Durable sleeps of a workflow (Effect's ``effect/workflow/DurableClock``)::

    yield from durable_clock.sleep(name="cool-off", duration=3 * 24 * 3600)

A sleep longer than ``in_memory_threshold`` (default 60 seconds) is
scheduled with the engine and suspends the execution until the clock
wakes it; a shorter one runs as an activity sleeping in memory.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Never

from pyfect._core import Effect
from pyfect.clock import sleep as clock_sleep
from pyfect.duration import Duration, Seconds, to_seconds
from pyfect.effect import gen, succeed
from pyfect.workflow._services import WorkflowEngine, WorkflowInstance
from pyfect.workflow.activity import make as make_activity
from pyfect.workflow.durable_deferred import DurableDeferred
from pyfect.workflow.durable_deferred import make as make_deferred


@dataclass(frozen=True, slots=True)
class DurableClock:
    """A named timer of a workflow and the deferred its wake-up completes."""

    name: str
    duration: Seconds
    deferred: DurableDeferred[None]


def make(*, name: str, duration: Duration) -> DurableClock:
    return DurableClock(
        name=name,
        duration=to_seconds(duration),
        deferred=make_deferred(f"DurableClock/{name}"),
    )


DEFAULT_IN_MEMORY_THRESHOLD: Seconds = to_seconds(60)


def sleep(
    *, name: str, duration: Duration, in_memory_threshold: Duration | None = None
) -> Effect[None, Never, WorkflowEngine | WorkflowInstance]:
    """Wait ``duration`` inside a workflow. A zero duration does nothing."""
    seconds = to_seconds(duration)
    threshold = (
        DEFAULT_IN_MEMORY_THRESHOLD
        if in_memory_threshold is None
        else to_seconds(in_memory_threshold)
    )
    if seconds == 0:
        return succeed(None)
    if seconds <= threshold:
        return make_activity(name=f"DurableClock/{name}", execute=clock_sleep(seconds))

    def body():
        engine = yield from WorkflowEngine()
        instance = yield from WorkflowInstance()
        clock = make(name=name, duration=seconds)
        yield from engine.schedule_clock(
            instance.workflow, execution_id=instance.execution_id, clock=clock
        )
        return (yield from clock.deferred.wait())

    return gen(body)


__all__ = ["DEFAULT_IN_MEMORY_THRESHOLD", "DurableClock", "make", "sleep"]
