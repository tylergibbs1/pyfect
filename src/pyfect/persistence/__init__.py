"""Persistence (Effect's ``effect/persistence``): key-value stores,
requests whose outcomes are stored, and caches over them.

- ``key_value_store``: ``KeyValueStore``, a string-keyed store of text and
  bytes in memory, files, SQL or any text mapping, and schema-typed stores.
- ``persistable``: ``Persistable`` requests, which carry the schemas of
  their success and error and a ``primary_key()``.
- ``persistence``: ``Persistence``, request outcomes stored by those
  schemas in memory, a ``KeyValueStore`` or SQL.
- ``persisted_cache``: ``PersistedCache``, a ``Cache`` in front of a store.
- ``user_directories``: ``UserDirectories``, where a program keeps its
  files per user.
- ``rate_limiter``: ``RateLimiter``, limits per key by fixed window or
  token bucket, and adaptive limits learned from ``429`` responses.
- ``circuit_breaker``: ``CircuitBreaker``, stops calling a key that keeps
  failing.
- ``redis``: the ``Redis`` service the Redis stores run on, made over a
  client by ``redis.make``; ``redis_py`` (extra ``pyfect[redis]``, imported
  on its own) provides it on redis-py.

``RequestResolver.persisted`` stores a resolver's outcomes.
"""

from pyfect.persistence import (
    circuit_breaker,
    key_value_store,
    persistable,
    persisted_cache,
    persistence,
    rate_limiter,
    redis,
    user_directories,
)
from pyfect.persistence._error import PersistenceError
from pyfect.persistence.circuit_breaker import CircuitBreaker, CircuitBreakerError
from pyfect.persistence.key_value_store import KeyValueStore, KeyValueStoreError
from pyfect.persistence.persistable import Persistable
from pyfect.persistence.persisted_cache import PersistedCache
from pyfect.persistence.persistence import BackingPersistence, Persistence
from pyfect.persistence.rate_limiter import RateLimiter, RateLimiterError
from pyfect.persistence.redis import Redis, RedisError
from pyfect.persistence.user_directories import UserDirectories

__all__ = [
    "BackingPersistence",
    "CircuitBreaker",
    "CircuitBreakerError",
    "KeyValueStore",
    "KeyValueStoreError",
    "Persistable",
    "PersistedCache",
    "Persistence",
    "PersistenceError",
    "RateLimiter",
    "RateLimiterError",
    "Redis",
    "RedisError",
    "UserDirectories",
    "circuit_breaker",
    "key_value_store",
    "persistable",
    "persisted_cache",
    "persistence",
    "rate_limiter",
    "redis",
    "user_directories",
]
