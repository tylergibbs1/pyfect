"""Ports of Effect's rpc/RpcSerialization.test.ts. Each test's docstring is
the Effect test title, prefixed by its describe block.

Omitted: the "SchemaBinary" block (pyfect has no SchemaBinary
serialization yet); the "jsonRpc inherited properties" cases that pollute
``Object.prototype`` (Python dicts have no prototype to inherit keys
from; the clean-prototype case is kept); the "codecFor" block's custom
hole codec cases (they need SchemaBinary's codec holes, except the text
one, kept).
"""

import json
from datetime import UTC, datetime
from typing import Any

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.rpc import serialization as rs

_FAILURE = {"_tag": "Fail", "error": {"code": -32021, "message": "Missing capability"}}
_DEFECT = {"_tag": "Die", "defect": {"message": "boom"}}
_INTERRUPT = {"_tag": "Interrupt", "fiberId": 42}


def _exit_success(request_id: object, value: object) -> dict[str, Any]:
    return {"_tag": "Exit", "requestId": request_id, "exit": {"_tag": "Success", "value": value}}


def _request(id: object, tag: object, **rest: object) -> dict[str, Any]:
    return {"_tag": "Request", "id": id, "tag": tag, "payload": None, "headers": [], **rest}


def _assert_max_buffer(parser: rs.Parser, data: str, size: int) -> None:
    with pytest.raises(rs.MaxBufferSizeExceeded) as raised:
        parser.decode(data)
    assert raised.value.max_buffer_size == size


@pytest.mark.parametrize(
    "serialization", [rs.json_rpc(), rs.nd_json_rpc()], ids=["jsonRpc", "ndJsonRpc"]
)
@pytest.mark.parametrize(
    "cause",
    [[_FAILURE], [_DEFECT], [_INTERRUPT], [_FAILURE, _DEFECT, _INTERRUPT], []],
    ids=["typed failure", "defect", "interruption", "mixed causes", "empty cause"],
)
def test_cause_roundtrips(serialization: rs.RpcSerializationService, cause: list[object]) -> None:
    """RpcSerialization / {name} cause roundtrips / preserves %s"""
    response = {"_tag": "Exit", "requestId": 1, "exit": {"_tag": "Failure", "cause": cause}}
    encoded = serialization.make_unsafe().encode(response)
    assert encoded is not None
    assert serialization.make_unsafe().decode(encoded) == [response]


@pytest.mark.parametrize(
    "serialization", [rs.json_rpc(), rs.nd_json_rpc()], ids=["jsonRpc", "ndJsonRpc"]
)
def test_preserves_a_protocol_defect(serialization: rs.RpcSerializationService) -> None:
    """RpcSerialization / {name} cause roundtrips / preserves a protocol defect"""
    response = {"_tag": "Defect", "defect": {"message": "protocol failed"}}
    encoded = serialization.make_unsafe().encode(response)
    assert encoded is not None
    assert serialization.make_unsafe().decode(encoded) == [response]


@pytest.mark.parametrize(
    ("tag", "request_id"), [("Ack", 0), ("Ack", ""), ("Interrupt", 0), ("Interrupt", "")]
)
def test_json_rpc_preserves_request_id(tag: str, request_id: object) -> None:
    """RpcSerialization / jsonRpc preserves %s requestId %j"""
    parser = rs.json_rpc().make_unsafe()
    encoded = json.dumps(
        {"jsonrpc": "2.0", "method": f"@effect/rpc/{tag}", "params": {"requestId": request_id}}
    )
    assert parser.decode(encoded) == [{"_tag": tag, "requestId": request_id}]


def test_json_rpc_decodes_a_success_response() -> None:
    """RpcSerialization / jsonRpc inherited properties / decodes a success response with a clean
    prototype"""
    decoded = rs.json_rpc().make_unsafe().decode('{"jsonrpc":"2.0","id":1,"result":"ok"}')
    assert decoded == [_exit_success(1, "ok")]


def test_json_decode_keeps_array_payloads_flat() -> None:
    """RpcSerialization / json decode keeps array payloads flat"""
    assert rs.json.make_unsafe().decode("[1,2,3]") == [1, 2, 3]


def test_json_decode_wraps_non_array_payloads() -> None:
    """RpcSerialization / json decode wraps non-array payloads"""
    assert rs.json.make_unsafe().decode('{"a":1}') == [{"a": 1}]


