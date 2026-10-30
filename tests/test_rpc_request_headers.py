"""A request's in-band ``headers`` are pairs of strings or an object of
strings (Effect's ``Headers.fromInput``); any other shape is a defect for
that request, never headers read character by character."""

# pyright: reportUnknownLambdaType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false

import asyncio
import json
from typing import Any

import pytest

from pyfect import effect, layer
from pyfect import schema as S
from pyfect.http import router
from pyfect.http.web import WebRequest
from pyfect.rpc import RpcGroup, make
from pyfect.rpc import serialization as rs
from pyfect.rpc import server as rpc_server


class Echo(RpcGroup):
    echo = make("Echo", success=S.Record(S.String, S.String))


def _send(headers: object) -> list[dict[str, Any]]:
    handlers = Echo.to_layer(
        Echo.handlers().handle(Echo.echo)(
            lambda request: effect.succeed(
                {k: v for k, v in request.headers.items() if k.startswith("x-")}
            )
        )
    )
    app = (
        rpc_server.layer_http(Echo, path="/rpc", protocol="http")
        .pipe(layer.provide(handlers))
        .pipe(layer.provide(rs.layer_ndjson))
    )
    message = {"_tag": "Request", "id": "1", "tag": "Echo", "payload": None, "headers": headers}

    async def main() -> list[dict[str, Any]]:
        made = router.to_web_handler(app, disable_logger=True)
        try:
            request = WebRequest("http://test/rpc", method="POST", body=json.dumps(message) + "\n")
            response = await made.handler(request)
            assert response.status == 200
            text = await response.text()
            return [json.loads(line) for line in text.splitlines() if line.strip()]
        finally:
            await made.dispose()

    return asyncio.run(main())


def _exit(replies: list[dict[str, Any]]) -> dict[str, Any]:
    (reply,) = [r for r in replies if r.get("_tag") == "Exit"]
    return reply["exit"]


@pytest.mark.parametrize("headers", [[["X-A", "b"]], {"X-A": "b"}], ids=["pairs", "object"])
def test_pairs_or_an_object_of_strings_are_headers(headers: object):
    assert _exit(_send(headers)) == {"_tag": "Success", "value": {"x-a": "b"}}


def test_no_headers_are_none():
    assert _exit(_send(None)) == {"_tag": "Success", "value": {}}


@pytest.mark.parametrize(
    "headers", ["ab", ["a"], [["a"]], 5, [[1, 2]], [["x-a", "b", "c"]], {"x-a": 1}]
)
def test_any_other_shape_is_a_defect_for_the_request(headers: object):
    exit = _exit(_send(headers))
    assert exit["_tag"] == "Failure"
