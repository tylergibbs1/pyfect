"""(pyfect) The NDJSON decoders do not copy a line to read it.

A line in one chunk is decoded where it lies, and the last line (the text after the last
break) is not joined with an empty end piece, so a long line costs its decoded text and
nothing more. The leading byte-order mark is still skipped as ``utf-8-sig`` skips it: on the
first line only.
"""

from __future__ import annotations

from collections.abc import Callable

from _memory import SLACK, Peak, peak

import pyfect as fx
from pyfect import stream
from pyfect.encoding import Json, ndjson

_CHARS = 1 << 20
_TEXT = "丁" * _CHARS
"""Not JSON, so the parse fails at once and the peak is the decoder's own."""
_DECODED = 2 * _CHARS
"""Bytes the decoded text takes: two per character."""


def _decode(chunks: tuple[bytes, ...]) -> fx.Exit[list[Json], ndjson.NdjsonError]:
    program = stream.from_iterable(chunks).pipe_through_channel(ndjson.decode()).run_collect()
    return fx.run_blocking_exit(program)


def _values(chunks: tuple[bytes, ...]) -> list[Json]:
    program = stream.from_iterable(chunks).pipe_through_channel(ndjson.decode()).run_collect()
    return fx.run_blocking(program.or_die())


def _decode_string(chunks: tuple[str, ...]) -> fx.Exit[list[Json], ndjson.NdjsonError]:
    program = (
        stream.from_iterable(chunks).pipe_through_channel(ndjson.decode_string()).run_collect()
    )
    return fx.run_blocking_exit(program)


def _peak(work: Callable[[], object], size: int) -> Peak:
    """``peak`` of ``work`` after a first run, which pays for one-time imports and caches."""
    work()
    return peak(work, size)


def _decoding(data: bytes) -> int:
    """What decoding ``data`` alone peaks at: CPython 3.13's UTF-8 decoder holds about three
    times what 3.14's does."""
    return _peak(data.decode, len(data)).peak


def test_a_last_line_of_bytes_costs_only_its_decoding() -> None:
    data = _TEXT.encode()
    found = _peak(lambda: _decode((data,)), len(data))
    assert found.peak <= _decoding(data) + 0.25 * len(data) + SLACK, found


def test_a_terminated_line_of_bytes_costs_only_its_decoding() -> None:
    data = _TEXT.encode() + b"\n"
    found = _peak(lambda: _decode((data,)), len(data))
    assert found.peak <= _decoding(data) + 0.25 * len(data) + SLACK, found


def test_a_last_line_of_text_is_not_copied() -> None:
    found = _peak(lambda: _decode_string((_TEXT,)), _DECODED)
    assert found.peak <= 0.5 * _DECODED + SLACK, found


def test_a_leading_byte_order_mark_is_skipped_in_one_chunk_and_split() -> None:
    assert _values((b"\xef\xbb\xbf1\n2\n",)) == [1, 2]
    assert _values(
        (
            b"\xef\xbb",
            b"\xbf1\n2",
        )
    ) == [1, 2]
    assert _values((b"\xef\xbb\xbf",)) == []


def test_a_byte_order_mark_after_the_first_line_is_kept() -> None:
    # U+FEFF is JSON whitespace to nobody: kept, it makes the line invalid JSON, as in
    # ``utf-8-sig``, which skips only the input's first three bytes.
    exit = _decode((b"1\n\xef\xbb\xbf2\n",))
    assert isinstance(exit, fx.Failure)
    assert isinstance(exit.cause.squash(), ndjson.NdjsonError)
    inside = _values((b'"\xef\xbb\xbf"\n"a\xef\xbb\xbf"\n',))
    assert inside == ["\ufeff", "a\ufeff"]
