"""``EntityAddress``: an entity's type, id and shard (Effect's
``EntityAddress``)."""

from __future__ import annotations

from pyfect import schema as S
from pyfect.cluster.entity_id import EntityId, EntityIdSchema
from pyfect.cluster.entity_type import EntityType, EntityTypeSchema
from pyfect.cluster.shard_id import ShardId


class EntityAddress(S.Class, identifier="~effect/cluster/EntityAddress"):
    shard_id: ShardId = S.field(ShardId, key="shardId")
    entity_type: EntityType = S.field(EntityTypeSchema, key="entityType")
    entity_id: EntityId = S.field(EntityIdSchema, key="entityId")

    def __str__(self) -> str:
        return f"EntityAddress({self.entity_type}, {self.entity_id}, {self.shard_id})"


def make(*, shard_id: ShardId, entity_type: EntityType, entity_id: EntityId) -> EntityAddress:
    return EntityAddress(shard_id=shard_id, entity_type=entity_type, entity_id=entity_id)


__all__ = ["EntityAddress", "make"]
