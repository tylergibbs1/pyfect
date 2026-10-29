"""Ports of platform-node's ``NodeHttpServer.test.ts`` against the live
stdlib server (``http.live_server``). Each test's docstring is the Effect
test title. Clients are raw sockets or the httpx test client.

Omitted:
- "does not duplicate Node's automatic 100 Continue with makeHandler": no
  ``makeHandler`` over a host server; the live server owns the socket.
- HTTP/2 cases ("takes the host header from the HTTP/2 authority",
  "acknowledges Expect: 100-continue over HTTP/2", "closes idle HTTP/2
  sessions on shutdown", "closes HTTP/2 sessions whose TLS handshake
  finishes during shutdown", the HTTP/2 rows of the protocol suites): the
  live server speaks HTTP/1.1 only.
- "toServerResponse works behind the decompression middleware": reads
  Node's ``http.ServerResponse`` out of the request.
- "fileWeb": ``fileWeb`` takes a Web ``File``.
- "completes a HEAD response once when close precedes the end callback",
  "returns none when a late remoteAddress read finds no socket", "waits
  for drain after a streaming write applies backpressure": emit Node
  stream events on mocked ``ServerResponse`` objects.
- WebSocket cases ("logs and traces status 101 after an upgraded
  WebSocket closes", "websocket options are forwarded to the
  WebSocketServer", "closes a WebSocket with the handler's ... code", "an
  upgrade connection reset by the peer does not crash the process", "fails
  refused websocket handshakes without hanging shutdown"): the live
  server's upgrade hands over the raw connection; WebSocket framing is
  ``pyfect.socket.ws``'s.
- "xForwardedHeaders trusts an IPv4-mapped peer and keeps provenance after
  modify": the middleware's cases are in ``test_http_middleware.py``; the
  live server listens on one address family, so it sees no IPv4-mapped
  peer. ("toURL reports https over TLS" is in
  ``test_node_http_server_features.py``.)
- "tracing", "HttpServerRespondable httpapi error", "RouterConfig",
  "HttpRouter prefixed", "redacts query params when inspecting requests":
  covered against the test client in ``test_http_router.py``,
  ``test_http_server_respondable.py`` and ``test_http_server_request.py``.
"""

from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from typing import Any

import pytest

import pyfect as fx
from pyfect import effect, layer, stream
from pyfect import exit as Exit
from pyfect.byte_size import ByteSize
from pyfect.http import body as http_body
from pyfect.http import router, server, server_response, url_params
from pyfect.http.client import HttpClient
from pyfect.http.incoming_message import MaxBodySize
from pyfect.http.server_request import HttpServerRequest, ServerRequest
from pyfect.http.server_response import HttpServerResponse
from pyfect.scope import Scope, scoped

from ._live_http import (
    exchange,
    expect_continue,
    parse_responses,
    port,
    run_live,
    until_close,
    with_socket,
)


def _serve(app: fx.Effect[HttpServerResponse, Any, Any]) -> fx.Effect[int, Any, Any]:
    return server.serve_effect(app).flat_map(lambda _: port)


def _with_request(
    f: Callable[[ServerRequest], fx.Effect[HttpServerResponse, Any, Any]],
) -> fx.Effect[HttpServerResponse, Any, HttpServerRequest | Scope]:
    return HttpServerRequest().flat_map(f)


