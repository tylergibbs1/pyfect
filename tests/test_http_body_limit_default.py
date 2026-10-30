"""A whole-body read of a request is bounded by default: ``MaxBodySize``
is 10 MiB unless an app sets it, and ``None`` opts out."""

import asyncio
from collections.abc import AsyncIterator
from typing import Any

import pytest

import pyfect as fx
from pyfect import byte_size, effect
from pyfect.http import server_response
from pyfect.http.incoming_message import MaxBodySize
from pyfect.http.server_request import HttpServerRequest, ServerRequest
from pyfect.http.web import WebRequest
from pyfect.http.web_handler import to_web_handler

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
