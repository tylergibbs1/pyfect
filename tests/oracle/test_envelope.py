"""Ports of Effect's ``test/cluster/Envelope.test.ts`` for
``pyfect.cluster.envelope``. Each test's docstring is the Effect test title.
"""

from typing import TypedDict

import pytest

from pyfect import schema as S
from pyfect.cluster import entity_address, envelope, shard_id
from pyfect.cluster.entity_id import EntityId
from pyfect.cluster.entity_type import EntityType
from pyfect.cluster.envelope import Request
from pyfect.cluster.runners._rpc import ReplyEncodedSchema
from pyfect.cluster.snowflake import Snowflake
from pyfect.encoding import schema_binary
from pyfect.http.headers import EMPTY


def _request(payload: object) -> Request[object]:
    return Request(
        request_id=Snowflake(1),
        address=entity_address.make(
            shard_id=shard_id.make("default", 1),
            entity_type=EntityType("TestEntity"),
            entity_id=EntityId("1"),
        ),
        tag="Test",
        payload=payload,
        headers=EMPTY,
    )


def test_leaves_the_encoded_payload_untouched():
    """Envelope.OpaqueHole / leaves the already-encoded payload untouched under the JSON codec"""
    encoded = envelope.encode(_request({"id": 1}))
    assert encoded["_tag"] == "Request"
    assert encoded["payload"] == {"id": 1}
    assert encoded["requestId"] == "1"

    decoded = envelope.decode(encoded)
    assert isinstance(decoded, Request)
    assert decoded.payload == {"id": 1}
    assert decoded == _request({"id": 1})


def test_carries_a_non_json_payload_through_the_hole():
    """Envelope.OpaqueHole / carries a non-JSON payload through the hole"""
    data = bytes([1, 2, 3])
    encoded = envelope.encode(_request(data))
    assert encoded["_tag"] == "Request"
    assert encoded["payload"] is data


def test_compiles_the_hole_and_reply_encoded_as_a_bytes_leaf_under_schema_binary() -> None:
    """Envelope.OpaqueHole / compiles the hole and Reply.Encoded as a bytes leaf under
    SchemaBinary"""
    data = bytes((1, 2, 3))
    encoded_bytes = S.encode_sync(schema_binary.to_codec(S.Bytes))(data)
    hole = schema_binary.to_codec(envelope.OpaqueHole)
    reply = schema_binary.to_codec(ReplyEncodedSchema)
    assert S.encode_sync(hole)(data) == encoded_bytes
    assert S.encode_unknown_sync(reply)(data) == encoded_bytes
    assert S.decode_sync(hole)(encoded_bytes) == data
    assert S.decode_unknown_sync(reply)(encoded_bytes) == data


def test_reports_non_byte_opaque_hole_inputs_as_schema_failures() -> None:
    """Envelope.OpaqueHole / reports non-byte OpaqueHole inputs as schema failures"""
    encode = S.encode_unknown_sync(schema_binary.to_codec(envelope.OpaqueHole))
    with pytest.raises(S.SchemaError, match="Expected bytes"):
        encode({"id": 1})


_NOTIFY_FRAMES = {
    "request": (
        "6c2094bcf5e129a8f594847d600a06aa86cb9895c59a1630d0dbb8f2340a54657374456e74697479"
        "b8e7a6da400131b0a6a3ab591381ae8dce1b02e0e8a3ee2f0764656661756c74a8faeec319030102"
        "03f8e9bd9d1b069693d89fee479899e5fd4a0454657374c89ebb996b00"
    ),
    "ack": (
        "6b2093bcf5e129a8f594847d5f0a706e27df9895c59a1630d0dbb8f2340a54657374456e74697479"
        "b8e7a6da400131b0a6a3ab591381ae8dce1b02e0e8a3ee2f0764656661756c74f8e9bd9d1b069693"
        "d89fee4780ae8dce1b069693d89fee47d0fc9ab865069693d89fee47"
    ),
    "interrupt": (
        "5f2093bcf5e129a8f594847d530a4a3836da9895c59a1630d0dbb8f2340a54657374456e74697479"
        "b8e7a6da400131b0a6a3ab591381ae8dce1b02e0e8a3ee2f0764656661756c74f8e9bd9d1b069693"
        "d89fee4780ae8dce1b069693d89fee47"
    ),
}


class _Notify(TypedDict):
    envelope: envelope.Partial
    persisted: bool


def test_runner_envelopes_are_written_as_effect_writes_them() -> None:
    """(not an Effect title) a Notify payload has Effect's bytes under SchemaBinary"""
    address = entity_address.make(
        shard_id=shard_id.make("default", 1),
        entity_type=EntityType("TestEntity"),
        entity_id=EntityId("1"),
    )
    id = Snowflake(1234567890123)
    messages: dict[str, tuple[envelope.Partial, bool]] = {
        "request": (
            Request(request_id=id, address=address, tag="Test", payload=bytes((1, 2, 3))),
            True,
        ),
        "ack": (envelope.AckChunk(id=id, address=address, request_id=id, reply_id=id), False),
        "interrupt": (envelope.Interrupt(id=id, address=address, request_id=id), False),
    }
    codec = schema_binary.to_codec(S.Struct(_Notify, envelope=envelope.PartialSchema))
    for name, (message, persisted) in messages.items():
        value: _Notify = {"envelope": message, "persisted": persisted}
        assert S.encode_sync(codec)(value).hex() == _NOTIFY_FRAMES[name]
        assert S.decode_sync(codec)(bytes.fromhex(_NOTIFY_FRAMES[name])) == value
