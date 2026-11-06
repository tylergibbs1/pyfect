"""Ports of platform-node's ``NodeHttpCompression.test.ts`` against
``http.platform.layer_live`` (Web handlers) and the live server. Each
test's docstring is the Effect test title.

The live platform offers gzip, deflate, zstd on Python 3.14 and brotli with the ``brotli``
extra, which the dev environment installs.
"""

from __future__ import annotations

import asyncio
import threading
import zlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import brotli as _brotli  # pyright: ignore[reportMissingTypeStubs]
import pytest

import pyfect as fx
from pyfect import effect, stream
from pyfect.http import live_server, router, server_response
from pyfect.http._brotli import Brotli
from pyfect.http.client import HttpClient
from pyfect.http.file_like import BytesFile
from pyfect.http.middleware import compression
from pyfect.http.platform import HttpPlatform
from pyfect.http.platform import _zstd_available as zstd_available  # pyright: ignore[reportPrivateUsage]
from pyfect.http.server_response import HttpServerResponse
from pyfect.http.web import WebRequest, WebResponse
from pyfect.http.web_handler import to_web_handler_layer
from pyfect.latch import Latch

from ._live_http import run_live

BIG_JSON = '{"text":"' + "All work and no play makes Jack a dull boy. " * 100 + '"}'
BIG_JSON_BYTES = BIG_JSON.encode()
ZSTD = zstd_available()


_library: Any = _brotli


def _unbrotli(data: bytes) -> bytes:
    return _library.decompress(data)


def _big_json_app() -> fx.Effect[HttpServerResponse]:
    return effect.succeed(server_response.text(BIG_JSON, content_type="application/json"))


def _get(
    app: fx.Effect[HttpServerResponse, Any, Any],
    options: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    method: str = "GET",
) -> tuple[WebResponse, bytes]:
    async def main() -> tuple[WebResponse, bytes]:
        made = to_web_handler_layer(app, live_server.layer_services, compression(**(options or {})))
        try:
            response = await made.handler(
                WebRequest("http://localhost/", method=method, headers=headers)
            )
            return response, await response.read()
        finally:
            await made.dispose()

    return asyncio.run(main())


def _gunzip(data: bytes) -> str:
    return zlib.decompress(data, 31).decode()


_RESPONSES: list[tuple[str, Callable[[], HttpServerResponse]]] = [
    ("Stream", lambda: server_response.stream(stream.succeed(BIG_JSON_BYTES))),
    ("Uint8Array", lambda: server_response.bytes_(BIG_JSON_BYTES)),
]


@pytest.mark.parametrize(("name", "make_response"), _RESPONSES, ids=[n for n, _ in _RESPONSES])
def test_preserves_a_content_type_header_override_when_compressing_responses(
    name: str, make_response: Callable[[], HttpServerResponse]
) -> None:
    """preserves a Content-Type header override when compressing ${name} responses"""
    original = make_response().set_header("content-type", "application/json")
    assert original.headers["content-type"] == "application/json"
    response, body = _get(effect.succeed(original), headers={"accept-encoding": "gzip"})
    assert response.get("content-encoding") == "gzip"
    assert _gunzip(body) == BIG_JSON
    assert response.get("content-type") == original.headers["content-type"]


def test_advertises_supported_algorithms() -> None:
    """advertises supported algorithms"""
    from pyfect.http.platform import layer_live

    algorithms = fx.run_blocking(
        HttpPlatform().map(lambda p: p.compression.algorithms).pipe(fx.provide(layer_live))
    )
    assert "gzip" in algorithms
    assert "deflate" in algorithms
    assert "br" in algorithms
    assert ("zstd" in algorithms) == ZSTD


def test_compresses_one_shot_bodies_asynchronously_with_gzip_and_an_exact_content_length() -> None:
    """compresses one-shot bodies asynchronously with gzip and an exact Content-Length"""
    response, body = _get(_big_json_app(), headers={"accept-encoding": "gzip"})
    assert response.get("content-encoding") == "gzip"
    assert response.get("vary") == "Accept-Encoding"
    assert response.get("content-length") == str(len(body))
    assert _gunzip(body) == BIG_JSON


def test_prefers_br_over_gzip_in_server_order() -> None:
    """prefers br over gzip in server order"""
    response, body = _get(_big_json_app(), headers={"accept-encoding": "gzip, br"})
    assert response.get("content-encoding") == "br"
    assert response.get("content-length") == str(len(body))
    assert _unbrotli(body).decode() == BIG_JSON


def test_a_stream_compressed_with_brotli_is_flushed_chunk_by_chunk() -> None:
    chunks = stream.from_iterable([BIG_JSON_BYTES, BIG_JSON_BYTES])
    app = server_response.stream(chunks, content_type="application/json")
    response, body = _get(effect.succeed(app), headers={"accept-encoding": "br"})
    assert response.get("content-encoding") == "br"
    assert _unbrotli(body) == BIG_JSON_BYTES * 2


def test_a_compressed_stream_leaves_the_servers_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """As ``node:zlib``'s transforms do: brotli's default quality takes seconds per megabyte."""
    threads: list[threading.Thread] = []
    chunk, finish = Brotli.chunk, Brotli.finish

    def on_chunk(self: Brotli, data: bytes) -> bytes:
        threads.append(threading.current_thread())
        return chunk(self, data)

    def on_finish(self: Brotli) -> bytes:
        threads.append(threading.current_thread())
        return finish(self)

    monkeypatch.setattr(Brotli, "chunk", on_chunk)
    monkeypatch.setattr(Brotli, "finish", on_finish)
    app = server_response.stream(
        stream.from_iterable([BIG_JSON_BYTES]), content_type="application/json"
    )
    _, body = _get(effect.succeed(app), headers={"accept-encoding": "br"})
    assert _unbrotli(body) == BIG_JSON_BYTES
    assert len(threads) == 2
    assert threading.main_thread() not in threads


