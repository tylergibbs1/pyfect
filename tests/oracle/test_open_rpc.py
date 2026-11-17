"""Ports of Effect 4.1.4's ``rpc/OpenRpc.test.ts`` (each docstring is the Effect test
title). The small validator of ``_json_schema_validator.py`` stands in for Ajv."""

from __future__ import annotations

# pyright: reportUnknownLambdaType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
import json
from collections.abc import Sequence
from typing import Any, Literal, NotRequired, TypedDict

import pytest

import pyfect as fx
from pyfect import effect, layer, stream, testing
from pyfect import schema as S
from pyfect.http import request as Req
from pyfect.http import router
from pyfect.json_schema import JsonSchema
from pyfect.rpc import RpcGroup, RpcMiddleware, make
from pyfect.rpc import open_rpc as O
from pyfect.rpc import serialization as rs
from pyfect.rpc import server as rpc_server
from pyfect.rpc.schema import Stream

from ._json_schema_validator import compile_in

_INFO: O.OpenRPCInfo = {"title": "Contract tests", "version": "1.0.0"}


def _document(group: type[RpcGroup[Any]], **options: Any) -> O.OpenRPCSpec:
    return O.from_rpc_group(group, info=_INFO, **options)


def _method(document: O.OpenRPCSpec, name: str) -> O.OpenRPCMethod:
    found = [method for method in document["methods"] if method["name"] == name]
    assert found, f"Missing method {name}"
    return found[0]


def _params_schema(method: O.OpenRPCMethod) -> JsonSchema:
    schema = method.get("x-effect-params-schema")
    assert schema is not None
    return schema


def _stream(method: O.OpenRPCMethod) -> O.OpenRPCEffectStream:
    described = method.get("x-effect-stream")
    assert described is not None
    return described


def _accepts(document: O.OpenRPCSpec, schema: JsonSchema, value: object) -> bool:
    return compile_in({"components": document["components"]}, schema)(value)


def _sort_errors(errors: Sequence[O.OpenRPCError] | None) -> list[O.OpenRPCError] | None:
    return None if errors is None else sorted(errors, key=lambda error: error["code"])


class _ConvertParams(TypedDict):
    optional: NotRequired[str]
    amount: float


def test_describes_encoded_named_parameters():
    """OpenRpc / describes encoded named parameters"""
    payload = S.Struct(_ConvertParams, amount=S.NumberFromString).annotate(
        identifier="ConvertParams"
    )

    class Group(RpcGroup):
        convert = make("convert", payload=payload, success=S.NumberFromString)

    document = _document(Group)
    convert = _method(document, "convert")
    assert convert["paramStructure"] == "by-name"
    assert convert["params"] == [
        {"name": "amount", "required": True, "schema": {"type": "string"}},
        {"name": "optional", "required": False, "schema": {"type": "string"}},
    ]
    params = _params_schema(convert)
    assert _accepts(document, params, {"amount": "42"})
    assert not _accepts(document, params, {"amount": 42})
    assert not _accepts(document, params, {"optional": "x"})
    assert _accepts(document, convert["result"]["schema"], "42")
    assert not _accepts(document, convert["result"]["schema"], 42)


def test_describes_the_fixed_prefix_of_positional_parameters():
    """OpenRpc / describes the fixed prefix of positional parameters"""

    class Group(RpcGroup):
        tuple_ = make("tuple", payload=S.Tuple(S.NumberFromString, S.optional_key(S.Boolean)))
        rest = make("rest", payload=S.TupleWithRest(S.Tuple(S.String), S.Boolean))

    document = _document(Group)
    tuple_ = _method(document, "tuple")
    assert tuple_["paramStructure"] == "by-position"
    assert tuple_["params"] == [
        {"name": "0", "required": True, "schema": {"type": "string"}},
        {"name": "1", "required": False, "schema": {"type": "boolean"}},
    ]
    assert _accepts(document, _params_schema(tuple_), ["1"])
    assert not _accepts(document, _params_schema(tuple_), ["1", False, True])
    rest = _method(document, "rest")
    assert rest["paramStructure"] == "by-position"
    assert rest["params"] == [{"name": "0", "required": True, "schema": {"type": "string"}}]
    assert _accepts(document, _params_schema(rest), ["prefix", True, False])
    assert not _accepts(document, _params_schema(rest), ["prefix", 1])


class _Named(TypedDict):
    name: str


