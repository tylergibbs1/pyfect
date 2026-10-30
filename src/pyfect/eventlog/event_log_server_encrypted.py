"""An event log server that stores encrypted batches it cannot read
(Effect's ``eventlog/EventLogServerEncrypted``).

Batches are kept per identity and store; a batch whose entries are all
stored is skipped, and its entries are acknowledged at the sequences they
were first stored at.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from typing import Never

from pyfect._core import Effect
from pyfect.context import Tag
from pyfect.effect import fail, gen, succeed, sync
from pyfect.eventlog import _uuid
from pyfect.eventlog.event_journal import EntryId, RemoteId, StoreId, make_remote_id_unsafe
from pyfect.eventlog.event_log_encryption import EncryptedBatch, EncryptedRemoteBatch, remote_batch
from pyfect.eventlog.event_log_message import (
    EventLogAuthentication,
    EventLogProtocolError,
    EventLogRemoteRpcs,
    WriteAck,
    WriteEntries,
    encode_changes_encrypted,
)
from pyfect.eventlog.event_log_server import ConnectionWrites
from pyfect.eventlog.event_log_server import layer_rpc_handlers as _layer_rpc_handlers
from pyfect.layer import Layer, unwrap
from pyfect.layer import effect as layer_effect
from pyfect.layer import provide as layer_provide
from pyfect.pubsub import PubSub
from pyfect.rc_map import RcMap
from pyfect.rpc.group import HandlersFor
from pyfect.rpc.server import ServerProtocol
from pyfect.rpc.server import layer as rpc_server_layer
from pyfect.scope import Scope, acquire_release, scoped
from pyfect.stream import Stream, from_iterable, from_subscription
from pyfect.stream import unwrap as stream_unwrap

__all__ = [
    "Storage",
    "StorageService",
    "layer",
    "layer_rpc_handlers",
    "layer_storage_memory",
    "make_storage_memory",
]


class StorageService(ABC):
    """Where an encrypted server keeps batches (Effect's ``Storage``)."""

    first_sequence: int | None = None

    @property
    @abstractmethod
    def get_id(self) -> Effect[RemoteId]: ...

    @abstractmethod
    def get_or_create_session_auth_binding(
        self, public_key: str, signing_public_key: bytes, /
    ) -> Effect[bytes]:
        """The signing key bound to ``public_key``, binding the given one
        on first use."""

    @abstractmethod
    def write(
        self, public_key: str, store_id: StoreId, batches: Sequence[EncryptedBatch], /
    ) -> Effect[list[EncryptedRemoteBatch]]:
        """Store the batches not already stored, in order."""

    @abstractmethod
    def entry_sequences(
        self, public_key: str, store_id: StoreId, entry_ids: Sequence[EntryId], /
    ) -> Effect[list[WriteAck]]:
        """Where each known entry was first stored."""

    @abstractmethod
    def changes(
        self, public_key: str, store_id: StoreId, start_sequence: int, /
    ) -> Stream[EncryptedRemoteBatch]:
        """The stored batches from ``start_sequence``, then new ones."""


class Storage(Tag[StorageService], key="effect/eventlog/EventLogServer/Storage"):
    """The storage of an encrypted server."""


def _to_write_acks(
    storage: StorageService,
    public_key: str,
    store_id: StoreId,
    batches: Sequence[EncryptedBatch],
    stored: Sequence[EncryptedRemoteBatch],
) -> Effect[tuple[WriteAck, ...]]:
    """Acknowledges each entry occurrence in request order: at its position
    in the batch this write stored, or, for a skipped batch, where it was
    first stored."""

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
            for ack in (yield from storage.entry_sequences(public_key, store_id, skipped)):
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


def _handlers(storage: StorageService):
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
        return _layer_rpc_handlers(
            remote_id=remote_id,
            first_sequence=storage.first_sequence,
            get_or_create_session_auth_binding=storage.get_or_create_session_auth_binding,
            on_write=on_write,
            changes=changes,
        )

    return gen(make)


layer_rpc_handlers: Layer[
    HandlersFor[EventLogRemoteRpcs] | EventLogAuthentication, Never, Storage
] = unwrap(Storage().flat_map(_handlers))
"""The RPC handlers of an encrypted server over its ``Storage``."""

layer: Layer[Never, Never, ServerProtocol | Storage] = rpc_server_layer(EventLogRemoteRpcs).pipe(
    layer_provide(layer_rpc_handlers)
)
"""An encrypted server over the ``ServerProtocol``."""


class _Journal:
    __slots__ = ("batches", "known_ids", "next_sequence")

    def __init__(self) -> None:
        # Entry id to the sequence it was first stored at.
        self.known_ids: dict[str, int] = {}
        self.batches: list[EncryptedRemoteBatch] = []
        self.next_sequence = 0


def _open_pubsub(_key: tuple[str, str]) -> Effect[PubSub[EncryptedRemoteBatch], Never, Scope]:
    return acquire_release(PubSub[EncryptedRemoteBatch].unbounded(), lambda p, _: p.shutdown())


class _MemoryStorage(StorageService):
    def __init__(self, pubsubs: RcMap[tuple[str, str], PubSub[EncryptedRemoteBatch]]) -> None:
        self._journals: dict[tuple[str, str], _Journal] = {}
        # A pubsub per store, shut down a minute after its last user or
        # when the storage's scope closes.
        self._pubsubs = pubsubs
        self._bindings: dict[str, bytes] = {}
        self._remote_id = make_remote_id_unsafe()

    def _journal(self, key: tuple[str, str]) -> _Journal:
        return self._journals.setdefault(key, _Journal())

    @property
    def get_id(self) -> Effect[RemoteId]:
        return succeed(self._remote_id)

    def get_or_create_session_auth_binding(
        self, public_key: str, signing_public_key: bytes, /
    ) -> Effect[bytes]:
        return sync(lambda: self._bindings.setdefault(public_key, signing_public_key))

    def write(
        self, public_key: str, store_id: StoreId, batches: Sequence[EncryptedBatch], /
    ) -> Effect[list[EncryptedRemoteBatch]]:
        key = (public_key, store_id)

        def store(pubsub: PubSub[EncryptedRemoteBatch]) -> list[EncryptedRemoteBatch]:
            journal = self._journal(key)
            stored: list[EncryptedRemoteBatch] = []
            for batch in batches:
                ids = [_uuid.stringify(i) for i in batch.entry_ids]
                if all(i in journal.known_ids for i in ids):
                    continue
                for offset, i in enumerate(ids):
                    journal.known_ids.setdefault(i, journal.next_sequence + offset)
                stored_batch = remote_batch(journal.next_sequence, batch)
                journal.next_sequence += len(ids)
                journal.batches.append(stored_batch)
                stored.append(stored_batch)
                pubsub.unsafe_publish(stored_batch)
            return stored

        return scoped(self._pubsubs.get(key).map(store))

    def entry_sequences(
        self, public_key: str, store_id: StoreId, entry_ids: Sequence[EntryId], /
    ) -> Effect[list[WriteAck]]:
        def read() -> list[WriteAck]:
            known = self._journal((public_key, store_id)).known_ids
            return [
                WriteAck(entry_id=i, sequence=known[_uuid.stringify(i)])
                for i in entry_ids
                if _uuid.stringify(i) in known
            ]

        return sync(read)

    def changes(
        self, public_key: str, store_id: StoreId, start_sequence: int, /
    ) -> Stream[EncryptedRemoteBatch]:
        key = (public_key, store_id)

        def open_changes():
            pubsub = yield from self._pubsubs.get(key)
            subscription = yield from pubsub.subscribe()
            backlog = [
                b
                for b in self._journal(key).batches
                if b.sequence + len(b.entry_ids) > start_sequence
            ]
            return from_iterable(backlog).concat(from_subscription(subscription))

        return stream_unwrap(gen(open_changes))


make_storage_memory: Effect[StorageService, Never, Scope] = RcMap.make(
    _open_pubsub, idle_time_to_live=60
).map(_MemoryStorage)
"""Storage kept in memory, its pubsubs shut down when the scope closes."""

layer_storage_memory: Layer[Storage] = layer_effect(Storage, make_storage_memory)
"""``Storage`` kept in memory."""
