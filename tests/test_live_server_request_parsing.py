"""The live server reads exactly one message where a strict HTTP/1.1 parser
(Node's ``llhttp``) does, and never lets a client hold a connection
forever: requests sent as raw bytes over a loopback socket."""

from __future__ import annotations

import socket
import time
from typing import Any

import pytest
from oracle._live_http import TIMEOUT, parse_responses, port, run_live, until_close, with_socket

import pyfect as fx
from pyfect import effect
from pyfect.duration import Seconds
from pyfect.http import router, server_response
from pyfect.http.server_request import HttpServerRequest, ServerRequest


def _echo(request: ServerRequest) -> fx.Effect[Any]:
    return effect.succeed(server_response.text(f"{request.url} {request.headers.get('host')}"))


def _routes() -> fx.Layer[Any, Any, Any]:
    admin = effect.succeed(server_response.text("ADMIN"))
    return router.add("GET", "/admin", admin).pipe(
        fx.layer.provide_merge(router.add("*", "*", HttpServerRequest().flat_map(_echo)))
    )


def _send(data: bytes, **options: Any) -> list[Any]:
    def program() -> Any:
        at = yield from port
        return (yield from until_close(at, data))

    served = effect.gen(program).pipe(fx.provide(router.serve(_routes(), disable_logger=True)))
    return parse_responses(run_live(served, **options))


# --- Host and request-target (findings 2, 17) -------------------------------------


@pytest.mark.parametrize(
    "host", [b"x/admin?", b"x?role=admin&", b"x#frag", b"user@x", b"a, b", b"x:port"]
)
def test_a_host_that_is_not_an_authority_is_a_400(host: bytes) -> None:
    [response] = _send(b"GET /public HTTP/1.1\r\nHost: " + host + b"\r\nConnection: close\r\n\r\n")
    assert response.status == 400


@pytest.mark.parametrize("host", [b"example.test", b"example.test:8080", b"[::1]:80", b"10.0.0.1"])
def test_an_authority_host_is_served(host: bytes) -> None:
    [response] = _send(b"GET /public HTTP/1.1\r\nHost: " + host + b"\r\nConnection: close\r\n\r\n")
    assert (response.status, response.body) == (200, b"/public " + host)


@pytest.mark.parametrize(
    "target",
    [b"evil.com/admin", b"admin", b"ftp://evil.com/admin", b"http:///admin", b"http:/x/admin"],
)
def test_a_target_in_no_request_target_form_is_a_400(target: bytes) -> None:
    [response] = _send(b"GET " + target + b" HTTP/1.1\r\nHost: good\r\nConnection: close\r\n\r\n")
    assert response.status == 400


def test_an_absolute_target_sets_the_normalized_host() -> None:
    """As Effect's Node server: ``host`` becomes the target URL's ``host``."""
    [response] = _send(
        b"GET HTTP://Example.TEST:80/public?q HTTP/1.1\r\nHost: good\r\nConnection: close\r\n\r\n"
    )
    assert (response.status, response.body) == (200, b"/public?q example.test")


def test_an_absolute_target_with_userinfo_is_a_400() -> None:
    [response] = _send(
        b"GET http://u@evil/admin HTTP/1.1\r\nHost: good\r\nConnection: close\r\n\r\n"
    )
    assert response.status == 400


# --- Content-Length and Transfer-Encoding (finding 7) ----------------------------


@pytest.mark.parametrize(
    "header",
    [
        b"Content-Length: \xa05",
        b"Content-Length: 5\xa0",
        b"Content-Length: \x855",
        b"Content-Length: 5, \xa05",
        b"Transfer-Encoding: chunked\xa0",
        b"Transfer-Encoding: \x85chunked",
    ],
)
def test_framing_padded_with_non_ascii_whitespace_is_a_400(header: bytes) -> None:
    data = b"POST /x HTTP/1.1\r\nHost: a\r\n" + header + b"\r\n\r\nhelloGET /admin HTTP/1.1\r\n"
    [response] = _send(data + b"Host: a\r\nConnection: close\r\n\r\n")
    assert response.status == 400


@pytest.mark.parametrize("header", [b"Content-Length: \t5 ", b"Transfer-Encoding: \tchunked "])
def test_framing_padded_with_spaces_and_tabs_is_read(header: bytes) -> None:
    body = b"5\r\nhello\r\n0\r\n\r\n" if b"chunked" in header else b"hello"
    data = b"POST /x HTTP/1.1\r\nHost: a\r\nConnection: close\r\n" + header + b"\r\n\r\n" + body
    [response] = _send(data)
    assert (response.status, response.body) == (200, b"/x a")


