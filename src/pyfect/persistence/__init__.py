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

``RequestResolver.persisted`` stores a resolver's outcomes.
"""

from pyfect.persistence import (
    key_value_store,
    persistable,
    persisted_cache,
    persistence,
    user_directories,
)
from pyfect.persistence._error import PersistenceError
from pyfect.persistence.key_value_store import KeyValueStore, KeyValueStoreError
from pyfect.persistence.persistable import Persistable
from pyfect.persistence.persisted_cache import PersistedCache
from pyfect.persistence.persistence import BackingPersistence, Persistence
from pyfect.persistence.user_directories import UserDirectories

__all__ = [
    "BackingPersistence",
    "KeyValueStore",
    "KeyValueStoreError",
    "Persistable",
    "PersistedCache",
    "Persistence",
    "PersistenceError",
    "UserDirectories",
    "key_value_store",
    "persistable",
    "persisted_cache",
    "persistence",
    "user_directories",
]
