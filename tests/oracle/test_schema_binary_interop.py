"""Frames Effect wrote under Node (``schema_binary_wire.ts``) for the schemas
that mix the binary layer with the rest: what this repo's types and Python's
values make different from a JavaScript object. Not Effect test titles: found
by comparing bytes against Effect."""
# pyright: reportPrivateUsage=false, reportUnknownMemberType=false

from __future__ import annotations

from datetime import UTC, datetime
from hashlib import sha256
from typing import Any, cast

import pytest

from pyfect import exit as Exit
from pyfect import redacted
from pyfect import schema as S
from pyfect.cluster import envelope, reply
from pyfect.cluster.cluster_cron import CronPayload
from pyfect.cluster.cluster_error import (
    AlreadyProcessingMessage,
    EntityNotAssignedToRunner,
    MailboxFull,
)
from pyfect.cluster.cluster_workflow_engine._entities import (
    PAYLOAD_PARENT_KEY,
    ResumePayload,
    _ParentSchema,
)
from pyfect.cluster.entity_address import EntityAddress
from pyfect.cluster.entity_id import EntityId
from pyfect.cluster.entity_type import EntityType
from pyfect.cluster.shard_id import ShardId
from pyfect.cluster.snowflake import Snowflake
from pyfect.encoding import schema_binary as B
from pyfect.eventlog import event_log_message as M
from pyfect.eventlog.event_journal import EntryId, RemoteId, StoreId
from pyfect.eventlog.event_log_encryption import EncryptedBatch, EncryptedRemoteBatch
from pyfect.http import headers

from ._schema_binary import Opt, struct
from ._schema_binary_frames import (
    CLUSTER,
    DICTIONARY_LIMITS,
    EVENT_LOG,
    OPTIONAL_DICTIONARY,
    PARITY,
)


def _recursive(value: Any) -> Any:
    holder: list[Any] = []
    node = struct(v=value, children=S.Array(S.suspend(lambda: holder[0])))
    holder.append(node)
    return node


_record = _recursive(S.Number)
_second = datetime.fromtimestamp(1, UTC)

_CASES: dict[str, tuple[Any, Any]] = {
    "recursive_redacted": (
        _recursive(S.Redacted(S.String)),
        {"v": redacted.make("x"), "children": ()},
    ),
    "optional_recursive": (
        struct(parent=Opt(_record), n=S.Number),
        {"parent": {"v": 1, "children": ()}, "n": 2},
    ),
    "redacted_recursive": (S.Redacted(_record), redacted.make({"v": 1, "children": ()})),
    "zoned_offset_zero_in_union": (
        S.Union(S.DateTimeZoned, S.Number),
        _second.astimezone(UTC),
    ),
    "wide_number_in_union": (S.NullOr(S.Number), 2**53),
    "redacted_same_member": (S.Union(S.String, S.Redacted(S.String)), "x"),
    "optional_tuple_element": (S.Tuple(S.String, S.OptionalKey(S.String)), ("a", "b")),
    "rank_zoned": (S.Union(S.DateTimeZoned, S.DateTimeUtc), _second),
    "rank_bigint": (S.Union(S.BigInt, S.Number), 1),
    "rank_unknown": (S.Union(S.Unknown, S.String), "x"),
}


@pytest.mark.parametrize("name", _CASES)
@pytest.mark.parametrize("mode", ["default", "fingerprint"])
def test_writes_and_reads_effects_frame(name: str, mode: str) -> None:
    schema, value = _CASES[name]
    fingerprint = mode == "fingerprint"
    frame = bytes.fromhex(PARITY[name][mode])
    codec = B.to_codec(schema, fingerprint=fingerprint)
    assert S.encode_unknown_sync(codec)(value) == frame
    assert S.encode_unknown_sync(codec)(S.decode_unknown_sync(codec)(frame)) == frame


def test_a_wide_number_in_a_union_stays_a_bigint_members_when_there_is_one() -> None:
    codec = B.to_codec(S.Union(S.Number, S.BigInt))
    assert S.decode_unknown_sync(codec)(S.encode_unknown_sync(codec)(2**60)) == 2**60


