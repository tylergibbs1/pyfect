"""Ports of Effect's ``test/cluster/Envelope.test.ts`` for
``pyfect.cluster.envelope``. Each test's docstring is the Effect test title.

Omitted: "compiles the hole and Reply.Encoded as a bytes leaf under
SchemaBinary" and "reports non-byte OpaqueHole inputs as schema failures":
``SchemaBinary`` (Effect's binary codec compiler) is not ported.
"""

from pyfect.cluster import entity_address, envelope, shard_id
from pyfect.cluster.entity_id import EntityId
from pyfect.cluster.entity_type import EntityType
from pyfect.cluster.envelope import Request
from pyfect.cluster.snowflake import Snowflake
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
