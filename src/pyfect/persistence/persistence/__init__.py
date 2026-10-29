"""Request outcomes stored outside the process (Effect's
``effect/persistence/Persistence``)::

    persistence = yield from Persistence()
    store = yield from persistence.make(store_id="users", time_to_live=lambda _e, _r: 3600)
    yield from store.set(GetUser(1), fx.exit.succeed(user))
    stored = yield from store.get(GetUser(1))     # an Exit, or None

``Persistence`` writes each outcome as JSON by the request's schemas
(``pyfect.persistence.persistable``) into a ``BackingPersistence``:
``layer_memory``, ``layer_kvs`` (a ``KeyValueStore``), ``layer_redis``
(the ``Redis`` service), ``layer_sql`` (one SQL table) or
``layer_sql_multi_table`` (a table per store), each also available as its
backing layer for ``layer``.
"""

from typing import Never

from pyfect.layer import Layer, provide
from pyfect.persistence._error import PersistenceError
from pyfect.persistence.key_value_store import KeyValueStore
from pyfect.persistence.persistence._kvs import layer_backing_kvs
from pyfect.persistence.persistence._memory import layer_backing_memory, make_backing_memory
from pyfect.persistence.persistence._redis import layer_backing_redis
from pyfect.persistence.persistence._service import (
    BackingEntry,
    BackingPersistence,
    BackingPersistenceService,
    BackingPersistenceStore,
    Persistence,
    PersistenceService,
    PersistenceStore,
    layer,
    unsafe_ttl_to_expires,
)
from pyfect.persistence.persistence._sql import (
    SQL_CLEANUP_BATCH_SIZE,
    layer_backing_sql,
    layer_backing_sql_multi_table,
)
from pyfect.persistence.redis import Redis
from pyfect.sql.client import SqlClient

layer_memory: Layer[Persistence] = layer.pipe(provide(layer_backing_memory))
"""``Persistence`` in memory."""

layer_kvs: Layer[Persistence, Never, KeyValueStore] = layer.pipe(provide(layer_backing_kvs))
"""``Persistence`` in the ``KeyValueStore``."""

layer_redis: Layer[Persistence, Never, Redis] = layer.pipe(provide(layer_backing_redis))
"""``Persistence`` in Redis."""

layer_sql: Layer[Persistence, Never, SqlClient] = layer.pipe(provide(layer_backing_sql))
"""``Persistence`` in one SQL table."""

layer_sql_multi_table: Layer[Persistence, Never, SqlClient] = layer.pipe(
    provide(layer_backing_sql_multi_table)
)
"""``Persistence`` in a SQL table per store."""

__all__ = [
    "SQL_CLEANUP_BATCH_SIZE",
    "BackingEntry",
    "BackingPersistence",
    "BackingPersistenceService",
    "BackingPersistenceStore",
    "Persistence",
    "PersistenceError",
    "PersistenceService",
    "PersistenceStore",
    "layer",
    "layer_backing_kvs",
    "layer_backing_memory",
    "layer_backing_redis",
    "layer_backing_sql",
    "layer_backing_sql_multi_table",
    "layer_kvs",
    "layer_memory",
    "layer_redis",
    "layer_sql",
    "layer_sql_multi_table",
    "make_backing_memory",
    "unsafe_ttl_to_expires",
]