def test_preserves_the_content_type_of_file_responses_when_compressed_with_brotli(
    tmp_path: Path,
) -> None:
    """preserves the Content-Type of file responses when compressed with Brotli"""
    path = tmp_path / "index.html"
    contents = f"<!doctype html><html><body>{'<p>Hello world</p>' * 100}</body></html>"
    path.write_text(contents)
    app = server_response.file(str(path))

    uncompressed, plain = _get(app, headers={"accept-encoding": "identity"})
    assert uncompressed.status == 200
    assert uncompressed.get("content-encoding") is None
    assert uncompressed.get("content-type") == "text/html"
    assert plain.decode() == contents

    compressed, body = _get(app, headers={"accept-encoding": "br"})
    assert compressed.status == 200
    assert compressed.get("content-encoding") == "br"
    assert _unbrotli(body).decode() == contents
    assert compressed.get("content-type") == uncompressed.get("content-type")


def test_compresses_with_deflate() -> None:
    """compresses with deflate"""
    response, body = _get(_big_json_app(), headers={"accept-encoding": "deflate"})
    assert response.get("content-encoding") == "deflate"
    assert response.get("content-length") == str(len(body))
    assert zlib.decompress(body).decode() == BIG_JSON


@pytest.mark.skipif(not ZSTD, reason="compression.zstd needs Python 3.14")
def test_compresses_with_zstd_when_opted_in() -> None:
    """compresses with zstd when opted in"""
    from compression import zstd  # pyright: ignore[reportMissingTypeStubs]

    response, body = _get(
        _big_json_app(), {"algorithms": ["zstd", "gzip"]}, {"accept-encoding": "zstd"}
    )
    assert response.get("content-encoding") == "zstd"
    assert response.get("content-length") == str(len(body))
    assert zstd.decompress(body).decode() == BIG_JSON  # pyright: ignore[reportUnknownMemberType]


def test_excludes_zstd_unless_opted_in() -> None:
    """excludes zstd unless opted in"""
    response, _ = _get(_big_json_app(), headers={"accept-encoding": "zstd, gzip"})
    assert response.get("content-encoding") == "gzip"


def test_compresses_stream_bodies_without_a_content_length() -> None:
    """compresses stream bodies without a Content-Length"""
    app = effect.succeed(
        server_response.stream(
            stream.from_iterable([BIG_JSON_BYTES]), content_type="application/json"
        )
    )
    response, body = _get(app, headers={"accept-encoding": "gzip"})
    assert response.get("content-encoding") == "gzip"
    assert response.get("content-length") is None
    assert _gunzip(body) == BIG_JSON


def test_compresses_file_responses_through_the_streaming_path_and_weakens_the_etag() -> None:
    """compresses file responses through the streaming path and weakens the ETag"""
    path = Path(__file__)
    app = server_response.file(str(path), headers={"content-type": "text/plain"})
    response, body = _get(app, headers={"accept-encoding": "gzip"})
    assert response.get("content-encoding") == "gzip"
    assert response.get("content-length") is None
    etag = response.get("etag")
    assert etag is not None
    assert etag.startswith("W/")
    assert _gunzip(body) == path.read_text()


def test_does_not_acquire_file_bodies_for_compressed_head_requests() -> None:
    """does not acquire file bodies for compressed HEAD requests"""
    acquired: list[int] = []

    class CountingFile(BytesFile):
        def stream(self) -> stream.Stream[bytes, object]:
            acquired.append(1)
            return super().stream()

    app = server_response.file_web(CountingFile(b"abc", "test.txt"))
    response, body = _get(app, {"min_size": 0}, {"accept-encoding": "gzip"}, method="HEAD")
    assert response.status == 200
    assert body == b""
    assert acquired == []


def test_flushes_compressed_chunks_incrementally_over_the_wire() -> None:
    """flushes compressed chunks incrementally over the wire"""
    latch = Latch(False)
    body = stream.succeed(b"data: first\n\n").concat(
        stream.from_effect(latch.wait()).drain().concat(stream.succeed(b"data: second\n\n"))
    )
    app = router.add(
        "GET",
        "/sse",
        effect.succeed(server_response.stream(body, content_type="text/event-stream")),
    )

    @fx.fn
    def program():
        client = yield from HttpClient()
        response = yield from client.get("/sse", headers={"accept-encoding": "gzip"})
        encoding = response.headers.get("content-encoding")
        received: list[bytes] = []

        def took(chunk: bytes) -> fx.Effect[None]:
            received.append(chunk)
            return latch.open().as_void()

        # The source ends only after the latch opens, which happens once the
        # first decoded event arrives: this deadlocks unless compressed
        # chunks are flushed as they are made.
        yield from response.stream.run_for_each(took).timeout(5)
        return encoding, b"".join(received)

    served = program().pipe(
        fx.provide(router.serve(app, middleware=compression(), disable_logger=True))
    )
    assert run_live(served) == ("gzip", b"data: first\n\ndata: second\n\n")
