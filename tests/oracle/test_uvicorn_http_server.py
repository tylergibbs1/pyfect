"""Ports of platform-node's ``NodeHttpServer.test.ts`` against the uvicorn
server (``http.uvicorn_server``), whose requests go through
``http.asgi``. Each test's docstring is the Effect test title.

The server-independent titles already ported for the live server
(``test_node_http_server.py``, ``test_node_http_server_features.py``) run
here again, with ``run_live`` serving through uvicorn; the WebSocket
titles the live server omits are ported here.

Omitted, besides the live server's omissions:
- "delivers a partial-read 413 ...", "returns 413 before a chunked upload
  finishes", the ``100 Continue`` titles, "forwards status text %j",
  "absolute-form request-target replaces the host": framing, ``100
  Continue``, reason phrases and request targets are uvicorn's (it sends
  the standard phrase, and ``Expect`` is answered when the app reads).
- "coalesces streaming chunks from the same pull": ASGI sends one
  ``http.response.body`` message per chunk.
- "answers keep-alive requests while graceful shutdown drains an existing
  connection": uvicorn closes keep-alive connections once their response
  is sent during shutdown.
- "switches other protocols to the raw connection", "reads $name before
  switching protocols", "does not switch protocols $name", "serves other
  requests after a truncated multipart upgrade body", "writes upgrade
  response header values as Latin-1": ASGI has no raw upgrades; only
  WebSockets are upgraded.
- "fails refused websocket handshakes without hanging shutdown": uvicorn
  refuses the handshake itself, without calling the app.
- "request URL toURL reports https over TLS": TLS is uvicorn's (its
  ``ssl_*`` options in ``config``).
"""

from __future__ import annotations

import socket
import struct
import time
from collections.abc import Callable, Iterator
from typing import Any, Literal

import pytest
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import ClientConnection, connect

import pyfect as fx
from pyfect import effect, layer, logger
from pyfect.deferred import Deferred
from pyfect.exit import Failure
from pyfect.http import router, server_response, uvicorn_server
from pyfect.http.client import HttpClient
from pyfect.http.server_request import HttpServerRequest
from pyfect.http.server_response import HttpServerResponse
from pyfect.logger import CurrentLogAnnotations, Logger
from pyfect.scope import scoped
from pyfect.socket import CloseEvent, SocketError
from pyfect.tracer import CurrentTracer, NativeSpan, SpanRequest, Tracer

from . import test_node_http_server as node
from . import test_node_http_server_features as features
from ._live_http import port

TIMEOUT = 5.0


def run_uvicorn(program: fx.Effect[Any, Any, Any], **options: Any) -> Any:
    """Run ``program`` with a uvicorn test server (and its client)."""
    provided = scoped(program).pipe(fx.provide(uvicorn_server.layer_test(**options)))
    return fx.run_sync(provided.or_die())


