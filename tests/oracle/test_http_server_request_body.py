"""Ports of Effect's ``http/HttpServerRequest.body.test.ts``. Each test's
docstring is the Effect test title; ``ReadableStream`` bodies are async
generators."""

import asyncio
from collections.abc import AsyncIterator
from typing import Literal

import pytest

import pyfect as fx
from pyfect import effect, stream
from pyfect.byte_size import ByteSize
from pyfect.http import request as client_request
from pyfect.http import server_response
from pyfect.http.incoming_message import MaxBodySize
from pyfect.http.server_request import HttpServerRequest, from_client_request
from pyfect.http.web import WebRequest, WebResponse
from pyfect.http.web_handler import WebHandler, from_web_handler, to_web_handler

PAYLOAD = "hello"


async def _chunked(chunks: list[str], close: bool = True) -> AsyncIterator[bytes]:
    for chunk in chunks:
        yield chunk.encode()
    if not close:
        await asyncio.Event().wait()


async def _stalled(chunks: list[str]) -> AsyncIterator[bytes]:
    """Never ends, and its cancellation never settles."""
    try:
        for chunk in chunks:
            yield chunk.encode()
        await asyncio.Event().wait()
    finally:
        await asyncio.shield(asyncio.Event().wait())


def test_from_web_handler_can_inspect_headers_without_reading_the_body() -> None:
    """fromWebHandler can inspect headers without reading the body"""
    request = from_client_request(
        client_request.post("http://localhost/upload")
        .set_header("x-test", "headers-only")
        .body_stream(stream.succeed(PAYLOAD.encode()), content_type="text/plain")
    )

    async def handler(web: WebRequest, _context: object = None) -> WebResponse:
        assert web.get("x-test") == "headers-only"
        return WebResponse(None, status=204)

    @fx.fn
    def program():
        response = yield from from_web_handler(handler).pipe(
            effect.provide_service(HttpServerRequest, request)
        )
        text = yield from request.text
        return response.status, text

    assert asyncio.run(fx.run_async(program().or_die())) == (204, PAYLOAD)


def _handler(accessor: Literal["arrayBuffer", "text"]) -> WebHandler:
    def read(request: object) -> fx.Effect[object, object]:
        from pyfect.http.server_request import ServerRequest

        assert isinstance(request, ServerRequest)
        return request.bytes_ if accessor == "arrayBuffer" else request.text

    app = (
        HttpServerRequest()
        .flat_map(lambda request: read(request).as_(server_response.empty()))
        .pipe(effect.provide_service(MaxBodySize, ByteSize(4)))
    )
    return to_web_handler(app)


def _post(
    handler: WebHandler, body: str | AsyncIterator[bytes], headers: dict[str, str] | None = None
) -> int:
    async def main() -> int:
        request = WebRequest("http://localhost/upload", method="POST", body=body, headers=headers)
        response = await asyncio.wait_for(handler(request), 5)
        return response.status

    return asyncio.run(main())


ACCESSORS = ["arrayBuffer", "text"]


@pytest.mark.parametrize("accessor", ACCESSORS)
def test_reads_a_body_at_the_limit(accessor: Literal["arrayBuffer", "text"]) -> None:
    """MaxBodySize via ${accessor} reads a body at the limit"""
    assert _post(_handler(accessor), "1234", {"content-length": "4"}) == 204


@pytest.mark.parametrize("accessor", ACCESSORS)
def test_returns_413_for_a_content_length_over_the_limit_without_reading_the_body(
    accessor: Literal["arrayBuffer", "text"],
) -> None:
    """MaxBodySize via ${accessor} returns 413 for a content-length over the limit without reading the body"""  # noqa: E501
    assert _post(_handler(accessor), _chunked([], close=False), {"content-length": "5"}) == 413


@pytest.mark.parametrize("accessor", ACCESSORS)
def test_returns_413_for_a_chunked_body_over_the_limit(
    accessor: Literal["arrayBuffer", "text"],
) -> None:
    """MaxBodySize via ${accessor} returns 413 for a chunked body over the limit"""
    assert _post(_handler(accessor), _stalled(["123", "45"])) == 413


@pytest.mark.parametrize("accessor", ACCESSORS)
def test_returns_413_when_the_body_is_longer_than_its_content_length(
    accessor: Literal["arrayBuffer", "text"],
) -> None:
    """MaxBodySize via ${accessor} returns 413 when the body is longer than its content-length"""
    assert _post(_handler(accessor), _stalled(["12345"]), {"content-length": "4"}) == 413
