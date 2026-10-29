"""Durable queues of schema-typed values (Effect's
``effect/persistence/PersistedQueue``)::

    queue = yield from persisted_queue.make(name="emails", schema=Email)
    yield from queue.offer(Email(to="ada@example.com"), id="welcome-ada")
    yield from queue.take(lambda email, meta: send(email))

``offer`` stores a value (an id the queue already has is not stored
again); ``take`` runs a handler on the next value: success completes it,
failure retries it on the queue's schedule until its attempts run out
(then it is failed, the dead letter), interruption releases it. Delivery
is at-least-once: a crash between a handler's success and its
acknowledgement delivers the value again, so handlers must be idempotent.

Queues come from ``PersistedQueueFactory`` (``layer``) over a
``PersistedQueueStore``: ``layer_store_memory``, ``layer_store_sql`` (any
``SqlClient``) or ``layer_store_redis``. ``layer_cleanup`` removes old
completed (and, optionally, failed) elements.
"""

from pyfect.persistence.persisted_queue._error import PersistedQueueError
from pyfect.persistence.persisted_queue._memory import layer_store_memory, make_store_memory
from pyfect.persistence.persisted_queue._queue import (
    DEFAULT_MAX_ATTEMPTS,
    DEFAULT_RETRY_SCHEDULE,
    Metadata,
    PersistedQueue,
    PersistedQueueFactory,
    PersistedQueueFactoryService,
    RetrySchedule,
    layer,
    layer_cleanup,
    make,
    make_factory,
)
from pyfect.persistence.persisted_queue._redis import layer_store_redis, make_store_redis
from pyfect.persistence.persisted_queue._sql import layer_store_sql, make_store_sql
from pyfect.persistence.persisted_queue._store import (
    Cleanup,
    Offer,
    PersistedQueueStore,
    PersistedQueueStoreService,
    TakenElement,
    TakeOptions,
)

__all__ = [
    "DEFAULT_MAX_ATTEMPTS",
    "DEFAULT_RETRY_SCHEDULE",
    "Cleanup",
    "Metadata",
    "Offer",
    "PersistedQueue",
    "PersistedQueueError",
    "PersistedQueueFactory",
    "PersistedQueueFactoryService",
    "PersistedQueueStore",
    "PersistedQueueStoreService",
    "RetrySchedule",
    "TakeOptions",
    "TakenElement",
    "layer",
    "layer_cleanup",
    "layer_store_memory",
    "layer_store_redis",
    "layer_store_sql",
    "make",
    "make_factory",
    "make_store_memory",
    "make_store_redis",
    "make_store_sql",
]
