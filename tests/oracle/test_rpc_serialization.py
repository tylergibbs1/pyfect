# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownMemberType=false
"""Ports of Effect's rpc/RpcSerialization.test.ts. Each test's docstring is
the Effect test title, prefixed by its describe block.

Omitted: the "jsonRpc inherited properties" cases that pollute
``Object.prototype`` (Python dicts have no prototype to inherit keys
from; the clean-prototype case is kept).
"""

import json
from datetime import UTC, datetime
from typing import Any, Literal, NotRequired, TypedDict

import pytest

import pyfect as fx
from pyfect import effect as E
from pyfect import exit as Exit
from pyfect import layer as L
from pyfect import schema as S
from pyfect import stream as Stream
from pyfect import testing
from pyfect.encoding import schema_binary
from pyfect.http import router, uvicorn_server
from pyfect.rpc import RpcGroup, make
from pyfect.rpc import client as rpc_client
from pyfect.rpc import serialization as rs
from pyfect.rpc import server as rpc_server

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


def test_schema_binary_writes_no_frame_for_no_messages() -> None:
    """(not an Effect title) Effect's parser encodes an empty batch to undefined."""
    assert rs.make_schema_binary().make_unsafe().encode([]) is None


def test_text_serializations_json_lower_the_hole() -> None:
    """RpcSerialization / codecFor / text serializations JSON-lower the hole"""
    encode = S.encode_sync(rs.json.codec_for(S.DateTimeUtc))
    assert encode(datetime(1970, 1, 1, tzinfo=UTC)) == "1970-01-01T00:00:00.000Z"
    assert rs.ndjson.codec_for is rs.json.codec_for
    assert rs.json_rpc().codec_for is rs.json.codec_for


# --- SchemaBinary ---------------------------------------------------------------------


class _Empty(TypedDict):
    pass


class _Echo(TypedDict):
    value: str


class _Counts(TypedDict):
    to: float


class EchoError(S.TaggedError, tag="EchoError"):
    at: datetime = S.field(S.DateTimeUtc)


_FAILED_AT = datetime(1970, 1, 1, tzinfo=UTC)


class _Rpcs(RpcGroup):
    echo = make("Echo", payload=S.Struct(_Echo), success=S.String)
    counts = make("Counts", payload=S.Struct(_Counts), success=S.Number, stream=True)
    fail = make("Fail", payload=S.Struct(_Empty), success=S.Null, error=EchoError)
    boom = make("Boom", payload=S.Struct(_Empty), success=S.Null)


def _binary_client(body: Any) -> Any:
    return _run_client(body, rs.layer_schema_binary())


def _run_client(body: Any, serialization: Any) -> Any:
    handlers = _Rpcs.to_layer(
        _Rpcs.handlers()
        .handle(_Rpcs.echo)(lambda request: E.succeed(f"{request.payload['value']}!"))
        .handle(_Rpcs.counts)(lambda request: Stream.range(1, int(request.payload["to"]) + 1))
        .handle(_Rpcs.fail)(lambda _: E.fail(EchoError(at=_FAILED_AT)))
        .handle(_Rpcs.boom)(lambda _: E.die(ValueError("boom")))
    )
    server: Any = router.serve(
        rpc_server.layer(_Rpcs)
        .pipe(L.provide(handlers))
        .pipe(L.provide_merge(rpc_server.layer_protocol_http("/rpc")))
        .pipe(L.provide(serialization)),
        disable_logger=True,
        disable_listen_log=True,
    )
    client: Any = rpc_client.layer_protocol_http(
        "", transform_client=lambda c: c.map_request(lambda r: r.append_url("/rpc"))
    )
    protocol: Any = (
        client.pipe(L.provide_merge(server))
        .pipe(L.provide(uvicorn_server.layer_test()))
        .pipe(L.provide(serialization))
    )
    program: Any = fx.scoped(E.gen(body)).pipe(fx.provide(protocol))
    return fx.run_sync(program.timeout(10).or_die())


def test_schema_binary_roundtrips_requests_and_streamed_responses_over_http() -> None:
    """RpcSerialization / SchemaBinary / roundtrips requests and streamed responses over HTTP"""

    def body():
        client = yield from rpc_client.make(_Rpcs)
        assert (yield from client.echo({"value": "hi"})) == "hi!"
        assert (yield from client.counts({"to": 3}).run_collect()) == [1, 2, 3]
        error = yield from client.fail({}).flip()
        assert isinstance(error, EchoError)
        assert error.at == _FAILED_AT
        exit_ = yield from client.boom({}).exit()
        assert Exit.is_failure(exit_)
        assert "boom" in str(exit_.cause)

    _binary_client(body)


def _uvarint(value: int) -> bytes:
    out = bytearray()
    while value >= 0x80:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return bytes(out)


class _Added(TypedDict):
    _tag: Literal["Request"]
    id: float | str
    tag: str
    payload: bytes
    headers: tuple[tuple[str, str], ...]
    added: NotRequired[str]


