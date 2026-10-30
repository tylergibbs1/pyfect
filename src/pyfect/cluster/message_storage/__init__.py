"""Where messages to entities and their replies are kept (Effect's
``MessageStorage``).

``MessageStorage`` is the service; ``layer_memory`` keeps one runner's
messages in memory, ``layer_noop`` keeps nothing, and drivers that persist
(``pyfect.cluster.sql_message_storage``) implement ``EncodedStorage`` and
are wrapped by ``make_encoded``.
"""

from pyfect.cluster.message_storage._encoded import (
    DuplicateEncoded,
    EncodedMessage,
    EncodedStorage,
    SaveResultEncoded,
    make_encoded,
)
from pyfect.cluster.message_storage._memory import (
    CLAIM_EXPIRATION_MILLIS,
    MemoryDriver,
    MemoryDriverService,
    MemoryEncoded,
    MemoryEntry,
    MemoryTransaction,
    layer_memory,
    make_memory_driver,
    memory_driver_layer,
)
from pyfect.cluster.message_storage._noop import NOOP, layer_noop
from pyfect.cluster.message_storage._service import (
    SAVE_SUCCESS,
    MessageStorage,
    MessageStorageService,
    SaveDuplicate,
    SaveResult,
    SaveSuccess,
    StorageBase,
    TransactionNotifications,
    make,
)

__all__ = [
    "CLAIM_EXPIRATION_MILLIS",
    "NOOP",
    "SAVE_SUCCESS",
    "DuplicateEncoded",
    "EncodedMessage",
    "EncodedStorage",
    "MemoryDriver",
    "MemoryDriverService",
    "MemoryEncoded",
    "MemoryEntry",
    "MemoryTransaction",
    "MessageStorage",
    "MessageStorageService",
    "SaveDuplicate",
    "SaveResult",
    "SaveResultEncoded",
    "SaveSuccess",
    "StorageBase",
    "TransactionNotifications",
    "layer_memory",
    "layer_noop",
    "make",
    "make_encoded",
    "make_memory_driver",
    "memory_driver_layer",
]