def test_keeps_the_whole_schema_for_union_and_record_payloads():
    """OpenRpc / keeps the whole schema for union and record payloads"""

    class Group(RpcGroup):
        mixed = make("mixed", payload=S.Union(S.Struct(_Named), S.Tuple(S.String)))
        record = make("record", payload=S.Record(S.String, S.NumberFromString))

    document = _document(Group)
    mixed = _method(document, "mixed")
    assert mixed["paramStructure"] == "either"
    assert mixed["params"] == []
    assert _accepts(document, _params_schema(mixed), {"name": "Ada"})
    assert _accepts(document, _params_schema(mixed), ["Ada"])
    assert not _accepts(document, _params_schema(mixed), "Ada")
    record = _method(document, "record")
    assert record["paramStructure"] == "by-name"
    assert record["params"] == []
    assert _accepts(document, _params_schema(record), {"any": "1"})
    assert not _accepts(document, _params_schema(record), {"any": 1})


class _TextNode(TypedDict):
    value: str
    children: Sequence[_TextNode]


class _CountNode(TypedDict):
    value: int
    children: Sequence[_CountNode]


class _NodePayload(TypedDict):
    node: _TextNode


def test_shares_definitions_and_keeps_colliding_recursive_identifiers_apart():
    """OpenRpc / shares definitions and keeps colliding recursive identifiers apart"""
    text_node: S.Codec[Any, Any] = S.Struct(
        _TextNode, value=S.String, children=S.Array(S.suspend(lambda: text_node))
    ).annotate(identifier="Node")
    count_node: S.Codec[Any, Any] = S.Struct(
        _CountNode, value=S.Int, children=S.Array(S.suspend(lambda: count_node))
    ).annotate(identifier="Node")

    class Group(RpcGroup):
        text = make("text", payload=S.Struct(_NodePayload, node=text_node), success=text_node)
        count = make("count", success=count_node)

    document = _document(Group)
    text = _method(document, "text")
    count = _method(document, "count")["result"]["schema"]
    assert isinstance(text["result"]["schema"]["$ref"], str)
    assert text["params"][0]["schema"]["$ref"] == text["result"]["schema"]["$ref"]
    assert count["$ref"] != text["result"]["schema"]["$ref"]
    result = text["result"]["schema"]
    assert _accepts(document, result, {"value": "a", "children": [{"value": "b", "children": []}]})
    assert not _accepts(
        document, result, {"value": "a", "children": [{"value": 1, "children": []}]}
    )
    assert _accepts(document, count, {"value": 1, "children": [{"value": 2, "children": []}]})
    assert not _accepts(document, count, {"value": 1, "children": [{"value": "b", "children": []}]})


class _First(TypedDict):
    value: str


def test_keeps_references_into_shared_definitions_valid_after_draft_7_lowering():
    """OpenRpc / keeps references into shared definitions valid after Draft 7 lowering"""
    pair = S.Tuple(S.String).annotate(identifier="Pair")
    first_schema = S.String.check(
        S.make_filter(
            lambda _: True,
            representation={"id": "test/OpenRpc/First", "payload": None, "schemas": (pair.ast,)},
            to_json_schema=lambda context: {"$ref": f"{context.schemas[0]['$ref']}/prefixItems/0"},
        )
    )

    class Group(RpcGroup):
        first = make("first", success=S.Struct(_First, value=first_schema))

    document = _document(Group)
    result = _method(document, "first")["result"]["schema"]
    assert _accepts(document, result, {"value": "a"})
    assert not _accepts(document, result, {"value": 1})


def test_keeps_external_references_in_descriptors():
    """OpenRpc / keeps external references in descriptors"""
    external_schema = S.Any.check(
        S.make_filter(
            lambda value: isinstance(value, str),
            to_json_schema=lambda _: {"$ref": "https://example.com/string.json"},
        )
    )

    class Group(RpcGroup):
        external = make("external", success=external_schema)

    document = _document(Group)
    assert (
        _method(document, "external")["result"]["schema"]["$ref"]
        == "https://example.com/string.json"
    )


def test_describes_void_calls_with_a_null_result_and_rejects_scalar_payloads():
    """OpenRpc / describes void calls with a null result and rejects scalar payloads"""

    class Group(RpcGroup):
        void = make("void")

    servers: list[O.OpenRPCServer] = [{"name": "production", "url": "https://example.com/rpc"}]
    assert _document(Group, servers=servers) == {
        "openrpc": "1.3.2",
        "info": _INFO,
        "servers": servers,
        "methods": [
            {
                "name": "void",
                "paramStructure": "by-name",
                "params": [],
                "result": {"name": "result", "schema": {"type": "null"}},
            }
        ],
        "components": {"schemas": {}},
    }

    class Scalar(RpcGroup):
        scalar = make("scalar", payload=S.String)

    with pytest.raises(ValueError, match='"scalar"'):
        _document(Scalar)


