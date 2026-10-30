"""``decompression()`` bounds what a compressed request body costs: the
decoded body and every stacked coding's output stay within the limit, and
no single read inflates more than a bounded piece."""

from __future__ import annotations

import asyncio
import tracemalloc
import zlib
from typing import Any

from pyfect import layer
from pyfect.http import server, server_response
from pyfect.http.incoming_message import MaxBodySize
from pyfect.http.middleware import decompression
from pyfect.http.server_request import HttpServerRequest, ServerRequest
from pyfect.http.web import WebRequest
from pyfect.http.web_handler import to_web_handler_layer

_MIB = 1024 * 1024


def _gzip_of_zeros(size: int) -> bytes:
    compressor = zlib.compressobj(wbits=31)
    block = bytes(_MIB)
    return b"".join(compressor.compress(block) for _ in range(size // _MIB)) + compressor.flush()


def _gzip(data: bytes) -> bytes:
    compressor = zlib.compressobj(wbits=31)
    return compressor.compress(data) + compressor.flush()


def _length(request: ServerRequest) -> Any:
    return request.bytes_.map(lambda body: server_response.text(str(len(body))))


def _post(body: bytes, encoding: str, limit: int = _MIB) -> tuple[int, bytes, int]:
    """The status and body of the answer, and the peak traced allocation."""
    app = HttpServerRequest().flat_map(_length)
    services = layer.merge(server.layer_services, layer.succeed(MaxBodySize, None))
    middleware = decompression(max_decompressed_size=limit)

    async def main() -> tuple[int, bytes]:
        handler = to_web_handler_layer(app, services, middleware).handler
        request = WebRequest(
            "http://localhost/", method="POST", body=body, headers={"content-encoding": encoding}
        )
        response = await handler(request)
        return response.status, await response.read()

    tracemalloc.start()
    try:
        status, text = asyncio.run(main())
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return status, text, peak


def test_a_gzip_bomb_fails_without_inflating_past_the_limit() -> None:
    bomb = _gzip_of_zeros(64 * _MIB)
    assert len(bomb) < 128 * 1024
    status, _body, peak = _post(bomb, "gzip")
    assert status == 413
    assert peak < 8 * _MIB


def test_a_stacked_gzip_bomb_fails_without_inflating_past_the_limit() -> None:
    bomb = _gzip(_gzip_of_zeros(64 * _MIB))
    assert len(bomb) < 4096
    status, _body, peak = _post(bomb, "gzip, gzip")
    assert status == 413
    assert peak < 8 * _MIB


def test_an_inner_coding_that_inflates_past_the_limit_fails() -> None:
    """The outer coding inflates 3 KB into 2 MB of empty deflate blocks:
    the decoded body is empty, but the work in between is still bounded."""
    empty_blocks = b"\x78\x9c" + b"\x00\x00\x00\xff\xff" * 400_000 + b"\x03\x00\x00\x00\x00\x01"
    assert zlib.decompress(empty_blocks) == b""
    status, _body, _peak = _post(_gzip(empty_blocks), "deflate, gzip")
    assert status == 413


def test_more_than_two_stacked_codings_are_unsupported() -> None:
    body = _gzip(_gzip(_gzip(b"hello")))
    assert _post(body, "gzip, gzip, gzip")[0] == 415
    assert _post(_gzip(_gzip(b"hello")), "gzip, gzip")[:2] == (200, b"5")


def test_a_body_at_the_limit_decodes_in_bounded_pieces() -> None:
    status, body, _peak = _post(_gzip_of_zeros(4 * _MIB), "gzip", limit=4 * _MIB)
    assert (status, body) == (200, str(4 * _MIB).encode())


def test_every_decompress_call_in_pyfect_is_bounded() -> None:
    """A guard: a ``decompress(data)`` without ``max_length`` inflates a
    whole chunk at once, so every call in the source passes one."""
    import ast
    from pathlib import Path

    import pyfect

    unbounded = [
        f"{path.name}:{node.lineno}"
        for path in Path(pyfect.__path__[0]).rglob("*.py")
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "decompress"
        and len(node.args) + len(node.keywords) < 2
    ]
    assert unbounded == []


def test_a_zero_limit_admits_no_decompressed_byte() -> None:
    assert _post(_gzip(b"x"), "gzip", limit=0)[0] == 413
    assert _post(_gzip(b""), "gzip", limit=0)[:2] == (200, b"0")
