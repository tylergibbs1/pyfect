"""An event log server that reads the entries it stores (Effect's
``eventlog/EventLogServerUnencrypted``).

Writes are authorized, mapped to a store, run through the server's own
group handlers (with their conflicts) and stored; change streams compact
the backlog with the registered compactors. ``EventLogServerUnencrypted``
writes events from the server itself.
"""

from __future__ import annotations

import bisect
from abc import ABC, abstractmethod
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from itertools import pairwise
from typing import Any, Literal, Never, cast, overload

from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect._layer_core import require_layer
from pyfect.context import Tag
from pyfect.effect import die, fail, gen, succeed, sync
from pyfect.errors import TaggedError
from pyfect.eventlog._identity import Identity, IdentityService
from pyfect.eventlog.event import AnyEvent, Event
from pyfect.eventlog.event_journal import (
    Entry,
    RemoteEntry,
    RemoteId,
    StoreId,
    make_entry_id_unsafe,
    make_remote_id_unsafe,
)
from pyfect.eventlog.event_log import (
    Conflict,
    EventLogSchema,
    HandlerInput,
    RegisteredCompactor,
    Registry,
    RegistryService,
    _under,  # pyright: ignore[reportPrivateUsage]
    layer_registry,
)
from pyfect.eventlog.event_log_message import (
    EventLogAuthentication,
    EventLogProtocolError,
    EventLogRemoteRpcs,
    WriteAck,
    WriteEntriesUnencrypted,
    encode_changes_unencrypted,
)
from pyfect.eventlog.event_log_server import ConnectionWrites
from pyfect.eventlog.event_log_server import layer_rpc_handlers as _layer_rpc_handlers
from pyfect.layer import Layer, merge, provide_merge, unwrap
from pyfect.layer import effect as layer_effect
from pyfect.layer import provide as layer_provide
from pyfect.layer import succeed as layer_succeed
from pyfect.logger._log import log_debug
from pyfect.pubsub import PubSub
from pyfect.rc_map import RcMap
from pyfect.redacted import make as redacted
from pyfect.rpc.group import HandlersFor
from pyfect.rpc.server import ServerProtocol
from pyfect.rpc.server import layer as rpc_server_layer
from pyfect.schema import decode_effect, encode_effect
from pyfect.scope import Scope, acquire_release, scoped
from pyfect.semaphore import Semaphore
from pyfect.stream import Stream, from_iterable, from_subscription
from pyfect.stream import unwrap as stream_unwrap

__all__ = [
    "EventLogServerAuthError",
    "EventLogServerAuthorization",
    "EventLogServerAuthorizationService",
    "EventLogServerStoreError",
    "EventLogServerUnencrypted",
    "EventLogServerUnencryptedService",
    "HistoryIndex",
    "Storage",
    "StorageService",
    "StoreMapping",
    "StoreMappingService",
    "compact_backlog",
    "layer",
    "layer_no_rpc_server",
    "layer_rpc_handlers",
    "layer_server",
    "layer_storage_memory",
    "layer_store_mapping_static",
    "make_storage_memory",
    "make_write",
]


@dataclass(eq=False)
class EventLogServerStoreError(TaggedError):
    reason: Literal["NotFound", "PersistenceFailure"]
    public_key: str | None = None
    store_id: StoreId | None = None
    message: str | None = None


@dataclass(eq=False)
class EventLogServerAuthError(TaggedError):
    reason: Literal["Unauthorized", "Forbidden"]
    public_key: str
    store_id: StoreId | None = None
    message: str | None = None


class EventLogServerAuthorizationService(ABC):
    """Who may write, read and authenticate."""

    @abstractmethod
    def authorize_write(
        self, *, public_key: str, store_id: StoreId, entries: Sequence[Entry]
    ) -> Effect[None, EventLogServerAuthError]: ...

    @abstractmethod
    def authorize_read(
        self, *, public_key: str, store_id: StoreId
    ) -> Effect[None, EventLogServerAuthError]: ...

    @abstractmethod
    def authorize_identity(self, *, public_key: str) -> Effect[None, EventLogServerAuthError]: ...


class EventLogServerAuthorization(
    Tag[EventLogServerAuthorizationService],
    key="effect/eventlog/EventLogServerUnencrypted/EventLogServerAuthorization",
):
    pass


