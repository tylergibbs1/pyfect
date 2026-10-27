"""Text channels: decoding and encoding chunks of bytes, and splitting
chunks of text into lines. Each reads and writes tuples (Effect's
non-empty arrays) and passes upstream's failure and end through."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import codecs
from typing import Any, Never

from pyfect._core import Effect, _FailCause, _Succeed, _Suspend, _Sync
from pyfect.cause import Cause
from pyfect.channel._base import AnyPull, end_with
from pyfect.channel._channel import Channel, from_transform
from pyfect.pull import catch_done, match_effect
from pyfect.scope import CloseableScope


def _decoder(encoding: str, fatal: bool, ignore_bom: bool) -> codecs.IncrementalDecoder:
    name = codecs.lookup(encoding).name
    if name == "utf-8" and not ignore_bom:
        name = "utf-8-sig"
    return codecs.getincrementaldecoder(name)("strict" if fatal else "replace")


def decode_text[E = Never, D = None](
    encoding: str = "utf-8", *, fatal: bool = False, ignore_bom: bool = False
) -> Channel[tuple[str, ...], E, D, tuple[bytes, ...], E, D]:
    """Decode chunks of bytes, keeping a character split across chunks
    whole. Bad bytes become U+FFFD, or a defect with ``fatal``. A UTF-8
    byte-order mark is dropped unless ``ignore_bom`` (WHATWG
    ``TextDecoder``)."""

    def transform(upstream: AnyPull, _scope: CloseableScope) -> Effect[AnyPull]:
        def build() -> AnyPull:
            decoder = _decoder(encoding, fatal, ignore_bom)
            pull: AnyPull

            def decoded(chunks: tuple[bytes, ...]) -> tuple[str, ...]:
                return tuple(decoder.decode(chunk) for chunk in chunks)

            def flush(leftover: Any) -> AnyPull:
                nonlocal pull
                pull = end_with(leftover)
                last = decoder.decode(b"", final=True)
                return _Succeed((last,)) if last else pull

            pull = catch_done(upstream.map(decoded), flush)
            return _Suspend(lambda: pull)

        return _Sync(build)

    channel: Channel[tuple[str, ...], E, D, tuple[bytes, ...], E, D] = from_transform(transform)
    return channel


def encode_text[E = Never, D = None]() -> Channel[tuple[bytes, ...], E, D, tuple[str, ...], E, D]:
    """Encode chunks of text as UTF-8."""

    def encoded(chunks: tuple[str, ...]) -> tuple[bytes, ...]:
        return tuple(chunk.encode() for chunk in chunks)

    channel: Channel[tuple[bytes, ...], E, D, tuple[str, ...], E, D] = from_transform(
        lambda upstream, _scope: _Succeed(upstream.map(encoded))
    )
    return channel


class _LineSplitter:
    """Splits text into lines at ``\\n``, ``\\r\\n`` and ``\\r``, carrying an
    unfinished line (and a ``\\r`` that may start a ``\\r\\n``) across
    chunks."""

    __slots__ = ("mid_crlf", "pending")

    def __init__(self) -> None:
        self.pending = ""
        self.mid_crlf = False

    def split(self, chunks: tuple[str, ...]) -> tuple[str, ...]:
        lines: list[str] = []
        for text in chunks:
            if not text:
                continue
            start = 0
            if self.mid_crlf:
                if text.startswith("\n"):
                    start = 1
                self.mid_crlf = False
            while True:
                cr = text.find("\r", start)
                lf = text.find("\n", start)
                if cr == -1 and lf == -1:
                    break
                if cr == -1 or (lf != -1 and lf < cr):
                    lines.append(self.pending + text[start:lf])
                    start = lf + 1
                else:
                    lines.append(self.pending + text[start:cr])
                    if cr + 1 == len(text):
                        self.mid_crlf = True
                        start = len(text)
                    else:
                        start = cr + (2 if lf == cr + 1 else 1)
                self.pending = ""
            self.pending += text[start:]
        return tuple(lines)

    def flush(self) -> str:
        last, self.pending, self.mid_crlf = self.pending, "", False
        return last


def split_lines[E = Never, D = None]() -> Channel[tuple[str, ...], E, D, tuple[str, ...], E, D]:
    """Split chunks of text into lines, without their line breaks; the
    text after the last break is the last line."""

    def transform(upstream: AnyPull, _scope: CloseableScope) -> Effect[AnyPull]:
        def build() -> AnyPull:
            lines = _LineSplitter()
            ended: list[Any] = []

            def written(chunks: tuple[str, ...]) -> AnyPull:
                split = lines.split(chunks)
                return _Succeed(split) if split else pull_or_flush

            def done(leftover: Any) -> AnyPull:
                ended.append(leftover)
                last = lines.flush()
                return _Succeed((last,)) if last else end_with(leftover)

            def failed(cause: Cause[Any]) -> AnyPull:
                return _FailCause(cause)

            def next_pull() -> AnyPull:
                if ended:
                    return end_with(ended[0])
                return match_effect(upstream, on_success=written, on_failure=failed, on_done=done)

            pull_or_flush = _Suspend(next_pull)
            return pull_or_flush

        return _Sync(build)

    channel: Channel[tuple[str, ...], E, D, tuple[str, ...], E, D] = from_transform(transform)
    return channel
