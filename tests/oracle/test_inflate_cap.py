"""``zip.decode`` keeps at most ``REPLAY_LIMIT`` bytes of an entry's compressed input to
replay through the port of Effect's inflater (security hardening, ``docs/PARITY.md``
section 4). A corrupt entry within it fails with Effect's message (``over-subscribed
Huffman code``, as under Node); one past it with Effect's kind and ``zlib``'s words."""

from __future__ import annotations

import struct
import tracemalloc
import zlib
from collections.abc import Iterator

import pyfect as fx
from pyfect import stream
from pyfect.encoding import zip as Zip
from pyfect.encoding._archive import NEED_INPUT, ByteQueue
from pyfect.encoding.zip._inflate import REPLAY_LIMIT, Inflater
from pyfect.result import Ok

from ._inflate_corpus import per_message, zip_archive

BLOCK = bytes(range(256)) * 255 + bytes(255)
"""65,535 bytes: one full stored block."""


def stored(size: int) -> Iterator[bytes]:
    """Deflate data of ``size`` bytes of stored blocks that are not the last."""
    while size > 0:
        part = BLOCK[: min(len(BLOCK), size - 5)]
        yield struct.pack("<BHH", 0, len(part), len(part) ^ 0xFFFF) + part
        size -= 5 + len(part)


def corrupt_entry(size: int) -> bytes:
    """``size`` bytes of deflate data ending in an over-subscribed code length code."""
    tail = per_message()[0]
    data = b"".join(stored(size - len(tail))) + tail
    assert len(data) == size
    return zip_archive(data, 0, 0xFFFFFFFF)


def failure(archive: bytes) -> tuple[str, str]:
    chunks = [archive[i : i + 65536] for i in range(0, len(archive), 65536)]
    effect = (
        stream.from_iterable(chunks)
        .pipe_through_channel(Zip.decode())
        .map_effect(lambda entry: entry.body.run_drain())
        .run_drain()
    )
    result = fx.run_blocking_exit(effect)
    assert isinstance(result, fx.Failure)
    found = result.cause.find_error()
    assert isinstance(found, Ok)
    return found.value.kind, found.value.message


def test_a_corrupt_entry_within_the_limit_fails_with_effects_message() -> None:
    assert failure(corrupt_entry(REPLAY_LIMIT - 1024)) == (
        "InvalidData",
        "over-subscribed Huffman code",
    )


def test_a_corrupt_entry_past_the_limit_fails_with_zlibs_words() -> None:
    assert failure(corrupt_entry(REPLAY_LIMIT + 1024)) == (
        "InvalidData",
        "invalid code lengths set",
    )


def test_a_large_entry_holds_at_most_the_limit() -> None:
    """32 MiB of deflate data, inflated a 64 KiB chunk at a time."""
    size = 32 * 1024 * 1024

    def chunks() -> Iterator[bytes]:
        yield from stored(size - 5)
        yield struct.pack("<BHH", 1, 0, 0xFFFF)

    tracemalloc.start()
    try:
        queue = ByteQueue()
        inflater = Inflater(queue)
        source = chunks()
        out = 0
        while (pulled := inflater.pull()) is not None:
            if pulled is NEED_INPUT:
                queue.push(next(source))
            else:
                out += len(pulled)
        peak = tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()
    assert out > size * 0.99
    assert peak < REPLAY_LIMIT + 2 * 1024 * 1024


def test_zlib_words_for_the_over_subscribed_code() -> None:
    """What the local ``zlib`` says, which the test above expects."""
    try:
        zlib.decompress(per_message()[0], -15)
    except zlib.error as error:
        assert str(error).endswith("invalid code lengths set")
