"""``zip``'s inflater handing a stream over from ``zlib`` to the port of Effect's, and
``ByteQueue.unread``, which gives input back across chunks."""

from __future__ import annotations

import zlib

from pyfect.encoding._archive import NEED_INPUT, ByteQueue
from pyfect.encoding.zip._inflate import Inflater


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
