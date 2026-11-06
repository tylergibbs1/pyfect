"""The JSON forms of the cluster's and the event log's classes: Effect's keys,
in Effect's order. Every expected text was printed by Effect 4.0.6 under Node
(``JSON.stringify`` of ``Schema.encodeUnknownSync(Schema.toCodecJson(schema))``),
so ``serialization="ndjson"`` writes what an Effect peer writes."""
# pyright: reportPrivateUsage=false

from datetime import UTC, datetime
from typing import Any

import pytest
from hypothesis import given, settings

from pyfect import schema as S
from pyfect._json_text import parse, stringify
from pyfect.ai.chat import ChatNotFoundError
from pyfect.cluster.cluster_cron import CronPayload
from pyfect.cluster.cluster_error import AlreadyProcessingMessage
from pyfect.cluster.entity_address import EntityAddress
from pyfect.cluster.entity_id import EntityId
from pyfect.cluster.entity_type import EntityType
from pyfect.cluster.shard_id import ShardId
from pyfect.cluster.singleton_address import SingletonAddress
from pyfect.cluster.snowflake import Snowflake
from pyfect.duration import Seconds
from pyfect.eventlog import event_log_message as M
from pyfect.eventlog.event_journal import Entry, EntryId, RemoteEntry, RemoteId, StoreId
from pyfect.eventlog.event_log_encryption import EncryptedBatch, EncryptedRemoteBatch
from pyfect.graphql.client_error import TransportError
from pyfect.persistence.circuit_breaker import CircuitOpen
from pyfect.persistence.rate_limiter import RateLimitExceeded
from pyfect.workflow.durable_deferred import TokenParsed

_BYTES = bytes([1, 2, 255])
_BYTES_FORM = '{"0":1,"1":2,"2":255}'
_ID = bytes([7] * 16)
_ID_FORM = '"BwcHBwcHBwcHBwcHBwcHBw=="'
_ADDRESS = EntityAddress(
    shard_id=ShardId(group="default", id=3),
    entity_type=EntityType("Counter"),
    entity_id=EntityId("c1"),
)
_ADDRESS_FORM = '{"shardId":{"group":"default","id":3},"entityType":"Counter","entityId":"c1"}'
_ENTRY = Entry(id=EntryId(_ID), event="e", primary_key="k", payload=_BYTES)
_ENTRY_FORM = f'{{"id":{_ID_FORM},"event":"e","primaryKey":"k","payload":"AQL/"}}'
_BATCH = EncryptedBatch(entry_ids=(EntryId(_ID),), iv=_BYTES, encrypted_batch=_BYTES)
_BATCH_BODY = f'"entryIds":[{_ID_FORM}],"iv":{_BYTES_FORM},"encryptedBatch":{_BYTES_FORM}'
_STORE = StoreId("s")