@pytest.fixture(autouse=True)
def _serve_with_uvicorn(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(node, "run_live", run_uvicorn)
    monkeypatch.setattr(features, "run_live", run_uvicorn)
    yield


# --- titles shared with the live server ----------------------------------------------

test_returns_400_for_malformed_json_within_max_body_size = (
    node.test_returns_400_for_malformed_json_within_max_body_size
)
test_aborts_the_response_when_a_streamed_body_fails_after_it_started = (
    node.test_aborts_the_response_when_a_streamed_body_fails_after_it_started
)
test_answers_rejected_http_1_1_headers_with_a_500_and_reports_the_failure = (
    node.test_answers_rejected_http_1_1_headers_with_a_500_and_reports_the_failure
)
test_disposes_after_a_client_aborts_a_handler_awaiting_an_upstream_request = (
    node.test_disposes_after_a_client_aborts_a_handler_awaiting_an_upstream_request
)
test_search_params_parser_parses_the_query = node.test_search_params_parser_parses_the_query
test_schema = features.test_schema
test_schema_json_applies_a_json_reviver = features.test_schema_json_applies_a_json_reviver
test_form_data = features.test_form_data
test_schema_body_form = features.test_schema_body_form
test_form_data_with_max_size = features.test_form_data_with_max_size
test_mount_app = features.test_mount_app
test_file = features.test_file
test_schema_body_url_params = features.test_schema_body_url_params
test_schema_body_url_params_error = features.test_schema_body_url_params_error
test_schema_body_form_json = features.test_schema_body_form_json
test_html = features.test_html
test_set_cookie = features.test_set_cookie
test_uninterruptible_routes = features.test_uninterruptible_routes
test_error_schema = features.test_error_schema


def test_keeps_routes_isolated_between_independent_servers() -> None:
    """keeps routes isolated between independent servers"""

    def serving(path: str) -> fx.Layer[Any, Any, Any]:
        routes = router.add("GET", path, server_response.text(path))
        return router.serve(routes, disable_logger=True).pipe(
            layer.provide_merge(uvicorn_server.layer_test())
        )

    def get(path: str) -> fx.Effect[tuple[int, str], Any, HttpClient]:
        @fx.fn
        def body():
            client = yield from HttpClient()
            response = yield from client.get(path)
            return response.status, (yield from response.text)

        return body()

    @fx.fn
    def program():
        first = yield from scoped(get("/a").zip(get("/b"))).pipe(fx.provide(serving("/a")))
        second = yield from scoped(get("/b").zip(get("/a"))).pipe(fx.provide(serving("/b")))
        return first, second

    first, second = fx.run_sync(program().or_die())
    assert first == ((200, "/a"), (404, ""))
    assert second == ((200, "/b"), (404, ""))


# --- WebSockets ------------------------------------------------------------------------


def _routed(
    path: str, handler: HttpServerResponse | fx.Effect[HttpServerResponse, Any, Any], **options: Any
) -> Callable[[fx.Effect[Any, Any, Any]], Any]:
    def run(program: fx.Effect[Any, Any, Any]) -> Any:
        routes = router.add("GET", path, handler)
        served = program.pipe(fx.provide(router.serve(routes, disable_logger=True)))
        return run_uvicorn(served.timeout(TIMEOUT), **options)

    return run


def _ws(at: int, path: str = "/ws", *, compression: str | None = None) -> ClientConnection:
    return connect(f"ws://127.0.0.1:{at}{path}", open_timeout=TIMEOUT, compression=compression)


def _close_code(at: int, on_open: Any = None) -> fx.Effect[int | None]:
    def run() -> int | None:
        with _ws(at) as ws:
            if on_open is not None:
                on_open()
            try:
                ws.recv(timeout=TIMEOUT)
            except ConnectionClosed as closed:
                return None if closed.rcvd is None else closed.rcvd.code
        return None

    return effect.blocking(run)


class _Spans:
    def __init__(self) -> None:
        self.spans: list[NativeSpan] = []

    def span(self, request: SpanRequest) -> NativeSpan:
        span = NativeSpan(request)
        self.spans.append(span)
        return span


def test_logs_and_traces_status_101_after_an_upgraded_websocket_closes() -> None:
    """logs and traces status 101 after an upgraded WebSocket closes"""
    logged: Deferred[object] = Deferred()

    def record(options: Any) -> None:
        annotations = options.fiber.get_ref(CurrentLogAnnotations)
        if annotations.get("http.url") == "/ws":
            fx.run_sync(logged.succeed(annotations.get("http.status")))

    spans = _Spans()

    @fx.fn
    def handler():
        request = yield from HttpServerRequest()
        sock = yield from request.upgrade
        from pyfect.socket import to_stream

        yield from to_stream(sock).run_drain().ignore()
        return server_response.empty()

    @fx.fn
    def program():
        at = yield from port

        def talk() -> int:
            with _ws(at) as ws:
                status = ws.response.status_code if ws.response is not None else 0
                ws.close(1000)
            return status

        status = yield from effect.blocking(talk)
        return status, (yield from logged.wait())

    routes = router.add("GET", "/ws", scoped(handler()))
    served = program().pipe(
        fx.provide(
            router.serve(routes).pipe(
                layer.provide(logger.layer([Logger.make(record)])),
                # The tracer middleware reads the current tracer.
            )
        )
    )
    traced = served.pipe(effect.provide_service(CurrentTracer, Tracer.make(spans.span)))
    status, logged_status = run_uvicorn(traced.timeout(TIMEOUT))
    assert status == 101
    assert logged_status == 101
    server_spans = [span for span in spans.spans if span.kind == "server"]
    assert [span.attributes.get("http.response.status_code") for span in server_spans] == [101]


@pytest.mark.parametrize("fail_handler", [False, True], ids=["recovers", "fails"])
def test_logs_the_fallback_status_when_an_upgrade_fails(fail_handler: bool) -> None:
    """logs the fallback status when an upgrade fails and the handler ${fails/recovers}"""
    logged: list[object] = []

    def record(options: Any) -> None:
        annotations = options.fiber.get_ref(CurrentLogAnnotations)
        if annotations.get("http.url") == "/ws":
            logged.append(annotations.get("http.status"))

    @fx.fn
    def handler():
        request = yield from HttpServerRequest()
        result = yield from request.upgrade.exit()
        assert isinstance(result, Failure)
        if fail_handler:
            return (yield from effect.fail(RuntimeError("upgrade failed")))
        return server_response.empty(status=426)

    @fx.fn
    def program():
        client = yield from HttpClient()
        # An ordinary HTTP request has no upgrade transport, so acquisition fails.
        response = yield from client.get("/ws")
        return response.status

    routes = router.add("GET", "/ws", handler())
    served = program().pipe(
        fx.provide(router.serve(routes).pipe(layer.provide(logger.layer([Logger.make(record)]))))
    )
    status = run_uvicorn(served.timeout(TIMEOUT))
    assert status == (500 if fail_handler else 426)
    assert logged == [status]


def test_websocket_options_are_forwarded_to_the_websocketserver() -> None:
    """websocket options are forwarded to the WebSocketServer"""

    @fx.fn
    def handler():
        request = yield from HttpServerRequest()
        sock = yield from request.upgrade.or_die()

        @fx.fn
        def pull_forever():
            reader = yield from sock.reader
            while True:
                yield from reader.pull

        yield from scoped(pull_forever()).pipe(fx.catch_tag(SocketError, lambda _: effect.void))
        return server_response.empty()

    @fx.fn
    def program():
        at = yield from port

        def extensions(compress: Literal["deflate"] | None) -> list[str]:
            with _ws(at, compression=compress) as ws:
                offered = ws.response.headers.get("sec-websocket-extensions") if ws.response else ""
                return [] if not offered else [offered.split(";")[0]]

        compressed = yield from effect.blocking(lambda: extensions("deflate"))
        plain = yield from effect.blocking(lambda: extensions(None))
        return compressed, plain

    run = _routed("/ws", handler(), config={"ws_per_message_deflate": True})
    compressed, plain = run(program())
    # The server accepts the extension when the client offers it...
    assert "permessage-deflate" in compressed
    # ...and clients that do not offer it still connect uncompressed.
    assert "permessage-deflate" not in plain


@pytest.mark.parametrize(
    ("name", "exit", "code"),
    [
        ("success", "success", 1000),
        ("interrupt", "interrupt", 1001),
        ("failure", "failure", 1011),
        ("defect", "defect", 1011),
        ("explicit close before failure", "explicit", 4400),
    ],
)
def test_closes_a_websocket_with_the_handlers_code(name: str, exit: str, code: int) -> None:
    """closes a WebSocket with the handler's ${name} code"""
    opened: Deferred[None] = Deferred()

    @fx.fn
    def handler():
        request = yield from HttpServerRequest()
        sock = yield from request.upgrade
        yield from sock.reader
        yield from opened.wait()
        if exit == "explicit":
            writer = yield from sock.writer
            yield from writer.write(CloseEvent(4400, "handler closed"))
        if exit == "interrupt":
            return (yield from effect.interrupt())
        if exit in ("failure", "explicit"):
            return (yield from effect.fail(RuntimeError("handler failed")))
        if exit == "defect":
            return (yield from effect.die(RuntimeError("handler defect")))
        return server_response.empty()

    @fx.fn
    def program():
        at = yield from port
        return (yield from _close_code(at, lambda: fx.run_sync(opened.succeed(None))))

    assert _routed("/ws", handler())(program()) == code


def test_an_upgrade_connection_reset_by_the_peer_does_not_crash_the_process() -> None:
    """an upgrade connection reset by the peer does not crash the process"""

    def reset(at: int) -> None:
        conn = socket.create_connection(("127.0.0.1", at), timeout=TIMEOUT)
        conn.sendall(
            b"GET /ws HTTP/1.1\r\nHost: 127.0.0.1\r\nUpgrade: websocket\r\n"
            b"Connection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
            b"Sec-WebSocket-Version: 13\r\n\r\n"
        )
        time.sleep(0.05)
        # SO_LINGER 0: close with a reset.
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        conn.close()
        time.sleep(0.05)

    @fx.fn
    def program():
        at = yield from port
        yield from effect.blocking(lambda: reset(at))
        client = yield from HttpClient()
        response = yield from client.get("/")
        return response.status

    assert _routed("/", server_response.text("ok"))(program()) == 200


def test_does_not_write_the_http_response_to_an_upgraded_connection() -> None:
    """does not write the HTTP response to an upgraded connection"""

    @fx.fn
    def handler():
        request = yield from HttpServerRequest()
        sock = yield from request.upgrade.or_die()
        yield from sock.reader
        writer = yield from sock.writer
        yield from writer.write("refused")
        yield from writer.write(CloseEvent(4400, "refused"))
        return server_response.empty()

    @fx.fn
    def program():
        at = yield from port

        def talk() -> tuple[list[object], int | None]:
            frames: list[object] = []
            with _ws(at) as ws:
                try:
                    while True:
                        frames.append(ws.recv(timeout=TIMEOUT))
                except ConnectionClosed as closed:
                    return frames, None if closed.rcvd is None else closed.rcvd.code

        return (yield from effect.blocking(talk))

    frames, code = _routed("/ws", scoped(handler()))(program())
    assert frames == ["refused"]
    assert code == 4400


def test_writes_the_http_response_when_the_upgrade_is_not_consumed() -> None:
    """writes the HTTP response when the upgrade is not consumed"""

    @fx.fn
    def program():
        at = yield from port

        def raw() -> bytes:
            with socket.create_connection(("127.0.0.1", at), timeout=TIMEOUT) as conn:
                conn.sendall(
                    b"GET /no-ws HTTP/1.1\r\nHost: 127.0.0.1\r\nUpgrade: websocket\r\n"
                    b"Connection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
                    b"Sec-WebSocket-Version: 13\r\n\r\n"
                )
                received = bytearray()
                while chunk := conn.recv(65536):
                    received += chunk
                return bytes(received)

        return (yield from effect.blocking(raw))

    response = _routed("/no-ws", server_response.text("upgrade refused", status=426))(program())
    assert response.startswith(b"HTTP/1.1 426")
    assert b"upgrade refused" in response
