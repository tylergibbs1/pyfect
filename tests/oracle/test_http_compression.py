"""Ports of Effect's ``http/HttpCompression.test.ts``.

Each test's docstring is the Effect test title. A Web handler is a
``web_handler`` asyncio handler; a Web ``ReadableStream`` raw body is an
async iterable of bytes, and ``new Response(null)`` a ``WebResponse()``.
"""

import asyncio
import zlib
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest

from pyfect import effect, stream
from pyfect.context import Context
from pyfect.http import server, server_response
from pyfect.http.cookies import from_set_cookie
from pyfect.http.middleware import compression
from pyfect.http.platform import (
    Compression,
    CompressionAlgorithm,
    HttpPlatform,
    HttpPlatformService,
)
from pyfect.http.server_response import HttpServerResponse
from pyfect.http.web import WebRequest, WebResponse
from pyfect.http.web_handler import WebHandler, to_web_handler_layer, to_web_handler_with
from pyfect.latch import Latch

BIG_TEXT = "All work and no play makes Jack a dull boy. " * 100
BIG_JSON = '{"text":"' + BIG_TEXT + '"}'
BIG_JSON_BYTES = BIG_JSON.encode()

_WBITS = {"gzip": 31, "deflate": 15}


def _big_json_app() -> effect.Effect[HttpServerResponse]:
    return effect.succeed(server_response.text(BIG_JSON, content_type="application/json"))


def _decompress(data: bytes, algorithm: str) -> str:
    return zlib.decompress(data, _WBITS[algorithm]).decode()


def _platform_context(compressor: Compression) -> Context[HttpPlatform]:
    return Context.make(
        HttpPlatform,
        HttpPlatformService(
            "web",
            compressor,
            lambda *_a, **_k: effect.die(RuntimeError("not implemented")),
            lambda *_a, **_k: effect.die(RuntimeError("not implemented")),
        ),
    )


def _negotiation_context(algorithms: tuple[CompressionAlgorithm, ...]) -> Context[HttpPlatform]:
    """A platform that only marks the algorithm it was asked for."""
    return _platform_context(
        Compression(
            frozenset(algorithms),
            lambda response, algorithm, _level: effect.succeed(
                response.set_header("content-encoding", algorithm)
            ),
        )
    )


def _handler(
    app: effect.Effect[HttpServerResponse, Any, Any],
    options: dict[str, Any] | None = None,
    context: Context[Any] | None = None,
) -> WebHandler:
    middleware = compression(**(options or {}))
    if context is not None:
        return to_web_handler_with(context)(app, middleware)
    return to_web_handler_layer(app, server.layer_services, middleware).handler


def _get(
    make: Callable[[], WebHandler],
    headers: dict[str, str] | None = None,
    method: str = "GET",
) -> tuple[WebResponse, bytes]:
    async def main() -> tuple[WebResponse, bytes]:
        response = await make()(WebRequest("http://localhost/", method=method, headers=headers))
        return response, await response.read()

    return asyncio.run(main())


async def _chunks(data: bytes) -> AsyncIterator[bytes]:
    yield data


def _random_bytes(length: int) -> bytes:
    data = bytearray(length)
    state = 0x9E3779B9
    for i in range(length):
        state ^= (state << 13) & 0xFFFFFFFF
        state ^= state >> 17
        state ^= (state << 5) & 0xFFFFFFFF
        data[i] = state & 0xFF
    return bytes(data)


_RESPONSES: list[tuple[str, Callable[[], HttpServerResponse]]] = [
    ("Stream", lambda: server_response.stream(stream.succeed(BIG_JSON_BYTES))),
    ("Uint8Array", lambda: server_response.bytes_(BIG_JSON_BYTES)),
    ("Raw", lambda: server_response.raw(_chunks(BIG_JSON_BYTES), content_type="text/plain")),
]


@pytest.mark.parametrize(("name", "make_response"), _RESPONSES, ids=[n for n, _ in _RESPONSES])
def test_preserves_a_content_type_header_override_when_compressing_web_responses(
    name: str, make_response: Callable[[], HttpServerResponse]
) -> None:
    """preserves a Content-Type header override when compressing web ${name} responses"""
    del name
    original = make_response().set_header("content-type", "application/json")
    assert original.headers["content-type"] == "application/json"
    response, body = _get(lambda: _handler(effect.succeed(original)), {"accept-encoding": "gzip"})
    assert response.get("content-encoding") == "gzip"
    assert _decompress(body, "gzip") == BIG_JSON
    assert response.get("content-type") == "application/json"