class StoreMappingService(ABC):
    """Which store a public key's store id means."""

    @abstractmethod
    def resolve(
        self, *, public_key: str, store_id: StoreId
    ) -> Effect[StoreId, EventLogServerStoreError]: ...

    @abstractmethod
    def has_store(
        self, *, public_key: str, store_id: StoreId
    ) -> Effect[bool, EventLogServerStoreError]: ...


class StoreMapping(
    Tag[StoreMappingService], key="effect/eventlog/EventLogServerUnencrypted/StoreMapping"
):
    pass


def _store_not_found(store_id: StoreId, public_key: str | None) -> EventLogServerStoreError:
    message = (
        f"No provisioned store found for store id: {store_id}"
        if public_key is None
        else f"No provisioned store found for public key: {public_key} and store id: {store_id}"
    )
    return EventLogServerStoreError("NotFound", public_key, store_id, message)


@dataclass(frozen=True, slots=True)
class _StaticMapping(StoreMappingService):
    store_id: StoreId

    def resolve(
        self, *, public_key: str, store_id: StoreId
    ) -> Effect[StoreId, EventLogServerStoreError]:
        if store_id == self.store_id:
            return succeed(self.store_id)
        return fail(_store_not_found(store_id, public_key))

    def has_store(
        self, *, public_key: str, store_id: StoreId
    ) -> Effect[bool, EventLogServerStoreError]:
        return succeed(store_id == self.store_id)


def layer_store_mapping_static(*, store_id: StoreId) -> Layer[StoreMapping]:
    """Every public key maps ``store_id`` to itself; other stores are not found."""
    return layer_succeed(StoreMapping, _StaticMapping(store_id))


class StorageService(ABC):
    """Where an unencrypted server keeps entries."""

    first_sequence: int | None = None

    @property
    @abstractmethod
    def get_id(self) -> Effect[RemoteId]: ...

    @abstractmethod
    def get_or_create_session_auth_binding(
        self, public_key: str, signing_public_key: bytes, /
    ) -> Effect[bytes]: ...

    @abstractmethod
    def entries_after(
        self, store_id: StoreId, oldest: Entry, batch: Sequence[Entry] | None = None, /
    ) -> Effect[list[RemoteEntry]]:
        """Stored entries at or after ``oldest``: with a ``batch``, only
        those it repeats or shares an event and primary key with."""

    @abstractmethod
    def write(
        self, store_id: StoreId, entries: Sequence[Entry], /
    ) -> Effect[list[RemoteEntry]]: ...

    @abstractmethod
    def changes(
        self,
        store_id: StoreId,
        start_sequence: int,
        compactors: Mapping[str, RegisteredCompactor],
        /,
    ) -> Stream[RemoteEntry]: ...

    def with_transaction[A, E, R](self, effect: Effect[A, E, R], /) -> Effect[A, E, R]:
        """Run ``effect`` in the storage's transaction, so its writes commit
        together and publish in commit order."""
        require_effect(effect, "effect")
        return self._with_transaction(effect)

    @abstractmethod
    def _with_transaction[A, E, R](self, effect: Effect[A, E, R], /) -> Effect[A, E, R]: ...


class Storage(Tag[StorageService], key="effect/eventlog/EventLogServerUnencrypted/Storage"):
    pass


_EMPTY_PRIVATE_KEY = redacted(bytes(32))


def _client_identity(public_key: str) -> IdentityService:
    return IdentityService(public_key, _EMPTY_PRIVATE_KEY)


def _server_write_public_key(store_id: StoreId) -> str:
    return f"effect-eventlog-server-write:{store_id}"


class HistoryIndex:
    """Stored entries by id and by event and primary key."""

    def __init__(self, history: Sequence[Entry]) -> None:
        self._ids: set[bytes] = set()
        self._by_key: dict[tuple[str, str], list[Entry]] = {}
        # Storage returns history in sequence order; conflicts are in id order.
        for entry in sorted(history, key=lambda e: e.id):
            self._ids.add(entry.id)
            self._by_key.setdefault((entry.event, entry.primary_key), []).append(entry)

    def has(self, entry: Entry) -> bool:
        return entry.id in self._ids

    def conflicts(self, entry: Entry) -> list[Entry]:
        stored = self._by_key.get((entry.event, entry.primary_key), [])
        return [candidate for candidate in stored if candidate.id > entry.id]


