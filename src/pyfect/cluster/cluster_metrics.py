"""The metrics a cluster runner reports (Effect's ``ClusterMetrics``)."""

from __future__ import annotations

from pyfect import metric
from pyfect.duration import Duration
from pyfect.metric import Gauge, Histogram

entities: Gauge[int] = metric.gauge("effect_cluster_entities", bigint=True)
"""Active entities, per entity type."""

entity_mailbox_size: Gauge[int] = metric.gauge("effect_cluster_entity_mailbox_size", bigint=True)
"""Requests in an entity's mailbox, per entity (with ``entity_mailbox_metrics``)."""

entity_mailbox_size_max: Gauge[int] = metric.gauge(
    "effect_cluster_entity_mailbox_size_max", bigint=True
)
"""The largest mailbox of an entity type."""

singletons: Gauge[int] = metric.gauge("effect_cluster_singletons", bigint=True)
"""Singletons running on this runner."""

runners: Gauge[int] = metric.gauge("effect_cluster_runners", bigint=True)
"""Runners known to this runner."""

runners_healthy: Gauge[int] = metric.gauge("effect_cluster_runners_healthy", bigint=True)
"""Whether this runner is healthy (1) or not (0)."""

shards: Gauge[int] = metric.gauge("effect_cluster_shards", bigint=True)
"""Shards whose lock this runner holds."""

shards_releasing: Gauge[int] = metric.gauge("effect_cluster_shards_releasing", bigint=True)
"""Shards this runner is releasing."""

shard_release_duration: Histogram[Duration] = metric.timer(
    "effect_cluster_shard_release",
    description=(
        "Time taken to release a shard, including entity teardown, retries and lock storage "
        "recovery"
    ),
)
"""How long releasing a shard took."""

__all__ = [
    "entities",
    "entity_mailbox_size",
    "entity_mailbox_size_max",
    "runners",
    "runners_healthy",
    "shard_release_duration",
    "shards",
    "shards_releasing",
    "singletons",
]
