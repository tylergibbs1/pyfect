"""Compressing request bodies (Effect's ``internal/compressionBody``)."""

from __future__ import annotations

import zlib
from typing import Literal

from pyfect.effect import Effect, succeed, sync
from pyfect.http import body as _body
from pyfect.stream import Stream
from pyfect.stream import suspend as suspend_stream
from pyfect.stream import sync as sync_stream

type CompressionAlgorithm = Literal["gzip", "deflate"]

_WBITS: dict[CompressionAlgorithm, int] = {"gzip": 31, "deflate": 15}


def _compressor(algorithm: CompressionAlgorithm) -> zlib._Compress:  # pyright: ignore[reportPrivateUsage]
    return zlib.compressobj(wbits=_WBITS[algorithm])


def _compress_stream(
    chunks: Stream[bytes, object], algorithm: CompressionAlgorithm
) -> Stream[bytes, object]:
    def make() -> Stream[bytes, object]:
        compressor = _compressor(algorithm)
        compressed = chunks.map(compressor.compress).concat(sync_stream(compressor.flush))
        return compressed.filter(lambda chunk: len(chunk) > 0)

    return suspend_stream(make)


def compress_body(
    body: _body.HttpBody, algorithm: CompressionAlgorithm, min_size: int = 1024
) -> Effect[_body.HttpBody]:
    """``body`` compressed with ``algorithm``; bodies other than bytes and
    streams, and those known to be shorter than ``min_size``, unchanged. A
    compressed stream has no known length."""
    if not isinstance(body, _body.Bytes | _body.Stream):
        return succeed(body)
    if body.content_length is not None and body.content_length < min_size:
        return succeed(body)
    if isinstance(body, _body.Bytes):
        data, content_type = body.body, body.content_type

        def compress() -> _body.HttpBody:
            compressor = _compressor(algorithm)
            return _body.bytes_(compressor.compress(data) + compressor.flush(), content_type)

        return sync(compress)
    return succeed(_body.stream(_compress_stream(body.stream, algorithm), body.content_type))