_FORMS: dict[str, tuple[Any, Any, str]] = {
    "entity_address": (EntityAddress, _ADDRESS, _ADDRESS_FORM),
    "singleton_address": (
        SingletonAddress,
        SingletonAddress(shard_id=ShardId(group="default", id=1), name="s"),
        '{"shardId":{"group":"default","id":1},"name":"s"}',
    ),
    "already_processing": (
        AlreadyProcessingMessage,
        AlreadyProcessingMessage(envelope_id=Snowflake(123), address=_ADDRESS),
        f'{{"_tag":"AlreadyProcessingMessage","envelopeId":"123","address":{_ADDRESS_FORM}}}',
    ),
    "cron": (
        CronPayload,
        CronPayload(date_time=datetime.fromtimestamp(1, UTC)),
        '{"dateTime":"1970-01-01T00:00:01.000Z"}',
    ),
    "cron_executor": (
        CronPayload,
        CronPayload(date_time=datetime.fromtimestamp(1, UTC), executor=True),
        '{"dateTime":"1970-01-01T00:00:01.000Z","executor":true}',
    ),
    "protocol_error": (
        M.EventLogProtocolError,
        M.EventLogProtocolError(request_tag="r", code="Forbidden", message="m"),
        '{"_tag":"EventLogProtocolError","requestTag":"r","code":"Forbidden","message":"m"}',
    ),
    "protocol_error_keys": (
        M.EventLogProtocolError,
        M.EventLogProtocolError(
            request_tag="r", code="Forbidden", message="m", public_key="p", store_id=_STORE
        ),
        '{"_tag":"EventLogProtocolError","requestTag":"r","publicKey":"p","storeId":"s",'
        '"code":"Forbidden","message":"m"}',
    ),
    "hello": (
        M.HelloResponse,
        M.HelloResponse(remote_id=RemoteId(_ID), challenge=_BYTES),
        f'{{"remoteId":{_ID_FORM},"challenge":{_BYTES_FORM}}}',
    ),
    "hello_sequence": (
        M.HelloResponse,
        M.HelloResponse(remote_id=RemoteId(_ID), challenge=_BYTES, first_sequence=4),
        f'{{"remoteId":{_ID_FORM},"challenge":{_BYTES_FORM},"firstSequence":4}}',
    ),
    "authenticate": (
        M.Authenticate,
        M.Authenticate(
            public_key="p", signing_public_key=_BYTES, signature=_BYTES, algorithm="Ed25519"
        ),
        f'{{"publicKey":"p","signingPublicKey":{_BYTES_FORM},"signature":{_BYTES_FORM},'
        '"algorithm":"Ed25519"}',
    ),
    "write_ack": (
        M.WriteAck,
        M.WriteAck(entry_id=EntryId(_ID), sequence=2),
        f'{{"entryId":{_ID_FORM},"sequence":2}}',
    ),
    "entry": (Entry, _ENTRY, _ENTRY_FORM),
    "remote_entry": (
        RemoteEntry,
        RemoteEntry(remote_sequence=1, entry=_ENTRY),
        f'{{"remoteSequence":1,"entry":{_ENTRY_FORM}}}',
    ),
    "encrypted_batch": (EncryptedBatch, _BATCH, f"{{{_BATCH_BODY}}}"),
    "encrypted_remote_batch": (
        EncryptedRemoteBatch,
        EncryptedRemoteBatch(
            sequence=1, entry_ids=(EntryId(_ID),), iv=_BYTES, encrypted_batch=_BYTES
        ),
        f'{{"sequence":1,{_BATCH_BODY}}}',
    ),
    "write_entries": (
        M.WriteEntries,
        M.WriteEntries(public_key="p", store_id=_STORE, batches=(_BATCH,)),
        f'{{"publicKey":"p","storeId":"s","batches":[{{{_BATCH_BODY}}}]}}',
    ),
    "write_entries_unencrypted": (
        M.WriteEntriesUnencrypted,
        M.WriteEntriesUnencrypted(public_key="p", store_id=_STORE, entries=(_ENTRY,)),
        f'{{"publicKey":"p","storeId":"s","entries":[{_ENTRY_FORM}]}}',
    ),
    "single": (
        M.SingleMessage,
        M.SingleMessage(data=_BYTES),
        f'{{"_tag":"Single","data":{_BYTES_FORM}}}',
    ),
    "chunked": (
        M.ChunkedMessage,
        M.ChunkedMessage(id=1, part=(0, 2), data=_BYTES),
        f'{{"_tag":"Chunked","id":1,"part":[0,2],"data":{_BYTES_FORM}}}',
    ),
    "changes_payload": (
        M.ChangesRpc.payload_schema,
        {"public_key": "p", "store_id": _STORE, "start_sequence": 0},
        '{"publicKey":"p","storeId":"s","startSequence":0}',
    ),
    "latest_sequence_payload": (
        M.LatestSequenceRpc.payload_schema,
        {"public_key": "p", "store_id": _STORE},
        '{"publicKey":"p","storeId":"s"}',
    ),
}


@pytest.mark.parametrize("name", _FORMS)
def test_writes_effects_json(name: str) -> None:
    schema, value, form = _FORMS[name]
    assert stringify(S.encode_unknown_sync(S.to_codec_json(schema))(value)) == form


@pytest.mark.parametrize("name", _FORMS)
def test_reads_effects_json(name: str) -> None:
    schema, value, form = _FORMS[name]
    assert S.decode_unknown_sync(S.to_codec_json(schema))(parse(form)) == value


