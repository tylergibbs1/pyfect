"""An event log server that stores encrypted batches it cannot read
(Effect's ``eventlog/EventLogServerEncrypted``).

Batches are kept per identity and store; a batch whose entries are all
stored is skipped, and its entries are acknowledged at the sequences they
were first stored at. The server also serves ``EventLogCompactionRpcs``:
with a storage that provides ``compaction`` it says so in ``Hello`` and
applies the compaction policy (threshold, lag, no-op backoff, commit
checks); otherwise those RPCs fail ``NotFound``.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Never

from pyfect._core import Effect
from pyfect._public import publish
from pyfect.effect import fail, gen
from pyfect.eventlog import _uuid
from pyfect.eventlog._server_encrypted.handlers import layer_compaction_rpc_handlers
from pyfect.eventlog._server_encrypted.memory import make_storage_memory_with
from pyfect.eventlog._server_encrypted.models import (
    BeginBusy,
    BeginStarted,
    CompactionActivation,
    CompactionBatchHeader,
    CompactionBeginResult,
    CompactionConfig,
    CompactionInvalidRequest,
    CompactionNotFound,
    CompactionOptions,
    CompactionRollbackError,
    CompactionStoreStatus,
    NoOpState,
    RollbackRefusal,
    StagedHeader,
    StorageCompaction,
    make_compaction_config,
)
from pyfect.eventlog._server_encrypted.storage import Storage, StorageService
from pyfect.eventlog.event_journal import StoreId
from pyfect.eventlog.event_log_encryption import EncryptedBatch, EncryptedRemoteBatch
from pyfect.eventlog.event_log_message import (
    EventLogAuthentication,
    EventLogCompactionRpcs,
    EventLogProtocolError,
    EventLogRemoteRpcs,
    WriteAck,
    WriteEntries,
    encode_changes_encrypted,
)
from pyfect.eventlog.event_log_server import ConnectionWrites
from pyfect.eventlog.event_log_server import layer_rpc_handlers as _layer_rpc_handlers
from pyfect.layer import Layer, provide_merge, unwrap
from pyfect.layer import effect as layer_effect
from pyfect.layer import provide as layer_provide
from pyfect.rpc.group import HandlersFor
from pyfect.rpc.server import ServerProtocol
from pyfect.rpc.server import layer as rpc_server_layer
from pyfect.scope import Scope
from pyfect.stream import Stream

__all__ = [
    "BeginBusy",
    "BeginStarted",
    "CompactionActivation",
    "CompactionBatchHeader",
    "CompactionBeginResult",
    "CompactionConfig",
    "CompactionInvalidRequest",
    "CompactionNotFound",
    "CompactionOptions",
    "CompactionRollbackError",
    "CompactionStoreStatus",
    "EventLogEncryptedServerRpcs",
    "NoOpState",
    "RollbackRefusal",
    "StagedHeader",
    "Storage",
    "StorageCompaction",
    "StorageService",
    "layer",
    "layer_rpc_handlers",
    "layer_storage_memory",
    "layer_storage_memory_with",
    "make_compaction_config",
    "make_storage_memory",
    "make_storage_memory_with",
]

publish(globals())


class EventLogEncryptedServerRpcs(EventLogRemoteRpcs, EventLogCompactionRpcs):
    """Every RPC an encrypted server serves (Effect's
    ``EventLogRemoteRpcs.merge(EventLogCompactionRpcs)``)."""


def _to_write_acks(
    storage: StorageService,
    public_key: str,
    store_id: StoreId,
    batches: Sequence[EncryptedBatch],
    stored: Sequence[EncryptedRemoteBatch],
) -> Effect[tuple[WriteAck, ...]]:
    """Acknowledges each entry occurrence in request order: at its position
    in the batch this write stored, or, for a skipped batch, where it was
    first stored if that is above the active compaction base."""

    def body():
        # Stored batches keep request order, and each batch has its own random iv.
        stored_at: list[int | None] = []
        next_stored = 0
        for batch in batches:
            if next_stored < len(stored) and stored[next_stored].iv == batch.iv:
                stored_at.append(stored[next_stored].sequence)
                next_stored += 1
            else:
                stored_at.append(None)
        skipped = [
            entry_id
            for batch, at in zip(batches, stored_at, strict=True)
            if at is None
            for entry_id in batch.entry_ids
        ]
        first_stored: dict[str, int] = {}
        if skipped:
            # An id first stored at or below the active base may have been
            # dropped, so acking it would move the client's cursor past
            # kept entries.
            base = -math.inf
            if storage.compaction is not None:
                base = (yield from storage.compaction.status(public_key, store_id)).base
            for ack in (yield from storage.entry_sequences(public_key, store_id, skipped)):
                if ack.sequence > base:
                    first_stored[_uuid.stringify(ack.entry_id)] = ack.sequence
        acks: list[WriteAck] = []
        for batch, at in zip(batches, stored_at, strict=True):
            for i, entry_id in enumerate(batch.entry_ids):
                sequence = first_stored.get(_uuid.stringify(entry_id)) if at is None else at + i
                if sequence is not None:
                    acks.append(WriteAck(entry_id=entry_id, sequence=sequence))
        return tuple(acks)

    return gen(body)


def _error(code: str, message: str, public_key: str | None = None) -> EventLogProtocolError:
    return EventLogProtocolError(
        request_tag="WriteEntries",
        code=code,  # pyright: ignore[reportArgumentType]
        message=message,
        public_key=public_key,
    )


def _handlers(
    storage: StorageService,
) -> Effect[
    Layer[
        HandlersFor[EventLogRemoteRpcs]
        | HandlersFor[EventLogCompactionRpcs]
        | EventLogAuthentication
    ]
]:
    def on_write(
        data: bytes, authenticated: frozenset[str], writes: ConnectionWrites
    ) -> Effect[tuple[WriteAck, ...], EventLogProtocolError]:
        def body():
            request = yield from WriteEntries.decode(data).map_error(
                lambda _: _error("InternalServerError", "Decoding failure")
            )
            if request.public_key not in authenticated:
                return (
                    yield from fail(
                        _error("Forbidden", "Identity is not authenticated", request.public_key)
                    )
                )
            if not request.batches:
                return ()
            entry_ids = [i for batch in request.batches for i in batch.entry_ids]
            write = storage.write(request.public_key, request.store_id, request.batches).flat_map(
                lambda stored: _to_write_acks(
                    storage, request.public_key, request.store_id, request.batches, stored
                )
            )
            return (
                yield from writes.track(
                    public_key=request.public_key,
                    store_id=request.store_id,
                    entry_ids=entry_ids,
                    write=write,
                ).catch_cause(
                    lambda _: fail(
                        _error("InternalServerError", "Persistence failure", request.public_key)
                    )
                )
            )

        return gen(body)

    def changes(
        public_key: str, store_id: StoreId, start_sequence: int, writes: ConnectionWrites
    ) -> Stream[bytes, object]:
        return writes.filter(
            public_key=public_key,
            store_id=store_id,
            entry_ids=lambda batch: batch.entry_ids,
            sequence=lambda batch: batch.sequence + len(batch.entry_ids) - 1,
            stream=storage.changes(public_key, store_id, start_sequence),
        ).map_array_effect(lambda batches: encode_changes_encrypted(batches).map(lambda d: (d,)))

    def make():
        remote_id = yield from storage.get_id
        remote = _layer_rpc_handlers(
            remote_id=remote_id,
            first_sequence=storage.first_sequence,
            compaction=storage.compaction is not None,
            get_or_create_session_auth_binding=storage.get_or_create_session_auth_binding,
            on_write=on_write,
            changes=changes,
            latest_sequence=storage.latest_sequence,
        )
        # The remote handlers' layer provides the auth middleware the
        # compaction RPCs need too.
        return layer_compaction_rpc_handlers(storage).pipe(provide_merge(remote))

    return gen(make)


layer_rpc_handlers: Layer[
    HandlersFor[EventLogRemoteRpcs] | HandlersFor[EventLogCompactionRpcs] | EventLogAuthentication,
    Never,
    Storage,
] = unwrap(Storage().flat_map(_handlers))
"""The RPC handlers of an encrypted server over its ``Storage``:
``EventLogRemoteRpcs`` and ``EventLogCompactionRpcs``."""

layer: Layer[Never, Never, ServerProtocol | Storage] = rpc_server_layer(
    EventLogEncryptedServerRpcs
).pipe(layer_provide(layer_rpc_handlers))
"""An encrypted server over the ``ServerProtocol``, serving
``EventLogRemoteRpcs`` and ``EventLogCompactionRpcs``."""


make_storage_memory: Effect[StorageService, Never, Scope] = make_storage_memory_with()
"""Storage kept in memory with the default compaction tuning; its pubsubs
and sweep stop when the scope closes."""


def layer_storage_memory_with(compaction: CompactionOptions | None = None) -> Layer[Storage]:
    """``Storage`` kept in memory, with ``compaction`` tuning. Dies on
    invalid options (see ``make_compaction_config``)."""
    return layer_effect(Storage, make_storage_memory_with(compaction))


layer_storage_memory: Layer[Storage] = layer_storage_memory_with()
"""``Storage`` kept in memory, with the default compaction tuning."""
