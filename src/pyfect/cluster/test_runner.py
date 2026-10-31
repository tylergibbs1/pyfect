"""A single runner in memory, for tests (Effect's ``TestRunner``):
sharding with no other runners, message storage in memory and default
settings."""

from __future__ import annotations

from pyfect import layer as layer_
from pyfect.cluster import message_storage, runner_health, runner_storage, runners, sharding
from pyfect.cluster import sharding_config as sharding_config_
from pyfect.cluster.message_storage import MemoryDriver, MessageStorage
from pyfect.cluster.runners import Runners
from pyfect.cluster.sharding import Sharding
from pyfect.layer import Layer

layer: Layer[Sharding | Runners | MessageStorage | MemoryDriver] = (
    sharding.layer.pipe(layer_.provide_merge(runners.layer_noop))
    .pipe(layer_.provide_merge(message_storage.layer_memory))
    .pipe(layer_.provide(layer_.merge(runner_storage.layer_memory, runner_health.layer_noop)))
    .pipe(layer_.provide(sharding_config_.layer()))
)
"""Sharding, runners and message storage of one runner in memory."""

__all__ = ["layer"]
