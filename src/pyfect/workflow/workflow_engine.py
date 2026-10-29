"""Workflow engines (Effect's ``effect/workflow/WorkflowEngine``): the
``WorkflowEngine`` service, ``make_unsafe`` building one from an engine
working on encoded values, and ``layer_memory``, an engine keeping its
state in memory (for tests and local development; nothing survives the
process).
"""

from __future__ import annotations

from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.workflow._encoded import (
    DEFAULT_SUSPENDED_RETRY_SCHEDULE,
    DeferredState,
    Encoded,
    make_deferred_state,
    make_unsafe,
)
from pyfect.workflow._memory import make_memory
from pyfect.workflow._services import (
    WorkflowEngine,
    WorkflowEngineService,
    WorkflowInstance,
    WorkflowInstanceService,
)

layer_memory: Layer[WorkflowEngine] = layer_effect(WorkflowEngine, make_memory())
"""An engine keeping its state in memory: for tests and local development,
not for workflows that must survive the process."""

__all__ = [
    "DEFAULT_SUSPENDED_RETRY_SCHEDULE",
    "DeferredState",
    "Encoded",
    "WorkflowEngine",
    "WorkflowEngineService",
    "WorkflowInstance",
    "WorkflowInstanceService",
    "layer_memory",
    "make_deferred_state",
    "make_unsafe",
]