def test_ndjson_fails_when_an_unterminated_frame_exceeds_max_buffer_size() -> None:
    """RpcSerialization / ndjson fails when an unterminated frame exceeds maxBufferSize"""
    parser = rs.make_ndjson(max_buffer_size=4).make_unsafe()
    assert parser.decode("12") == []
    assert parser.decode("34") == []
    _assert_max_buffer(parser, "5", 4)


def test_ndjson_allows_an_unbounded_incomplete_frame() -> None:
    """RpcSerialization / ndjson allows an unbounded incomplete frame"""
    parser = rs.make_ndjson(max_buffer_size="unbounded").make_unsafe()
    assert parser.decode("x" * 1024) == []


def test_ndjson_decodes_a_multibyte_character_split_across_byte_chunks() -> None:
    """RpcSerialization / ndjson decodes a multibyte character split across byte chunks"""
    parser = rs.ndjson.make_unsafe()
    message = {"value": "€"}
    encoded = parser.encode(message)
    assert isinstance(encoded, str)
    data = encoded.encode()
    split = data.index(0xE2) + 1
    assert parser.decode(data[:split]) == []
    assert parser.decode(data[split:]) == [message]


def test_ndjson_uses_the_ndjson_content_type() -> None:
    """RpcSerialization / ndjson uses the application/x-ndjson content type"""
    assert rs.make_ndjson().content_type == "application/x-ndjson"
    assert rs.ndjson.content_type == "application/x-ndjson"


def test_ndjson_fails_with_ndjson_decode_error_for_a_malformed_line() -> None:
    """RpcSerialization / ndjson fails with NdjsonDecodeError and a SyntaxError cause for a
    malformed non-empty line"""
    parser = rs.ndjson.make_unsafe()
    with pytest.raises(rs.NdjsonDecodeError) as raised:
        parser.decode('{"id":1}\nnot json\n{"id":2}\n')
    assert isinstance(raised.value.cause, json.JSONDecodeError)


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_ndjson_skips_blank_lines(newline: str) -> None:
    """RpcSerialization / ndjson skips blank lines with %j line endings"""
    parser = rs.ndjson.make_unsafe()
    data = f'{newline}{{"id":1}}{newline}{newline}{{"id":2}}{newline}'
    assert parser.decode(data) == [{"id": 1}, {"id": 2}]


@testing.effect
def test_layer_ndjson_with_forwards_max_buffer_size():
    """RpcSerialization / layerNdjsonWith forwards maxBufferSize to its decoder"""
    service = yield from rs.RpcSerialization().pipe(
        fx.provide(rs.layer_ndjson_with(max_buffer_size=4))
    )
    parser = service.make_unsafe()
    assert parser.decode("12") == []
    assert parser.decode("34") == []
    _assert_max_buffer(parser, "5", 4)


def test_nd_json_rpc_forwards_max_buffer_size() -> None:
    """RpcSerialization / ndJsonRpc forwards maxBufferSize to its ndjson framing parser"""
    parser = rs.nd_json_rpc(max_buffer_size=4).make_unsafe()
    assert parser.decode("12") == []
    assert parser.decode("34") == []
    with pytest.raises(rs.MaxBufferSizeExceeded):
        parser.decode("5")


def test_json_rpc_encodes_a_non_batched_single_response_array_as_an_object() -> None:
    """RpcSerialization / jsonRpc encodes a non-batched single response array as an object"""
    parser = rs.json_rpc().make_unsafe()
    assert len(parser.decode('{"jsonrpc":"2.0","id":1,"method":"users.get"}')) == 1
    encoded = parser.encode([_exit_success("1", {"id": 1})])
    assert isinstance(encoded, str)
    assert json.loads(encoded) == {"jsonrpc": "2.0", "id": "1", "result": {"id": 1}}


def test_json_rpc_encodes_batched_responses_as_an_array() -> None:
    """RpcSerialization / jsonRpc encodes batched responses as an array"""
    parser = rs.json_rpc().make_unsafe()
    decoded = parser.decode(
        '[{"jsonrpc":"2.0","id":"1","method":"users.get"},{"jsonrpc":"2.0","id":2,"method":"users.list"}]'
    )
    assert len(decoded) == 2
    encoded = parser.encode([_exit_success("1", "one"), _exit_success(2, "two")])
    assert isinstance(encoded, str)
    assert json.loads(encoded) == [
        {"jsonrpc": "2.0", "id": "1", "result": "one"},
        {"jsonrpc": "2.0", "id": 2, "result": "two"},
    ]


