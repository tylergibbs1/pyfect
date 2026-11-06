"""Ports of Effect's ``http/HttpDecompression.test.ts``.

Each test's docstring is the Effect test title. Web handlers are
``web_handler`` asyncio handlers; request bodies are compressed with
``zlib``. ``decompresses bodies for routes under a prefixed router`` is in
``test_http_router.py``, next to the router it needs.
"""

import asyncio
import zlib
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest

import pyfect as fx
from pyfect import effect, layer
from pyfect.byte_size import ByteSize
from pyfect.http import server, server_response
from pyfect.http.incoming_message import MaxBodySize
from pyfect.http.middleware import decompression
from pyfect.http.request import post as client_post
from pyfect.http.server_request import HttpServerRequest, ServerRequest, from_client_request
from pyfect.http.server_response import HttpServerResponse
from pyfect.http.web import WebRequest, WebResponse
from pyfect.http.web_handler import WebHandler, request_to_web, to_web_handler_layer
from pyfect.result import Ok

BIG_JSON = '{"text":"' + "All work and no play makes Jack a dull boy. " * 100 + '"}'
_WBITS = {"gzip": 31, "deflate": 15}


def _compress(data: str | bytes, formats: tuple[str, ...]) -> bytes:
    out = data.encode() if isinstance(data, str) else data
    for name in formats:
        compressor = zlib.compressobj(wbits=_WBITS[name])
        out = compressor.compress(out) + compressor.flush()
    return out


def _read(accessor: str, request: ServerRequest) -> fx.Effect[str, Any]:
    match accessor:
        case "json":
            import json

            return request.json.map(lambda value: json.dumps(value, separators=(",", ":")))
        case "text":
            return request.text
        case "arrayBuffer":
            return request.bytes_.map(bytes.decode)
        case _:
            return request.stream.run_collect().map(lambda chunks: b"".join(chunks).decode())


def _echo(accessor: str) -> Callable[[ServerRequest], fx.Effect[HttpServerResponse, Any]]:
    """The body read through ``accessor``, with the encoding headers the
    app sees."""

    def respond(request: ServerRequest) -> fx.Effect[HttpServerResponse, Any]:
        headers = {
            "x-content-encoding": request.headers.get("content-encoding", ""),
            "x-content-length": request.headers.get("content-length", ""),
        }
        return _read(accessor, request).map(
            lambda body: server_response.text(body, headers=headers)
        )

    return respond


def _echo_app(accessor: str) -> fx.Effect[HttpServerResponse, Any, Any]:
    return HttpServerRequest().flat_map(_echo(accessor))


def _handler(
    app: fx.Effect[HttpServerResponse, Any, Any],
    options: dict[str, Any] | None = None,
    max_body_size: ByteSize | None = None,
) -> WebHandler:
    services = layer.merge(server.layer_services, layer.succeed(MaxBodySize, max_body_size))
    return to_web_handler_layer(app, services, decompression(**(options or {}))).handler


def _post(
    make: Callable[[], WebHandler],
    body: bytes | str,
    headers: dict[str, str] | None = None,
) -> tuple[WebResponse, bytes]:
    async def main() -> tuple[WebResponse, bytes]:
        request = WebRequest("http://localhost/", method="POST", body=body, headers=headers)
        response = await make()(request)
        return response, await response.read()

    return asyncio.run(main())


def test_keeps_headers_only_to_web_lazy() -> None:
    """keeps headers-only toWeb lazy"""
    payload = "compressed payload"
    body = _compress(payload, ("gzip",))
    request = from_client_request(
        client_post("http://localhost/")
        .set_header("content-encoding", "gzip")
        .set_header("x-test", "headers-only")
        .body_stream(fx.stream.succeed(body))
    )

    @fx.fn
    def app():
        decompressed = yield from HttpServerRequest()
        web = request_to_web(decompressed)
        assert isinstance(web, Ok)
        assert web.value.get("x-test") == "headers-only"
        yield from effect.yield_now()
        assert (yield from decompressed.text) == payload
        return server_response.empty()

    program = decompression()(app()).pipe(effect.provide_service(HttpServerRequest, request))
    fx.run_blocking(program.or_die())


@pytest.mark.parametrize("accessor", ["json", "text", "arrayBuffer", "stream"])
def test_decompresses_a_gzip_body_and_hides_the_encoding_headers(accessor: str) -> None:
    """decompresses a gzip body read via ${accessor} and hides the encoding headers"""
    response, body = _post(
        lambda: _handler(_echo_app(accessor)),
        _compress(BIG_JSON, ("gzip",)),
        {"content-type": "application/json", "content-encoding": "gzip"},
    )
    assert response.status == 200
    assert body.decode() == BIG_JSON
    assert response.get("x-content-encoding") == ""
    assert response.get("x-content-length") == ""