@pytest.mark.parametrize("leftover", [8 * 1024, 512 * 1024])
def test_delivers_a_partial_read_413_and_drains_or_closes(leftover: int) -> None:
    """delivers a partial-read 413 and drains or closes for %i leftover bytes"""
    body = b"rejected" * 16 * 1024

    def handle(request: ServerRequest) -> fx.Effect[HttpServerResponse, Any]:
        if request.url == "/next":
            return effect.succeed(server_response.text("next"))
        return (
            request.stream.take(1)
            .run_drain()
            .as_(server_response.bytes_(body, status=413, content_type="text/plain"))
        )

    head = (
        f"POST / HTTP/1.1\r\nhost: localhost\r\ncontent-length: {leftover + 1}\r\n"
        "connection: keep-alive\r\n\r\nx"
    ).encode()

    def use(conn: Any) -> list[Any]:
        conn.sendall(head)
        received = bytearray()
        while b"\r\n\r\n" not in received:
            received += conn.recv(65536)
        conn.sendall(bytes(leftover))
        conn.sendall(b"GET /next HTTP/1.1\r\nhost: localhost\r\nconnection: close\r\n\r\n")
        while chunk := conn.recv(65536):
            received += chunk
        return parse_responses(bytes(received))

    @fx.fn
    def program():
        at = yield from _serve(_with_request(handle))
        return (yield from with_socket(at, use))

    responses = run_live(program())
    first = responses[0]
    assert first.status == 413
    assert first.body == body
    assert first.header("content-length") == str(len(body))
    if leftover > 256 * 1024:
        assert first.header("connection") == "close"
        assert len(responses) == 1
    else:
        assert first.header("connection") == "keep-alive"
        assert [r.status for r in responses[1:]] == [200]
        assert responses[1].body == b"next"


def test_returns_413_before_a_chunked_upload_finishes() -> None:
    """returns 413 before a chunked upload finishes"""
    app = router.add(
        "POST",
        "/body",
        _with_request(lambda request: request.text.as_(server_response.empty())).pipe(
            effect.provide_service(MaxBodySize, ByteSize(4))
        ),
    )

    def use(conn: Any) -> tuple[bytes, bytes]:
        conn.sendall(
            b"POST /body HTTP/1.1\r\nhost: localhost\r\ntransfer-encoding: chunked\r\n\r\n"
            b"5\r\n12345\r\n"
        )
        received = bytearray()
        while b"\r\n\r\n" not in received:
            received += conn.recv(65536)
        # The final chunk is withheld until the server has answered.
        conn.sendall(b"10\r\nremaining upload\r\n0\r\n\r\n")
        return bytes(received), b""

    @fx.fn
    def program():
        at = yield from port
        return (yield from with_socket(at, use))

    received, _ = run_live(_routed(app, program()))
    assert received.startswith(b"HTTP/1.1 413 ")


def _routed(app: fx.Layer[Any, Any, Any], program: fx.Effect[Any, Any, Any]) -> Any:
    """``program`` with ``app`` served by the router."""
    return program.pipe(fx.provide(router.serve(app, disable_logger=True)))


def test_returns_400_for_malformed_json_within_max_body_size() -> None:
    """returns 400 for malformed JSON within MaxBodySize"""
    app = router.add(
        "POST",
        "/body",
        _with_request(lambda request: request.json.as_(server_response.empty())).pipe(
            effect.provide_service(MaxBodySize, ByteSize(4))
        ),
    )

    @fx.fn
    def program():
        client = yield from HttpClient()
        response = yield from client.post("/body", body=http_body.text("{"))
        return response.status

    assert run_live(_routed(app, program())) == 400


def test_rejects_expect_100_continue_without_requesting_the_body() -> None:
    """rejects Expect: 100-continue without requesting the body"""

    def handle(request: ServerRequest) -> fx.Effect[HttpServerResponse]:
        # Obtaining a body accessor must not start reading the body.
        _ = (request.stream, request.text, request.multipart, request.multipart_stream)
        return effect.succeed(server_response.empty(status=413))

    @fx.fn
    def program():
        at = yield from _serve(_with_request(handle))
        return (yield from expect_continue(at, b"hello"))

    result = run_live(program())
    assert result.status == 413
    assert result.continues == 0
    assert not result.uploaded


def _read_with(accessor: str, request: ServerRequest) -> fx.Effect[str, Any]:
    match accessor:
        case "stream":
            return request.stream.run_collect().map(lambda chunks: b"".join(chunks).decode())
        case "array_buffer":
            return request.bytes_.map(bytes.decode)
        case "json":
            return request.json.map(str)
        case "url_params_body":
            return request.url_params_body.map(url_params.to_string)
        case _:
            return request.text