def test_applies_group_annotation_defaults_and_method_overrides():
    """OpenRpc / applies group annotation defaults and method overrides"""
    examples: list[O.OpenRPCExamplePairing] = [
        {"name": "default", "params": [], "result": {"name": "result", "value": None}}
    ]

    class Group(RpcGroup):
        inherited = make("inherited").annotate_merge(O.annotations(summary=None, tags=None))
        overridden = make("overridden").annotate_merge(
            O.annotations(
                summary="Local summary",
                description="Local description",
                tags=[],
                examples=[],
                errors=[],
                deprecated=False,
                external_docs={"url": "https://example.com/local"},
            )
        )

    annotated = (
        Group.annotate(O.Summary, "Default summary")
        .annotate(O.Description, "Default description")
        .annotate(O.Tags, [{"name": "default"}])
        .annotate(O.Examples, examples)
        .annotate(O.Errors, [{"code": 7, "message": "Unavailable"}])
        .annotate(O.Deprecated, True)
        .annotate(O.ExternalDocs, {"url": "https://example.com/default"})
    )
    document = _document(annotated)
    inherited = {k: v for k, v in _method(document, "inherited").items() if k != "name"}
    assert inherited == {
        "paramStructure": "by-name",
        "params": [],
        "result": {"name": "result", "schema": {"type": "null"}},
        "summary": "Default summary",
        "description": "Default description",
        "tags": [{"name": "default"}],
        "examples": examples,
        "deprecated": True,
        "externalDocs": {"url": "https://example.com/default"},
        "errors": [{"code": 7, "message": "Unavailable"}],
    }
    overridden = _method(document, "overridden")
    assert overridden.get("summary") == "Local summary"
    assert overridden.get("description") == "Local description"
    assert overridden.get("tags") == []
    assert overridden.get("examples") == []
    assert overridden.get("errors") == []
    assert overridden.get("deprecated") is False
    assert overridden.get("externalDocs") == {"url": "https://example.com/local"}


class _Unauthorized(TypedDict):
    code: Literal[42]
    message: Literal["Unauthorized"]


class _Auth(RpcMiddleware[Any, Any, Any], key="OpenRpcTest/Auth"):
    error = S.Struct(_Unauthorized)


class _Known(TypedDict):
    code: Literal["41"]
    message: Literal["Known"]


class _Dynamic(TypedDict):
    code: int
    message: str


def test_derives_literal_error_metadata_on_a_best_effort_basis():
    """OpenRpc / derives literal error metadata on a best-effort basis"""
    known, dynamic = S.Struct(_Known), S.Struct(_Dynamic)

    class Group(RpcGroup):
        derived = make("derived", error=S.Union(known, dynamic)).middleware(_Auth)
        dynamic_ = make("dynamic", error=dynamic)
        explicit = make("explicit", error=known).annotate(
            O.Errors, [{"code": 7, "message": "Explicit"}]
        )

    document = _document(Group)
    assert _sort_errors(_method(document, "derived").get("errors")) == [
        {"code": 41, "message": "Known"},
        {"code": 42, "message": "Unauthorized"},
    ]
    assert "errors" not in _method(document, "dynamic")
    assert _method(document, "explicit").get("errors") == [{"code": 7, "message": "Explicit"}]


class _NeverError(TypedDict):
    code: int
    message: str


def test_ignores_never_members_when_deriving_literal_errors():
    """OpenRpc / ignores Never members when deriving literal errors"""
    error = S.Struct(
        _NeverError,
        code=S.Union(S.Literal(41), S.Never),
        message=S.Union(S.Literal("Known"), S.suspend(lambda: S.Never)),
    )

    class Group(RpcGroup):
        never = make("never", error=error)

    assert _method(_document(Group), "never").get("errors") == [{"code": 41, "message": "Known"}]


class _Item(TypedDict):
    value: float


class _StreamFailure(TypedDict):
    code: Literal[21]
    message: Literal["Stream failed"]


class _RpcFailure(TypedDict):
    code: Literal[22]
    message: Literal["RPC failed"]


