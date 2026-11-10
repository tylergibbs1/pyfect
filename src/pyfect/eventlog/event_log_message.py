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
from pyfect.encoding.schema_binary import BytesCodec, to_codec
from pyfect.eventlog._identity import Identity
from pyfect.eventlog._transferable_bytes import TransferableBytes
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
from pyfect.schema._undefined import Undefined

type ProtocolErrorCode = Literal[
    "Unauthorized", "Forbidden", "NotFound", "InvalidRequest", "InternalServerError"
]


def _absent_or(schema: Any) -> Any:
    """Effect's ``Schema.optional(schema)``."""
    return S.Union(schema, Undefined)


class EventLogProtocolError(S.TaggedError, tag="EventLogProtocolError"):
    """A server refused or failed a request."""

    request_tag: str = S.field(S.String, key="requestTag")
    public_key: str | None = S.field(_absent_or(S.String), default=None, key="publicKey")
    store_id: StoreId | None = S.field(_absent_or(S.String), default=None, key="storeId")
    code: ProtocolErrorCode = S.field(
        S.Literals("Unauthorized", "Forbidden", "NotFound", "InvalidRequest", "InternalServerError")
    )
    message: str


class EventLogAuthentication(
    RpcMiddleware[Identity, EventLogProtocolError],
    key="effect/eventlog/EventLogMessage/EventLogAuthentication",
):
    """The server middleware providing the authenticated ``Identity``."""

    error = EventLogProtocolError


class HelloResponse(S.Class, identifier="effect/eventlog/EventLogRemote/HelloResponse"):
    """The server's remote id, a challenge to sign, the first sequence its
    changes start at, and whether it serves compaction."""

    remote_id: RemoteId = S.field(RemoteIdSchema, key="remoteId")
    challenge: bytes = S.field(TransferableBytes)
    first_sequence: int | None = S.field(_absent_or(S.Natural), default=None, key="firstSequence")
    compaction: Literal[True] | None = S.field(_absent_or(S.Literal(True)), default=None)
    """``True`` when the server serves ``EventLogCompactionRpcs``."""


class Authenticate(S.Class, identifier="effect/eventlog/EventLogRemote/Authenticate"):
    """An identity's public key, its signing public key and the signature
    of the session auth payload."""

    public_key: str = S.field(S.String, key="publicKey")
    signing_public_key: bytes = S.field(TransferableBytes, key="signingPublicKey")
    signature: bytes = S.field(TransferableBytes)
    algorithm: Literal["Ed25519"] = S.field(S.Literal("Ed25519"))


class SingleMessage(
    S.TaggedClass, tag="Single", identifier="effect/eventlog/EventLogRemote/SingleMessage"
):
    data: bytes = S.field(TransferableBytes)


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
    data: bytes = S.field(TransferableBytes)

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

    entry_id: EntryId = S.field(EntryIdSchema, key="entryId")
    sequence: int = S.field(S.Natural)


class WriteEntries(S.Class, identifier="effect/eventlog/EventLogRemote/WriteEntries"):
    """Encrypted batches to write to ``store_id``."""

    public_key: str = S.field(S.String, key="publicKey")
    store_id: StoreId = S.field(StoreIdSchema, key="storeId")
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

    public_key: str = S.field(S.String, key="publicKey")
    store_id: StoreId = S.field(StoreIdSchema, key="storeId")
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
    payload=S.Struct(WriteSinglePayload, data=TransferableBytes),
    success=S.Array(WriteAck),
    error=EventLogProtocolError,
).middleware(EventLogAuthentication)
ChangesRpc = make(
    "EventLog.Changes",
    payload=S.Struct(
        ChangesPayload, public_key=S.String, store_id=StoreIdSchema, start_sequence=S.Natural
    ).pipe(
        S.encode_keys(
            {"public_key": "publicKey", "store_id": "storeId", "start_sequence": "startSequence"}
        )
    ),
    success=S.Union(SingleMessage, ChunkedMessage),
    error=EventLogProtocolError,
    stream=True,
).middleware(EventLogAuthentication)