@pytest.mark.parametrize("accessor", ["stream", "text", "json", "url_params_body", "array_buffer"])
def test_sends_one_100_continue_when_consuming(accessor: str) -> None:
    """sends one 100 Continue when consuming %s"""

    def handle(original: ServerRequest) -> fx.Effect[HttpServerResponse, Any]:
        request = original.modify(url="/body")
        return _read_with(accessor, request).map(server_response.text)

    payload = {"json": b'"hello"', "url_params_body": b"hello=world"}.get(accessor, b"hello")

    @fx.fn
    def program():
        at = yield from _serve(_with_request(handle))
        return (yield from expect_continue(at, payload))

    result = run_live(program())
    assert result.status == 200
    assert result.body == (b"hello=world" if accessor == "url_params_body" else b"hello")
    assert result.continues == 1
    assert result.uploaded


@pytest.mark.parametrize("accessor", ["multipart", "multipart_stream"])
def test_sends_one_100_continue_when_consuming_multipart(accessor: str) -> None:
    """sends one 100 Continue when consuming %s"""
    from pyfect.http import multipart

    def handle(original: ServerRequest) -> fx.Effect[HttpServerResponse, Any]:
        request = original.modify(url="/upload")
        if accessor == "multipart":
            field = request.multipart.map(lambda parts: str(parts["message"]))
        else:
            field = request.multipart_stream.run_collect().map(
                lambda parts: "".join(
                    part.value if isinstance(part, multipart.Field) else "file" for part in parts
                )
            )
        text: fx.Effect[HttpServerResponse, Any, Any] = field.map(server_response.text)
        return text

    payload = (
        b'--boundary\r\nContent-Disposition: form-data; name="message"\r\n\r\n'
        b"hello\r\n--boundary--\r\n"
    )

    @fx.fn
    def program():
        at = yield from _serve(_with_request(handle))
        return (
            yield from expect_continue(
                at, payload, {"content-type": "multipart/form-data; boundary=boundary"}
            )
        )

    result = run_live(program())
    assert result.status == 200
    assert result.body == b"hello"
    assert result.continues == 1
    assert result.uploaded


def test_sends_one_100_continue_across_repeated_original_and_modified_body_reads() -> None:
    """sends one 100 Continue across repeated original and modified body reads"""

    @fx.fn
    def handle(original: ServerRequest):
        modified = original.modify(url="/body")
        bodies = yield from fx.all(original.text, modified.text, concurrency="unbounded")
        repeated = yield from fx.all(original.text, modified.text)
        return server_response.text(",".join([*bodies, *repeated]))

    @fx.fn
    def program():
        at = yield from _serve(_with_request(handle))
        return (yield from expect_continue(at, b"hello"))

    result = run_live(program())
    assert result.status == 200
    assert result.body == b"hello,hello,hello,hello"
    assert result.continues == 1
    assert result.uploaded


@pytest.mark.parametrize("status_text", ["Uploaded", ""])
def test_forwards_status_text(status_text: str) -> None:
    """forwards status text %j"""
    app = router.add("GET", "/", server_response.empty(status=201, status_text=status_text))

    @fx.fn
    def program():
        at = yield from port
        return (
            yield from until_close(at, b"GET / HTTP/1.1\r\nhost: x\r\nconnection: close\r\n\r\n")
        )

    [response] = parse_responses(run_live(_routed(app, program())))
    assert response.status == 201
    # Node falls back to the standard reason phrase for an empty one.
    assert response.reason == (status_text or "Created")


def test_coalesces_streaming_chunks_from_the_same_pull() -> None:
    """coalesces streaming chunks from the same pull"""
    body = stream.from_iterable([b"a", b"b", b"c"])
    app = effect.succeed(server_response.stream(body))

    @fx.fn
    def program():
        at = yield from _serve(app)
        return (
            yield from until_close(at, b"GET / HTTP/1.1\r\nhost: x\r\nconnection: close\r\n\r\n")
        )

    received = run_live(program())
    _head, _, chunked = received.partition(b"\r\n\r\n")
    assert chunked == b"3\r\nabc\r\n0\r\n\r\n"


