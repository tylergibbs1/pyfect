"""The URLs ``http_runner``'s client protocols dial, read from Effect's
``HttpRunner.ts``: a path without a leading slash gets one, and ``https``
switches the scheme to ``https`` / ``wss``."""

from __future__ import annotations

from typing import Any, Never

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.cluster import http_runner
from pyfect.cluster.runner_address import RunnerAddress
from pyfect.cluster.runners import RpcClientProtocol
from pyfect.deferred import Deferred
from pyfect.http import client as http_client
from pyfect.http import response as http_response
from pyfect.http.client import HttpClient
from pyfect.http.request import HttpClientRequest
from pyfect.rpc import client as rpc_client
from pyfect.rpc import make as make_rpc
from pyfect.rpc import serialization
from pyfect.rpc.group import RpcGroup
from pyfect.scope import fork_scoped
from pyfect.socket import WebSocketConstructor

ADDRESS = RunnerAddress(host="::1", port=8080)


class _PingRpcs(RpcGroup):
    ping = make_rpc("Ping", success=S.String)


@pytest.mark.parametrize(
    ("path", "https", "expected"),
    [
        ("runner", False, "http://[::1]:8080/runner/"),
        ("/runner", True, "https://[::1]:8080/runner/"),
    ],
)
@testing.effect
def test_http_client_protocol_url(path: str, https: bool, expected: str):
    urls: list[str] = []

    def send(request: HttpClientRequest, _url: fx.Url, _signal: Any, _fiber: Any) -> Any:
        urls.append(request.url)
        body = '[{"_tag":"Exit","requestId":"0","exit":{"_tag":"Success","value":"pong"}}]'
        return fx.succeed(http_response.make(request, body))

    @fx.gen
    def body():
        runner_protocol = yield from RpcClientProtocol()
        protocol = yield from runner_protocol.make(ADDRESS)
        client = yield from rpc_client.make(
            _PingRpcs, rpc_client.ClientOptions(generate_request_id=lambda: "0")
        ).pipe(fx.provide_service(rpc_client.ClientProtocol, protocol))
        assert (yield from client.ping()) == "pong"
        assert urls == [expected]

    yield from fx.scoped(
        body.pipe(fx.provide(http_runner.layer_client_protocol_http(path=path, https=https)))
        .pipe(fx.provide(serialization.layer_json))
        .pipe(fx.provide_service(HttpClient, http_client.make(send)))
    )


class _OpenWebSocket:
    ready_state = 1

    def add_event_listener(self, type: Any, listener: Any, *, once: bool = False) -> None:
        pass

    def remove_event_listener(self, type: Any, listener: Any) -> None:
        pass

    def close(self, code: int | None = None, reason: str | None = None) -> None:
        pass

    def send(self, data: bytes | str) -> None:
        pass


@pytest.mark.parametrize(
    ("path", "https", "expected"),
    [
        ("runner", False, "ws://[::1]:8080/runner"),
        ("/runner", True, "wss://[::1]:8080/runner"),
    ],
)
@testing.effect
def test_websocket_client_protocol_url(path: str, https: bool, expected: str):
    urls: list[str] = []

    def construct(url: str, _options: Any) -> _OpenWebSocket:
        urls.append(url)
        return _OpenWebSocket()

    @fx.gen
    def body():
        connected = yield from Deferred[None, Never].make()
        hooks = rpc_client.ConnectionHooksService(connected.succeed(None).as_void(), fx.void)

        @fx.gen
        def connect():
            runner_protocol = yield from RpcClientProtocol()
            protocol = yield from runner_protocol.make(ADDRESS)
            yield from fork_scoped(protocol.run(0, lambda _: fx.void))
            yield from connected.wait()
            assert urls == [expected]

        yield from fx.scoped(
            connect.pipe(
                fx.provide(http_runner.layer_client_protocol_websocket(path=path, https=https))
            )
            .pipe(fx.provide(serialization.layer_json))
            .pipe(fx.provide_service(WebSocketConstructor, construct))
            .pipe(fx.provide_service(rpc_client.ConnectionHooks, hooks))
        )

    yield from body
