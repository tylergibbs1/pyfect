"""How often shard locks are refreshed (Effect's ``internal/shardLock``)."""

from __future__ import annotations

from pyfect.cluster.sharding_config import ShardingConfigService
from pyfect.duration import Duration


def effective_interval(config: ShardingConfigService) -> Duration:
    """The refresh interval, at most a third of the lock expiration."""
    return Duration(min(config.shard_lock_refresh_interval, config.shard_lock_expiration / 3))


__all__ = ["effective_interval"]
