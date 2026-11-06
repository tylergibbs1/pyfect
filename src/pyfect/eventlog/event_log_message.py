"""The RPCs between an event log and its remote server (Effect's
``eventlog/EventLogMessage``).

A client says ``Hello`` (the server's remote id and a one-time
challenge), ``Authenticate``\\s an identity by signing the challenge,
then writes entries (``WriteSingle``, or ``WriteChunked`` parts of at
most 512,000 bytes) and streams ``Changes``. Writes and changes carry
their entries as ``SchemaBinary`` bytes: encrypted batches, or plain
entries for an unencrypted server.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any, Literal, TypedDict, Unpack

from pyfect import schema as S
from pyfect._core import Effect
from pyfect.encoding.schema_binary import BytesCodec, to_codec, wire_name
from pyfect.encoding.schema_binary._undefined import Undefined
from pyfect.eventlog._identity import Identity
from pyfect.eventlog.event_journal import (
    Entry,
    EntryId,
    EntryIdSchema,
    RemoteEntry,
    RemoteId,
    RemoteIdSchema,
    StoreId,
    StoreIdSchema,
)
from pyfect.eventlog.event_log_encryption import EncryptedBatch, EncryptedRemoteBatch
from pyfect.rpc import RpcGroup, RpcMiddleware, make

type ProtocolErrorCode = Literal[
    "Unauthorized", "Forbidden", "NotFound", "InvalidRequest", "InternalServerError"
]


def _absent_or(schema: Any, name: str) -> Any:
    """Effect's ``Schema.optional(schema)`` of the field ``name``."""
    return S.Union(schema, Undefined).pipe(wire_name(name))


class EventLogProtocolError(S.TaggedError, tag="EventLogProtocolError"):
    """A server refused or failed a request."""

    request_tag: str = S.field(S.String.pipe(wire_name("requestTag")))
    code: ProtocolErrorCode = S.field(
        S.Literals("Unauthorized", "Forbidden", "NotFound", "InvalidRequest", "InternalServerError")
    )
    message: str
    public_key: str | None = S.field(_absent_or(S.String, "publicKey"), default=None)
    store_id: StoreId | None = S.field(_absent_or(S.String, "storeId"), default=None)


class EventLogAuthentication(
    RpcMiddleware[Identity, EventLogProtocolError],
    key="effect/eventlog/EventLogMessage/EventLogAuthentication",
):
    """The server middleware providing the authenticated ``Identity``."""

    error = EventLogProtocolError


class HelloResponse(S.Class, identifier="effect/eventlog/EventLogRemote/HelloResponse"):
    """The server's remote id, a challenge to sign, and the first sequence
    its changes start at."""

    remote_id: RemoteId = S.field(wire_name("remoteId")(RemoteIdSchema))
    challenge: bytes = S.field(S.Bytes)
    first_sequence: int | None = S.field(_absent_or(S.Natural, "firstSequence"), default=None)


class Authenticate(S.Class, identifier="effect/eventlog/EventLogRemote/Authenticate"):
    """An identity's public key, its signing public key and the signature
    of the session auth payload."""

    public_key: str = S.field(S.String.pipe(wire_name("publicKey")))
    signing_public_key: bytes = S.field(S.Bytes.pipe(wire_name("signingPublicKey")))
    signature: bytes = S.field(S.Bytes)
    algorithm: Literal["Ed25519"] = S.field(S.Literal("Ed25519"))


class SingleMessage(
    S.TaggedClass, tag="Single", identifier="effect/eventlog/EventLogRemote/SingleMessage"
):
    data: bytes = S.field(S.Bytes)


def _part_in_range(part: tuple[int, int]) -> bool:
    return part[0] < part[1]


CHUNK_SIZE = 512_000

type JoinState = dict[int, _Parts]


_MAX_ARRAY_LENGTH = 2**32 - 1


class _Parts:
    """The parts of one message received so far, by index: held as they
    arrive, so a declared total reserves nothing (Effect's sparse array of
    ``length`` slots, the first total or past the highest index)."""

    __slots__ = ("bytes", "count", "length", "parts")

    def __init__(self, total: int) -> None:
        if total > _MAX_ARRAY_LENGTH:
            raise ValueError("Invalid array length")
        self.parts: dict[int, bytes] = {}
        self.length = total
        self.count = 0
        self.bytes = 0


