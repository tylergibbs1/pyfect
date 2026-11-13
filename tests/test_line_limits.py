"""(pyfect) Every line decoder can bound the memory a peer that never sends a line break
takes.

``split_lines`` and the NDJSON decoders hold a line until its break arrives, so a peer
sending text without one (a TCP client, a child process) grew the reader's memory without
bound: 32 MiB without a newline peaked at 64 MiB. As in Effect they stay unbounded by default;
each takes an opt-in limit, checked here against input that never ends, so a decoder that
buffered past its limit would never finish. The MCP stdio server has Effect's 16 MiB limit
(NDJSON-RPC framing) built in.
"""

from __future__ import annotations

from typing import Any

import pyfect as fx
from pyfect import stream, testing
from pyfect.channel import LineTooLongError
from pyfect.encoding import ndjson
from pyfect.encoding.ndjson import NdjsonError

_CHUNK = "x" * 1024
_LIMIT = 64 * 1024


def _endless_text() -> stream.Stream[str]:
    return stream.succeed(_CHUNK).forever()


def _endless_bytes() -> stream.Stream[bytes]:
    return stream.succeed(_CHUNK.encode()).forever()


@testing.effect
def test_stream_split_lines_within_fails_a_line_past_its_limit():
    """(pyfect) Stream.split_lines_within fails a line without a break once it passes the
    limit"""
    error = yield from _endless_text().split_lines_within(_LIMIT).run_drain().flip()
    assert isinstance(error, LineTooLongError)
    assert error.max_length == _LIMIT


@testing.effect
def test_stream_split_lines_within_keeps_lines_up_to_the_limit():
    """(pyfect) Stream.split_lines_within writes lines of up to the limit as split_lines
    does"""
    text = stream.make("a" * 8 + "\nbb", "\r\n", "c")
    lines = yield from text.split_lines_within(8).run_collect()
    assert list(lines) == ["a" * 8, "bb", "c"]


def _too_large(error: Any) -> None:
    assert isinstance(error, NdjsonError)
    assert error.reason == "LineTooLarge"


@testing.effect
def test_ndjson_decode_string_fails_a_line_past_max_line_length():
    """(pyfect) ndjson.decode_string(max_line_length=) fails a line without a break once it
    passes the limit"""
    decoded = _endless_text().pipe_through_channel(ndjson.decode_string(max_line_length=_LIMIT))
    _too_large((yield from decoded.run_drain().flip()))


@testing.effect
def test_ndjson_duplex_string_and_schema_take_max_line_length():
    """(pyfect) the text NDJSON schema decoder fails a line past max_line_length"""
    from pyfect import schema as S

    decoded = _endless_text().pipe_through_channel(
        ndjson.decode_schema_string(S.Any, max_line_length=_LIMIT)
    )
    _too_large((yield from decoded.run_drain().flip()))


@testing.effect
def test_ndjson_decode_fails_a_line_past_max_line_bytes():
    """(pyfect) ndjson.decode(max_line_bytes=) fails a line without a break once it passes
    the limit"""
    decoded = _endless_bytes().pipe_through_channel(ndjson.decode(max_line_bytes=_LIMIT))
    _too_large((yield from decoded.run_drain().flip()))


@testing.effect
def test_ndjson_decode_string_keeps_lines_up_to_the_limit():
    """(pyfect) ndjson.decode_string(max_line_length=) parses lines of up to the limit"""
    text = stream.make('{"a":', "1}\n[2]")
    values = yield from text.pipe_through_channel(
        ndjson.decode_string(max_line_length=7)
    ).run_collect()
    assert list(values) == [{"a": 1}, [2]]


def test_mcp_stdio_server_ends_on_a_line_past_16_mib():
    """(pyfect) the MCP stdio server stops reading a line past 16 MiB (Effect's NDJSON-RPC
    max_buffer_size), instead of holding it"""
    from pyfect import stdio
    from pyfect.ai import mcp_protocol as P
    from pyfect.ai import mcp_server as M
    from pyfect.rpc.serialization import DEFAULT_MAX_BUFFER_SIZE, MaxBufferSizeExceeded

    chunk = b"x" * (1024 * 1024)
    serving = M.run_stdio(name="test-server", version="1.0.0", protocols=(P.v2025_11_25,)).pipe(
        fx.provide_service(M.McpServer, fx.run_blocking(M.make()))
    )
    endless = stream.succeed(chunk).forever()
    exit_ = fx.run_blocking(
        serving.pipe(fx.provide(stdio.layer_test(stdin=endless))).timeout("1 minute").exit()
    )
    assert isinstance(exit_, fx.Failure)
    [defect] = exit_.cause.defects
    assert isinstance(defect, MaxBufferSizeExceeded), exit_.cause.pretty()
    assert defect.max_buffer_size == DEFAULT_MAX_BUFFER_SIZE