LatestSequenceRpc = make(
    "EventLog.LatestSequence",
    payload=S.Struct(LatestSequencePayload, public_key=S.String, store_id=StoreIdSchema).pipe(
        S.encode_keys({"public_key": "publicKey", "store_id": "storeId"})
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


# Encrypted remote compaction (Effect 4.1.2).


class CompactionStatus(S.Class, identifier="effect/eventlog/EventLogRemote/CompactionStatus"):
    """A store's compaction state as reported to clients: ``wanted`` when
    the server would open a stage, ``head`` the highest stored sequence."""

    wanted: bool = S.field(S.Boolean)
    head: int = S.field(S.Int)


class CompactionStarted(S.TaggedClass, tag="Started"):
    """A stage was opened, pinned to the active generation and to the last
    input sequence."""

    stage_id: str = S.field(S.String, key="stageId")


class CompactionBusy(S.TaggedClass, tag="Busy"):
    """Another stage is open on the store."""


class CompactionNotWanted(S.TaggedClass, tag="NotWanted"):
    """The store doesn't need compacting."""


type CompactionBeginResult = CompactionStarted | CompactionBusy | CompactionNotWanted

CompactionBeginResultSchema = S.Union(CompactionStarted, CompactionBusy, CompactionNotWanted)


class CompactionInputHeader(
    S.Class, identifier="effect/eventlog/EventLogRemote/CompactionInputHeader"
):
    """The header of one input batch: an entry's input sequence is
    ``sequence`` plus its position in ``entry_ids``."""

    sequence: int = S.field(S.Natural)
    entry_ids: tuple[EntryId, ...] = S.field(S.NonEmptyArray(EntryIdSchema), key="entryIds")


class CompactionSnapshot(S.TaggedClass, tag="Snapshot"):
    """A run that activates its ``segment_count`` uploaded segments."""

    segment_count: int = S.field(S.Natural, key="segmentCount")


class CompactionNoOp(S.TaggedClass, tag="NoOp"):
    """A run that dropped nothing."""


type CompactionResult = CompactionSnapshot | CompactionNoOp

CompactionResultSchema = S.Union(CompactionSnapshot, CompactionNoOp)


class CompactionScopePayload(TypedDict):
    public_key: str
    store_id: StoreId


class CompactionStagePayload(TypedDict):
    public_key: str
    store_id: StoreId
    stage_id: str


class CompactionFetchPayload(TypedDict):
    public_key: str
    store_id: StoreId
    stage_id: str
    batches: tuple[int, ...]
    """The input sequence of each batch to fetch."""


class CompactionPartPayload(TypedDict):
    public_key: str
    store_id: StoreId
    stage_id: str
    chunk: ChunkedMessage


class CompactionCommitPayload(TypedDict):
    public_key: str
    store_id: StoreId
    stage_id: str
    result: CompactionResult


_SCOPE_KEYS = {"public_key": "publicKey", "store_id": "storeId"}
_STAGE_KEYS = {**_SCOPE_KEYS, "stage_id": "stageId"}

COMPACTION_INPUT_HEADERS_CODEC: BytesCodec[tuple[CompactionInputHeader, ...]] = to_codec(
    S.NonEmptyArray(CompactionInputHeader)
)
"""A ``CompactionInput`` frame (Effect's ``CompactionInputRpc.HeadersFromSchemaBinary``)."""

COMPACTION_SEGMENT_CODEC: BytesCodec[tuple[EncryptedBatch, ...]] = to_codec(
    S.NonEmptyArray(EncryptedBatch)
)
"""A ``CompactionPart`` segment (Effect's ``CompactionPartRpc.SegmentFromSchemaBinary``)."""


def encode_compaction_input_headers(
    headers: Sequence[CompactionInputHeader],
) -> Effect[bytes, S.SchemaError]:
    return S.encode_effect(COMPACTION_INPUT_HEADERS_CODEC)(tuple(headers))


def decode_compaction_input_headers(
    data: bytes, **options: Unpack[S.ParseOptions]
) -> Effect[tuple[CompactionInputHeader, ...], S.SchemaError]:
    return S.decode_effect(COMPACTION_INPUT_HEADERS_CODEC, **options)(data)


def encode_compaction_segment(batches: Sequence[EncryptedBatch]) -> Effect[bytes, S.SchemaError]:
    return S.encode_effect(COMPACTION_SEGMENT_CODEC)(tuple(batches))


def decode_compaction_segment(
    data: bytes, **options: Unpack[S.ParseOptions]
) -> Effect[tuple[EncryptedBatch, ...], S.SchemaError]:
    return S.decode_effect(COMPACTION_SEGMENT_CODEC, **options)(data)


CompactionStatusRpc = make(
    "EventLog.CompactionStatus",
    payload=S.Struct(CompactionScopePayload, public_key=S.String, store_id=StoreIdSchema).pipe(
        S.encode_keys(_SCOPE_KEYS)
    ),
    success=CompactionStatus,
    error=EventLogProtocolError,
).middleware(EventLogAuthentication)
"""Reports a store's compaction state."""

CompactionBeginRpc = make(
    "EventLog.CompactionBegin",
    payload=S.Struct(CompactionScopePayload, public_key=S.String, store_id=StoreIdSchema).pipe(
        S.encode_keys(_SCOPE_KEYS)
    ),
    success=CompactionBeginResultSchema,
    error=EventLogProtocolError,
).middleware(EventLogAuthentication)
"""Opens a compaction stage."""

CompactionInputRpc = make(
    "EventLog.CompactionInput",
    payload=S.Struct(
        CompactionStagePayload, public_key=S.String, store_id=StoreIdSchema, stage_id=S.String
    ).pipe(S.encode_keys(_STAGE_KEYS)),
    success=S.Union(SingleMessage, ChunkedMessage),
    error=EventLogProtocolError,
    stream=True,
).middleware(EventLogAuthentication)
"""Streams a stage's input batch headers in input order: the pinned
snapshot, then the originals up to the stage's ``through``, framed as in
``ChangesRpc``. Fails ``NotFound`` once the stage or its pin is gone."""

CompactionFetchRpc = make(
    "EventLog.CompactionFetch",
    payload=S.Struct(
        CompactionFetchPayload,
        public_key=S.String,
        store_id=StoreIdSchema,
        stage_id=S.String,
        batches=S.Array(S.Natural),
    ).pipe(S.encode_keys(_STAGE_KEYS)),
    success=S.Union(SingleMessage, ChunkedMessage),
    error=EventLogProtocolError,
    stream=True,
).middleware(EventLogAuthentication)
"""Streams the encrypted input batches at the given input sequences, framed
and encoded as in ``ChangesRpc``. Fails ``NotFound`` once the stage or its
pin is gone."""

CompactionPartRpc = make(
    "EventLog.CompactionPart",
    payload=S.Struct(
        CompactionPartPayload,
        public_key=S.String,
        store_id=StoreIdSchema,
        stage_id=S.String,
        chunk=ChunkedMessage,
    ).pipe(S.encode_keys(_STAGE_KEYS)),
    error=EventLogProtocolError,
).middleware(EventLogAuthentication)
"""Uploads one piece of a snapshot segment (an encoded non-empty array of
encrypted batches, indexed by ``chunk.id``). A re-uploaded segment is
acknowledged without storing it again; one that fails validation aborts
the stage with ``InvalidRequest``."""

CompactionAbortRpc = make(
    "EventLog.CompactionAbort",
    payload=S.Struct(
        CompactionStagePayload, public_key=S.String, store_id=StoreIdSchema, stage_id=S.String
    ).pipe(S.encode_keys(_STAGE_KEYS)),
    error=EventLogProtocolError,
).middleware(EventLogAuthentication)
"""Releases an open stage. A late abort is a no-op."""

CompactionCommitRpc = make(
    "EventLog.CompactionCommit",
    payload=S.Struct(
        CompactionCommitPayload,
        public_key=S.String,
        store_id=StoreIdSchema,
        stage_id=S.String,
        result=CompactionResultSchema,
    ).pipe(S.encode_keys(_STAGE_KEYS)),
    success=S.Literals("Committed", "Superseded"),
    error=EventLogProtocolError,
).middleware(EventLogAuthentication)
"""Commits a stage: ``Superseded`` when its pinned generation is no longer
active; ``InvalidRequest`` (aborting the stage) when the segments are
incomplete or the kept ids are not a non-empty, repeat-free subsequence of
the pinned input; ``NotFound`` when the stage expired, was aborted or
committed, or is unknown, so a retried commit fails too."""


class EventLogCompactionRpcs(RpcGroup):
    """The RPCs of encrypted remote compaction, served by the encrypted
    server next to ``EventLogRemoteRpcs``; clients call them only when
    ``HelloResponse.compaction`` is set."""

    compaction_status = CompactionStatusRpc
    compaction_begin = CompactionBeginRpc
    compaction_input = CompactionInputRpc
    compaction_fetch = CompactionFetchRpc
    compaction_part = CompactionPartRpc
    compaction_abort = CompactionAbortRpc
    compaction_commit = CompactionCommitRpc


__all__ = [
    "CHANGES_ENCRYPTED_CODEC",
    "CHANGES_UNENCRYPTED_CODEC",
    "CHUNK_SIZE",
    "COMPACTION_INPUT_HEADERS_CODEC",
    "COMPACTION_SEGMENT_CODEC",
    "WRITE_ENTRIES_CODEC",
    "WRITE_ENTRIES_UNENCRYPTED_CODEC",
    "Authenticate",
    "AuthenticateRpc",
    "ChangesPayload",
    "ChangesRpc",
    "ChunkedMessage",
    "CompactionAbortRpc",
    "CompactionBeginResult",
    "CompactionBeginResultSchema",
    "CompactionBeginRpc",
    "CompactionBusy",
    "CompactionCommitPayload",
    "CompactionCommitRpc",
    "CompactionFetchPayload",
    "CompactionFetchRpc",
    "CompactionInputHeader",
    "CompactionInputRpc",
    "CompactionNoOp",
    "CompactionNotWanted",
    "CompactionPartPayload",
    "CompactionPartRpc",
    "CompactionResult",
    "CompactionResultSchema",
    "CompactionScopePayload",
    "CompactionSnapshot",
    "CompactionStagePayload",
    "CompactionStarted",
    "CompactionStatus",
    "CompactionStatusRpc",
    "EventLogAuthentication",
    "EventLogCompactionRpcs",
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
    "decode_compaction_input_headers",
    "decode_compaction_segment",
    "encode_changes_encrypted",
    "encode_changes_unencrypted",
    "encode_compaction_input_headers",
    "encode_compaction_segment",
]
