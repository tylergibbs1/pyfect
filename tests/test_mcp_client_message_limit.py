"""The MCP client's ``max_message_bytes`` holds while a message is read: a
server sending an endless JSON body or stdout line is cut off near the
limit, not buffered whole first."""

from __future__ import annotations

# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false
from typing import Any, cast

import pytest

import pyfect as fx
from pyfect import sink, stream, testing
from pyfect.ai import mcp_client as C
from pyfect.ai import mcp_client_error as CE
from pyfect.ai import mcp_protocol as P
from pyfect.ai.mcp_schema import JsonObject
from pyfect.deferred import Deferred
from pyfect.http.client import HttpClient
from pyfect.http.client import make as make_http_client
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse
from pyfect.http.response import make as make_response
from pyfect.process import ChildProcessHandle, ChildProcessSpawner, ChildProcessSpawnerService
from pyfect.process import make as make_command
from pyfect.result import Err

LIMIT = 1024
CHUNK = 1024
CHUNKS = 64
REQUEST: JsonObject = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}


class Counter:
    def __init__(self) -> None:
        self.pulled = 0

    def body(self, first: bytes = b'{"jsonrpc":"2.0","id":1,"result":{"pad":"') -> Any:
        def step(i: int) -> fx.Effect[tuple[bytes, int] | None]:
            def run() -> tuple[bytes, int] | None:
                if i >= CHUNKS:
                    return None
                chunk = (first + b"A" * (CHUNK - len(first))) if i == 0 else b"A" * CHUNK
                self.pulled += len(chunk)
                return chunk, i + 1

            return fx.sync(run)

        return stream.unfold(0, step)


def _limit_error(result: object) -> None:
    assert isinstance(result, Err), result
    error = cast("Any", result).error
    assert isinstance(error, CE.McpClientError), error
    assert isinstance(error.reason, CE.LimitError), error


def _http_transport(
    status: int, counter: Counter, headers: dict[str, str] | None = None
) -> fx.Effect[Any, Any, Any]:
    def handle(request: HttpClientRequest) -> fx.Effect[HttpClientResponse]:
        return fx.sync(
            lambda: make_response(
                request,
                counter.body(),
                status=status,
                headers={"content-type": "application/json", **(headers or {})},
            )
        )

    client = make_http_client(lambda request, _url, _signal, _fiber: handle(request))
    return C.http(
        url="http://mcp.invalid/mcp", protocol=P.v2025_11_25, max_message_bytes=LIMIT
    ).pipe(fx.provide_service(HttpClient, client))


@pytest.mark.parametrize("status", [200, 500])
@testing.effect
def test_http_json_body_stops_at_the_limit(status: int):
    counter = Counter()
    transport = yield from _http_transport(status, counter)
    result = yield from transport.request(REQUEST, None).result()
    if status == 200:
        _limit_error(result)
    else:
        # An oversized error body is dropped; the status still reports.
        assert isinstance(result, Err)
        assert isinstance(result.error.reason, CE.HttpError)
    assert counter.pulled <= LIMIT + CHUNK


@testing.effect
def test_http_declared_length_over_the_limit_is_not_read():
    counter = Counter()
    transport = yield from _http_transport(200, counter, {"content-length": str(CHUNK * CHUNKS)})
    _limit_error((yield from transport.request(REQUEST, None).result()))
    assert counter.pulled == 0


@pytest.mark.parametrize("declared", ["\u00b2", "\u0661\u0662", "1_0", "-1", " 7 "])
@testing.effect
def test_http_odd_declared_length_is_still_read_under_the_limit(declared: str):
    """A content-length that is not ASCII digits is ignored (counted while
    read), never a crash."""
    counter = Counter()
    transport = yield from _http_transport(200, counter, {"content-length": declared})
    _limit_error((yield from transport.request(REQUEST, None).result()))
    assert counter.pulled <= LIMIT + CHUNK


@testing.effect
def test_stdio_line_stops_at_the_limit():
    counter = Counter()
    exit = Deferred[int]()

    def kill(**_options: object) -> fx.Effect[None]:
        return exit.succeed(0).as_void()

    handle = ChildProcessHandle(
        pid=cast("Any", 1),
        exit_code=cast("Any", exit.wait()),
        is_running=fx.succeed(True),
        kill=kill,
        stdin=cast("Any", sink.drain.ensuring(exit.succeed(0))),
        stdout=counter.body(b"{"),
        stderr=stream.empty,
        all=stream.empty,
        get_input_fd=lambda _: cast("Any", sink.drain),
        get_output_fd=lambda _: stream.empty,
        unref=cast("Any", fx.succeed(fx.succeed(None))),
    )
    spawner = ChildProcessSpawnerService(lambda _: fx.succeed(handle))
    transport = yield from C.stdio(
        command=make_command("server"), protocol=P.v2025_11_25, max_message_bytes=LIMIT
    ).pipe(fx.provide_service(ChildProcessSpawner, spawner))
    result = yield from transport.request(REQUEST, None).timeout(5).result()
    _limit_error(result)
    assert counter.pulled <= LIMIT + CHUNK