_DECODE_ERRORS: dict[str, tuple[Any, object, str]] = {
    "address_type": (
        EntityAddress,
        {"shardId": {"group": "default", "id": 3}, "entityType": 1, "entityId": "c"},
        'Expected string\n  at ["entityType"]',
    ),
    "address_missing": (
        EntityAddress,
        {"entityType": "a", "entityId": "c"},
        'Missing key\n  at ["shardId"]',
    ),
    "entry": (
        Entry,
        {"id": "AA==", "event": "e", "primaryKey": 1, "payload": "AQ"},
        'Expected string\n  at ["primaryKey"]',
    ),
    "protocol": (
        M.EventLogProtocolError,
        {"_tag": "EventLogProtocolError", "requestTag": 1, "code": "Forbidden", "message": "m"},
        'Expected string\n  at ["requestTag"]',
    ),
    "ack": (M.WriteAck, {"entryId": 1, "sequence": -1}, 'Expected string\n  at ["entryId"]'),
    "write": (M.WriteEntries, {"publicKey": "p", "batches": []}, 'Missing key\n  at ["storeId"]'),
    "remote": (
        RemoteEntry,
        {"remoteSequence": "x", "entry": {}},
        'Expected number\n  at ["remoteSequence"]',
    ),
    "cron": (CronPayload, {"dateTime": 1}, 'Expected string\n  at ["dateTime"]'),
    "already": (
        AlreadyProcessingMessage,
        {"_tag": "AlreadyProcessingMessage", "envelopeId": 1, "address": {}},
        'Expected string\n  at ["envelopeId"]',
    ),
}


@pytest.mark.parametrize("name", _DECODE_ERRORS)
def test_a_decode_error_names_effects_key(name: str) -> None:
    schema, value, expected = _DECODE_ERRORS[name]
    with pytest.raises(S.SchemaError) as error:
        S.decode_unknown_sync(S.to_codec_json(schema))(value)
    assert str(error.value) == expected


def test_a_constructor_error_names_the_keyword() -> None:
    with pytest.raises(S.SchemaError) as error:
        Entry(id=EntryId(_ID), event="e", primary_key=1, payload=_BYTES)  # pyright: ignore[reportArgumentType]
    assert str(error.value) == 'Expected string\n  at ["primary_key"]'


_OTHER_FORMS: dict[str, tuple[Any, Any, str]] = {
    "token_parsed": (
        TokenParsed,
        TokenParsed(workflow_name="a", execution_id="b", deferred_name="c"),
        '{"workflowName":"a","executionId":"b","deferredName":"c"}',
    ),
    "rate_limit": (
        RateLimitExceeded,
        RateLimitExceeded(retry_after=Seconds(1.0), key="k", limit=1, remaining=0),
        '{"_tag":"RateLimitExceeded","retryAfter":1000,"key":"k","limit":1,"remaining":0}',
    ),
    "circuit_open": (
        CircuitOpen,
        CircuitOpen(key="k", retry_after=Seconds(1.0)),
        '{"_tag":"CircuitOpen","key":"k","retryAfter":1000}',
    ),
    "chat_not_found": (
        ChatNotFoundError,
        ChatNotFoundError(chat_id="x"),
        '{"_tag":"ChatNotFoundError","chatId":"x"}',
    ),
    "graphql_transport": (
        TransportError,
        TransportError(description="d", status=503, close_code=1006, retry_after=Seconds(1.0)),
        '{"_tag":"TransportError","description":"d","status":503,"retryAfter":1000,'
        '"closeCode":1006}',
    ),
}


@pytest.mark.parametrize("name", _OTHER_FORMS)
def test_other_classes_write_and_read_effects_json(name: str) -> None:
    schema, value, form = _OTHER_FORMS[name]
    codec = S.to_codec_json(schema)
    assert stringify(S.encode_unknown_sync(codec)(value)) == form
    assert S.decode_unknown_sync(codec)(parse(form)) == value


_CLASSES = sorted({schema for schema, _, _ in _FORMS.values() if isinstance(schema, type)}, key=str)


@pytest.mark.parametrize("cls", _CLASSES)
def test_every_keyed_class_round_trips_through_json_from_its_strategy(cls: Any) -> None:
    codec = S.to_codec_json(cls)

    @given(S.to_strategy(cls))
    @settings(max_examples=25, deadline=None)
    def round_trips(value: Any) -> None:
        assert S.decode_unknown_sync(codec)(S.encode_unknown_sync(codec)(value)) == value

    round_trips()