def test_describes_streams_for_both_stream_constructors():
    """OpenRpc / describes streams for both stream constructors"""
    item = S.Struct(_Item, value=S.NumberFromString).annotate(identifier="StreamItem")
    stream_failure, rpc_failure = S.Struct(_StreamFailure), S.Struct(_RpcFailure)

    class Group(RpcGroup):
        flag = make("flag", success=item, error=stream_failure, stream=True)
        schema = make("schema", success=Stream(item, stream_failure), error=rpc_failure)
        unary = make("unary", success=item)

    document = _document(Group)
    for name in ("flag", "schema"):
        streaming = _method(document, name)
        described = _stream(streaming)
        assert described["encoding"] == "effect-jsonrpc"
        assert streaming["result"]["schema"] == {"type": "null"}
        assert _accepts(document, described["itemSchema"], {"value": "1"})
        assert not _accepts(document, described["itemSchema"], {"value": 1})
        assert _accepts(document, described["chunkSchema"], [{"value": "1"}])
        assert not _accepts(document, described["chunkSchema"], [])
        error = {"code": 21, "message": "Stream failed"}
        assert _accepts(document, described["errorSchema"], error)
        assert _accepts(document, described["causeSchema"], [{"_tag": "Fail", "error": error}])
    assert _sort_errors(_method(document, "schema").get("errors")) == [
        {"code": 21, "message": "Stream failed"},
        {"code": 22, "message": "RPC failed"},
    ]
    assert "x-effect-stream" not in _method(document, "unary")


class _NotFound(TypedDict):
    code: Literal[404]
    message: Literal["Not found"]


class _ConvertPayload(TypedDict):
    at: Any
    count: float


class _Converted(TypedDict):
    at: Any
    count: int


class _Rpcs(RpcGroup):
    convert = make(
        "Convert",
        payload=S.Struct(_ConvertPayload, at=S.DateTimeUtc, count=S.NumberFromString),
        success=S.Struct(_Converted, at=S.DateTimeUtc, count=S.BigInt),
    )
    missing = make("Missing", error=S.Struct(_NotFound))
    values = make("Values", success=S.BigInt, stream=True)


@testing.effect
def test_describes_what_the_json_rpc_serializer_sends():
    """OpenRpc / describes what the JSON-RPC serializer sends"""
    handlers = _Rpcs.to_layer(
        _Rpcs.handlers()
        .handle(_Rpcs.convert)(
            lambda request: effect.succeed(
                {"at": request.payload["at"], "count": int(request.payload["count"])}
            )
        )
        .handle(_Rpcs.missing)(lambda _: effect.fail({"code": 404, "message": "Not found"}))
        .handle(_Rpcs.values)(lambda _: stream.make(1, 2))
    )
    server = (
        rpc_server.layer_http(_Rpcs, path="/rpc", protocol="http")
        .pipe(layer.provide(handlers))
        .pipe(layer.provide(rs.layer_nd_json_rpc()))
    )
    client = yield from router.in_memory_client(server)

    def call(method: str, params: object = None) -> fx.Effect[list[Any], Any, Any]:
        body: dict[str, object] = {"jsonrpc": "2.0", "id": 1, "method": method}
        if params is not None:
            body["params"] = params
        request = Req.post("http://test/rpc").body_text(
            json.dumps(body) + "\n", "application/json-rpc"
        )
        return (
            client.execute(request)
            .flat_map(lambda response: response.text)
            .map(lambda text: [json.loads(line) for line in text.strip().split("\n")])
        )

    spec = _document(_Rpcs)
    params = {"at": "1970-01-01T00:00:00.000Z", "count": "42"}
    assert _accepts(spec, _params_schema(_method(spec, "Convert")), params)
    [converted] = yield from call("Convert", params)
    assert converted["result"] == params
    assert _accepts(spec, _method(spec, "Convert")["result"]["schema"], converted["result"])

    [missing] = yield from call("Missing")
    assert _method(spec, "Missing").get("errors") == [
        {"code": missing["error"]["code"], "message": missing["error"]["message"]}
    ]

    frames = yield from call("Values")
    described = _stream(_method(spec, "Values"))
    terminal = frames.pop()
    assert frames
    for frame in frames:
        assert frame["chunk"] is True
        assert _accepts(spec, described["chunkSchema"], frame["result"])
    assert [value for frame in frames for value in frame["result"]] == ["1", "2"]
    assert _accepts(spec, _method(spec, "Values")["result"]["schema"], terminal["result"])
