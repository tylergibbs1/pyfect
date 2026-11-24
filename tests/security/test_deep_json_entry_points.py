"""JSON from a peer nests at most ``_json_text.MAX_DEPTH`` deep. Deeper text is
refused before it is parsed, with the error each entry point gives malformed
JSON. ``json.loads`` reads about ten thousand levels on Python 3.13 and a
hundred thousand on 3.14; a value that deep made the code walking it with
plain recursion raise ``RecursionError``, a defect."""

from __future__ import annotations

# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false, reportUnknownLambdaType=false
import ast
import asyncio
from collections.abc import Iterator
from typing import Any

import _source
import pytest
from oracle._http_api import struct

import pyfect as fx
from pyfect import _json_text, effect, layer
from pyfect import schema as S
from pyfect.exit import Failure, Success
from pyfect.http import router, server, server_response
from pyfect.http.server_request import HttpServerRequest
from pyfect.http.web import WebRequest
from pyfect.http.web_handler import to_web_handler
from pyfect.http_api import builder
from pyfect.http_api import endpoint as ep
from pyfect.http_api.api import HttpApi
from pyfect.http_api.group import HttpApiGroup
from pyfect.result import Ok
from pyfect.rpc import serialization

LIMIT = _json_text.MAX_DEPTH
DEEP = 5_000
"""Read by ``json.loads`` on 3.13 and 3.14, too deep for a recursive walk."""


def nested(depth: int) -> str:
    return "[" * depth + "]" * depth


def test_parse_reads_the_limit_and_refuses_one_level_more() -> None:
    assert _json_text.parse(nested(LIMIT)) is not None
    for text in (nested(LIMIT + 1), nested(DEEP)):
        with pytest.raises(ValueError, match="nested more than 512 levels"):
            _json_text.parse(text)


def test_bytes_are_counted_as_the_text_they_decode_to() -> None:
    for encoding in ("utf-8", "utf-16-le", "utf-32"):
        assert _json_text.parse(nested(LIMIT).encode(encoding)) is not None
        with pytest.raises(ValueError, match="nested"):
            _json_text.parse(bytearray(nested(LIMIT + 1).encode(encoding)))
    # U+225B in UTF-16 is the bytes '[' and '"': only the decoded text is counted.
    assert _json_text.parse(('["' + "≛" * 600 + '"]').encode("utf-16-le")) == ["≛" * 600]


def test_brackets_in_strings_do_not_count() -> None:
    assert _json_text.parse(f'["{"[" * DEEP}"]') == ["[" * DEEP]


def test_a_caller_can_ask_for_less() -> None:
    assert _json_text.parse(nested(8), max_depth=8) is not None
    with pytest.raises(ValueError, match="nested more than 8 levels"):
        _json_text.parse(nested(9), max_depth=8)


def _status(app: Any, body: str) -> int:
    async def main() -> int:
        request = WebRequest("http://localhost/x", method="POST", body=body)
        return (await to_web_handler(app)(request)).status

    return asyncio.run(main())


def test_server_request_json_is_a_400() -> None:
    @fx.gen
    def echo():
        request = yield from HttpServerRequest()
        value = yield from request.json
        return server_response.json_unsafe(value)

    assert _status(echo, nested(LIMIT)) == 200
    assert _status(echo, nested(DEEP)) == 400


def test_server_request_schema_body_with_a_reviver_is_a_400() -> None:
    from pyfect.http.incoming_message import schema_body_json

    decode = schema_body_json(S.Unknown, reviver=lambda _key, value: value)

    @fx.gen
    def app():
        request = yield from HttpServerRequest()
        yield from decode(request)
        return server_response.text("ok")

    assert _status(app, nested(LIMIT)) == 200
    assert _status(app, nested(DEEP)) == 400


def test_http_api_json_payload_is_a_400() -> None:
    group = HttpApiGroup.make("g").add(ep.post("p", "/p", payload=struct({"a": S.Json})))
    api = HttpApi.make("api").add(group)
    live = builder.group(
        api, group, lambda h: h.handle(group.endpoints["p"])(lambda _: effect.void)
    )
    app = builder.layer(api).pipe(layer.provide(live)).pipe(layer.provide(server.layer_services))

    async def main(bodies: list[str]) -> list[int]:
        made = router.to_web_handler(app, disable_logger=True)
        headers = {"content-type": "application/json"}
        try:
            return [
                (
                    await made.handler(
                        WebRequest("http://localhost/p", method="POST", headers=headers, body=body)
                    )
                ).status
                for body in bodies
            ]
        finally:
            await made.dispose()

    shallow, deep = (f'{{"a":{nested(depth)}}}' for depth in (LIMIT - 1, DEEP))
    assert asyncio.run(main([shallow, deep])) == [204, 400]


def test_schema_from_json_string_is_a_schema_error() -> None:
    for schema in (S.UnknownFromJsonString, S.from_json_string(S.Json)):
        assert isinstance(S.decode_unknown_exit(schema)(nested(LIMIT)), Success)
        exit = S.decode_unknown_exit(schema)(nested(DEEP))
        assert isinstance(exit, Failure)
        found = exit.cause.find_error()
        assert isinstance(found, Ok) and isinstance(found.value, S.SchemaError)


