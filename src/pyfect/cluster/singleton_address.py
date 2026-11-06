"""``SingletonAddress``: a singleton's name and the shard that owns it
(Effect's ``SingletonAddress``)."""

from __future__ import annotations

from pyfect import schema as S
from pyfect.cluster.shard_id import ShardId
from pyfect.encoding.schema_binary import wire_name


class SingletonAddress(S.Class, identifier="~effect/cluster/SingletonAddress"):
    """Equal by name and shard."""

    shard_id: ShardId = S.field(ShardId.pipe(wire_name("shardId")))
    name: str

    def __str__(self) -> str:
        return f"SingletonAddress({self.name}, {self.shard_id})"


__all__ = ["SingletonAddress"]