class ChunkedMessage(
    S.TaggedClass, tag="Chunked", identifier="effect/eventlog/EventLogRemote/ChunkedMessage"
):
    """Part ``part[0]`` of ``part[1]`` of the message ``id``."""

    id: int = S.field(S.Int)
    part: tuple[int, int] = S.field(
        S.Tuple(S.Natural, S.Natural).check(
            S.make_filter(_part_in_range, expected="a chunk part with an index less than its total")
        )
    )
    data: bytes = S.field(S.Bytes)

    chunk_size = CHUNK_SIZE

    @staticmethod
    def initial_join_state() -> JoinState:
        return {}

    @staticmethod
    def split(id: int, data: bytes) -> list[ChunkedMessage]:
        """``data`` in parts of at most ``CHUNK_SIZE`` bytes (one part when
        empty)."""
        parts = max(1, math.ceil(len(data) / CHUNK_SIZE))
        return [
            ChunkedMessage(id=id, part=(i, parts), data=data[i * CHUNK_SIZE : (i + 1) * CHUNK_SIZE])
            for i in range(parts)
        ]

    @staticmethod
    def join(state: JoinState, part: ChunkedMessage) -> bytes | None:
        """Record ``part``; the whole message once every part has arrived
        (a repeated part is ignored)."""
        index, total = part.part
        entry = state.get(part.id)
        if entry is None:
            entry = state[part.id] = _Parts(total)
        if index in entry.parts:
            return None
        entry.parts[index] = part.data
        entry.length = max(entry.length, index + 1)
        entry.count += 1
        entry.bytes += len(part.data)
        if entry.count != total:
            return None
        if len(entry.parts) != entry.length:
            # Effect joins every slot, and an empty one throws (keeping the entry).
            raise ValueError("Chunked message is missing a part")
        del state[part.id]
        return b"".join(entry.parts[i] for i in range(entry.length))


class WriteAck(S.Class, identifier="effect/eventlog/EventLogMessage/WriteAck"):
    """The server stored ``entry_id`` at ``sequence``."""

    entry_id: EntryId = S.field(wire_name("entryId")(EntryIdSchema))
    sequence: int = S.field(S.Natural)


class WriteEntries(S.Class, identifier="effect/eventlog/EventLogRemote/WriteEntries"):
    """Encrypted batches to write to ``store_id``."""

    public_key: str = S.field(S.String.pipe(wire_name("publicKey")))
    store_id: StoreId = S.field(S.String.pipe(wire_name("storeId")))
    batches: tuple[EncryptedBatch, ...]

    @property
    def encoded(self) -> Effect[bytes, S.SchemaError]:
        return S.encode_effect(WRITE_ENTRIES_CODEC)(self)

    @staticmethod
    def decode(
        data: bytes, **options: Unpack[S.ParseOptions]
    ) -> Effect[WriteEntries, S.SchemaError]:
        return S.decode_effect(WRITE_ENTRIES_CODEC, **options)(data)


class WriteEntriesUnencrypted(
    S.Class, identifier="effect/eventlog/EventLogRemote/WriteEntriesUnencrypted"
):
    """Plain entries to write to ``store_id``."""

    public_key: str = S.field(S.String.pipe(wire_name("publicKey")))
    store_id: StoreId = S.field(S.String.pipe(wire_name("storeId")))
    entries: tuple[Entry, ...]

    @property
    def encoded(self) -> Effect[bytes, S.SchemaError]:
        return S.encode_effect(WRITE_ENTRIES_UNENCRYPTED_CODEC)(self)

    @staticmethod
    def decode(
        data: bytes, **options: Unpack[S.ParseOptions]
    ) -> Effect[WriteEntriesUnencrypted, S.SchemaError]:
        return S.decode_effect(WRITE_ENTRIES_UNENCRYPTED_CODEC, **options)(data)


WRITE_ENTRIES_CODEC: BytesCodec[WriteEntries] = to_codec(WriteEntries)
WRITE_ENTRIES_UNENCRYPTED_CODEC: BytesCodec[WriteEntriesUnencrypted] = to_codec(
    WriteEntriesUnencrypted
)

CHANGES_ENCRYPTED_CODEC: BytesCodec[tuple[EncryptedRemoteBatch, ...]] = to_codec(
    S.NonEmptyArray(EncryptedRemoteBatch)
)
CHANGES_UNENCRYPTED_CODEC: BytesCodec[tuple[RemoteEntry, ...]] = to_codec(
    S.NonEmptyArray(RemoteEntry)
)