def test_schema_binary_fingerprints_envelopes() -> None:
    """RpcSerialization / SchemaBinary / fingerprints envelopes"""
    parser = rs.make_schema_binary().make_unsafe()
    incompatible = S.Struct(
        _Added,
        _tag=S.Literal("Request"),
        id=S.Union(S.String, S.Number),
        tag=S.String,
        payload=S.Bytes,
        headers=S.Array(S.Tuple(S.String, S.String)),
        added=S.String,
    )
    frame = S.encode_unknown_sync(schema_binary.to_codec(incompatible, fingerprint=True))(
        {"_tag": "Request", "id": 1, "tag": "Echo", "payload": bytes((1,)), "headers": ()}
    )
    with pytest.raises(S.SchemaError, match="matching layout fingerprint"):
        parser.decode(frame)


class _Writer(TypedDict):
    value: str
    added: NotRequired[str]


def test_schema_binary_does_not_fingerprint_payloads_by_default() -> None:
    """RpcSerialization / SchemaBinary / does not fingerprint payloads by default"""
    service = rs.make_schema_binary()
    writer = S.Struct(_Writer, value=S.String, added=S.String)
    reader = S.Struct(_Echo, value=S.String)
    encoded: Any = S.encode_unknown_sync(service.codec_for(writer))({"value": "ok", "added": "new"})
    assert isinstance(encoded, bytes)
    assert S.decode_unknown_sync(service.codec_for(reader))(encoded) == {"value": "ok"}


class _Numeric(TypedDict):
    value: float


def test_layer_schema_binary_fingerprints_payloads_when_enabled() -> None:
    """RpcSerialization / SchemaBinary / layerSchemaBinary fingerprints payloads when enabled"""
    service = rs.make_schema_binary(fingerprint_payloads=True)
    writer = S.Struct(_Echo, value=S.String)
    reader = S.Struct(_Numeric, value=S.Number)
    encoded: Any = S.encode_unknown_sync(service.codec_for(writer))({"value": "ok"})
    assert S.decode_unknown_sync(service.codec_for(writer))(encoded) == {"value": "ok"}
    with pytest.raises(S.SchemaError, match="matching layout fingerprint"):
        S.decode_unknown_sync(service.codec_for(reader))(encoded)


def test_schema_binary_uses_fingerprinted_envelope_framing_and_the_binary_content_type() -> None:
    """RpcSerialization / SchemaBinary / uses fingerprinted envelope framing and the binary
    content type"""
    service = rs.make_schema_binary()
    parser = service.make_unsafe()
    request = {
        "_tag": "Request",
        "id": 1,
        "tag": "Echo",
        "payload": bytes((1, 2, 3)),
        "headers": (),
    }
    frame = parser.encode(request)
    assert service.content_type == "application/vnd.effect.rpc+schema-binary"
    assert service.includes_framing is True
    assert isinstance(frame, bytes)
    assert parser.decode(frame) == [request]


def test_schema_binary_keeps_varied_frames_decodable_across_parser_replacement() -> None:
    """RpcSerialization / SchemaBinary / keeps varied frames decodable across parser replacement"""
    service = rs.make_schema_binary()
    encoder = service.make_unsafe()
    for index in range(200):
        request: dict[str, Any] = {
            "_tag": "Request",
            "id": index if index % 2 == 0 else f"request-{index}",
            "tag": f"Echo{index % 7}",
            "payload": bytes((index + offset) & 0xFF for offset in range(index % 17)),
            "headers": tuple((f"x-{offset}", f"{index}") for offset in range(index % 4)),
        }
        if index % 3 == 0:
            request |= {
                "traceId": f"trace-{index}",
                "spanId": f"span-{index}",
                "sampled": index % 2 == 0,
            }
        frame = encoder.encode(request)
        assert isinstance(frame, bytes)
        split = 1 + len(request["tag"]) % (len(frame) - 1)
        parser = service.make_unsafe()
        assert parser.decode(frame[:split]) == []
        assert parser.decode(frame[split:]) == [request]


def test_schema_binary_owns_encoded_frames_without_copying_envelope_holes() -> None:
    """RpcSerialization / SchemaBinary / owns encoded frames without copying envelope holes"""
    service = rs.make_schema_binary()
    encoder = service.make_unsafe()
    payload = bytearray((1, 2, 3))
    request = {"_tag": "Request", "id": 1, "tag": "Echo", "payload": bytes(payload), "headers": ()}
    frame = encoder.encode(request)
    assert isinstance(frame, bytes)
    expected = bytes(frame)
    payload[:] = bytes((9, 9, 9))
    for i in range(1000):
        encoder.encode({**request, "id": i})
    assert frame == expected
    assert service.make_unsafe().decode(frame) == [{**request, "payload": bytes((1, 2, 3))}]


def test_schema_binary_defaults_max_frame_size_to_16_mib() -> None:
    """RpcSerialization / SchemaBinary / defaults maxFrameSize to 16 MiB"""
    service = rs.make_schema_binary()
    assert service.make_unsafe().decode(_uvarint(16 * 1024 * 1024)) == []
    with pytest.raises(S.SchemaError, match="frame within maxFrameSize"):
        service.make_unsafe().decode(_uvarint(16 * 1024 * 1024 + 1))


