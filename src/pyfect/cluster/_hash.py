"""The shard an entity id falls in, as Effect computes it."""

from __future__ import annotations

from pyfect._string_hash import string_hash


def shard_number(entity_id: str, shards_per_group: int) -> int:
    """``Math.abs(hashString(entityId) % shardsPerGroup) + 1`` (JavaScript's
    ``%`` keeps the dividend's sign)."""
    h = string_hash(entity_id)
    remainder = abs(h) % shards_per_group
    return remainder + 1