def test_preserves_a_header_only_content_type_when_compressing_web_raw_responses() -> None:
    """preserves a header-only Content-Type when compressing web Raw responses"""

    def app() -> effect.Effect[HttpServerResponse]:
        return effect.sync(
            lambda: server_response.raw(
                _chunks(BIG_JSON_BYTES), headers={"content-type": "application/json"}
            )
        )

    plain, plain_body = _get(lambda: _handler(app()), {"accept-encoding": "identity"})
    assert plain.get("content-type") == "application/json"
    assert plain_body.decode() == BIG_JSON
    compressed, body = _get(lambda: _handler(app()), {"accept-encoding": "gzip"})
    assert compressed.get("content-encoding") == "gzip"
    assert _decompress(body, "gzip") == BIG_JSON
    assert compressed.get("content-type") == plain.get("content-type")


def test_compresses_a_compressible_response_with_gzip() -> None:
    """compresses a compressible response with gzip"""
    response, body = _get(lambda: _handler(_big_json_app()), {"accept-encoding": "gzip"})
    assert response.status == 200
    assert response.get("content-encoding") == "gzip"
    assert response.get("vary") == "Accept-Encoding"
    assert response.get("content-length") is None
    assert _decompress(body, "gzip") == BIG_JSON


def test_compresses_with_deflate_when_requested() -> None:
    """compresses with deflate when requested"""
    response, body = _get(lambda: _handler(_big_json_app()), {"accept-encoding": "deflate"})
    assert response.get("content-encoding") == "deflate"
    assert _decompress(body, "deflate") == BIG_JSON


_ALL: tuple[CompressionAlgorithm, ...] = ("gzip", "deflate", "br", "zstd")


def test_server_preference_order_picks_br_over_gzip_when_supported() -> None:
    """server preference order picks br over gzip when supported"""
    response, _ = _get(
        lambda: _handler(_big_json_app(), None, _negotiation_context(_ALL)),
        {"accept-encoding": "gzip, br"},
    )
    assert response.get("content-encoding") == "br"


def test_client_q_values_decide_acceptability_only_server_order_decides_ranking() -> None:
    """client q-values decide acceptability only, server order decides ranking"""
    response, _ = _get(
        lambda: _handler(_big_json_app(), None, _negotiation_context(_ALL)),
        {"accept-encoding": "gzip;q=1, br;q=0.5"},
    )
    assert response.get("content-encoding") == "br"


def _uncompressed(accept: str) -> WebResponse:
    response, body = _get(lambda: _handler(_big_json_app()), {"accept-encoding": accept})
    assert response.get("content-encoding") is None
    assert body.decode() == BIG_JSON
    return response


def test_q_0_makes_a_coding_unacceptable() -> None:
    """q=0 makes a coding unacceptable"""
    assert _uncompressed("gzip;q=0").get("vary") == "Accept-Encoding"


def test_falls_through_server_order_past_q_0_codings() -> None:
    """falls through server order past q=0 codings"""
    response, _ = _get(lambda: _handler(_big_json_app()), {"accept-encoding": "gzip;q=0, deflate"})
    assert response.get("content-encoding") == "deflate"


def test_wildcard_matches_unlisted_codings() -> None:
    """wildcard matches unlisted codings"""
    response, _ = _get(lambda: _handler(_big_json_app()), {"accept-encoding": "*"})
    assert response.get("content-encoding") == "gzip"


def test_wildcard_with_q_0_disables_unlisted_codings() -> None:
    """wildcard with q=0 disables unlisted codings"""
    assert _uncompressed("*;q=0").status == 200


def test_sends_identity_with_200_when_nothing_is_acceptable_never_406() -> None:
    """sends identity with 200 when nothing is acceptable, never 406"""
    response = _uncompressed("br, identity;q=0")
    assert response.status == 200
    assert response.get("vary") == "Accept-Encoding"


def test_treats_a_malformed_accept_encoding_as_absent() -> None:
    """treats a malformed Accept-Encoding as absent"""
    _uncompressed("gzip;q=oops")


def test_treats_an_out_of_range_q_value_as_absent() -> None:
    """treats an out-of-range q-value as absent"""
    _uncompressed("gzip;q=1.5")


