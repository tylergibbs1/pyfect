"""(pyfect) Every line and frame splitter takes time linear in its input, however it is chunked.

A splitter that searched its whole pending buffer again for each arriving chunk, or copied
the buffer to add a chunk to it, cost quadratic time when a peer trickled one long line in
small chunks (Effect's RPC NDJSON parser does this too): a 16 MiB line sent 16 bytes at a time
took minutes of CPU. Here each splitter is fed a long line in small chunks, and many short
lines in one chunk, at two sizes four times apart. Linear work grows four times; the check
allows eight, where quadratic work grows sixteen. The time is the thread's CPU time, the least
of a few runs, so a loaded machine does not decide it.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import pytest

from pyfect import schema as S
from pyfect.channel._text import (
    _LineSplitter,  # pyright: ignore[reportPrivateUsage]
)
from pyfect.encoding import schema_binary, sse
from pyfect.encoding.csv._parser import Parser as CsvParser
from pyfect.encoding.ndjson import _ByteLines  # pyright: ignore[reportPrivateUsage]
from pyfect.http.multipart_parser._headers import HeadersParser
from pyfect.rpc.serialization import make_ndjson
from pyfect.sql.clickhouse._rows import RowSplitter

_SIZE = 256 * 1024
_CHUNK = 16
_RUNS = 3

type Run = Callable[[int], Callable[[], None]]
"""Given a size, the work of splitting that much input."""


def _cpu(work: Callable[[], None]) -> float:
    best = float("inf")
    for _ in range(_RUNS):
        start = time.thread_time()
        work()
        best = min(best, time.thread_time() - start)
    return best


def _pieces[T: (str, bytes)](data: T, size: int = _CHUNK) -> list[T]:
    return [data[i : i + size] for i in range(0, len(data), size)]


def _rpc_ndjson(line: str) -> Callable[[], None]:
    chunks = _pieces(line + "\n")

    def work() -> None:
        parser = make_ndjson(max_buffer_size="unbounded").make_unsafe()
        for chunk in chunks:
            parser.decode(chunk)

    return work


def _rows(line: bytes) -> Callable[[], None]:
    chunks = _pieces(line + b"\n")

    def work() -> None:
        splitter = RowSplitter(None)
        for chunk in chunks:
            splitter.feed(chunk)

    return work


def _lines(chunks: list[str]) -> Callable[[], None]:
    def work() -> None:
        splitter = _LineSplitter()
        for chunk in chunks:
            splitter.split((chunk,))
        splitter.flush()

    return work


def _byte_lines(chunks: list[bytes]) -> Callable[[], None]:
    def work() -> None:
        lines = _ByteLines(True, float("inf"))
        out: list[Any] = []
        for chunk in chunks:
            lines.step((chunk,), out)

    return work


def _sse(chunks: list[str]) -> Callable[[], None]:
    def work() -> None:
        parser = sse.make_parser(lambda _event: None, max_event_size=1 << 40)
        for chunk in chunks:
            parser.feed(chunk)

    return work


def _csv(chunks: list[str]) -> Callable[[], None]:
    def work() -> None:
        parser = CsvParser(",", float("inf"), True)
        out: list[Any] = []
        for chunk in chunks:
            parser.feed(chunk, out)
        parser.end(out)

    return work


def _schema_binary(size: int) -> Callable[[], None]:
    chunks = _pieces(schema_binary.encoder(S.String).encode("x" * size))

    def work() -> None:
        parser = schema_binary.parser(S.String)
        for chunk in chunks:
            parser.feed_sync(chunk)

    return work


_CASES: dict[str, Run] = {
    "rpc ndjson, one long line": lambda n: _rpc_ndjson('"' + "x" * n + '"'),
    "rpc ndjson, many lines": lambda n: _rpc_ndjson("\n".join(["1"] * (n // 2))),
    "clickhouse rows, one long row": lambda n: _rows(b"x" * n),
    "split_lines, one long line": lambda n: _lines(_pieces("x" * n + "\n")),
    "split_lines, many lines in one chunk": lambda n: _lines(["\n" * n]),
    "split_lines, many CR lines in one chunk": lambda n: _lines(["\r" * n]),
    "ndjson bytes, one long line": lambda n: _byte_lines(_pieces(b" " * n + b"\n")),
    "ndjson bytes, many lines in one chunk": lambda n: _byte_lines([b"\n" * n]),
    "sse, one long line": lambda n: _sse(_pieces("data: " + "x" * n + "\n\n")),
    "sse, many lines in one chunk": lambda n: _sse(["data: x\n" * (n // 8)]),
    "csv, one long field": lambda n: _csv(_pieces("x" * n + "\n")),
    "csv, one long quoted field": lambda n: _csv(_pieces('"' + "x" * n + '"\n')),
    "schema_binary, one long frame": _schema_binary,
}


@pytest.mark.parametrize("name", list(_CASES))
def test_a_splitter_takes_linear_time(name: str) -> None:
    run = _CASES[name]
    small = _cpu(run(_SIZE))
    large = _cpu(run(4 * _SIZE))
    assert large < 8 * small, f"{name}: {small:.3f}s for {_SIZE}, {large:.3f}s for 4x"


def test_multipart_header_values_are_joined_once() -> None:
    """A part's header block is at most 16 KiB, too small for timing to tell; its parser
    keeps the pieces of a key and value and joins them once, checked here by feeding the
    value a byte at a time."""
    parser = HeadersParser()
    value = b"form-data; name=" + b"x" * 8000
    parser.write(b"content-dis", 0)
    parser.write(b"position: ", 0)
    rest = value + b"\r\n\r\n"
    result: object = None
    for i in range(len(rest)):
        result = parser.write(rest[i : i + 1], 0)
    assert getattr(result, "headers", None) == {"content-disposition": value.decode()}
