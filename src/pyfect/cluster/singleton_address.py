"""``SingletonAddress``: a singleton's name and the shard that owns it
(Effect's ``SingletonAddress``)."""

from __future__ import annotations

from pyfect import schema as S
from pyfect.cluster.shard_id import ShardId


class SingletonAddress(S.Class, identifier="~effect/cluster/SingletonAddress"):
    """Equal by name and shard."""

    shard_id: ShardId
    name: str

    def __str__(self) -> str:
        return f"SingletonAddress({self.name}, {self.shard_id})"


__all__ = ["SingletonAddress"]