def test_aborts_the_response_when_a_streamed_body_fails_after_it_started() -> None:
    """aborts the response when a streamed body fails after it started"""
    body = stream.make(b"partial").concat(stream.fail(RuntimeError("boom")))
    app = effect.succeed(server_response.stream(body))

    @fx.fn
    def program():
        at = yield from _serve(app)
        return (yield from until_close(at, b"GET / HTTP/1.1\r\nhost: x\r\n\r\n"))

    received = run_live(program())
    assert received.startswith(b"HTTP/1.1 200 ")
    assert b"partial" in received
    # The chunked body never ends, so the client cannot take it as complete.
    assert not received.endswith(b"0\r\n\r\n")


def test_answers_rejected_http_1_1_headers_with_a_500_and_reports_the_failure() -> None:
    """when writeHead throws answers rejected HTTP/1.1 headers with a 500 and reports the failure"""
    app = effect.succeed(server_response.text("ok", headers={"x-bad": "a\nb"}))

    @fx.fn
    def program():
        at = yield from _serve(app)
        return (yield from until_close(at, b"GET / HTTP/1.1\r\nhost: x\r\n\r\n"))

    [response] = parse_responses(run_live(program()))
    assert response.status == 500
    assert response.header("x-bad") is None


def test_answers_keep_alive_requests_while_graceful_shutdown_drains_an_existing_connection() -> (
    None
):
    """answers keep-alive requests while graceful shutdown drains an existing connection"""
    from pyfect.http import live_server
    from pyfect.latch import Latch
    from pyfect.scope import scoped

    request_started = Latch()
    release_response = Latch()
    app = request_started.open().and_then(release_response.wait()).as_(server_response.text("ok"))

    def use(conn: Any) -> tuple[bytes, bytes]:
        conn.sendall(b"GET /first HTTP/1.1\r\nHost: localhost\r\n\r\n")
        first = bytearray()
        while not first.endswith(b"\r\n\r\nok"):
            chunk = conn.recv(65536)
            if not chunk:
                break
            first += chunk
        conn.sendall(b"GET /second HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n")
        second = bytearray()
        while chunk := conn.recv(65536):
            second += chunk
        return bytes(first), bytes(second)

    @fx.fn
    def serving():
        at = yield from _serve(app)
        client = yield from with_socket(at, use).fork_daemon()
        yield from request_started.wait()
        # The response is released once the server has started shutting down.
        yield from (
            effect.blocking(lambda: time.sleep(0.1)).and_then(release_response.open()).fork_daemon()
        )
        return client

    @fx.fn
    def program():
        layer_live = live_server.layer(host="127.0.0.1", graceful_shutdown_timeout=10)
        client = yield from scoped(serving()).pipe(fx.provide(layer_live))
        return (yield from client.join())

    started_at = time.monotonic()
    first, second = fx.run_sync(program().or_die())
    assert time.monotonic() - started_at < 5
    [first_response] = parse_responses(first)
    assert first_response.status == 200
    assert first_response.header("connection") == "keep-alive"
    # The second keep-alive request is answered before the shutdown timeout.
    [second_response] = parse_responses(second)
    assert second_response.status == 200
    assert second_response.body == b"ok"


def test_disposes_after_a_client_aborts_a_handler_awaiting_an_upstream_request() -> None:
    """disposes after a client aborts a handler awaiting an upstream request"""
    from pyfect.deferred import Deferred

    started: Deferred[None] = Deferred()
    interrupted: Deferred[None] = Deferred()
    # Routed handlers are interruptible: the abort reaches the one waiting.
    waiting = started.succeed(None).flat_map(lambda _: effect.never)
    app = router.add(
        "GET", "/", waiting.on_interrupt(interrupted.succeed(None)).as_(server_response.empty())
    )

    @fx.fn
    def program():
        at = yield from port

        @fx.fn
        def abort():
            def send(conn: Any) -> None:
                conn.sendall(b"GET / HTTP/1.1\r\nhost: x\r\n\r\n")
                time.sleep(0.1)

            fiber = yield from with_socket(at, send).fork()
            yield from started.wait()
            yield from fiber.await_exit()

        yield from abort()
        yield from interrupted.wait().timeout(2)
        return True

    started_at = time.monotonic()
    assert run_live(_routed(app, program()), graceful_shutdown_timeout=0.1)
    assert time.monotonic() - started_at < 2


