"""``ExecutionPlan``: run an effect or a stream with different resources per
step until it succeeds (Effect v4's unstable ``ExecutionPlan``)::

    from pyfect import execution_plan

    plan = execution_plan.make(
        execution_plan.Step(primary_layer, attempts=2),
        execution_plan.Step(fallback_layer),
    )
    fx.run_sync(fetch.pipe(fx.with_execution_plan(plan)))

A step provides a layer or a context and retries ``attempts`` times on its
``schedule`` while ``while_(error)`` holds. The plan provides only what
every step provides. Inside an attempt, ``CurrentMetadata`` holds the
attempt number and step index; ``on_event`` observes ``AttemptStart`` /
``AttemptSuccess`` / ``AttemptFailure`` for each attempt.
"""

from pyfect.execution_plan._events import (
    AttemptFailure,
    AttemptStart,
    AttemptSuccess,
    CurrentMetadata,
    Event,
    Metadata,
)
from pyfect.execution_plan._model import ExecutionPlan, Step, make, merge
from pyfect.execution_plan._run import with_execution_plan

__all__ = [
    "AttemptFailure",
    "AttemptStart",
    "AttemptSuccess",
    "CurrentMetadata",
    "Event",
    "ExecutionPlan",
    "Metadata",
    "Step",
    "make",
    "merge",
    "with_execution_plan",
]