def test_layer_schema_binary_overrides_max_frame_size() -> None:
    """RpcSerialization / SchemaBinary / layerSchemaBinary overrides maxFrameSize"""
    service = rs.make_schema_binary(max_frame_size=4)
    assert service.make_unsafe().decode(_uvarint(4)) == []
    with pytest.raises(S.SchemaError, match="frame within maxFrameSize"):
        service.make_unsafe().decode(_uvarint(5))


def test_layer_schema_binary_allows_an_unbounded_max_frame_size() -> None:
    """RpcSerialization / SchemaBinary / layerSchemaBinary allows an unbounded maxFrameSize"""
    service = rs.make_schema_binary(max_frame_size="unbounded")
    assert service.make_unsafe().decode(_uvarint(16 * 1024 * 1024 + 1)) == []


# --- codecFor -------------------------------------------------------------------------


def _json_string_codec(schema: Any) -> Any:
    """A hole codec observably unlike ``S.to_codec_json``: JSON, then a string."""
    return S.from_json_string(S.to_codec_json(schema))


_json_strings = L.succeed(
    rs.RpcSerialization, rs.with_codec_for(rs.make_ndjson(), _json_string_codec)
)


def test_codec_for_builds_each_servers_codecs_when_that_server_is_created() -> None:
    """RpcSerialization / codecFor / builds each server's codecs when that server is created"""
    as_json_string = [False]

    def codec_for(schema: Any) -> Any:
        return _json_string_codec(schema) if as_json_string[0] else S.to_codec_json(schema)

    serialization = L.succeed(rs.RpcSerialization, rs.with_codec_for(rs.make_ndjson(), codec_for))

    def echo(value: str) -> Any:
        def body():
            client = yield from rpc_client.make(_Rpcs)
            return (yield from client.echo({"value": value}))

        return _run_client(body, serialization)

    assert echo("first") == "first!"
    as_json_string[0] = True
    assert echo("second") == "second!"


def test_codec_for_fills_the_request_payload_hole_with_the_serializations_codec() -> None:
    """RpcSerialization / codecFor / fills the request payload hole with the serialization's
    codec"""
    frames: list[object] = []
    inner = rs.make_ndjson()

    class _Noting:
        def __init__(self) -> None:
            self.parser = inner.make_unsafe()

        def decode(self, data: rs.Frame, /) -> list[object]:
            decoded = self.parser.decode(data)
            frames.extend(m for m in decoded if m.get("_tag") == "Request")  # pyright: ignore[reportAttributeAccessIssue]
            return decoded

        def encode(self, response: object, /) -> rs.Frame | None:
            return self.parser.encode(response)

    service = rs.RpcSerializationService(
        make_unsafe=_Noting,
        content_type=inner.content_type,
        includes_framing=inner.includes_framing,
        codec_for=_json_string_codec,
    )

    def body():
        client = yield from rpc_client.make(_Rpcs)
        assert (yield from client.echo({"value": "hi"})) == "hi!"

    _run_client(body, L.succeed(rs.RpcSerialization, service))
    [frame] = frames
    payload = frame["payload"]  # pyright: ignore[reportIndexIssue]
    assert isinstance(payload, str), "the payload hole must carry the codec's output"
    assert json.loads(payload) == {"value": "hi"}


def test_codec_for_fills_the_stream_chunk_holes_with_the_serializations_codec() -> None:
    """RpcSerialization / codecFor / fills the stream chunk holes with the serialization's codec"""

    def body():
        client = yield from rpc_client.make(_Rpcs)
        assert (yield from client.counts({"to": 3}).run_collect()) == [1, 2, 3]

    _run_client(body, _json_strings)


def test_codec_for_fills_the_exit_hole_with_the_serializations_codec() -> None:
    """RpcSerialization / codecFor / fills the exit hole with the serialization's codec"""

    def body():
        client = yield from rpc_client.make(_Rpcs)
        error = yield from client.fail({}).flip()
        assert isinstance(error, EchoError)
        assert error.at == _FAILED_AT

    _run_client(body, _json_strings)


def test_codec_for_fills_the_defect_hole_with_the_serializations_codec() -> None:
    """RpcSerialization / codecFor / fills the defect hole with the serialization's codec"""

    def body():
        client = yield from rpc_client.make(_Rpcs)
        exit_ = yield from client.boom({}).exit()
        assert Exit.is_failure(exit_)
        assert "boom" in str(exit_.cause)

    _run_client(body, _json_strings)


@testing.effect
def test_layer_schema_binary_provides_the_serialization():
    """(not an Effect title) the layer provides the service Effect's layer does"""
    program: Any = rs.RpcSerialization()
    service: Any = yield from program.pipe(fx.provide(rs.layer_schema_binary()))
    assert service.content_type == "application/vnd.effect.rpc+schema-binary"
