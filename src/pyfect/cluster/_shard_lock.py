"""How often shard locks are refreshed (Effect's ``internal/shardLock``)."""

from __future__ import annotations

from pyfect.cluster.sharding_config import ShardingConfigService
from pyfect.duration import Seconds


def effective_interval(config: ShardingConfigService) -> Seconds:
    """The refresh interval, at most a third of the lock expiration."""
    return Seconds(min(config.shard_lock_refresh_interval, config.shard_lock_expiration / 3))


__all__ = ["effective_interval"]