# --- chunked trailers (finding 8) ------------------------------------------------


def _chunked(trailers: bytes) -> bytes:
    return (
        b"POST /x HTTP/1.1\r\nHost: a\r\nTransfer-Encoding: chunked\r\n\r\n"
        b"1\r\na\r\n0\r\n" + trailers + b"GET /admin HTTP/1.1\r\nHost: a\r\n"
        b"Connection: close\r\n\r\n"
    )


def _read_body(request: ServerRequest) -> fx.Effect[Any, Any]:
    return request.text.map(server_response.text)


@pytest.mark.parametrize(
    "trailers",
    [
        b"X: y\n\r\n",  # a bare LF inside a trailer line
        b"X: y\n\n\r\n",
        b"X: y\r\r\n\r\n",  # a bare CR
        b"no colon\r\n\r\n",
        b"bad name: y\r\n\r\n",
        b"X: \x00\r\n\r\n",
    ],
)
def test_a_malformed_trailer_line_fails_the_body_and_closes(trailers: bytes) -> None:
    def program() -> Any:
        at = yield from port
        return (yield from until_close(at, _chunked(trailers)))

    app = router.add("POST", "/x", HttpServerRequest().flat_map(_read_body))
    served = effect.gen(program).pipe(fx.provide(router.serve(app, disable_logger=True)))
    responses = parse_responses(run_live(served))
    assert [r.status for r in responses] == [400]


def test_well_formed_trailers_end_the_body() -> None:
    def program() -> Any:
        at = yield from port
        return (yield from until_close(at, _chunked(b"X-Sum: 1\r\nY:\r\n\r\n")))

    app = router.add("POST", "/x", HttpServerRequest().flat_map(_read_body)).pipe(
        fx.layer.provide_merge(
            router.add("GET", "/admin", effect.succeed(server_response.text("A")))
        )
    )
    served = effect.gen(program).pipe(fx.provide(router.serve(app, disable_logger=True)))
    responses = parse_responses(run_live(served))
    assert [(r.status, r.body) for r in responses] == [(200, b"a"), (200, b"A")]


# --- request timeout (finding 13) ------------------------------------------------


def _held(head: bytes, **options: Any) -> float:
    """Seconds until the server closes a connection that sent ``head`` and
    then nothing (the app answers without reading the body)."""

    def use(conn: socket.socket) -> float:
        started = time.monotonic()
        conn.sendall(head)
        while conn.recv(65536):
            pass
        return time.monotonic() - started

    def program() -> Any:
        at = yield from port
        return (yield from with_socket(at, use))

    app = router.add("*", "*", effect.succeed(server_response.empty(status=404)))
    served = effect.gen(program).pipe(fx.provide(router.serve(app, disable_logger=True)))
    return run_live(served, **options)


@pytest.mark.parametrize("framing", [b"Content-Length: 1\r\n", b"Transfer-Encoding: chunked\r\n"])
def test_a_body_that_never_arrives_is_cut_off_at_the_request_timeout(framing: bytes) -> None:
    head = b"POST /x HTTP/1.1\r\nHost: a\r\n" + framing + b"\r\n"
    elapsed = _held(head, request_timeout="300 millis", keep_alive_timeout=Seconds(TIMEOUT))
    assert 0.2 < elapsed < TIMEOUT / 2


def test_a_body_read_by_the_app_is_cut_off_at_the_request_timeout() -> None:
    def use(conn: socket.socket) -> tuple[bytes, float]:
        started = time.monotonic()
        conn.sendall(b"POST /x HTTP/1.1\r\nHost: a\r\nContent-Length: 10\r\n\r\nab")
        received = bytearray()
        while chunk := conn.recv(65536):
            received += chunk
        return bytes(received), time.monotonic() - started

    def program() -> Any:
        at = yield from port
        return (yield from with_socket(at, use))

    app = router.add("POST", "/x", HttpServerRequest().flat_map(_read_body))
    served = effect.gen(program).pipe(fx.provide(router.serve(app, disable_logger=True)))
    received, elapsed = run_live(served, request_timeout="300 millis")
    assert 0.2 < elapsed < TIMEOUT / 2
    assert [r.status for r in parse_responses(received)] in ([], [400], [408])


def test_a_connection_token_padded_with_non_ascii_whitespace_is_no_token() -> None:
    """HTTP/1.0 keeps a connection open only for a ``keep-alive`` token;
    ``keep-alive`` and an NBSP is none, so a second request is not read."""
    first = b"GET /a HTTP/1.0\r\nConnection: keep-alive\xa0\r\n\r\n"
    second = b"GET /admin HTTP/1.1\r\nHost: a\r\nConnection: close\r\n\r\n"
    assert [r.body for r in _send(first + second)] == [b"/a None"]


