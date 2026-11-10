"""Remotes an event log syncs with (Effect's ``eventlog/EventLogRemote``).

A remote sends the journal's new entries with ``write`` and streams the
entries others wrote with ``changes``. ``make_encrypted`` and
``make_unencrypted`` are remotes over the ``EventLogRemoteRpcs`` of an
``EventLogRemoteClient``; they authenticate each identity once (again
after a ``Forbidden``) and register with the log's ``Registry``.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Generator, Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Never, Protocol

from pyfect._concurrency import for_each
from pyfect._core import Effect
from pyfect._public import publish
from pyfect.cache import Cache
from pyfect.context import Tag
from pyfect.effect import gen, succeed
from pyfect.eventlog._identity import Identity, IdentityService
from pyfect.eventlog._identity_derivation import make_get_identity_root_secret_material
from pyfect.eventlog._remote_compaction_client import (
    CompactionStage,
    EncryptedCompaction,
    EventLogRemoteCompaction,
    RemoteSession,
)
from pyfect.eventlog._remote_error import EventLogRemoteError
from pyfect.eventlog.event_journal import (
    EntriesById,
    Entry,
    EventJournalError,
    RemoteEntry,
    RemoteId,
    StoreId,
)
from pyfect.eventlog.event_log import Registry
from pyfect.eventlog.event_log_encryption import (
    EventLogEncryption,
    EventLogEncryptionService,
    layer_subtle,
)
from pyfect.eventlog.event_log_message import (
    CHUNK_SIZE,
    Authenticate,
    ChunkedMessage,
    EventLogCompactionRpcs,
    EventLogProtocolError,
    EventLogRemoteRpcs,
    HelloResponse,
    SingleMessage,
    WriteAck,
    WriteEntries,
    WriteEntriesUnencrypted,
    decode_changes_encrypted,
    decode_changes_unencrypted,
)
from pyfect.eventlog.event_log_session_auth import (
    SessionAuthPayload,
    encode_session_auth_payload,
    sign_session_auth_payload_bytes,
)
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.layer import provide as layer_provide
from pyfect.queue import Dequeue, Queue
from pyfect.redacted import value as reveal
from pyfect.result import Err, Ok, Result
from pyfect.rpc.client import ClientOptions, ClientProtocol
from pyfect.rpc.client import make as make_rpc_client
from pyfect.schema import SchemaError
from pyfect.scope import Scope, fork_scoped
from pyfect.stream import Stream
from pyfect.stream import unwrap as unwrap_stream

__all__ = [
    "Changes",
    "CompactionStage",
    "DecodeChanges",
    "EncodeWrite",
    "EventLogRemote",
    "EventLogRemoteClient",
    "EventLogRemoteCompaction",
    "EventLogRemoteError",
    "EventLogRemoteService",
    "LatestSequence",
    "MakeCompaction",
    "RemoteSession",
    "WhenAuthenticated",
    "WriteFn",
    "layer_client",
    "layer_encrypted",
    "layer_encrypted_with",
    "layer_unencrypted",
    "make_encrypted",
    "make_encrypted_with",
    "make_unencrypted",
    "make_with",
]

publish(globals())


class Changes(Protocol):
    def __call__(
        self,
        *,
        identity: IdentityService,
        store_id: StoreId,
        start_sequence: int,
        known_entries: EntriesById | None = None,
    ) -> Effect[Dequeue[RemoteEntry, EventLogRemoteError], Never, Scope]: ...


class WriteFn(Protocol):
    def __call__(
        self, *, identity: IdentityService, store_id: StoreId, entries: Sequence[Entry]
    ) -> Effect[Sequence[WriteAck] | None, EventLogRemoteError]: ...


class LatestSequence(Protocol):
    def __call__(
        self, *, identity: IdentityService, store_id: StoreId
    ) -> Effect[int | None, EventLogRemoteError]: ...


class WhenAuthenticated(Protocol):
    """Runs an effect once the ``Identity`` it runs as is authenticated
    with the remote."""

    def __call__[A, E, R](
        self, effect: Effect[A, E, R], /
    ) -> Effect[A, E | EventLogRemoteError, R | Identity]: ...


def _authenticated[A, E, R](effect: Effect[A, E, R], /) -> Effect[A, E, R]:
    return effect


@dataclass(frozen=True, slots=True)
class EventLogRemoteService:
    """A remote: its id, the sequence its changes start at, ``changes``
    from ``start_sequence``, ``write`` (succeeding with the acks, or
    ``None`` when it has none), ``when_authenticated`` and
    ``latest_sequence``, the highest sequence it has stored for a store
    (a pyfect addition, ``None`` for a remote that cannot tell, which
    ``EventLogService.synced`` then does not wait for), and ``compaction``."""

    id: RemoteId
    changes: Changes
    write: WriteFn
    first_sequence: int | None = None
    when_authenticated: WhenAuthenticated = _authenticated
    latest_sequence: LatestSequence | None = None
    compaction: EventLogRemoteCompaction | None = None
    """Encrypted remote compaction: present when the remote advertises
    ``HelloResponse.compaction`` and the RPC client includes
    ``EventLogCompactionRpcs``."""


class EventLogRemote(Tag[EventLogRemoteService], key="effect/eventlog/EventLogRemote"):
    """A remote of the event log."""


class EventLogRemoteClient(
    Tag[EventLogRemoteRpcs], key="effect/eventlog/EventLogRemote/EventLogRemoteClient"
):
    """The RPC client of an event log server. The ``EventLogCompactionRpcs``
    are optional: the encrypted remote offers compaction only when the
    client is also an ``EventLogCompactionRpcs`` client."""


class _RemoteAndCompactionRpcs(EventLogRemoteRpcs, EventLogCompactionRpcs):
    """Both groups (Effect's ``EventLogRemoteRpcs.merge(EventLogCompactionRpcs)``)."""


layer_client: Layer[EventLogRemoteClient, Never, ClientProtocol] = layer_effect(
    EventLogRemoteClient,
    make_rpc_client(_RemoteAndCompactionRpcs, ClientOptions(disable_tracing=True)),
)
"""``EventLogRemoteClient`` over the ``ClientProtocol``, with both groups."""

_get_material = make_get_identity_root_secret_material()


def _make_authenticate(
    identity: IdentityService, hello: HelloResponse
) -> Effect[Authenticate, Any]:
    def body():
        material = yield from _get_material(identity)
        payload = yield from encode_session_auth_payload(
            SessionAuthPayload(
                remote_id=hello.remote_id,
                challenge=hello.challenge,
                public_key=identity.public_key,
                signing_public_key=material.signing_public_key,
            )
        )
        signature = yield from sign_session_auth_payload_bytes(
            payload, reveal(material.signing_private_key)
        )
        return Authenticate(
            public_key=identity.public_key,
            signing_public_key=material.signing_public_key,
            signature=signature,
            algorithm="Ed25519",
        )

    return gen(body)


type EncodeWrite = Callable[[IdentityService, StoreId, Sequence[Entry]], Effect[bytes, SchemaError]]
type DecodeChanges = Callable[
    [IdentityService, StoreId, bytes, EntriesById | None],
    Effect[Sequence[RemoteEntry], SchemaError | EventJournalError],
]


def _is_forbidden(error: object) -> bool:
    if isinstance(error, EventLogRemoteError) and error.method == "authenticate":
        error = error.cause
    return isinstance(error, EventLogProtocolError) and error.code == "Forbidden"


def _as_remote_error(method: str) -> Callable[[object], EventLogRemoteError]:
    return lambda cause: EventLogRemoteError(method=method, cause=cause)


def _to_remote_error(method: str) -> Callable[[object], EventLogRemoteError]:
    """Wraps a failure, keeping an ``EventLogRemoteError`` as it is."""
    return lambda cause: (
        cause
        if isinstance(cause, EventLogRemoteError)
        else EventLogRemoteError(method=method, cause=cause)
    )


def _as_changes_error(cause: object) -> EventLogRemoteError:
    # Only changes keeps an authentication error as it is; write and
    # authenticate wrap whatever failed, a hello or authentication included.
    if isinstance(cause, EventLogRemoteError):
        return cause
    return EventLogRemoteError(method="changes", cause=cause)


def _pump_changes(
    client: EventLogRemoteRpcs,
    decode_changes: DecodeChanges,
    outgoing: Queue[RemoteEntry, EventLogRemoteError],
    *,
    identity: IdentityService,
    store_id: StoreId,
    start_sequence: int,
    known_entries: EntriesById | None,
) -> Effect[Never, Any, Scope]:
    """Subscribe to the server's changes and offer the decoded entries from
    ``start_sequence`` to ``outgoing``, joining chunked messages."""

    def pump():
        chunked = ChunkedMessage.initial_join_state()
        incoming = yield from client.changes(
            {
                "public_key": identity.public_key,
                "store_id": store_id,
                "start_sequence": start_sequence,
            },
            as_queue=True,
        )

        # A batch can start before start_sequence; those entries are dropped.
        def offer(data: bytes):
            entries = yield from decode_changes(identity, store_id, data, known_entries)
            kept = [e for e in entries if e.remote_sequence >= start_sequence]
            if kept:
                yield from outgoing.offer_all(kept)

        while True:
            parts = yield from incoming.take_all()
            for part in parts:
                if isinstance(part, SingleMessage):
                    yield from offer(part.data)
                    continue
                data = ChunkedMessage.join(chunked, part)
                if data is not None:
                    yield from offer(data)

    return gen(pump)


@dataclass(slots=True)
class _HelloState:
    """The server's last hello; ``None`` makes the next authentication say
    hello again."""

    hello: HelloResponse | None


class _Session:
    """A remote's authentication: each identity authenticates once, and
    again after a ``Forbidden``."""

    __slots__ = ("_auth_cache", "_identities", "_state", "client")

    def __init__(
        self,
        client: EventLogRemoteRpcs,
        state: _HelloState,
        identities: dict[str, IdentityService],
        auth_cache: Cache[str, None, EventLogRemoteError],
    ) -> None:
        self.client = client
        self._state = state
        self._identities = identities
        self._auth_cache = auth_cache

    def ensure_authenticated(self, identity: IdentityService) -> Effect[None, EventLogRemoteError]:
        self._identities.setdefault(identity.public_key, identity)
        return self._auth_cache.get(identity.public_key)

    def reset_authentication(self, identity: IdentityService) -> Effect[None]:
        """The next request says hello and authenticates again."""
        self._state.hello = None
        return self._auth_cache.invalidate(identity.public_key)

    def retry_forbidden[A, E, R](
        self, effect: Effect[A, E, R], identity: IdentityService
    ) -> Effect[A, E, R]:
        def while_(error: E) -> Effect[bool]:
            return self.reset_authentication(identity).as_(_is_forbidden(error))

        return effect.retry(while_=while_, times=5)

    def request[A, E](
        self, method: str, identity: IdentityService, effect: Effect[A, E], /
    ) -> Effect[A, EventLogRemoteError]:
        authenticated = self.ensure_authenticated(identity).and_then(effect)
        return self.retry_forbidden(authenticated, identity).map_error(_to_remote_error(method))

    def framed[A, E, E2](
        self,
        method: str,
        identity: IdentityService,
        frames: Callable[[], Stream[SingleMessage | ChunkedMessage, E]],
        decode: Callable[[bytes], Effect[Iterable[A], E2]],
        /,
    ) -> Stream[A, EventLogRemoteError]:
        # Not retried like ``request``; a refused identity authenticates again
        # on the next request.
        def open_frames() -> Stream[A, E | E2]:
            state = ChunkedMessage.initial_join_state()

            def join(frame: SingleMessage | ChunkedMessage) -> Result[bytes, None]:
                data = (
                    frame.data
                    if isinstance(frame, SingleMessage)
                    else ChunkedMessage.join(state, frame)
                )
                return Err(None) if data is None else Ok(data)

            return frames().filter_map(join).map_effect(decode).flatten_iterable()

        def reset_if_forbidden(error: object) -> Effect[None]:
            return self.reset_authentication(identity) if _is_forbidden(error) else succeed(None)

        opened: Stream[A, E | E2 | EventLogRemoteError] = unwrap_stream(
            self.ensure_authenticated(identity).map(lambda _: open_frames())
        )
        return opened.tap_error(reset_if_forbidden).map_error(_to_remote_error(method))


def _make_session(
    client: EventLogRemoteRpcs,
) -> Effect[tuple[_Session, HelloResponse], EventLogRemoteError]:
    def body():
        hello_call = client.hello().map_error(_as_remote_error("hello"))
        first: HelloResponse = yield from hello_call
        state = _HelloState(first)
        identities: dict[str, IdentityService] = {}

        def lookup(public_key: str) -> Effect[None, EventLogRemoteError]:
            def authenticate():
                hello = state.hello
                if hello is None:
                    hello = state.hello = yield from hello_call
                request = yield from _make_authenticate(identities[public_key], hello)
                yield from client.authenticate(request)

            return gen(authenticate).map_error(_as_remote_error("authenticate"))

        auth_cache = yield from Cache.make(lookup, capacity=sys.maxsize)
        return _Session(client, state, identities, auth_cache), first

    return gen(body)


type MakeCompaction = Callable[[RemoteSession, EventLogRemoteRpcs], EventLogRemoteCompaction | None]


def make_with(
    encode_write: EncodeWrite, decode_changes: DecodeChanges
) -> Effect[EventLogRemoteService, EventLogRemoteError, Scope | EventLogRemoteClient | Registry]:
    """A remote over the ``EventLogRemoteClient`` writing entries encoded
    by ``encode_write`` and decoding changes with ``decode_changes``,
    registered with the ``Registry`` until the scope closes."""
    return _make_remote(encode_write, decode_changes, None)


def _make_remote(
    encode_write: EncodeWrite,
    decode_changes: DecodeChanges,
    make_compaction: MakeCompaction | None,
) -> Effect[EventLogRemoteService, EventLogRemoteError, Scope | EventLogRemoteClient | Registry]:
    def body():
        client = yield from EventLogRemoteClient()
        registry = yield from Registry()
        session, hello = yield from _make_session(client)
        chunk_ids = [0]

        def write(
            *, identity: IdentityService, store_id: StoreId, entries: Sequence[Entry]
        ) -> Effect[Sequence[WriteAck] | None, EventLogRemoteError]:
            def run():
                yield from session.ensure_authenticated(identity)
                encoded = yield from encode_write(identity, store_id, entries)
                if len(encoded) <= CHUNK_SIZE:
                    return (yield from client.write_single({"data": encoded}))
                chunk_ids[0] += 1
                parts = ChunkedMessage.split(chunk_ids[0] - 1, encoded)
                # Only the part the server receives last carries acks.
                acks = yield from for_each(parts, client.write_chunked, concurrency=4)
                return [ack for part in acks for ack in part]

            return session.retry_forbidden(gen(run), identity).map_error(_as_remote_error("write"))

        def changes(
            *,
            identity: IdentityService,
            store_id: StoreId,
            start_sequence: int,
            known_entries: EntriesById | None = None,
        ) -> Effect[Dequeue[RemoteEntry, EventLogRemoteError], Never, Scope]:
            def run():
                outgoing = yield from Queue[RemoteEntry, EventLogRemoteError].unbounded()

                pump = _pump_changes(
                    client,
                    decode_changes,
                    outgoing,
                    identity=identity,
                    store_id=store_id,
                    start_sequence=start_sequence,
                    known_entries=known_entries,
                )

                # Forbidden retries resubscribe from the same sequence; other
                # failures reach the EventLog, which reconnects.
                yield from fork_scoped(
                    session.retry_forbidden(
                        session.ensure_authenticated(identity).and_then(pump), identity
                    )
                    .map_error(_as_changes_error)
                    .catch_cause(outgoing.fail_cause)
                )
                return outgoing

            return gen(run)

        def latest_sequence(
            *, identity: IdentityService, store_id: StoreId
        ) -> Effect[int | None, EventLogRemoteError]:
            call = session.ensure_authenticated(identity).and_then(
                client.latest_sequence({"public_key": identity.public_key, "store_id": store_id})
            )
            return session.retry_forbidden(call, identity).map_error(
                _as_remote_error("latestSequence")
            )

        def when_authenticated[A, E, R](
            effect: Effect[A, E, R], /
        ) -> Effect[A, E | EventLogRemoteError, R | Identity]:
            return Identity().flat_map(session.ensure_authenticated).and_then(effect)

        remote = EventLogRemoteService(
            id=hello.remote_id,
            first_sequence=hello.first_sequence,
            changes=changes,
            write=write,
            when_authenticated=when_authenticated,
            latest_sequence=latest_sequence,
            compaction=(
                make_compaction(session, client)
                if hello.compaction is True and make_compaction is not None
                else None
            ),
        )
        yield from registry.register_remote(remote)
        return remote

    return gen(body)


def _make_encrypted_compaction(
    encryption: EventLogEncryptionService,
) -> MakeCompaction:
    def make(session: RemoteSession, client: EventLogRemoteRpcs) -> EventLogRemoteCompaction | None:
        if not isinstance(client, EventLogCompactionRpcs):
            return None
        return EncryptedCompaction(session, client, encryption)

    return make


def _encrypted(compaction: bool) -> Generator[Any, Any, EventLogRemoteService]:
    encryption = yield from EventLogEncryption()

    def encode_write(
        identity: IdentityService, store_id: StoreId, entries: Sequence[Entry]
    ) -> Effect[bytes, SchemaError]:
        return encryption.encrypt(identity, store_id, entries).flat_map(
            lambda batches: (
                WriteEntries(
                    public_key=identity.public_key, store_id=store_id, batches=tuple(batches)
                ).encoded
            )
        )

    def decode_changes(
        identity: IdentityService, store_id: StoreId, data: bytes, known: EntriesById | None
    ) -> Effect[Sequence[RemoteEntry], SchemaError | EventJournalError]:
        # Decryption is skipped only for batches whose entries are all stored.
        def run():
            batches = yield from decode_changes_encrypted(data)
            if known is None:
                return (yield from encryption.decrypt(identity, store_id, batches))
            stored = yield from known([i for batch in batches for i in batch.entry_ids])
            offset = 0
            known_batches: list[list[Entry] | None] = []
            for batch in batches:
                found = stored[offset : offset + len(batch.entry_ids)]
                offset += len(batch.entry_ids)
                entries = [entry for entry in found if entry is not None]
                known_batches.append(entries if len(entries) == len(found) else None)
            decrypted = yield from encryption.decrypt(
                identity,
                store_id,
                [b for b, k in zip(batches, known_batches, strict=True) if k is None],
            )
            result: list[RemoteEntry] = []
            next_decrypted = iter(decrypted)
            for batch, entries in zip(batches, known_batches, strict=True):
                if entries is None:
                    result.extend(next(next_decrypted) for _ in batch.entry_ids)
                else:
                    result.extend(
                        RemoteEntry(remote_sequence=batch.sequence + j, entry=entry)
                        for j, entry in enumerate(entries)
                    )
            return result

        return gen(run)

    make_compaction = _make_encrypted_compaction(encryption) if compaction else None
    return (yield from _make_remote(encode_write, decode_changes, make_compaction))


def make_encrypted_with(
    *, compaction: bool = True
) -> Effect[
    EventLogRemoteService,
    EventLogRemoteError,
    Scope | EventLogRemoteClient | EventLogEncryption | Registry,
]:
    """A remote sending entries encrypted with the ``EventLogEncryption``.
    It has a ``compaction`` member when the server advertises compaction and
    the RPC client includes ``EventLogCompactionRpcs``, unless built with
    ``compaction=False``; without one this client never calls the
    compaction RPCs."""
    return gen(lambda: _encrypted(compaction))


make_encrypted: Effect[
    EventLogRemoteService,
    EventLogRemoteError,
    Scope | EventLogRemoteClient | EventLogEncryption | Registry,
] = make_encrypted_with()
"""A remote sending entries encrypted with the ``EventLogEncryption``
(``make_encrypted_with`` opts out of running compaction)."""


def _encode_unencrypted(
    identity: IdentityService, store_id: StoreId, entries: Sequence[Entry]
) -> Effect[bytes, SchemaError]:
    return WriteEntriesUnencrypted(
        public_key=identity.public_key, store_id=store_id, entries=tuple(entries)
    ).encoded


def _decode_unencrypted(
    _identity: IdentityService, _store_id: StoreId, data: bytes, _known: EntriesById | None
) -> Effect[Sequence[RemoteEntry], SchemaError]:
    return decode_changes_unencrypted(data)


make_unencrypted: Effect[
    EventLogRemoteService, EventLogRemoteError, Scope | EventLogRemoteClient | Registry
] = make_with(_encode_unencrypted, _decode_unencrypted)
"""A remote sending plain entries (to an unencrypted server)."""


def layer_encrypted_with(
    *, compaction: bool = True
) -> Layer[EventLogRemote, EventLogRemoteError, ClientProtocol | Registry]:
    """An encrypted remote over the ``ClientProtocol``; ``compaction=False``
    leaves it without its ``compaction`` member, so this client never calls
    the compaction RPCs."""
    return (
        layer_effect(EventLogRemote, make_encrypted_with(compaction=compaction))
        .pipe(layer_provide(layer_client))
        .pipe(layer_provide(layer_subtle))
    )


layer_encrypted: Layer[EventLogRemote, EventLogRemoteError, ClientProtocol | Registry] = (
    layer_encrypted_with()
)
"""An encrypted remote over the ``ClientProtocol`` (``layer_encrypted_with``
opts out of running compaction)."""

layer_unencrypted: Layer[EventLogRemote, EventLogRemoteError, ClientProtocol | Registry] = (
    layer_effect(EventLogRemote, make_unencrypted).pipe(layer_provide(layer_client))
)
"""An unencrypted remote over the ``ClientProtocol``."""
