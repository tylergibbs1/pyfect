"""Text channels: decoding and encoding chunks of bytes, and splitting
chunks of text into lines. Each reads and writes tuples (Effect's
non-empty arrays) and passes upstream's failure and end through."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Never

from pyfect._core import Effect, _FailCause, _Succeed, _Suspend, _Sync
from pyfect._js import text_decoder, text_encode
from pyfect.cause import Cause
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
            decoder = text_decoder(encoding, fatal=fatal, ignore_bom=ignore_bom)
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
            start = self._split_chunk(text, start, lines)
            if start < len(text):
                self._pending.append(text[start:])
                self.pending_length += len(text) - start
        return tuple(lines)

    def _split_chunk(self, text: str, start: int, lines: list[str]) -> int:
        """Appends the lines of ``text`` from ``start``; returns where the unfinished rest
        starts. The next CR and LF are each searched for again only once passed, so a chunk
        of many lines is searched once, not once per line for the break it lacks."""
        cr = text.find("\r", start)
        lf = text.find("\n", start)
        while cr != -1 or lf != -1:
            if cr == -1 or (lf != -1 and lf < cr):
                lines.append(self._line(text[start:lf]))
                start = lf + 1
            else:
                lines.append(self._line(text[start:cr]))
                if cr + 1 == len(text):
                    self.mid_crlf = True
                    return len(text)
                start = cr + (2 if lf == cr + 1 else 1)
            if 0 <= cr < start:
                cr = text.find("\r", start)
            if 0 <= lf < start:
                lf = text.find("\n", start)
        return start

    def flush(self) -> str:
        last = self._line("")
        self.mid_crlf = False
        return last


class LineTooLongError(Exception):
    """A line passed ``split_lines_within``'s limit."""

    def __init__(self, max_length: int) -> None:
        super().__init__(f"Line exceeds {max_length} characters")
        self.max_length = max_length


def splitter(
    max_length: int | None, too_long: Callable[[int], object] = LineTooLongError
) -> Channel[Any, Any, Any, Any, Any, Any, Any]:
    """The line splitter, failing with ``too_long(max_length)`` past ``max_length``."""

    def transform(upstream: AnyPull, _scope: CloseableScope) -> Effect[AnyPull]:
        def build() -> AnyPull:
            lines = _LineSplitter()
            ended: list[Any] = []

            def written(chunks: tuple[str, ...]) -> AnyPull:
                split = lines.split(chunks)
                if max_length is not None and (
                    lines.pending_length > max_length
                    or any(len(line) > max_length for line in split)
                ):
                    return _FailCause(fail_cause(too_long(max_length)))
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

    return from_transform(transform)


def split_lines[E = Never, D = None]() -> Channel[tuple[str, ...], E, D, tuple[str, ...], E, D]:
    """Split chunks of text into lines, without their line breaks; the
    text after the last break is the last line."""
    return splitter(None)


def split_lines_within[E = Never, D = None](
    max_length: int,
) -> Channel[tuple[str, ...], E | LineTooLongError, D, tuple[str, ...], E, D]:
    """``split_lines`` for text from a peer you do not control: a line
    longer than ``max_length`` characters fails with ``LineTooLongError``
    as soon as that much of it has arrived, so memory stays bounded."""
    return splitter(max_length)