def test_optional_keys_of_one_schema_share_a_dictionary_table() -> None:
    schema = struct(a=Opt(S.String), b=Opt(S.String), c=S.String)
    values = [
        {"a": "shared", "c": "other"},
        {"b": "shared", "c": "shared"},
        {"a": "shared", "c": "shared"},
        {"b": "shared", "c": "shared"},
    ]
    writer = B.encoder(schema, dictionary=True)
    frames = [bytes.fromhex(frame) for frame in OPTIONAL_DICTIONARY]
    assert [writer.encode(value) for value in values] == frames
    reader = B.parser(schema, dictionary=True)
    assert [reader.feed_sync(frame)[0] for frame in frames] == values


def test_a_dictionary_stream_stops_at_effects_limits() -> None:
    """Past 64 unrepeated strings a slot gives up; past 512 entries it stops adding."""
    digest = sha256()
    referencing = B.encoder(S.String, dictionary=True)
    for i in (*range(63), 0, *range(63, 523), 511, 512, 0):
        digest.update(referencing.encode(f"value-{i}"))
    give_up = B.encoder(S.String, dictionary=True)
    for i in (*range(64), 0):
        digest.update(give_up.encode(f"value-{i}"))
    assert digest.hexdigest() == DICTIONARY_LIMITS


# --- event log ---------------------------------------------------------------------------


_ID = cast("EntryId", bytes.fromhex("018f4a1e7b0070008000000000000001"))
_REMOTE = cast("RemoteId", bytes.fromhex("0102030405060708090a0b0c0d0e0f10"))
_STORE = StoreId("s")
_BATCH: dict[str, Any] = {
    "entry_ids": (_ID,),
    "iv": bytes((1, 2)),
    "encrypted_batch": bytes((3, 4)),
}

_EVENT_LOG: dict[str, tuple[Any, Any]] = {
    "hello": (
        M.HelloResponse,
        M.HelloResponse(remote_id=_REMOTE, challenge=bytes((5,)), first_sequence=3),
    ),
    "hello_no_sequence": (
        M.HelloResponse,
        M.HelloResponse(remote_id=_REMOTE, challenge=bytes((5,))),
    ),
    "authenticate": (
        M.Authenticate,
        M.Authenticate(
            public_key="pk",
            signing_public_key=bytes((6,)),
            signature=bytes((7,)),
            algorithm="Ed25519",
        ),
    ),
    "write_ack": (M.WriteAck, M.WriteAck(entry_id=_ID, sequence=9)),
    "changes_payload": (
        M.ChangesRpc.payload_schema,
        {"public_key": "pk", "store_id": _STORE, "start_sequence": 2},
    ),
    "protocol_error": (
        M.EventLogProtocolError,
        M.EventLogProtocolError(request_tag="T", code="NotFound", message="m", public_key="pk"),
    ),
    "protocol_error_bare": (
        M.EventLogProtocolError,
        M.EventLogProtocolError(request_tag="T", code="NotFound", message="m"),
    ),
    "write_encrypted": (
        M.WriteEntries,
        M.WriteEntries(public_key="pk", store_id=_STORE, batches=(EncryptedBatch(**_BATCH),)),
    ),
    "changes_encrypted": (
        S.NonEmptyArray(EncryptedRemoteBatch),
        (EncryptedRemoteBatch(sequence=4, **_BATCH),),
    ),
}


@pytest.mark.parametrize("name", _EVENT_LOG)
def test_event_log_message_reads_effects_frame(name: str) -> None:
    schema, value = _EVENT_LOG[name]
    codec = B.to_codec(schema)
    frame = bytes.fromhex(EVENT_LOG[name])
    assert S.decode_unknown_sync(codec)(frame) == value
    # Effect leaves an undefined optional off; a value compares by what it holds.
    assert S.decode_unknown_sync(codec)(S.encode_unknown_sync(codec)(value)) == value


