"""The service that routes messages to entities (Effect's ``Sharding``):
it maps entity ids to shards, takes the shard locks assigned to this
runner, registers entities and singletons, makes entity clients and
delivers messages, directly or through ``MessageStorage``."""

# The tag first: the entity modules the implementation imports read it.
from pyfect.cluster.sharding._service import Sharding, ShardingService

# isort: split
from pyfect.cluster.sharding._make import layer

__all__ = ["Sharding", "ShardingService", "layer"]