def test_an_expectation_padded_with_non_ascii_whitespace_is_a_417() -> None:
    data = b"POST /x HTTP/1.1\r\nHost: a\r\nContent-Length: 0\r\nExpect: 100-continue\xa0\r\n"
    [response] = _send(data + b"Connection: close\r\n\r\n")
    assert response.status == 417


def test_the_live_server_never_trims_unicode_whitespace() -> None:
    """A no-argument ``strip``/``split`` takes NBSP, NEL and the like as
    whitespace, which no HTTP parser in front of the server does."""
    import ast
    from pathlib import Path

    import pyfect.http.live_server as live

    offenders = [
        f"{path.name}:{node.lineno}"
        for path in sorted(Path(live.__file__).parent.glob("*.py"))
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in ("strip", "lstrip", "rstrip", "split", "isspace")
        and not node.args
    ]
    assert offenders == []


@pytest.mark.parametrize("extension", [b";a\rb", b";a\x00", b";\x7f"])
def test_a_chunk_extension_with_a_control_character_fails_the_body(extension: bytes) -> None:
    data = (
        b"POST /x HTTP/1.1\r\nHost: a\r\nTransfer-Encoding: chunked\r\n\r\n"
        b"1" + extension + b"\r\na\r\n0\r\n\r\nGET /admin HTTP/1.1\r\nHost: a\r\n"
        b"Connection: close\r\n\r\n"
    )

    def program() -> Any:
        at = yield from port
        return (yield from until_close(at, data))

    app = router.add("POST", "/x", HttpServerRequest().flat_map(_read_body))
    served = effect.gen(program).pipe(fx.provide(router.serve(app, disable_logger=True)))
    assert [r.status for r in parse_responses(run_live(served))] == [400]


def _chunked_status(size_line: bytes) -> list[tuple[int, bytes]]:
    data = (
        b"POST /x HTTP/1.1\r\nHost: a\r\nTransfer-Encoding: chunked\r\nConnection: close\r\n\r\n"
        + size_line
        + b"\r\na\r\n0\r\n\r\n"
    )

    def program() -> Any:
        at = yield from port
        return (yield from until_close(at, data))

    app = router.add("POST", "/x", HttpServerRequest().flat_map(_read_body))
    served = effect.gen(program).pipe(fx.provide(router.serve(app, disable_logger=True)))
    return [(r.status, r.body) for r in parse_responses(run_live(served))]


# Node 24's llhttp on each size line (ahttp_live_chunk_extensions): RFC 9112's chunk-ext with
# no whitespace, a token name, and an optional token (possibly empty) or quoted-string value.
_NODE_ACCEPTS = [
    b"1",
    b"1;a",
    b"1;a=b",
    b'1;a="b c"',
    b'1;a="b\\"c"',
    b"1;a;b=c",
    b"1;a=",
    b"1;a=;b",
    b'1;a=""',
    b'1;a="x\ty"',
    b'1;a="\x80"',
    b'1;a="b\\\x80"',
    b'1;a="b\\\t"',
    b"1;a!#$%&'*+-.^_`|~=b",
    b'1;a="b";c',
    b"1;a=b;c=d;e",
    b"01",
    b"00000000000000000000000000001",
]
_NODE_REFUSES = [
    b"1;a b",
    b'1;a="open',
    b"1;a=b=c",
    b"1;;",
    b"1 ",
    b"1;",
    b"1\t",
    b"1 ;a",
    b"1; a",
    b"1;a =b",
    b"1;a= b",
    b"1;a=b ",
    b"1;a=b;",
    b'1;a="b"c',
    b'1;a="b" ',
    b'1;a="b\\"',
    b'1;a="\x7f"',
    b'1;a="\x01"',
    b'1;a="b\\\x01"',
    b'1;a="x\\\x7fy"',
    b"1;a=b\x7f",
    b"1;\x80a",
    b"1;a=\x80",
    b"1;a=,",
    b"1;a\t=b",
    b"10000000000000000",
]


@pytest.mark.parametrize("size_line", _NODE_ACCEPTS)
def test_a_chunk_size_line_node_accepts_is_read(size_line: bytes) -> None:
    assert _chunked_status(size_line) == [(200, b"a")]


@pytest.mark.parametrize("size_line", _NODE_REFUSES)
def test_a_chunk_size_line_node_refuses_is_a_400(size_line: bytes) -> None:
    assert [status for status, _ in _chunked_status(size_line)] == [400]