@pytest.mark.parametrize(
    "name",
    ["authenticate", "write_ack", "changes_payload", "write_encrypted", "changes_encrypted"],
)
def test_event_log_message_writes_effects_frame(name: str) -> None:
    schema, value = _EVENT_LOG[name]
    assert S.encode_unknown_sync(B.to_codec(schema))(value) == bytes.fromhex(EVENT_LOG[name])


# --- cluster -----------------------------------------------------------------------------


_ADDRESS = EntityAddress(
    shard_id=ShardId(group="default", id=7),
    entity_type=EntityType("Thing"),
    entity_id=EntityId("e1"),
)
_ReplyExit = S.Exit(S.Number, S.String, S.Defect())
_Reply = S.Union(reply.with_exit_schema(_ReplyExit), reply.chunk_schema(S.Number))


def test_a_traced_request_envelope_has_effects_bytes() -> None:
    value = envelope.Request[object](
        request_id=Snowflake(123),
        address=_ADDRESS,
        tag="Inc",
        payload=bytes((1,)),
        headers=headers.from_input({"x-a": "b"}),
        trace_id="t",
        span_id="s",
        sampled=True,
    )
    codec = B.to_codec_direct(envelope.PartialSchema)
    frame = bytes.fromhex(CLUSTER["request_traced"])
    assert S.encode_unknown_sync(codec)(value) == frame
    assert S.decode_unknown_sync(codec)(frame) == value


@pytest.mark.parametrize(
    ("name", "value"),
    [
        (
            "reply_exit",
            reply.WithExit(request_id=Snowflake(5), id=Snowflake(6), exit=Exit.succeed(1)),
        ),
        (
            "reply_chunk",
            reply.Chunk(request_id=Snowflake(5), id=Snowflake(6), sequence=2, values=(1, 2)),
        ),
    ],
)
def test_a_reply_has_effects_bytes(name: str, value: Any) -> None:
    codec = B.to_codec_direct(_Reply)
    frame = bytes.fromhex(CLUSTER[name])
    assert S.encode_unknown_sync(codec)(value) == frame
    assert S.decode_unknown_sync(codec)(frame) == value


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("mailbox_full", MailboxFull(address=_ADDRESS)),
        (
            "already_processing",
            AlreadyProcessingMessage(envelope_id=Snowflake(5), address=_ADDRESS),
        ),
    ],
)
def test_a_runner_error_has_effects_bytes(name: str, value: Any) -> None:
    codec = B.to_codec_direct(
        S.Union(EntityNotAssignedToRunner, MailboxFull, AlreadyProcessingMessage)
    )
    frame = bytes.fromhex(CLUSTER[name])
    assert S.encode_unknown_sync(codec)(value) == frame
    assert S.decode_unknown_sync(codec)(frame) == value


def test_cron_payload_has_effects_bytes() -> None:
    value = CronPayload(date_time=datetime.fromtimestamp(1, UTC), executor=True)
    codec = B.to_codec_direct(CronPayload)
    frame = bytes.fromhex(CLUSTER["cron"])
    assert S.encode_unknown_sync(codec)(value) == frame
    assert S.decode_unknown_sync(codec)(frame) == value


def test_workflow_resume_payload_has_effects_bytes() -> None:
    codec = B.to_codec_direct(ResumePayload)
    frame = bytes.fromhex(CLUSTER["resume"])
    assert S.encode_unknown_sync(codec)(ResumePayload(childExecutionId="c")) == frame


def test_workflow_parent_key_has_effects_bytes() -> None:
    codec = B.to_codec_direct(struct(n=S.Number, **{PAYLOAD_PARENT_KEY: Opt(_ParentSchema)}))
    value = {
        "n": 1,
        PAYLOAD_PARENT_KEY: {"workflowName": "w", "executionId": "e", "detached": True},
    }
    assert S.encode_unknown_sync(codec)(value) == bytes.fromhex(CLUSTER["workflow_run"])
