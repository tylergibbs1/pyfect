"""Text channels: decoding and encoding chunks of bytes, and splitting
chunks of text into lines. Each reads and writes tuples (Effect's
non-empty arrays) and passes upstream's failure and end through."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import codecs
from typing import Any, Never

from pyfect._core import Effect, _FailCause, _Succeed, _Suspend, _Sync
from pyfect._js import text_decoder, text_encode
from pyfect.cause import fail as fail_cause
from pyfect.channel._base import AnyPull, end_with
from pyfect.channel._channel import Channel, from_transform
from pyfect.pull import catch_done, match_effect
from pyfect.scope import CloseableScope


def decode_text[E = Never, D = None](
    encoding: str = "utf-8", *, fatal: bool = False, ignore_bom: bool = False
) -> Channel[tuple[str, ...], E, D, tuple[bytes, ...], E, D]:
    """Decode chunks of bytes, keeping a character split across chunks
    whole. Bad bytes become U+FFFD, or a defect with ``fatal``. A UTF-8
    byte-order mark is dropped unless ``ignore_bom`` (WHATWG
    ``TextDecoder``)."""

    def transform(upstream: AnyPull, _scope: CloseableScope) -> Effect[AnyPull]:
        def build() -> AnyPull:
            decoding = _Decoding(text_decoder(encoding, fatal=fatal, ignore_bom=ignore_bom))
            pull = catch_done(upstream.map(decoding.decoded), decoding.flush)
            return _Suspend(lambda: pull if decoding.ended is None else decoding.ended)

        return _Sync(build)

    channel: Channel[tuple[str, ...], E, D, tuple[bytes, ...], E, D] = from_transform(transform)
    return channel


class _Decoding:
    """One run of ``decode_text``: ``ended`` is the end it repeats once
    upstream has ended."""

    __slots__ = ("decoder", "ended")

    def __init__(self, decoder: codecs.IncrementalDecoder) -> None:
        self.decoder = decoder
        self.ended: AnyPull | None = None

    def decoded(self, chunks: tuple[bytes, ...]) -> tuple[str, ...]:
        decoder = self.decoder
        return tuple(decoder.decode(chunk) for chunk in chunks)

    def flush(self, leftover: Any) -> AnyPull:
        ended = self.ended = end_with(leftover)
        last = self.decoder.decode(b"", final=True)
        return _Succeed((last,)) if last else ended


def encode_text[E = Never, D = None]() -> Channel[tuple[bytes, ...], E, D, tuple[str, ...], E, D]:
    """Encode chunks of text as UTF-8."""

    def encoded(chunks: tuple[str, ...]) -> tuple[bytes, ...]:
        return tuple(text_encode(chunk) for chunk in chunks)

    channel: Channel[tuple[bytes, ...], E, D, tuple[str, ...], E, D] = from_transform(
        lambda upstream, _scope: _Succeed(upstream.map(encoded))
    )
    return channel


class _LineSplitter:
    """Splits text into lines at ``\\n``, ``\\r\\n`` and ``\\r``, carrying an
    unfinished line (and a ``\\r`` that may start a ``\\r\\n``) across
    chunks."""

    __slots__ = ("_pending", "mid_crlf", "pending_length")

    def __init__(self) -> None:
        self._pending: list[str] = []  # pieces, joined once the line ends: linear time
        self.pending_length = 0
        self.mid_crlf = False

    def _line(self, end: str) -> str:
        if not self._pending:
            return end
        self._pending.append(end)
        line = "".join(self._pending)
        self._pending = []
        self.pending_length = 0
        return line

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
                    lines.append(self._line(text[start:lf]))
                    start = lf + 1
                else:
                    lines.append(self._line(text[start:cr]))
                    if cr + 1 == len(text):
                        self.mid_crlf = True
                        start = len(text)
                    else:
                        start = cr + (2 if lf == cr + 1 else 1)
            if start < len(text):
                self._pending.append(text[start:])
                self.pending_length += len(text) - start
        return tuple(lines)

    def flush(self) -> str:
        last = self._line("")
        self.mid_crlf = False
        return last


class LineTooLongError(Exception):
    """A line passed ``split_lines_within``'s limit."""

    def __init__(self, max_length: int) -> None:
        super().__init__(f"Line exceeds {max_length} characters")
        self.max_length = max_length


def _splitter(max_length: int | None) -> Channel[Any, Any, Any, Any, Any, Any, Any]:
    def transform(upstream: AnyPull, _scope: CloseableScope) -> Effect[AnyPull]:
        def build() -> AnyPull:
            return _Suspend(_Splitting(upstream, max_length).next_pull)

        return _Sync(build)

    return from_transform(transform)


class _Splitting:
    """One run of ``split_lines``: ``ended`` holds upstream's leftover once
    it has ended."""

    __slots__ = ("ended", "lines", "max_length", "upstream")

    def __init__(self, upstream: AnyPull, max_length: int | None) -> None:
        self.upstream = upstream
        self.max_length = max_length
        self.lines = _LineSplitter()
        self.ended: tuple[Any] | None = None

    def next_pull(self) -> AnyPull:
        if self.ended is not None:
            return end_with(self.ended[0])
        return match_effect(
            self.upstream, on_success=self.written, on_failure=_FailCause, on_done=self.done
        )

    def written(self, chunks: tuple[str, ...]) -> AnyPull:
        lines, max_length = self.lines, self.max_length
        split = lines.split(chunks)
        if max_length is not None and (
            lines.pending_length > max_length or any(len(line) > max_length for line in split)
        ):
            return _FailCause(fail_cause(LineTooLongError(max_length)))
        return _Succeed(split) if split else _Suspend(self.next_pull)

    def done(self, leftover: Any) -> AnyPull:
        self.ended = (leftover,)
        last = self.lines.flush()
        return _Succeed((last,)) if last else end_with(leftover)


def split_lines[E = Never, D = None]() -> Channel[tuple[str, ...], E, D, tuple[str, ...], E, D]:
    """Split chunks of text into lines, without their line breaks; the
    text after the last break is the last line."""
    return _splitter(None)


def split_lines_within[E = Never, D = None](
    max_length: int,
) -> Channel[tuple[str, ...], E | LineTooLongError, D, tuple[str, ...], E, D]:
    """``split_lines`` for text from a peer you do not control: a line
    longer than ``max_length`` characters fails with ``LineTooLongError``
    as soon as that much of it has arrived, so memory stays bounded."""
    return _splitter(max_length)