def test_json_rpc_preserves_id_0() -> None:
    """RpcSerialization / jsonRpc preserves id 0 across decode and encode"""
    parser = rs.json_rpc().make_unsafe()
    assert parser.decode('{"jsonrpc":"2.0","id":0,"method":"users.get"}') == [
        _request(0, "users.get")
    ]
    encoded = parser.encode(_request(0, "users.get"))
    assert encoded == '{"jsonrpc":"2.0","method":"users.get","params":null,"id":0}'


def test_json_rpc_maps_null_id_to_internal_notification_sentinel() -> None:
    """RpcSerialization / jsonRpc maps null id to internal notification sentinel"""
    parser = rs.json_rpc().make_unsafe()
    assert parser.decode('{"jsonrpc":"2.0","id":null,"method":"users.get"}') == [
        _request("", "users.get")
    ]


def test_json_rpc_skips_non_objects_in_a_batch() -> None:
    """RpcSerialization / jsonRpc skips non-objects in a batch without losing requests"""
    parser = rs.json_rpc().make_unsafe()
    assert parser.decode("null") == []
    assert parser.decode("7") == []
    decoded = parser.decode(
        '[null,{"jsonrpc":"2.0","method":1},{"jsonrpc":"2.0","id":2,"method":"users.get"}]'
    )
    assert decoded == [_request("", 1, isNotification=True), _request(2, "users.get")]


def test_nd_json_rpc_keeps_requests_sharing_a_chunk_with_a_non_message() -> None:
    """RpcSerialization / ndJsonRpc keeps requests that share a chunk with a value that is not a
    message"""
    parser = rs.nd_json_rpc().make_unsafe()
    decoded = parser.decode('null\n{"jsonrpc":"2.0","id":2,"method":"users.get"}\n')
    assert decoded == [_request(2, "users.get")]


def test_json_rpc_preserves_empty_string_id() -> None:
    """RpcSerialization / jsonRpc preserves empty string id across decode and encode"""
    parser = rs.json_rpc().make_unsafe()
    assert parser.decode('{"jsonrpc":"2.0","id":"","method":"users.get"}') == [
        _request("", "users.get")
    ]
    encoded = parser.encode(_request("", "users.get"))
    assert encoded == '{"jsonrpc":"2.0","method":"users.get","params":null,"id":""}'


def test_json_rpc_decodes_standard_error_objects_as_typed_failures() -> None:
    """RpcSerialization / jsonRpc decodes standard error objects as typed failures"""
    parser = rs.json_rpc().make_unsafe()
    error: dict[str, object] = {
        "code": -32021,
        "message": "Missing capability",
        "data": {"requiredCapabilities": {}},
    }
    decoded = parser.decode(json.dumps({"jsonrpc": "2.0", "id": 1, "error": error}))
    assert decoded == [
        {
            "_tag": "Exit",
            "requestId": 1,
            "exit": {"_tag": "Failure", "cause": [{"_tag": "Fail", "error": error}]},
        }
    ]


def test_json_rpc_encodes_a_notification_without_an_id() -> None:
    """RpcSerialization / jsonRpc encodes a notification without an id"""
    parser = rs.json_rpc().make_unsafe()
    decoded = parser.decode('{"jsonrpc":"2.0","method":"notifications/message"}')
    assert decoded == [_request("", "notifications/message", isNotification=True)]
    encoded = parser.encode(
        {
            "_tag": "Request",
            "id": "",
            "tag": "notifications/message",
            "payload": {"level": "info"},
            "headers": [["x-test", "value"]],
            "traceId": "trace",
            "spanId": "span",
            "sampled": True,
            "isNotification": True,
        }
    )
    assert encoded == (
        '{"jsonrpc":"2.0","method":"notifications/message","params":{"level":"info"},'
        '"headers":[["x-test","value"]],"traceId":"trace","spanId":"span","sampled":true}'
    )


def test_text_serializations_json_lower_the_hole() -> None:
    """RpcSerialization / codecFor / text serializations JSON-lower the hole"""
    encode = S.encode_sync(rs.json.codec_for(S.DateTimeUtc))
    assert encode(datetime(1970, 1, 1, tzinfo=UTC)) == "1970-01-01T00:00:00.000Z"
    assert rs.ndjson.codec_for is rs.json.codec_for
    assert rs.json_rpc().codec_for is rs.json.codec_for