def _representative_sequences(
    remote_entries: Sequence[RemoteEntry], compacted_count: int
) -> list[int] | None:
    if compacted_count == 0:
        return []
    if compacted_count > len(remote_entries):
        return None
    max_sequence = remote_entries[-1].remote_sequence
    if compacted_count == 1:
        return [max_sequence]
    selected = [e.remote_sequence for e in remote_entries[: compacted_count - 1]]
    selected.append(max_sequence)
    if any(b <= a for a, b in pairwise(selected)):
        return None
    return selected


def compact_backlog(
    remote_entries: Sequence[RemoteEntry], compactors: Mapping[str, RegisteredCompactor]
) -> Effect[list[RemoteEntry]]:
    """Runs of entries sharing a compactor, compacted; outputs take the
    sequences of their run's first entries and its last (a run that
    cannot be renumbered stays as it was)."""
    if not compactors or not remote_entries:
        return succeed(list(remote_entries))

    def body():
        result: list[RemoteEntry] = []
        index = 0
        while index < len(remote_entries):
            compactor = compactors.get(remote_entries[index].entry.event)
            if compactor is None:
                result.append(remote_entries[index])
                index += 1
                continue
            group: list[RemoteEntry] = []
            while index < len(remote_entries) and (
                compactors.get(remote_entries[index].entry.event) is compactor
            ):
                group.append(remote_entries[index])
                index += 1
            entries = [e.entry for e in group]
            positions: dict[bytes, int] = {e.id: i for i, e in enumerate(entries)}
            compacted: list[list[Entry]] = [[] for _ in entries]

            def write(
                entry: Entry,
                source: Entry | None,
                positions: dict[bytes, int] = positions,
                compacted: list[list[Entry]] = compacted,
            ) -> Effect[None]:
                return sync(lambda: compacted[positions.get((source or entry).id, 0)].append(entry))

            yield from compactor.effect(entries, write)
            flat = [e for part in compacted for e in part]
            sequences = _representative_sequences(group, len(flat))
            if sequences is None:
                result.extend(group)
            else:
                result.extend(
                    RemoteEntry(remote_sequence=s, entry=e)
                    for s, e in zip(sequences, flat, strict=True)
                )
        return result

    return gen(body)


type _ServerHandler = Callable[..., Effect[Any, Any, Identity]]


def _make_server_handler(registry: RegistryService) -> _ServerHandler:
    def handle(
        *,
        public_key: str,
        store_id: StoreId,
        entry: Entry,
        conflicts: Sequence[Entry],
        payload: tuple[Any] | None = None,
    ) -> Effect[Any, Any, Identity]:
        handler = registry.handlers.get(entry.event)
        if handler is None:
            return log_debug(f'Event handler not found for: "{entry.event}"')
        decode = decode_effect(handler.event.payload_codec)

        def body():
            decoded: list[Conflict[Any]] = []
            for conflict in conflicts:
                value = yield from _under(handler.context, decode(conflict.payload))
                decoded.append(Conflict(conflict, value))
            if payload is not None:
                value = payload[0]
            else:
                value = yield from decode(entry.payload).map_error(
                    lambda _: EventLogServerStoreError(
                        "PersistenceFailure", public_key, store_id, "Failed to decode event"
                    )
                )
            return (
                yield from handler.handler(HandlerInput(store_id, value, entry, tuple(decoded)))
            )

        return _under(handler.context, gen(body))

    return handle


def _protocol_error(
    code: Literal["Unauthorized", "Forbidden", "InternalServerError"],
    message: str | None,
    public_key: str | None = None,
    store_id: StoreId | None = None,
    request_tag: str = "WriteEntries",
) -> EventLogProtocolError:
    return EventLogProtocolError(
        request_tag=request_tag,
        code=code,
        message=message or "",
        public_key=public_key,
        store_id=store_id,
    )


