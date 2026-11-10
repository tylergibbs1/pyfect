"""One raw deflate stream read from a ``ByteQueue``: ``zlib`` for speed, Effect's
inflater (``_inflate_port``) for what Effect reports.

``zlib`` hands out output where Effect's inflater does: at every 64 KiB of output
and where the queue runs dry. It keeps the input it took, up to ``REPLAY_LIMIT``. When
``zlib`` rejects the stream, or the decoder is about to report an end of input or a
size mismatch (``fall_back``), the entry is replayed through Effect's inflater, which
then reads the rest of the stream: its errors are the ones Effect reports, at the
same output, and the output it repeats is not handed out again. Past the limit, an
entry fails with zlib's words: holding and replaying more would let one upload hold
its whole compressed size in memory and a fiber for minutes."""

from __future__ import annotations

import zlib

from pyfect.encoding._archive import NEED_INPUT, ByteQueue, NeedInput
from pyfect.encoding.zip._inflate_port import OUTPUT_SIZE, InflateError
from pyfect.encoding.zip._inflate_port import Inflater as EffectInflater

__all__ = ["InflateError", "Inflater"]

REPLAY_LIMIT = 4 * 1024 * 1024
"""The most input of an entry kept for a replay."""

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
"""zlib's messages, past ``REPLAY_LIMIT``, where Effect's say the same in other words.
Effect tells apart what zlib reports as one ("invalid code lengths set", "invalid bit
length repeat"), and those keep zlib's text."""


class _Replay:
    """The queue Effect's inflater reads after a fallback: the input ``zlib`` took,
    then the queue itself."""

    __slots__ = ("_data", "_from_queue", "_position", "_queue")

    def __init__(self, taken: list[bytes], queue: ByteQueue) -> None:
        self._data = b"".join(taken)
        self._position = 0
        self._queue = queue
        self._from_queue = False

    @property
    def length(self) -> int:
        return len(self._data) - self._position + self._queue.length

    def take_some(self, most: int) -> bytes:
        if self._position < len(self._data):
            end = min(len(self._data), self._position + most)
            out = self._data[self._position : end]
            self._position = end
            self._from_queue = False
            return out
        self._from_queue = True
        return self._queue.take_some(most)

    def unread(self, data: bytes) -> None:
        if self._from_queue:
            self._queue.unread(data)
        else:
            self._position -= len(data)

    def give_back(self) -> None:
        """Returns the replayed input past the stream's end to the queue."""
        if self._position < len(self._data):
            self._queue.unread(self._data[self._position :])
            self._position = len(self._data)


class Inflater:
    __slots__ = ("_decompressor", "_effect", "_kept", "_more", "_produced", "_queue",
                 "_replay", "_skip", "_tail", "_taken")  # fmt: skip

    def __init__(self, queue: ByteQueue) -> None:
        self._queue = queue
        self._decompressor = zlib.decompressobj(-15)
        self._tail = b""
        # Whether the last call stopped at the output limit, so zlib may hold more
        self._more = False
        # Output handed out so far
        self._produced = 0
        # The input taken, for a replay; None once it passed REPLAY_LIMIT
        self._taken: list[bytes] | None = []
        self._kept = 0
        self._effect: EffectInflater | None = None
        self._replay: _Replay | None = None
        # Output Effect's inflater repeats, which was handed out already
        self._skip = 0

    def pull(self) -> bytes | NeedInput | None:
        """Output up to the next point where Effect's inflater hands it out,
        ``NEED_INPUT``, or ``None`` once the stream has ended, when the input past
        it is back on the queue. Raises ``InflateError`` on corrupt data."""
        if self._effect is not None:
            return self._pull_effect()
        decompressor = self._decompressor
        if decompressor.eof:
            return None
        queue = self._queue
        limit = OUTPUT_SIZE - self._produced % OUTPUT_SIZE
        parts: list[bytes] = []
        size = 0
        while True:
            data = self._tail
            if not data and not self._more:
                if queue.length == 0:
                    # Effect's inflater stops here too
                    break
                data = queue.take_some(_INPUT_SIZE)
                self._keep(data)
            try:
                out = decompressor.decompress(data, limit - size)
            except zlib.error as error:
                if not self.fall_back(self._produced):
                    message = str(error).partition(": ")[2]
                    raise InflateError(_MESSAGES.get(message, message)) from None
                return self._pull_effect()
            self._tail = decompressor.unconsumed_tail
            self._more = len(out) == limit - size
            size += len(out)
            parts.append(out)
            if decompressor.eof:
                queue.unread(decompressor.unused_data)
                self._taken = []
                break
            if size == limit:
                break
        if size == 0:
            return None if decompressor.eof else NEED_INPUT
        self._produced += size
        return parts[0] if len(parts) == 1 else b"".join(parts)

    def _keep(self, data: bytes) -> None:
        taken = self._taken
        if taken is None:
            return
        self._kept += len(data)
        if self._kept > REPLAY_LIMIT:
            self._taken = None
        else:
            taken.append(data)

    def fall_back(self, delivered: int) -> bool:
        """Replays the entry through Effect's inflater, which reads the rest of it,
        handing out output past the first ``delivered`` bytes. ``False`` when it
        already does, the stream has ended or its input passed ``REPLAY_LIMIT``."""
        if self._effect is not None or self._decompressor.eof or self._taken is None:
            return False
        self._replay = _Replay(self._taken, self._queue)
        self._effect = EffectInflater(self._replay)
        self._skip = delivered
        self._taken = []
        return True

    def _pull_effect(self) -> bytes | NeedInput | None:
        effect = self._effect
        replay = self._replay
        assert effect is not None
        assert replay is not None
        while True:
            out = effect.pull()
            if out is NEED_INPUT:
                return NEED_INPUT
            if out is None:
                replay.give_back()
                return None
            if self._skip >= len(out):
                self._skip -= len(out)
                continue
            if self._skip:
                out = out[self._skip :]
                self._skip = 0
            return out
