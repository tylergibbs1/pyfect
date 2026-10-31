"""The cluster workflow engine (Effect's ``ClusterWorkflowEngine``): a
``WorkflowEngine`` whose executions, activities, deferred completions,
resumes, interrupts and durable clocks are persisted cluster entity
messages, so durable workflows survive runner restarts and move with
their shards.

``layer`` provides the engine on ``Sharding`` and ``MessageStorage`` and
registers the durable clock entity; ``make`` builds the engine alone."""

from typing import Never

from pyfect import layer as layer_
from pyfect.cluster.cluster_workflow_engine._engine import clock_entity_layer, make
from pyfect.cluster.message_storage import MessageStorage
from pyfect.cluster.sharding import Sharding
from pyfect.layer import Layer
from pyfect.workflow import WorkflowEngine

layer: Layer[WorkflowEngine, Never, Sharding | MessageStorage] = clock_entity_layer.pipe(
    layer_.provide_merge(layer_.effect(WorkflowEngine, make()))
)
"""The cluster workflow engine on ``Sharding`` and ``MessageStorage``."""

__all__ = ["layer", "make"]
