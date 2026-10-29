"""Durable workflows (Effect's ``effect/workflow``)::

    from pyfect.workflow import activity, durable_deferred, workflow, workflow_engine

    Order = workflow.make(
        "Order",
        payload=S.Struct(OrderPayload),
        success=S.String,
        idempotency_key=lambda order: order["id"],
    )

    def run_order(order: OrderPayload, execution_id: str):
        charge_id = yield from activity.make(
            name="charge", success=S.String, execute=charge(order)
        ).pipe(Order.with_compensation(lambda charge_id, cause: refund(charge_id)))
        yield from durable_clock.sleep(name="cool-off", duration=3600)
        return charge_id

    OrderLive = Order.to_layer(fx.fn(run_order)).pipe(
        fx.layer.provide_merge(workflow_engine.layer_memory)
    )

- ``workflow``: ``Workflow`` (``make``, ``execute``, ``poll``,
  ``interrupt``, ``resume``, ``to_layer``, ``with_compensation``), its
  results ``Complete`` / ``Suspended``, ``CaptureDefects`` and
  ``SuspendOnFailure``, the execution's ``scope`` and ``add_finalizer``.
- ``activity``: steps whose results are stored and replayed.
- ``durable_deferred``: named wait points completed from outside by token.
- ``durable_clock``: durable sleeps.
- ``durable_queue``: work handed to ``PersistedQueue`` workers.
- ``workflow_engine``: the ``WorkflowEngine`` service and ``layer_memory``.
- ``workflow_proxy`` / ``workflow_proxy_server``: RPC and HTTP API groups
  that execute, discard and resume workflows. Import them by name
  (``from pyfect.workflow import workflow_proxy``); they load the RPC and
  HTTP API packages, which ``import pyfect`` leaves out.
"""

from pyfect.workflow import (
    activity,
    durable_clock,
    durable_deferred,
    durable_queue,
    workflow,
    workflow_engine,
)
from pyfect.workflow._result import Complete, Result, Suspended
from pyfect.workflow._services import (
    WorkflowEngine,
    WorkflowEngineService,
    WorkflowInstance,
    WorkflowInstanceService,
)
from pyfect.workflow.activity import Activity
from pyfect.workflow.durable_clock import DurableClock
from pyfect.workflow.durable_deferred import DurableDeferred
from pyfect.workflow.durable_queue import DurableQueue
from pyfect.workflow.workflow import Workflow

__all__ = [
    "Activity",
    "Complete",
    "DurableClock",
    "DurableDeferred",
    "DurableQueue",
    "Result",
    "Suspended",
    "Workflow",
    "WorkflowEngine",
    "WorkflowEngineService",
    "WorkflowInstance",
    "WorkflowInstanceService",
    "activity",
    "durable_clock",
    "durable_deferred",
    "durable_queue",
    "workflow",
    "workflow_engine",
]