def _rpc_handlers():
    storage = yield from Storage()
    mapping = yield from StoreMapping()
    auth = yield from EventLogServerAuthorization()
    registry = yield from Registry()
    handler = _make_server_handler(registry)
    remote_id = yield from storage.get_id

    def process_entries(
        public_key: str, store_id: StoreId, entries: Sequence[Entry]
    ) -> Effect[tuple[WriteAck, ...], Any, Identity]:
        def body():
            ordered = sorted(entries, key=lambda e: e.id)
            stored = yield from storage.entries_after(store_id, ordered[0], ordered)
            index = HistoryIndex([r.entry for r in stored])
            persisted: list[Entry] = []
            for entry in ordered:
                if index.has(entry):
                    continue
                yield from handler(
                    public_key=public_key,
                    store_id=store_id,
                    entry=entry,
                    conflicts=index.conflicts(entry),
                )
                persisted.append(entry)
            committed = yield from storage.write(store_id, persisted)
            sequences = {r.entry.id: r.remote_sequence for r in [*stored, *committed]}
            return tuple(
                WriteAck(entry_id=e.id, sequence=sequences[e.id])
                for e in entries
                if e.id in sequences
            )

        return storage.with_transaction(gen(body))

    def authorize_identity(public_key: str) -> Effect[None, EventLogProtocolError]:
        return auth.authorize_identity(public_key=public_key).map_error(
            lambda error: _protocol_error(
                "Forbidden" if error.reason == "Forbidden" else "Unauthorized",
                error.message,
                public_key,
                request_tag="Authenticate",
            )
        )

    def on_write(
        data: bytes, authenticated: frozenset[str], writes: ConnectionWrites
    ) -> Effect[tuple[WriteAck, ...], EventLogProtocolError]:
        def body():
            request = yield from WriteEntriesUnencrypted.decode(data).map_error(
                lambda _: _protocol_error("InternalServerError", "Decoding failure")
            )
            public_key = request.public_key
            if public_key not in authenticated:
                return (
                    yield from fail(
                        _protocol_error("Forbidden", "Identity is not authenticated", public_key)
                    )
                )
            if not request.entries:
                return ()

            def unauthorized(error: EventLogServerStoreError | EventLogServerAuthError):
                return _protocol_error("Unauthorized", error.message, public_key, request.store_id)

            store_id = yield from mapping.resolve(
                public_key=public_key, store_id=request.store_id
            ).map_error(unauthorized)
            yield from auth.authorize_write(
                public_key=public_key, store_id=store_id, entries=request.entries
            ).map_error(unauthorized)
            write = process_entries(public_key, store_id, request.entries)
            from pyfect.effect import provide_service

            return (
                yield from writes.track(
                    public_key=public_key,
                    store_id=request.store_id,
                    entry_ids=[e.id for e in request.entries],
                    write=write,
                )
                .catch_cause(
                    lambda _: fail(
                        _protocol_error("InternalServerError", "Persistence failure", public_key)
                    )
                )
                .pipe(provide_service(Identity, _client_identity(public_key)))
            )

        return gen(body)

    def changes(
        public_key: str, store_id: StoreId, start_sequence: int, writes: ConnectionWrites
    ) -> Stream[bytes, object]:
        def open_changes():
            resolved = yield from mapping.resolve(public_key=public_key, store_id=store_id)
            yield from auth.authorize_read(public_key=public_key, store_id=resolved)
            return writes.filter(
                public_key=public_key,
                store_id=store_id,
                entry_ids=lambda remote_entry: [remote_entry.entry.id],
                sequence=lambda remote_entry: remote_entry.remote_sequence,
                stream=storage.changes(resolved, start_sequence, registry.compactors),
            ).map_array_effect(
                lambda entries: encode_changes_unencrypted(entries).map(lambda d: (d,))
            )

        return stream_unwrap(gen(open_changes))

    return _layer_rpc_handlers(
        remote_id=remote_id,
        first_sequence=storage.first_sequence,
        authorize_identity=authorize_identity,
        get_or_create_session_auth_binding=storage.get_or_create_session_auth_binding,
        on_write=on_write,
        changes=changes,
    )


layer_rpc_handlers: Layer[
    HandlersFor[EventLogRemoteRpcs] | EventLogAuthentication,
    Never,
    Storage | StoreMapping | EventLogServerAuthorization | Registry,
] = unwrap(gen(_rpc_handlers))
"""The RPC handlers of an unencrypted server."""


class _MemoryStore:
    __slots__ = ("by_id", "by_key", "journal")

    def __init__(self) -> None:
        self.journal: list[RemoteEntry] = []
        self.by_id: dict[bytes, RemoteEntry] = {}
        self.by_key: dict[tuple[str, str], list[RemoteEntry]] = {}