def _upgrade_request(path: str = "/") -> bytes:
    return (
        f"GET {path} HTTP/1.1\r\nhost: x\r\nconnection: Upgrade\r\nupgrade: tcp\r\n\r\n"
    ).encode()


def _read_all(reader: Any) -> fx.Effect[bytes, Any]:
    """Pull until the client half-closes."""
    received = bytearray()

    def loop() -> fx.Effect[bytes, Any]:
        def took(chunks: tuple[bytes, ...] | None) -> fx.Effect[bytes, Any]:
            if chunks is None:
                return effect.succeed(bytes(received))
            for chunk in chunks:
                received.extend(chunk)
            return effect.suspend(loop)

        pulled: fx.Effect[Any, Any] = reader.pull
        return pulled.catch_all(lambda _: effect.succeed(None)).flat_map(took)

    return effect.suspend(loop)


ATTACH_HEAD = "POST /attach HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: Upgrade\r\nUpgrade: tcp\r\n"


def test_switches_other_protocols_to_the_raw_connection() -> None:
    """switches other protocols to the raw connection"""

    @fx.fn
    def handle(request: ServerRequest):
        socket = yield from request.upgrade.or_die()
        reader = yield from socket.reader
        writer = yield from socket.writer
        received = yield from _read_all(reader)
        # The client half-closed, but the connection stays writable.
        yield from writer.write(b"echo:" + received)
        return server_response.empty()

    app = router.add("POST", "/attach", scoped(handle_request(handle)))

    @fx.fn
    def program():
        at = yield from port
        # The bytes after the request head arrive with it, before the 101.
        return (yield from exchange(at, [(ATTACH_HEAD + "\r\nearly").encode()]))

    assert run_live(_routed(app, program())) == (
        b"HTTP/1.1 101 Switching Protocols\r\nConnection: Upgrade\r\nUpgrade: tcp\r\n\r\necho:early"
    )


def handle_request(f: Any) -> fx.Effect[HttpServerResponse, Any, Any]:
    return HttpServerRequest().flat_map(f)


@pytest.mark.parametrize(
    ("name", "parts", "read"),
    [
        (
            "a Content-Length body split from the head",
            [ATTACH_HEAD + "Content-Length: 5\r\n\r\nhe", "lloearly"],
            True,
        ),
        (
            "an unread Content-Length body",
            [ATTACH_HEAD + "Content-Length: 5\r\n\r\nhe", "lloearly"],
            False,
        ),
        (
            "a chunked body",
            [ATTACH_HEAD + "Transfer-Encoding: chunked\r\n\r\n5\r\nhe", "llo\r\n0\r\n\r\nearly"],
            True,
        ),
    ],
)
def test_reads_before_switching_protocols(name: str, parts: list[str], read: bool) -> None:
    """reads $name before switching protocols"""

    @fx.fn
    def handle(request: ServerRequest):
        body = (yield from request.text) if read else ""
        socket = yield from request.upgrade_with(
            headers={"content-type": "application/raw"}
        ).or_die()
        reader = yield from socket.reader
        writer = yield from socket.writer
        received = yield from _read_all(reader)
        yield from writer.write(f"{body}|".encode() + received)
        return server_response.empty()

    app = router.add("POST", "/attach", scoped(handle_request(handle)))

    @fx.fn
    def program():
        at = yield from port
        return (yield from exchange(at, [part.encode() for part in parts]))

    assert run_live(_routed(app, program())) == (
        b"HTTP/1.1 101 Switching Protocols\r\nConnection: Upgrade\r\nUpgrade: tcp\r\n"
        b"content-type: application/raw\r\n\r\n" + (b"hello" if read else b"") + b"|early"
    )