@pytest.mark.parametrize("formats", [("deflate",), ("deflate", "gzip")])
def test_decodes_content_encoding(formats: tuple[str, ...]) -> None:
    """decodes Content-Encoding: ${formats}"""
    response, body = _post(
        lambda: _handler(_echo_app("text")),
        _compress(BIG_JSON, formats),
        {"content-encoding": ", ".join(formats)},
    )
    assert response.status == 200
    assert body.decode() == BIG_JSON


def test_passes_through_bodies_without_a_coding_or_with_identity() -> None:
    """passes through bodies without a coding or with identity"""
    plain, plain_body = _post(lambda: _handler(_echo_app("text")), BIG_JSON)
    assert plain.status == 200
    assert plain_body.decode() == BIG_JSON
    identity, identity_body = _post(
        lambda: _handler(_echo_app("text")), BIG_JSON, {"content-encoding": "identity"}
    )
    assert identity.status == 200
    assert identity_body.decode() == BIG_JSON


def test_rejects_unsupported_codings_with_415_before_running_the_app() -> None:
    """rejects unsupported codings with 415 before running the app"""
    ran: list[bool] = []
    app = effect.sync(lambda: (ran.append(True), server_response.empty())[1])
    response, _ = _post(lambda: _handler(app), BIG_JSON, {"content-encoding": "br"})
    assert response.status == 415
    assert response.get("accept-encoding") == "gzip, deflate"
    assert ran == []


def test_fails_corrupt_gzip_bodies_with_400() -> None:
    """fails corrupt gzip bodies with 400"""
    response, _ = _post(
        lambda: _handler(_echo_app("text")), "not gzip", {"content-encoding": "gzip"}
    )
    assert response.status == 400


@pytest.mark.parametrize("accessor", ["text", "stream"])
def test_enforces_max_decompressed_size(accessor: str) -> None:
    """enforces maxDecompressedSize when reading via ${accessor}"""
    body = _compress(BIG_JSON, ("gzip",))
    # The limit applies to the inflated size, not the size on the wire.
    assert len(body) < 1024
    response, _ = _post(
        lambda: _handler(_echo_app(accessor), {"max_decompressed_size": 1024}),
        body,
        {"content-encoding": "gzip"},
    )
    assert response.status == 413


def test_falls_back_to_the_max_body_size_reference() -> None:
    """falls back to the MaxBodySize reference"""
    response, _ = _post(
        lambda: _handler(_echo_app("text"), None, ByteSize(1024)),
        _compress(BIG_JSON, ("gzip",)),
        {"content-encoding": "gzip"},
    )
    assert response.status == 413


def test_maps_multipart_decompression_failures_to_client_errors() -> None:
    """maps multipart decompression failures to client errors"""
    boundary = "----pyfectboundary"
    form = (
        f'--{boundary}\r\nContent-Disposition: form-data; name="text"\r\n\r\n'
        f"{BIG_JSON}\r\n--{boundary}--\r\n"
    ).encode()
    headers = {
        "content-type": f"multipart/form-data; boundary={boundary}",
        "content-encoding": "gzip",
    }
    app = HttpServerRequest().flat_map(
        lambda request: request.multipart_stream.run_drain().as_(server_response.empty())
    )

    def make() -> WebHandler:
        return _handler(app, {"max_decompressed_size": 1024})

    corrupt, _ = _post(make, "not gzip", headers)
    assert corrupt.status == 400
    too_large, _ = _post(make, _compress(form, ("gzip",)), headers)
    assert too_large.status == 413


def test_cancels_the_request_body_when_a_stream_read_stops_early() -> None:
    """cancels the request body when a stream read stops early"""
    compressed = _compress(BIG_JSON, ("gzip",))

    async def main() -> tuple[int, bool]:
        cancelled = asyncio.Event()

        async def body() -> AsyncIterator[bytes]:
            try:
                yield compressed
                await asyncio.Event().wait()  # never closes
            finally:
                cancelled.set()

        app = HttpServerRequest().flat_map(
            lambda request: request.stream.run_head().as_(server_response.empty())
        )
        handler = _handler(app)
        request = WebRequest(
            "http://localhost/",
            method="POST",
            body=body(),
            headers={"content-encoding": "gzip"},
        )
        response = await handler(request)
        await asyncio.wait_for(cancelled.wait(), 5)
        return response.status, cancelled.is_set()

    assert asyncio.run(main()) == (204, True)