class _MemoryStorage(StorageService):
    first_sequence = 1

    def __init__(self, semaphore: Semaphore, pubsubs: RcMap[str, PubSub[RemoteEntry]]) -> None:
        self._stores: dict[str, _MemoryStore] = {}
        # A pubsub per store, shut down a minute after its last user or
        # when the storage's scope closes.
        self._pubsubs = pubsubs
        self._bindings: dict[str, bytes] = {}
        self._remote_id = make_remote_id_unsafe()
        self._semaphore = semaphore

    def _store(self, store_id: StoreId) -> _MemoryStore:
        return self._stores.setdefault(store_id, _MemoryStore())

    @property
    def get_id(self) -> Effect[RemoteId]:
        return succeed(self._remote_id)

    def get_or_create_session_auth_binding(
        self, public_key: str, signing_public_key: bytes, /
    ) -> Effect[bytes]:
        return sync(lambda: self._bindings.setdefault(public_key, signing_public_key))

    def entries_after(
        self, store_id: StoreId, oldest: Entry, batch: Sequence[Entry] | None = None, /
    ) -> Effect[list[RemoteEntry]]:
        def read() -> list[RemoteEntry]:
            store = self._store(store_id)
            if batch is None:
                return [r for r in store.journal if r.entry.id >= oldest.id]
            found: dict[int, RemoteEntry] = {}
            scanned: set[tuple[str, str]] = set()
            for entry in batch:
                known = store.by_id.get(entry.id)
                if known is not None:
                    found[known.remote_sequence] = known
                key = (entry.event, entry.primary_key)
                if key in scanned:
                    continue
                scanned.add(key)
                for r in store.by_key.get(key, []):
                    if r.entry.id >= oldest.id:
                        found[r.remote_sequence] = r
            return [found[s] for s in sorted(found)]

        return sync(read)

    def write(self, store_id: StoreId, entries: Sequence[Entry], /) -> Effect[list[RemoteEntry]]:
        def body():
            store = self._store(store_id)
            if any(e.id in store.by_id for e in entries):
                return (yield from die(ValueError("Duplicate entries")))
            last = store.journal[-1].remote_sequence if store.journal else 0
            committed: list[RemoteEntry] = []
            for entry in entries:
                last += 1
                remote_entry = RemoteEntry(remote_sequence=last, entry=entry)
                committed.append(remote_entry)
                store.journal.append(remote_entry)
                store.by_id[entry.id] = remote_entry
                store.by_key.setdefault((entry.event, entry.primary_key), []).append(remote_entry)
            pubsub = yield from self._pubsubs.get(store_id)
            yield from pubsub.publish_all(committed)
            return committed

        return scoped(gen(body))

    def changes(
        self,
        store_id: StoreId,
        start_sequence: int,
        compactors: Mapping[str, RegisteredCompactor],
        /,
    ) -> Stream[RemoteEntry]:
        def open_changes():
            pubsub = yield from self._pubsubs.get(store_id)
            subscription = yield from pubsub.subscribe()
            journal = self._store(store_id).journal
            # The journal is append-only with strictly increasing sequences.
            start = bisect.bisect_left(journal, start_sequence, key=lambda r: r.remote_sequence)
            backlog = yield from compact_backlog(journal[start:], compactors)
            replayed_up_to = backlog[-1].remote_sequence if backlog else start_sequence - 1
            return from_iterable(backlog).concat(
                from_subscription(subscription).filter(lambda r: r.remote_sequence > replayed_up_to)
            )

        return stream_unwrap(gen(open_changes))

    def _with_transaction[A, E, R](self, effect: Effect[A, E, R], /) -> Effect[A, E, R]:
        return self._semaphore.with_permits(effect)


def _open_pubsub(_store_id: str) -> Effect[PubSub[RemoteEntry], Never, Scope]:
    return acquire_release(PubSub[RemoteEntry].unbounded(), lambda p, _: p.shutdown())


def _make_storage_memory():
    semaphore = yield from Semaphore.make(1)
    pubsubs = yield from RcMap.make(_open_pubsub, idle_time_to_live=60)
    return _MemoryStorage(semaphore, pubsubs)