@pytest.mark.parametrize(
    ("name", "parts", "headers", "max_body_size"),
    [
        (
            "when the unread body exceeds MaxBodySize",
            [ATTACH_HEAD + "Content-Length: 5\r\n\r\nhe", "llo"],
            {},
            ByteSize(4),
        ),
        *(
            (f"with a {name} header", [ATTACH_HEAD + "\r\n"], {name: "1"}, None)
            for name in ("connection", "upgrade", "content-length", "transfer-encoding")
        ),
        ("with an invalid header name", [ATTACH_HEAD + "\r\n"], {"x name": "1"}, None),
        (
            "with an invalid header value",
            [ATTACH_HEAD + "\r\n"],
            {"x-name": "a\r\nx-injected: 1"},
            None,
        ),
    ],
)
def test_does_not_switch_protocols(
    name: str, parts: list[str], headers: dict[str, str], max_body_size: ByteSize | None
) -> None:
    """does not switch protocols $name"""

    @fx.fn
    def handle(request: ServerRequest):
        socket = yield from request.upgrade_with(headers=headers)
        yield from socket.reader
        return server_response.empty()

    handler = scoped(handle_request(handle)).pipe(
        effect.provide_service(MaxBodySize, max_body_size)
    )
    app = router.add("POST", "/attach", handler)

    @fx.fn
    def program():
        at = yield from port
        return (yield from exchange(at, [part.encode() for part in parts]))

    received = run_live(_routed(app, program()))
    assert re.match(rb"HTTP/1\.1 [45]\d\d ", received), received


def test_serves_other_requests_after_a_truncated_multipart_upgrade_body() -> None:
    """serves other requests after a truncated multipart upgrade body"""

    @fx.fn
    def attach(request: ServerRequest):
        yield from request.multipart
        socket = yield from request.upgrade.or_die()
        yield from socket.reader
        return server_response.empty()

    app = router.add_all(
        [
            router.route("POST", "/attach", scoped(handle_request(attach))),
            router.route("GET", "/ping", server_response.text("pong")),
        ]
    )

    @fx.fn
    def program():
        at = yield from port
        # The client stops after the first boundary of a 200 byte body.
        received = yield from exchange(
            at,
            [
                (
                    ATTACH_HEAD + "Content-Type: multipart/form-data; boundary=abc\r\n"
                    "Content-Length: 200\r\n\r\n--abc\r\n"
                ).encode()
            ],
        )
        client = yield from HttpClient()
        ping = yield from client.get("/ping")
        return received, (yield from ping.text)

    received, pong = run_live(_routed(app, program()))
    assert not received.startswith(b"HTTP/1.1 101 ")
    assert pong == "pong"


def test_writes_upgrade_response_header_values_as_latin_1() -> None:
    """writes upgrade response header values as Latin-1"""

    @fx.fn
    def handle(request: ServerRequest):
        socket = yield from request.upgrade_with(headers={"x-name": "café"}).or_die()
        yield from socket.reader.or_die()
        return server_response.empty()

    app = router.add("POST", "/attach", scoped(handle_request(handle)))

    @fx.fn
    def program():
        at = yield from port
        return (yield from exchange(at, [(ATTACH_HEAD + "\r\n").encode()]))

    head = run_live(_routed(app, program())).partition(b"\r\n\r\n")[0]
    # Peers decode header bytes as Latin-1.
    assert "x-name: café" in head.decode("latin-1")


def test_writes_the_http_response_when_the_upgrade_is_not_consumed() -> None:
    """writes the HTTP response when the upgrade is not consumed"""
    app = router.add("GET", "/no-ws", server_response.text("upgrade refused", status=426))

    @fx.fn
    def program():
        at = yield from port
        return (yield from until_close(at, _upgrade_request("/no-ws")))

    received = run_live(_routed(app, program()))
    assert received.startswith(b"HTTP/1.1 426")
    assert b"upgrade refused" in received