def encode_changes_encrypted(
    batches: Sequence[EncryptedRemoteBatch],
) -> Effect[bytes, S.SchemaError]:
    """A ``Changes`` frame of encrypted batches (Effect's
    ``ChangesRpc.encodeEncrypted``)."""
    return S.encode_effect(CHANGES_ENCRYPTED_CODEC)(tuple(batches))


def decode_changes_encrypted(
    data: bytes, **options: Unpack[S.ParseOptions]
) -> Effect[tuple[EncryptedRemoteBatch, ...], S.SchemaError]:
    return S.decode_effect(CHANGES_ENCRYPTED_CODEC, **options)(data)


def encode_changes_unencrypted(entries: Sequence[RemoteEntry]) -> Effect[bytes, S.SchemaError]:
    """A ``Changes`` frame of plain entries (Effect's
    ``ChangesRpc.encodeUnencrypted``)."""
    return S.encode_effect(CHANGES_UNENCRYPTED_CODEC)(tuple(entries))


def decode_changes_unencrypted(
    data: bytes, **options: Unpack[S.ParseOptions]
) -> Effect[tuple[RemoteEntry, ...], S.SchemaError]:
    return S.decode_effect(CHANGES_UNENCRYPTED_CODEC, **options)(data)


class WriteSinglePayload(TypedDict):
    data: bytes


class ChangesPayload(TypedDict):
    public_key: str
    store_id: StoreId
    start_sequence: int


class LatestSequencePayload(TypedDict):
    public_key: str
    store_id: StoreId


HelloRpc = make("EventLog.Hello", success=HelloResponse)
AuthenticateRpc = make("EventLog.Authenticate", payload=Authenticate, error=EventLogProtocolError)
WriteChunkedRpc = make(
    "EventLog.WriteChunked",
    payload=ChunkedMessage,
    success=S.Array(WriteAck),
    error=EventLogProtocolError,
).middleware(EventLogAuthentication)
WriteSingleRpc = make(
    "EventLog.WriteSingle",
    payload=S.Struct(WriteSinglePayload, data=S.Bytes),
    success=S.Array(WriteAck),
    error=EventLogProtocolError,
).middleware(EventLogAuthentication)
ChangesRpc = make(
    "EventLog.Changes",
    payload=S.Struct(
        ChangesPayload,
        public_key=S.String.pipe(wire_name("publicKey")),
        store_id=wire_name("storeId")(StoreIdSchema),
        start_sequence=S.Natural.pipe(wire_name("startSequence")),
    ),
    success=S.Union(SingleMessage, ChunkedMessage),
    error=EventLogProtocolError,
    stream=True,
).middleware(EventLogAuthentication)


LatestSequenceRpc = make(
    "EventLog.LatestSequence",
    payload=S.Struct(
        LatestSequencePayload,
        public_key=S.String.pipe(wire_name("publicKey")),
        store_id=wire_name("storeId")(StoreIdSchema),
    ),
    success=S.NullOr(S.Int),
    error=EventLogProtocolError,
).middleware(EventLogAuthentication)
"""The highest sequence the server has stored for an identity's store, or
``None`` (a pyfect addition: what ``EventLog.synced`` waits for)."""


class EventLogRemoteRpcs(RpcGroup):
    """The RPCs of an event log server."""

    hello = HelloRpc
    authenticate = AuthenticateRpc
    write_chunked = WriteChunkedRpc
    write_single = WriteSingleRpc
    changes = ChangesRpc
    latest_sequence = LatestSequenceRpc


__all__ = [
    "CHANGES_ENCRYPTED_CODEC",
    "CHANGES_UNENCRYPTED_CODEC",
    "CHUNK_SIZE",
    "WRITE_ENTRIES_CODEC",
    "WRITE_ENTRIES_UNENCRYPTED_CODEC",
    "Authenticate",
    "AuthenticateRpc",
    "ChangesPayload",
    "ChangesRpc",
    "ChunkedMessage",
    "EventLogAuthentication",
    "EventLogProtocolError",
    "EventLogRemoteRpcs",
    "HelloResponse",
    "HelloRpc",
    "JoinState",
    "LatestSequencePayload",
    "LatestSequenceRpc",
    "ProtocolErrorCode",
    "SingleMessage",
    "StoreId",
    "StoreIdSchema",
    "WriteAck",
    "WriteChunkedRpc",
    "WriteEntries",
    "WriteEntriesUnencrypted",
    "WriteSinglePayload",
    "WriteSingleRpc",
    "decode_changes_encrypted",
    "decode_changes_unencrypted",
    "encode_changes_encrypted",
    "encode_changes_unencrypted",
]
