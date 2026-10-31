"""One runner whose messages are kept in SQL (Effect's ``SingleRunner``):
sharding with no other runners, settings read from the environment."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal

from pyfect import layer as layer_
from pyfect.cluster import (
    runner_health,
    runner_storage,
    runners,
    sharding,
    sql_message_storage,
    sql_runner_storage,
)
from pyfect.cluster import sharding_config as sharding_config_
from pyfect.cluster.message_storage import MessageStorage
from pyfect.cluster.runners import Runners
from pyfect.cluster.sharding import Sharding
from pyfect.cluster.sharding_config import ShardingConfigService
from pyfect.config import ConfigError
from pyfect.layer import Layer
from pyfect.sql.client import SqlClient


def layer(
    *,
    sharding_config: Callable[[ShardingConfigService], ShardingConfigService] | None = None,
    runner_storage_kind: Literal["memory", "sql"] = "sql",
) -> Layer[Sharding | Runners | MessageStorage, ConfigError, SqlClient]:
    """Sharding of one runner over ``SqlMessageStorage``; runner storage in
    SQL (or in memory), settings from the environment passed through
    ``sharding_config``."""
    locks = (
        runner_storage.layer_memory
        if runner_storage_kind == "memory"
        else sql_runner_storage.layer.or_die()
    )
    return (
        sharding.layer.pipe(layer_.provide_merge(runners.layer_noop))
        .pipe(layer_.provide_merge(sql_message_storage.layer))
        .pipe(layer_.provide(layer_.merge(locks, runner_health.layer_noop)))
        .pipe(layer_.provide(sharding_config_.layer_from_env(sharding_config)))
    )


__all__ = ["layer"]
