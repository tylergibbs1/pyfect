"""``zip``'s inflater handing a stream over from ``zlib`` to the port of Effect's,
where it hands out output, and ``ByteQueue.unread``, which gives input back across
chunks."""

from __future__ import annotations

import random
import zlib
from collections.abc import Iterator
from typing import Any

import pyfect as fx
from pyfect import stream, testing
from pyfect.encoding import zip as Zip
from pyfect.encoding._archive import NEED_INPUT, ByteQueue
from pyfect.encoding.zip._inflate import Inflater

OUTPUT_SIZE = 64 * 1024
"""Effect's inflater hands out output at every 64 KiB of it."""


def deflate(data: bytes) -> bytes:
    compressor = zlib.compressobj(6, zlib.DEFLATED, -15)
    return compressor.compress(data) + compressor.flush()


def test_a_fallback_after_zlib_took_the_end_gives_the_rest_back() -> None:
    """A fallback once ``zlib`` has taken input past the stream's end: the port repeats
    no output already handed out and puts the input past the end back."""
    content = bytes(range(256)) * 400
    queue = ByteQueue()
    queue.push(deflate(content) + b"after")
    inflater = Inflater(queue)
    first = inflater.pull()
    assert isinstance(first, bytes)
    assert len(first) == 64 * 1024
    assert inflater.fall_back(len(first))
    assert not inflater.fall_back(len(first))
    rest: list[bytes] = []
    while (out := inflater.pull()) is not None:
        assert out is not NEED_INPUT
        rest.append(out)
    assert first + b"".join(rest) == content
    assert queue.take(queue.length) == b"after"


def test_unread_puts_back_bytes_from_several_chunks() -> None:
    queue = ByteQueue()
    queue.push(b"abc")
    queue.push(b"defgh")
    assert queue.take_some(3) == b"abc"
    assert queue.take_some(2) == b"de"
    queue.unread(b"cde")
    assert (queue.length, queue.consumed) == (6, 2)
    assert queue.take(6) == b"cdefgh"


def local_header(content: bytes, data: bytes) -> bytes:
    """A local header of a deflated entry with its sizes, ahead of its data ``data``."""
    name = b"f"
    return (
        b"PK\x03\x04"
        + bytes((20, 0, 0, 0, 8, 0, 0, 0, 0x21, 0))
        + zlib.crc32(content).to_bytes(4, "little")
        + len(data).to_bytes(4, "little")
        + len(content).to_bytes(4, "little")
        + len(name).to_bytes(2, "little")
        + bytes(2)
        + name
    )


END_RECORD = b"PK\x05\x06" + bytes(18)


def body_chunks(chunks: list[bytes], pulled: list[int]) -> fx.Effect[list[bytes], Any]:
    """The body chunks of the one entry ``chunks`` hold, recording in ``pulled``, for
    each body chunk, how many of ``chunks`` had been read when it came out."""
    read = 0

    def source() -> Iterator[bytes]:
        nonlocal read
        for chunk in chunks:
            read += 1
            yield chunk

    def record() -> None:
        pulled.append(read)

    def body(entry: Zip.Entry[Zip.ZipError]) -> stream.Stream[bytes, Zip.ZipError]:
        return entry.body.tap(lambda _: fx.sync(record))

    return (
        stream.from_iterable(source(), chunk_size=1)
        .pipe_through_channel(Zip.decode())
        .flat_map(body)
        .run_collect()
    )


@testing.effect
def test_hands_out_the_output_zlib_holds_past_a_full_buffer_before_reading_more() -> Any:
    """Input that ends inside a match which fills the output buffer: zlib has taken all
    of it and holds the rest of the match, which comes out before more input is read."""
    content = bytes(200_000)
    data = deflate(content)

    def holds_output(end: int) -> bool:
        decompressor = zlib.decompressobj(-15)
        out = decompressor.decompress(data[:end], OUTPUT_SIZE)
        return (
            len(out) == OUTPUT_SIZE
            and not decompressor.unconsumed_tail
            and bool(decompressor.decompress(b"", OUTPUT_SIZE))
        )

    end = next(end for end in range(1, len(data)) if holds_output(end))
    decoded = len(zlib.decompressobj(-15).decompress(data[:end]))
    assert decoded > OUTPUT_SIZE
    header = local_header(content, data)
    pulled: list[int] = []
    chunks = [header + data[:end], data[end:] + END_RECORD]
    out = yield from body_chunks(chunks, pulled)
    assert b"".join(out) == content
    assert sum(len(chunk) for chunk, at in zip(out, pulled, strict=True) if at == 1) == decoded


@testing.effect
def test_hands_out_output_at_every_64_kib_when_input_runs_out_between() -> Any:
    """Input in pieces that run out between the 64 KiB points: output still comes
    out at each of them, counted from the start of the entry."""
    # Noise, which deflate stores, so that each piece of input is about as much output
    content = random.Random(1).randbytes(4 * OUTPUT_SIZE + 1000)
    data = deflate(content)
    assert len(data) > len(content)
    whole = local_header(content, data) + data + END_RECORD
    chunks = [whole[start : start + 4093] for start in range(0, len(whole), 4093)]
    out = yield from body_chunks(chunks, [])
    assert b"".join(out) == content
    start = 0
    for chunk in out:
        end = start + len(chunk)
        assert start // OUTPUT_SIZE == (end - 1) // OUTPUT_SIZE, (start, end)
        start = end