def test_does_not_write_the_http_response_to_an_upgraded_connection() -> None:
    """does not write the HTTP response to an upgraded connection"""

    @fx.fn
    def handle(request: ServerRequest):
        socket = yield from request.upgrade.or_die()
        yield from socket.reader
        writer = yield from socket.writer
        yield from writer.write(b"refused")
        return server_response.text("must not be sent")

    app = router.add("GET", "/ws", scoped(handle_request(handle)))

    @fx.fn
    def program():
        at = yield from port
        return (yield from until_close(at, _upgrade_request("/ws")))

    received = run_live(_routed(app, program()))
    head, _, trailing = received.partition(b"\r\n\r\n")
    assert head.startswith(b"HTTP/1.1 101 ")
    assert trailing == b"refused"


def _url_echo() -> fx.Layer[Any, Any, Any]:
    def echo(request: ServerRequest) -> fx.Effect[HttpServerResponse]:
        return effect.succeed(
            server_response.text(
                f"{request.headers.get('host')} {request.url} {request.original_url}"
            )
        )

    return router.add("GET", "*", _with_request(echo))


def test_absolute_form_request_target_replaces_the_host() -> None:
    """request URL absolute-form request-target replaces the host (RFC 9112 §3.2.2)"""

    @fx.fn
    def program():
        at = yield from port
        return (
            yield from until_close(
                at,
                b"GET http://example.test:4573/info?x=1 HTTP/1.1\r\nhost: other.test\r\n"
                b"connection: close\r\n\r\n",
            )
        )

    [response] = parse_responses(run_live(_routed(_url_echo(), program())))
    assert response.body == b"example.test:4573 /info?x=1 http://example.test:4573/info?x=1"


def test_search_params_parser_parses_the_query() -> None:
    """request URL searchParamsParser parses the query"""

    def echo(request: ServerRequest) -> fx.Effect[HttpServerResponse, Any]:
        from urllib.parse import urlsplit

        from pyfect.http.server_request import search_params_from_url

        params = search_params_from_url(urlsplit(request.original_url))
        return server_response.json(params)

    @fx.fn
    def program():
        at = yield from _serve(_with_request(echo))
        return (
            yield from until_close(
                at, b"GET /?a=1&b=2&b=3 HTTP/1.1\r\nhost: x\r\nconnection: close\r\n\r\n"
            )
        )

    [response] = parse_responses(run_live(program()))
    assert json.loads(response.body) == {"a": "1", "b": ["2", "3"]}


def test_keeps_routes_isolated_between_independent_servers() -> None:
    """keeps routes isolated between independent servers"""
    from pyfect.http import live_server
    from pyfect.http.router import HttpRouter

    health = layer.effect_discard(
        HttpRouter().flat_map(
            lambda service: service.add("GET", "/health", server_response.text("healthy"))
        )
    )
    # ``layer.merge`` of layers with no output infers Unknown.
    merge: Any = layer.merge
    public_app: fx.Layer[Any, Any, Any] = merge(
        router.add("GET", "/public", server_response.text("public")), health
    )
    internal_app: fx.Layer[Any, Any, Any] = merge(
        router.add("GET", "/internal", server_response.text("internal")), health
    )

    def status(at: int, path: str) -> fx.Effect[int]:
        request = f"GET {path} HTTP/1.1\r\nhost: x\r\nconnection: close\r\n\r\n".encode()
        return until_close(at, request).map(lambda data: parse_responses(data)[0].status)

    def served(app: fx.Layer[Any, Any, Any]) -> fx.Layer[Any, Any, Any]:
        return router.serve(app, disable_logger=True).pipe(
            layer.provide_merge(live_server.layer(host="127.0.0.1"))
        )

    @fx.fn
    def checks(public: int):
        internal = yield from port
        return [
            (yield from status(public, "/public")),
            (yield from status(internal, "/internal")),
            (yield from status(public, "/health")),
            (yield from status(internal, "/health")),
            (yield from status(public, "/internal")),
            (yield from status(internal, "/public")),
        ]

    program = port.flat_map(
        lambda public: checks(public).pipe(fx.provide(served(internal_app)))
    ).pipe(fx.provide(served(public_app)))
    assert fx.run_sync(program.or_die()) == [200, 200, 200, 200, 404, 404]