def test_does_not_compress_without_an_accept_encoding_header() -> None:
    """does not compress without an Accept-Encoding header"""
    response, body = _get(lambda: _handler(_big_json_app()))
    assert response.get("content-encoding") is None
    assert response.get("vary") == "Accept-Encoding"
    assert body.decode() == BIG_JSON


def _small_app() -> effect.Effect[HttpServerResponse]:
    return effect.succeed(server_response.text("{}", content_type="application/json"))


def test_skips_bodies_below_min_size_but_still_sets_vary() -> None:
    """skips bodies below minSize but still sets Vary"""
    response, body = _get(lambda: _handler(_small_app()), {"accept-encoding": "gzip"})
    assert response.get("content-encoding") is None
    assert response.get("vary") == "Accept-Encoding"
    assert response.get("content-length") == "2"
    assert body == b"{}"


def test_respects_a_custom_min_size() -> None:
    """respects a custom minSize"""
    response, _ = _get(lambda: _handler(_small_app(), {"min_size": 1}), {"accept-encoding": "gzip"})
    assert response.get("content-encoding") == "gzip"


def test_ignores_malformed_content_lengths_when_checking_min_size() -> None:
    """ignores malformed content lengths when checking minSize"""
    for content_length in ("1e3", "1.5"):
        app = effect.succeed(
            server_response.stream(
                stream.succeed(BIG_JSON_BYTES),
                content_type="application/json",
                headers={"content-length": content_length},
            )
        )
        response, _ = _get(lambda app=app: _handler(app), {"accept-encoding": "gzip"})
        assert response.get("content-encoding") == "gzip"


def _png_app() -> effect.Effect[HttpServerResponse]:
    return effect.succeed(server_response.bytes_(_random_bytes(2048), content_type="image/png"))


def test_skips_non_compressible_content_types_without_vary() -> None:
    """skips non-compressible content types without Vary"""
    response, _ = _get(lambda: _handler(_png_app()), {"accept-encoding": "gzip"})
    assert response.get("content-encoding") is None
    assert response.get("vary") is None


def test_supports_a_custom_compressible_predicate() -> None:
    """supports a custom compressible predicate"""

    def png(content_type: str) -> bool:
        return content_type == "image/png"

    options: dict[str, Any] = {"compressible": png}
    response, _ = _get(lambda: _handler(_png_app(), options), {"accept-encoding": "gzip"})
    assert response.get("content-encoding") == "gzip"


def _big_json_with(headers: dict[str, str]) -> effect.Effect[HttpServerResponse]:
    return effect.succeed(
        server_response.text(BIG_JSON, content_type="application/json", headers=headers)
    )


def test_leaves_already_encoded_responses_untouched() -> None:
    """leaves already-encoded responses untouched"""
    response, body = _get(
        lambda: _handler(_big_json_with({"content-encoding": "br"})), {"accept-encoding": "gzip"}
    )
    assert response.get("content-encoding") == "br"
    assert response.get("vary") is None
    assert body.decode() == BIG_JSON


def test_does_not_stamp_headers_when_a_raw_body_cannot_be_transformed() -> None:
    """does not stamp headers when a Raw body cannot be transformed"""
    app = effect.succeed(
        server_response.raw(
            WebResponse(), content_type="application/json", headers={"etag": '"abc"'}
        )
    )
    response, body = _get(lambda: _handler(app), {"accept-encoding": "gzip"})
    assert response.get("content-encoding") is None
    assert response.get("vary") is None
    assert response.get("etag") == '"abc"'
    assert body == b""


def test_strips_a_content_encoding_identity_opt_out_before_sending() -> None:
    """strips a Content-Encoding: identity opt-out before sending"""
    response, body = _get(
        lambda: _handler(_big_json_with({"content-encoding": "identity"})),
        {"accept-encoding": "gzip"},
    )
    assert response.get("content-encoding") is None
    assert body.decode() == BIG_JSON


def test_honors_cache_control_no_transform() -> None:
    """honors Cache-Control: no-transform"""
    response, body = _get(
        lambda: _handler(_big_json_with({"cache-control": "public, no-transform"})),
        {"accept-encoding": "gzip"},
    )
    assert response.get("content-encoding") is None
    assert body.decode() == BIG_JSON


