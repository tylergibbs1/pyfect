"""A whole-body read of a request is bounded by default: ``MaxBodySize``
is 10 MiB unless an app sets it, and ``None`` opts out."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any, TypedDict

import pytest

import pyfect as fx
from pyfect import byte_size, effect, stream
from pyfect import schema as S
from pyfect.exit import Failure
from pyfect.http import body as http_body
from pyfect.http import router, server_response
from pyfect.http.incoming_message import MaxBodySize
from pyfect.http.server_error import HttpServerError, RequestParseError
from pyfect.http.server_request import HttpServerRequest, ServerRequest
from pyfect.http.web import WebRequest
from pyfect.http.web_handler import to_web_handler
from pyfect.http_api import HttpApi, HttpApiGroup, builder, endpoint, get_group, test

_CHUNK = 64 * 1024
_DEFAULT = 10 * 1024 * 1024


def test_the_default_limit_is_10_mib() -> None:
    assert MaxBodySize.default() == byte_size.mebibytes(10)


def _post(body: AsyncIterator[bytes], headers: dict[str, str], *, limit: Any = "default") -> int:
    def read(request: ServerRequest) -> fx.Effect[Any, Any]:
        return request.text.as_(server_response.empty())

    app: fx.Effect[Any, Any, Any] = HttpServerRequest().flat_map(read)
    if limit != "default":
        app = app.pipe(effect.provide_service(MaxBodySize, limit))
    handler = to_web_handler(app)

    async def main() -> int:
        request = WebRequest("http://localhost/", method="POST", body=body, headers=headers)
        return (await asyncio.wait_for(handler(request), 10)).status

    return asyncio.run(main())


def _endless(pulled: list[int]) -> AsyncIterator[bytes]:
    async def chunks() -> AsyncIterator[bytes]:
        while True:
            pulled.append(_CHUNK)
            yield b" " * _CHUNK

    return chunks()


def test_a_body_with_no_length_stops_at_the_default_limit() -> None:
    pulled: list[int] = []
    assert _post(_endless(pulled), {"transfer-encoding": "chunked"}) == 413
    assert sum(pulled) <= _DEFAULT + _CHUNK


def test_a_declared_length_over_the_default_limit_is_refused_before_reading() -> None:
    pulled: list[int] = []
    status = _post(_endless(pulled), {"content-length": str(1 << 40)})
    assert status == 413
    assert sum(pulled) <= _CHUNK


@pytest.mark.parametrize("limit", [None, byte_size.mebibytes(11)])
def test_an_app_may_raise_or_remove_the_limit(limit: Any) -> None:
    size = _DEFAULT + _CHUNK

    async def body() -> AsyncIterator[bytes]:
        for _ in range(size // _CHUNK):
            yield b" " * _CHUNK

    assert _post(body(), {"content-length": str(size)}, limit=limit) == 204


class _Item(TypedDict):
    name: str


class _Items(HttpApiGroup, identifier="items"):
    add_item = endpoint.post("add", "/items", payload=S.Struct(_Item), success=S.Int)


_api = HttpApi.make("limits").add(_Items)
_ItemsLive = builder.group(
    _api, _Items, lambda h: h.handle(_Items.add_item)(lambda r: fx.succeed(len(r.payload["name"])))
)


def test_test_groups_refuses_a_payload_past_the_limit_as_the_network_server_does() -> None:
    """ahttp_test_groups_body_limit: in memory, as over the network, a payload past 10 MiB is
    refused, not decoded and handled. As in Effect's ``HttpApiTest`` (``Effect.orDie``
    around the app), the server's error is a defect of the call."""

    @fx.fn
    def program():
        api_client = yield from test.groups(_api, (_Items,), layer=_ItemsLive)
        big = _Item(name="x" * (_DEFAULT + 1))
        return (yield from get_group(api_client, _Items).add_item(payload=big).exit())

    exit_ = fx.run_blocking(fx.scoped(program()))
    assert isinstance(exit_, Failure)
    defect = exit_.cause.squash()
    assert isinstance(defect, HttpServerError)
    assert isinstance(defect.reason, RequestParseError)
    assert defect.reason.kind == "BodyTooLarge"


@pytest.mark.parametrize("body", ["bytes", "stream"])
def test_the_in_memory_client_bounds_a_body_read(body: str) -> None:
    def read(request: ServerRequest) -> fx.Effect[Any, Any]:
        return request.text.as_(server_response.empty())

    app = router.use(lambda routes: routes.add("POST", "/", HttpServerRequest().flat_map(read)))
    data = b" " * (_DEFAULT + 1)
    sent = (
        http_body.bytes_(data)
        if body == "bytes"
        else http_body.stream(stream.from_iterable([data[:_CHUNK], data[_CHUNK:]]))
    )

    @fx.fn
    def program():
        http = yield from router.in_memory_client(app)
        return (yield from http.post("http://localhost/", body=sent).exit())

    # A server answers 413; in memory the failure is a defect, as in Effect's HttpApiTest.
    exit_ = fx.run_blocking(fx.scoped(program()))
    assert isinstance(exit_, Failure)
    defect = exit_.cause.squash()
    assert isinstance(defect, HttpServerError)
    assert isinstance(defect.reason, RequestParseError)
    assert defect.reason.kind == "BodyTooLarge"