def _raw_requests(paths: list[str], method: str = "GET") -> bytes:
    """Effect's ``rawGet``: pipelined requests, the last one closing."""
    return b"".join(
        f"{method} {path} HTTP/1.1\r\nhost: 127.0.0.1\r\n{'connection: close\r\n' if index == len(paths) - 1 else ''}\r\n".encode()  # noqa: E501
        for index, path in enumerate(paths)
    )


@pytest.mark.parametrize(
    ("method", "status"),
    [("GET", 204), ("GET", 205), ("GET", 304), ("HEAD", 204), ("HEAD", 205)],
)
def test_sends_no_body_for_method_with_status(method: str, status: int) -> None:
    """sends no body for $method with status $status"""
    app = effect.succeed(server_response.text("x", status=status))

    @fx.fn
    def program():
        at = yield from _serve(app)
        return (yield from until_close(at, _raw_requests(["/"], method)))

    received = run_live(program()).decode("latin-1")
    assert re.match(rf"^HTTP/1.1 {status} ", received)
    assert received.endswith("\r\n\r\n")
    # 304 describes the representation, 204 and 205 have no content.
    if status == 304:
        assert re.search(r"\r\ncontent-length: 1\r\n", received, re.I)
    else:
        assert not re.search(r"\r\ncontent-length:", received, re.I)


class _Chunks:
    """An async iterable raw body that records whether it was closed
    (Node's ``Readable.destroyed``)."""

    def __init__(self, *chunks: bytes) -> None:
        self._chunks = list(chunks)
        self.closed = False

    def __aiter__(self) -> _Chunks:
        return self

    async def __anext__(self) -> bytes:
        if self.closed or not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)

    async def aclose(self) -> None:
        self.closed = True


def _mismatched(body: str) -> tuple[Callable[[], HttpServerResponse], int]:
    match body:
        case "bytes":
            return (lambda: server_response.text("hello").set_header("content-length", "3")), 3
        case "raw async iterable":
            return (lambda: server_response.raw(_Chunks(b"lorem ipsum"), content_length=3)), 3
        case "FormData":
            form = http_body.FormData().append("text", "hello")
            return (lambda: server_response.form_data(form, headers={"content-length": "3"})), 3
        case _:
            return (lambda: server_response.stream(stream.make(b"hello"), content_length=10)), 10


@pytest.mark.parametrize("body", ["bytes", "raw async iterable", "FormData", "Stream"])
def test_aborts_the_connection_when_a_body_doesnt_match_content_length(body: str) -> None:
    """aborts the connection when a $body body doesn't match content-length"""
    response, content_length = _mismatched(body)
    app = router.add_all(
        [
            router.route("GET", "/mismatch", effect.sync(response)),
            router.route("GET", "/next", server_response.text("next")),
        ]
    )

    @fx.fn
    def program():
        at = yield from port
        return (yield from until_close(at, _raw_requests(["/mismatch", "/next"])))

    received = run_live(_routed(app, program())).decode("latin-1")
    # The client must neither wait for the declared body nor read the next
    # response as part of it.
    head_end = received.find("\r\n\r\n")
    rest = "" if head_end == -1 else received[head_end + 4 :]
    assert len(rest) < content_length


@pytest.mark.parametrize(("method", "status"), [("GET", 103), ("GET", 600), ("HEAD", 600)])
def test_answers_a_response_with_an_invalid_status_with_a_500_and_closes_the_raw_body(
    method: str, status: int
) -> None:
    """when writeHead throws answers a $method response with status $status with a 500 and destroys the raw body"""  # noqa: E501
    chunks = _Chunks(b"ok")
    observed: list[Exit.Exit[Any, Any]] = []
    app = effect.succeed(server_response.raw(chunks, status=status))

    @fx.fn
    def program():
        yield from server.serve(
            app,
            lambda inner: inner.on_exit(lambda exit: effect.sync(lambda: observed.append(exit))),
        ).build()
        at = yield from port
        return (yield from until_close(at, _raw_requests(["/"], method)))

    [response] = parse_responses(run_live(program()), head=method == "HEAD")
    assert response.status == 500
    assert len(observed) == 1 and isinstance(observed[0], Exit.Failure)
    assert chunks.closed