make_storage_memory: Effect[StorageService, Never, Scope] = gen(_make_storage_memory)
"""Storage kept in memory (sequences start at 1), its pubsubs shut down when
the scope closes."""

layer_storage_memory: Layer[Storage] = layer_effect(Storage, make_storage_memory)


class EventLogServerUnencryptedService:
    """Writes events from the server itself."""

    def __init__(self, storage: StorageService, handler: _ServerHandler) -> None:
        self._storage = storage
        self._handler = handler

    def make_write(self, schema: EventLogSchema[Any]) -> Callable[..., Effect[Any, Any]]:
        events: dict[str, AnyEvent] = {}
        for group in schema.groups:
            events.update(group.events)

        @overload
        def write[P, A, E](
            *, store_id: StoreId, event: Event[P, A, E], payload: P
        ) -> Effect[A, E | EventLogServerStoreError]: ...
        @overload
        def write(*, store_id: StoreId, event: str, payload: Any) -> Effect[Any, Any]: ...
        def write(*, store_id: StoreId, event: AnyEvent | str, payload: Any) -> Effect[Any, Any]:
            tag = event if isinstance(event, str) else event.tag
            public_key = _server_write_public_key(store_id)
            schema_event = events.get(tag)
            if schema_event is None:
                return die(LookupError(f'Event schema not found for: "{tag}"'))

            def body():
                encoded = yield from encode_effect(schema_event.payload_codec)(payload).map_error(
                    lambda _: EventLogServerStoreError(
                        "PersistenceFailure", public_key, store_id, "Failed to encode event"
                    )
                )
                entry = Entry(
                    id=make_entry_id_unsafe(),
                    event=tag,
                    primary_key=schema_event.primary_key(payload),
                    payload=encoded,
                )
                from pyfect.effect import provide_service

                result = yield from self._handler(
                    public_key=public_key,
                    store_id=store_id,
                    entry=entry,
                    conflicts=(),
                    payload=(payload,),
                ).pipe(provide_service(Identity, _client_identity(public_key)))
                yield from self._storage.write(store_id, [entry])
                return result

            return self._storage.with_transaction(gen(body))

        return write


class EventLogServerUnencrypted(
    Tag[EventLogServerUnencryptedService], key="effect/eventlog/EventLogServerUnencrypted"
):
    pass


def make_write(
    schema: EventLogSchema[Any],
) -> Effect[Callable[..., Effect[Any, Any]], Never, EventLogServerUnencrypted]:
    """The server's ``write(store_id=, event=, payload=)`` for ``schema``."""
    return EventLogServerUnencrypted().map(lambda server: server.make_write(schema))


def _make_server():
    storage = yield from Storage()
    registry = yield from Registry()
    return EventLogServerUnencryptedService(storage, _make_server_handler(registry))


layer_server: Layer[EventLogServerUnencrypted | Registry, Never, Storage] = layer_effect(
    EventLogServerUnencrypted, gen(_make_server)
).pipe(provide_merge(layer_registry))
"""``EventLogServerUnencrypted`` and its ``Registry``."""


def layer[E, R](
    schema: EventLogSchema[Any], handlers: Layer[Any, E, R]
) -> Layer[
    Never,
    E,
    R | EventLogServerAuthorization | ServerProtocol | Storage | StoreMapping,
]:
    """An unencrypted server of ``schema`` with the group ``handlers``,
    over the ``ServerProtocol``."""
    require_layer(handlers, "handlers")
    del schema
    return (
        rpc_server_layer(EventLogRemoteRpcs)
        .pipe(layer_provide(layer_rpc_handlers))
        .pipe(layer_provide(handlers))
        .pipe(layer_provide(layer_server))
    )


def layer_no_rpc_server[E, R](
    schema: EventLogSchema[Any], handlers: Layer[Any, E, R]
) -> Layer[
    HandlersFor[EventLogRemoteRpcs] | EventLogAuthentication,
    E,
    R | EventLogServerAuthorization | Storage | StoreMapping,
]:
    """The RPC handlers of an unencrypted server, without the server."""
    require_layer(handlers, "handlers")
    del schema
    rpc_handlers = cast(
        "Layer[HandlersFor[EventLogRemoteRpcs] | EventLogAuthentication, E, Any]",
        layer_rpc_handlers,
    )
    return merge(rpc_handlers, handlers).pipe(layer_provide(layer_server))