def test_leaves_204_304_and_206_responses_untouched() -> None:
    """leaves 204, 304, and 206 responses untouched"""
    for status in (204, 304):
        app = effect.succeed(server_response.empty(status=status))
        response, _ = _get(lambda app=app: _handler(app), {"accept-encoding": "gzip"})
        assert response.status == status
        assert response.get("content-encoding") is None
        assert response.get("vary") is None
    partial_app = effect.succeed(
        server_response.text(BIG_JSON, status=206, content_type="application/json")
    )
    partial, body = _get(lambda: _handler(partial_app), {"accept-encoding": "gzip"})
    assert partial.status == 206
    assert partial.get("content-encoding") is None
    assert body.decode() == BIG_JSON


def test_mirrors_get_headers_for_head_requests_without_a_body() -> None:
    """mirrors GET headers for HEAD requests without a body"""
    response, body = _get(lambda: _handler(_big_json_app()), {"accept-encoding": "gzip"}, "HEAD")
    assert response.get("content-encoding") == "gzip"
    assert response.get("vary") == "Accept-Encoding"
    assert body == b""


def test_compresses_unknown_length_streams_incrementally() -> None:
    """compresses unknown-length streams incrementally"""
    latch = Latch()
    first = _random_bytes(1 << 17)
    second = _random_bytes(1 << 10)
    body = stream.succeed(first).concat(
        stream.from_effect(latch.wait()).drain().concat(stream.succeed(second))
    )
    app = effect.succeed(server_response.stream(body, content_type="text/event-stream"))

    async def main() -> bytes:
        response = await _handler(app)(
            WebRequest("http://localhost/", headers={"accept-encoding": "gzip"})
        )
        assert response.get("content-encoding") == "gzip"
        assert response.get("content-length") is None
        chunks = response.chunks()
        # The first compressed chunk arrives while the source is still open.
        received = [await anext(chunks)]
        latch.unsafe_open()
        received.extend([chunk async for chunk in chunks])
        return b"".join(received)

    decompressed = zlib.decompress(asyncio.run(main()), 31)
    assert decompressed == first + second


def _etag_of(etag: str, accept: str) -> str | None:
    response, _ = _get(
        lambda: _handler(_big_json_with({"etag": etag})), {"accept-encoding": accept}
    )
    return response.get("etag")


def test_weakens_a_strong_etag_on_compressed_responses() -> None:
    """weakens a strong ETag on compressed responses"""
    assert _etag_of('"abc"', "gzip") == 'W/"abc"'


def test_leaves_a_weak_etag_unchanged_on_compressed_responses() -> None:
    """leaves a weak ETag unchanged on compressed responses"""
    assert _etag_of('W/"abc"', "gzip") == 'W/"abc"'


def test_leaves_the_etag_of_skipped_responses_unchanged() -> None:
    """leaves the ETag of skipped responses unchanged"""
    assert _etag_of('"abc"', "identity") == '"abc"'


def test_falls_through_to_a_supported_algorithm_when_the_preferred_one_is_unavailable() -> None:
    """falls through to a supported algorithm when the preferred one is unavailable"""
    response, _ = _get(
        lambda: _handler(_big_json_app(), {"algorithms": ("br", "gzip")}),
        {"accept-encoding": "zstd, br, gzip"},
    )
    assert response.get("content-encoding") == "gzip"


def test_appends_accept_encoding_to_an_existing_vary_header() -> None:
    """appends Accept-Encoding to an existing Vary header"""
    response, _ = _get(
        lambda: _handler(_big_json_with({"vary": "Origin"})), {"accept-encoding": "gzip"}
    )
    assert response.get("vary") == "Origin, Accept-Encoding"


def test_does_not_duplicate_accept_encoding_in_vary_and_leaves_vary_star_alone() -> None:
    """does not duplicate Accept-Encoding in Vary and leaves Vary: * alone"""
    existing, _ = _get(
        lambda: _handler(_big_json_with({"vary": "accept-encoding"})), {"accept-encoding": "gzip"}
    )
    assert existing.get("vary") == "accept-encoding"
    star, _ = _get(lambda: _handler(_big_json_with({"vary": "*"})), {"accept-encoding": "gzip"})
    assert star.get("vary") == "*"


def test_preserves_cookies_on_compressed_responses() -> None:
    """preserves cookies on compressed responses"""
    app = effect.succeed(
        server_response.text(
            BIG_JSON, content_type="application/json", cookies=from_set_cookie(["session=abc"])
        )
    )
    response, _ = _get(lambda: _handler(app), {"accept-encoding": "gzip"})
    assert response.get("content-encoding") == "gzip"
    assert response.get_set_cookie() == ["session=abc"]
