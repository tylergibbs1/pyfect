"""One raw deflate stream read from a ``ByteQueue`` on ``zlib``, which hands back
the input past the stream's end (Effect writes its own inflater for this; the
standard library's is incremental, bounded per call and much faster than one in
Python). Its corrupt-data checks are the ones Effect's inflater copies."""

from __future__ import annotations

import zlib

from pyfect.encoding._archive import NEED_INPUT, ByteQueue, NeedInput

_OUTPUT_SIZE = 64 * 1024
_INPUT_SIZE = 64 * 1024
"""``zlib`` copies what it leaves unused on each call, so a whole archive held in one
chunk would cost a copy of what is left of it per 64 KiB of output and per entry."""

_MESSAGES = {
    "invalid stored block lengths": "stored block length is corrupt",
    "too many length or distance symbols": "too many length or distance codes",
    "invalid code -- missing end-of-block": "missing end-of-block code",
    "invalid literal/length code": "invalid literal or length code",
    "invalid distance too far back": "distance is beyond the start of the data",
}
"""zlib's messages where Effect's say the same in other words. Effect tells apart
what zlib reports as one ("invalid code lengths set", "invalid bit length repeat"),
and those keep zlib's text."""


class InflateError(Exception):
    pass


class Inflater:
    __slots__ = ("_decompressor", "_more", "_queue", "_tail")

    def __init__(self, queue: ByteQueue) -> None:
        self._queue = queue
        self._decompressor = zlib.decompressobj(-15)
        self._tail = b""
        # Whether the last call stopped at the output limit, so zlib may hold more
        self._more = False

    def pull(self) -> bytes | NeedInput | None:
        """Up to 64 KiB of output, ``NEED_INPUT``, or ``None`` once the stream has
        ended, when the input past it is back on the queue."""
        decompressor = self._decompressor
        while True:
            if decompressor.eof:
                return None
            data = self._tail
            if not data and not self._more:
                if self._queue.length == 0:
                    return NEED_INPUT
                data = self._queue.take_some(_INPUT_SIZE)
            try:
                out = decompressor.decompress(data, _OUTPUT_SIZE)
            except zlib.error as error:
                message = str(error).partition(": ")[2]
                raise InflateError(_MESSAGES.get(message, message)) from None
            self._tail = decompressor.unconsumed_tail
            self._more = len(out) == _OUTPUT_SIZE
            if decompressor.eof:
                self._queue.unread(decompressor.unused_data)
            if out:
                return out
