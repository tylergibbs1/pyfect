"""The httpx client closes every response before its loop stops: a
response whose read was interrupted, whose request scope closed, or that
was only partly read is closed, not left pending on a stopped loop."""

import asyncio
from collections.abc import AsyncIterator

import httpx
import pytest

import pyfect as fx
from pyfect.http import httpx_client, request
from pyfect.http.client import HttpClient
from pyfect.scope import Scope

# A response stream left unclosed on the stopped loop is reported as a
# never-awaited coroutine when it is collected.
pytestmark = pytest.mark.filterwarnings("error")


class _Body(httpx.AsyncByteStream):
    def __init__(self, closed: list[bool]) -> None:
        self._closed = closed

    async def __aiter__(self) -> AsyncIterator[bytes]:
        while True:
            yield b"chunk"
            await asyncio.sleep(0)

    async def aclose(self) -> None:
        await asyncio.sleep(0.3)
        self._closed.append(True)


def _closed_after(use: fx.Effect[object, object, HttpClient | Scope]) -> list[bool]:
    closed: list[bool] = []

    def handler(_sent: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_Body(closed))

    http = httpx_client.layer_with(transport=httpx.MockTransport(handler))
    fx.run_blocking(fx.scoped(use).pipe(fx.provide(http)).or_die())
    return closed


def test_a_response_whose_body_read_is_interrupted_is_closed() -> None:
    send = HttpClient().flat_map(lambda client: client.execute(request.get("http://test/")))
    read = send.flat_map(lambda response: response.stream.run_drain()).timeout(0.1)
    assert _closed_after(read.ignore()) == [True]


def test_a_scoped_request_is_closed_with_its_scope() -> None:
    send = HttpClient().flat_map(
        lambda client: client.with_scope().execute(request.get("http://test/"))
    )
    assert _closed_after(send) == [True]


def test_a_partly_read_response_is_closed() -> None:
    send = HttpClient().flat_map(lambda client: client.execute(request.get("http://test/")))
    read = send.flat_map(lambda response: response.stream.take(1).run_drain())
    assert _closed_after(read) == [True]
