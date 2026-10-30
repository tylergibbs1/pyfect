"""Which entities, shards and entity types are being torn down by the
runner itself (Effect's ``internal/interruptors``): an interrupt of an
entity's request while its key is held is the runner's, not the caller's.
Keys are reference counted, so overlapping holders compose."""

from __future__ import annotations

from pyfect._core import Effect
from pyfect.cluster.entity_address import EntityAddress
from pyfect.cluster.shard_id import ShardId
from pyfect.effect import suspend, sync

_counts: dict[str, int] = {}


def _acquire(key: str) -> None:
    _counts[key] = _counts.get(key, 0) + 1


def _release(key: str) -> None:
    n = _counts.get(key)
    if n is None:
        return
    if n <= 1:
        del _counts[key]
    else:
        _counts[key] = n - 1


def _around[A, E, R](key: str, effect: Effect[A, E, R]) -> Effect[A, E, R]:
    def body() -> Effect[A, E, R]:
        _acquire(key)
        return effect.ensuring(sync(lambda: _release(key)))

    return suspend(body)


def _entity_key(address: EntityAddress) -> str:
    return f"entity:{address.entity_type}:{address.entity_id}:{address.shard_id}"


def _shard_key(shard_id: ShardId) -> str:
    return f"shard:{shard_id}"


def _entity_type_key(entity_type: str) -> str:
    return f"type:{entity_type}"


def acquire_entity(address: EntityAddress) -> None:
    _acquire(_entity_key(address))


def release_entity(address: EntityAddress) -> None:
    _release(_entity_key(address))


def acquire_entity_type(entity_type: str) -> None:
    _acquire(_entity_type_key(entity_type))


def release_entity_type(entity_type: str) -> None:
    _release(_entity_type_key(entity_type))


def around_entity[A, E, R](address: EntityAddress, effect: Effect[A, E, R]) -> Effect[A, E, R]:
    return _around(_entity_key(address), effect)


def around_shard[A, E, R](shard_id: ShardId, effect: Effect[A, E, R]) -> Effect[A, E, R]:
    return _around(_shard_key(shard_id), effect)


def around_entity_type[A, E, R](entity_type: str, effect: Effect[A, E, R]) -> Effect[A, E, R]:
    return _around(_entity_type_key(entity_type), effect)


def is_active(address: EntityAddress) -> bool:
    """Whether the entity, its shard or its type is held."""
    return (
        _entity_key(address) in _counts
        or _shard_key(address.shard_id) in _counts
        or _entity_type_key(address.entity_type) in _counts
    )


def is_shard_active(shard_id: ShardId) -> bool:
    return _shard_key(shard_id) in _counts