_MESSAGE = '{"_tag":"Request","id":"1","tag":"t","payload":%s,"headers":[]}'
_JSON_RPC = '{"jsonrpc":"2.0","id":1,"method":"t","params":%s}'
_RPC = [
    (serialization.json, _MESSAGE, ValueError),
    (serialization.json_rpc(), _JSON_RPC, ValueError),
    (serialization.ndjson, _MESSAGE + "\n", serialization.NdjsonDecodeError),
    (serialization.nd_json_rpc(), _JSON_RPC + "\n", serialization.NdjsonDecodeError),
]


@pytest.mark.parametrize("case", _RPC, ids=["json", "json_rpc", "ndjson", "nd_json_rpc"])
def test_rpc_frames_fail_as_malformed_json(
    case: tuple[serialization.RpcSerializationService, str, type[Exception]],
) -> None:
    service, template, error = case
    assert service.make_unsafe().decode(template % nested(LIMIT - 1)) != []
    with pytest.raises(error):
        service.make_unsafe().decode(template % nested(DEEP))


def test_ndjson_decode_fails_with_invalid_json() -> None:
    from pyfect import stream
    from pyfect.encoding import ndjson

    def run(text: str) -> object:
        decoded = stream.from_arrays((text,)).pipe_through_channel(ndjson.decode_string())
        return fx.run_blocking(decoded.run_collect().exit())

    assert isinstance(run(nested(LIMIT) + "\n"), Success)
    exit = run(nested(DEEP) + "\n")
    assert isinstance(exit, Failure)
    found = exit.cause.find_error()
    assert isinstance(found, Ok) and found.value.reason == "InvalidJson"


def _parse_calls(tree: ast.Module) -> Iterator[ast.Call]:
    """The calls of ``_json_text.parse`` in ``tree``, by any alias."""
    names = {
        alias.asname or alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module == "pyfect._json_text"
        for alias in node.names
        if alias.name == "parse"
    }
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and (
            (isinstance(node.func, ast.Name) and node.func.id in names)
            or (
                isinstance(node.func, ast.Attribute)
                and node.func.attr == "parse"
                and isinstance(node.func.value, ast.Name)
                and "json_text" in node.func.value.id
            )
        ):
            yield node


_OWN_LIMIT = {
    # ``json_array.decode``'s ``max_depth`` (default 1000) bounds an element; the
    # scanner counts it and fails with ``"Limit"`` before the element is parsed.
    "encoding/_json_array_scanner.py": 2,
}


def test_no_caller_reads_deeper_than_the_limit() -> None:
    """``max_depth`` may only lower the limit: each value passed to
    ``_json_text.parse`` is a module constant no larger than ``MAX_DEPTH``,
    except where ``_OWN_LIMIT`` says why.
    (Only ``_json_text`` imports ``json``:
    ``test_js_formatting_guard.test_only_json_text_imports_json``.)"""
    passed: list[str] = []
    own: dict[str, int] = {}
    for path in _source.files(_source.SRC):
        if not _source.mentions(path, "max_depth"):
            continue
        tree = _source.tree(path)
        constants = {
            target.id: node.value.value
            for node in tree.body
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant)
            for target in node.targets
            if isinstance(target, ast.Name)
        }
        for call in _parse_calls(tree):
            for keyword in call.keywords:
                where = f"{path.relative_to(_source.SRC)}:{call.lineno}"
                assert keyword.arg is not None, where
                if keyword.arg != "max_depth":
                    continue
                name = str(path.relative_to(_source.SRC))
                if name in _OWN_LIMIT:
                    own[name] = own.get(name, 0) + 1
                    continue
                value = keyword.value
                limit = constants.get(value.id) if isinstance(value, ast.Name) else None
                assert isinstance(limit, int) and 0 < limit <= LIMIT, where
                passed.append(where)
    assert len(passed) == 4, passed
    assert own == _OWN_LIMIT


def test_json_array_keeps_its_own_max_depth() -> None:
    from pyfect import stream
    from pyfect.encoding import json_array

    def run(depth: int, max_depth: int = json_array.DEFAULT_MAX_DEPTH) -> object:
        text = f"[1, {nested(depth)}, 2]"
        decoded = stream.from_arrays((text,)).pipe_through_channel(
            json_array.decode_string(max_depth=max_depth)
        )
        return fx.run_blocking(decoded.run_collect().exit())

    read = run(LIMIT + 100)
    assert isinstance(read, Success) and len(read.value) == 3
    refused = run(LIMIT + 100, max_depth=LIMIT)
    assert isinstance(refused, Failure)
    found = refused.cause.find_error()
    assert isinstance(found, Ok) and found.value.kind == "Limit"


def test_jsonc_and_json5_read_any_depth_as_effects_do() -> None:
    """Their parser keeps its own stack, so the limit is not needed there."""
    from pyfect.encoding import json5, jsonc

    for parse in (jsonc.parse, json5.parse):
        read = parse(nested(DEEP))
        assert isinstance(read, Ok)
        value = read.value
        for _ in range(DEEP - 1):
            assert isinstance(value, list) and len(value) == 1
            value = value[0]
        assert value == []
