"""Effect's raw deflate (RFC 1951) decoder, ``internal/inflate.ts`` line for line.
It reads one stream from a queue without taking a byte past the stream's end, and
its errors and the points where it hands out output are the ones ``Zip.decode``
reports. ``_inflate.Inflater`` runs ``zlib`` and falls back to this one to learn
what Effect reports."""
# The generator below is one function, as in Effect, too large for pyright to infer its
# loop variables
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownMemberType=false

from __future__ import annotations

from collections.abc import Generator
from typing import Protocol

from pyfect.encoding._archive import NEED_INPUT, NeedInput


class InflateError(Exception):
    """Corrupt deflate data; the decoder maps it to its own error."""


class Source(Protocol):
    """What the inflater reads: ``ByteQueue``'s interface."""

    @property
    def length(self) -> int: ...

    def take_some(self, most: int) -> bytes: ...

    def unread(self, data: bytes) -> None: ...


OUTPUT_SIZE = 64 * 1024
_WINDOW_SIZE = 32 * 1024
_BUFFER_SIZE = _WINDOW_SIZE + OUTPUT_SIZE

# Shorter matches are copied faster by a loop than by a slice
_COPY_WITHIN_LENGTH = 32

# The fast path needs room for the longest match, and leaves the buffer short of full
_FAST_OUTPUT_END = _BUFFER_SIZE - 258

# Extra bits of the length codes 257 to 285 and of the distance codes, and the base
# values they are added to (RFC 1951, section 3.2.5)
_LENGTH_EXTRA = tuple(0 if i < 8 or i == 28 else (i >> 2) - 1 for i in range(29))
_DISTANCE_EXTRA = tuple(0 if i < 2 else (i >> 1) - 1 for i in range(30))


def _bases(first: int, extra: tuple[int, ...]) -> list[int]:
    out: list[int] = []
    base = first
    for bits in extra:
        out.append(base)
        base += 1 << bits
    return out


# The last length code is 258, not the 259 its predecessor would give
_LENGTH_BASE = (*_bases(3, _LENGTH_EXTRA[:28]), 258)
_DISTANCE_BASE = tuple(_bases(1, _DISTANCE_EXTRA))

_CODE_LENGTH_ORDER = (16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15)

_PRIMARY_BITS = 10
_LONG = -1

# Each byte with its bits in reverse order, as deflate stores codes
_REVERSED_BYTES = tuple(int(f"{i:08b}"[::-1], 2) for i in range(256))


class _Huffman:
    """``table`` decodes codes of up to ``bits`` bits in one lookup on the next input
    bits. Entries hold ``symbol << 4 | length``, zero for unused codes, or ``_LONG``
    for prefixes of longer codes, which ``_decode_long`` reads bit by bit from
    ``counts`` and ``symbols``."""

    __slots__ = ("bits", "counts", "mask", "symbols", "table")

    def __init__(self) -> None:
        self.table = [0] * (1 << _PRIMARY_BITS)
        self.bits = 0
        self.mask = 0
        self.counts = [0] * 16
        self.symbols = [0] * 288


def _huffman(
    codes: _Huffman, lengths: bytearray | bytes, start: int, end: int, complete: bool
) -> _Huffman:
    """Builds the code of the symbols with lengths ``lengths[start:end]``. As in zlib,
    code length codes must be complete, and other codes may only be incomplete when
    they have a single code of one bit or no codes at all."""
    counts = codes.counts
    symbols = codes.symbols
    table = codes.table
    counts[:] = [0] * 16
    max_length = 0
    for i in range(start, end):
        length = lengths[i]
        counts[length] += 1
        max_length = max(max_length, length)
    counts[0] = 0
    left = 1
    for length in range(1, 16):
        left = (left << 1) - counts[length]
        if left < 0:
            raise InflateError("over-subscribed Huffman code")
    if left > 0 and max_length > 0 and (complete or max_length != 1):
        raise InflateError("incomplete Huffman code")
    next_codes = [0] * 16
    offsets = [0] * 16
    code = 0
    for length in range(1, 16):
        code = (code + counts[length - 1]) << 1
        next_codes[length] = code
        if length < 15:
            offsets[length + 1] = offsets[length] + counts[length]
    bits = min(max(max_length, 1), _PRIMARY_BITS)
    size = 1 << bits
    # Unused codes read as zero
    table[:size] = [0] * size
    for symbol in range(end - start):
        length = lengths[start + symbol]
        if length == 0:
            continue
        symbols[offsets[length]] = symbol
        offsets[length] += 1
        code = next_codes[length]
        next_codes[length] += 1
        reversed_ = ((_REVERSED_BYTES[code & 0xFF] << 8) | _REVERSED_BYTES[code >> 8]) >> (
            16 - length
        )
        if length > bits:
            table[reversed_ & (size - 1)] = _LONG
            continue
        step = 1 << length
        table[reversed_:size:step] = [(symbol << 4) | length] * len(range(reversed_, size, step))
    codes.bits = bits
    codes.mask = size - 1
    return codes


def _decode_long(codes: _Huffman, bit_buffer: int, bit_count: int) -> int:
    """The table entry of the code in the low ``bit_count`` bits of ``bit_buffer``,
    ``_LONG`` when the code needs more bits, or zero when no code matches."""
    code = 0
    first = 0
    index = 0
    counts = codes.counts
    for length in range(1, 16):
        if length > bit_count:
            return _LONG
        code |= (bit_buffer >> (length - 1)) & 1
        count = counts[length]
        if code - count < first:
            return (codes.symbols[index + code - first] << 4) | length
        index += count
        first = (first + count) << 1
        code <<= 1
    return 0


_FIXED_LITERALS = _huffman(
    _Huffman(), bytes([8] * 144 + [9] * 112 + [7] * 24 + [8] * 8), 0, 288, False
)
# Distance codes 30 and 31 complete the fixed code but are invalid
_FIXED_DISTANCES = _huffman(_Huffman(), bytes([5] * 32), 0, 32, False)


class Inflater:
    """Decompresses one deflate stream from ``source``, reading no byte past its end."""

    __slots__ = ("_buffer", "_code_lengths", "_distances", "_generator", "_length_codes",
                 "_lengths", "_literals", "_start")  # fmt: skip

    def __init__(self, source: Source) -> None:
        # The window of earlier output, followed by up to OUTPUT_SIZE bytes of new output
        self._buffer = bytearray(_BUFFER_SIZE)
        self._code_lengths = bytearray(19)
        self._length_codes = _Huffman()
        self._lengths = bytearray(286 + 30)
        self._literals = _Huffman()
        self._distances = _Huffman()
        # Start of the output not handed out yet
        self._start = _WINDOW_SIZE
        self._generator = self._run(source)

    def pull(self) -> bytes | NeedInput | None:
        """Decompressed bytes, ``NEED_INPUT``, or ``None`` once the stream has ended."""
        start = self._start
        done = False
        try:
            end = next(self._generator)
        except StopIteration as stop:
            done = True
            # A finished generator returns None from later calls
            end = start if stop.value is None else stop.value
        if end == start:
            return None if done else NEED_INPUT
        buffer = self._buffer
        out = bytes(buffer[start:end])
        if end == _BUFFER_SIZE:
            # Keep the last output as the window
            buffer[:_WINDOW_SIZE] = buffer[OUTPUT_SIZE:]
            self._start = _WINDOW_SIZE
        else:
            self._start = end
        return out

    def _run(self, queue: Source) -> Generator[int, None, int]:  # noqa: PLR0912, PLR0915
        """Yields the output position when the queue is empty or the buffer is full,
        and returns it at the end. Output follows the window, so matches copy within
        the buffer. A new chunk is only taken when every held bit is needed, so held
        whole bytes always belong to the current chunk and can be given back before
        stored blocks and at the end."""
        buffer = self._buffer
        position: int = _WINDOW_SIZE
        # Matches cannot reach before this index: until the buffer is first full, the
        # window holds no output of this stream
        floor: int = _WINDOW_SIZE
        # The chunk being read; what is left of it goes back to the queue at the end
        input_: bytes = b""
        input_position: int = 0
        bit_buffer: int = 0
        bit_count: int = 0
        final: int = 0
        entry: int
        symbol: int
        length: int
        distance: int
        while True:
            while bit_count < 3:
                if input_position == len(input_):
                    if queue.length == 0:
                        yield position
                        continue
                    input_ = queue.take_some(queue.length)
                    input_position = 0
                bit_buffer |= input_[input_position] << bit_count
                input_position += 1
                bit_count += 8
            final = bit_buffer & 1
            type_ = (bit_buffer >> 1) & 3
            bit_buffer >>= 3
            bit_count -= 3
            if type_ == 0:
                # Stored block: drop the bits up to the byte boundary, then read the
                # length and its complement
                input_position -= bit_count >> 3
                bit_buffer = 0
                bit_count = 0
                while bit_count < 32:
                    if input_position == len(input_):
                        if queue.length == 0:
                            yield position
                            continue
                        input_ = queue.take_some(queue.length)
                        input_position = 0
                    bit_buffer |= input_[input_position] << bit_count
                    input_position += 1
                    bit_count += 8
                length = bit_buffer & 0xFFFF
                if length != (~bit_buffer & 0xFFFFFFFF) >> 16:
                    raise InflateError("stored block length is corrupt")
                bit_buffer = 0
                bit_count = 0
                left = length
                while left > 0:
                    if input_position == len(input_):
                        if queue.length == 0:
                            yield position
                            continue
                        input_ = queue.take_some(queue.length)
                        input_position = 0
                    n = min(left, len(input_) - input_position, _BUFFER_SIZE - position)
                    buffer[position : position + n] = input_[input_position : input_position + n]
                    input_position += n
                    position += n
                    left -= n
                    if position == _BUFFER_SIZE:
                        yield position
                        position = _WINDOW_SIZE
                        floor = 0
                if final:
                    break
                continue
            if type_ == 1:
                literals = _FIXED_LITERALS
                distances = _FIXED_DISTANCES
            elif type_ == 2:
                while bit_count < 14:
                    if input_position == len(input_):
                        if queue.length == 0:
                            yield position
                            continue
                        input_ = queue.take_some(queue.length)
                        input_position = 0
                    bit_buffer |= input_[input_position] << bit_count
                    input_position += 1
                    bit_count += 8
                literal_count = (bit_buffer & 31) + 257
                distance_count = ((bit_buffer >> 5) & 31) + 1
                code_length_count = ((bit_buffer >> 10) & 15) + 4
                bit_buffer >>= 14
                bit_count -= 14
                if literal_count > 286 or distance_count > 30:
                    raise InflateError("too many length or distance codes")
                code_lengths = self._code_lengths
                code_lengths[:] = bytes(19)
                for i in range(code_length_count):
                    while bit_count < 3:
                        if input_position == len(input_):
                            if queue.length == 0:
                                yield position
                                continue
                            input_ = queue.take_some(queue.length)
                            input_position = 0
                        bit_buffer |= input_[input_position] << bit_count
                        input_position += 1
                        bit_count += 8
                    code_lengths[_CODE_LENGTH_ORDER[i]] = bit_buffer & 7
                    bit_buffer >>= 3
                    bit_count -= 3
                length_codes = _huffman(self._length_codes, code_lengths, 0, 19, True)
                length_table = length_codes.table
                lengths = self._lengths
                count = literal_count + distance_count
                i = 0
                while i < count:
                    entry = 0
                    while True:
                        entry = length_table[bit_buffer & length_codes.mask]
                        length = entry & 15
                        if length != 0 and length <= bit_count:
                            break
                        if bit_count >= length_codes.bits:
                            raise InflateError("invalid code length code")
                        if input_position == len(input_):
                            if queue.length == 0:
                                yield position
                                continue
                            input_ = queue.take_some(queue.length)
                            input_position = 0
                        bit_buffer |= input_[input_position] << bit_count
                        input_position += 1
                        bit_count += 8
                    bit_buffer >>= entry & 15
                    bit_count -= entry & 15
                    symbol = entry >> 4
                    if symbol < 16:
                        lengths[i] = symbol
                        i += 1
                        continue
                    extra = 2 if symbol == 16 else 3 if symbol == 17 else 7
                    while bit_count < extra:
                        if input_position == len(input_):
                            if queue.length == 0:
                                yield position
                                continue
                            input_ = queue.take_some(queue.length)
                            input_position = 0
                        bit_buffer |= input_[input_position] << bit_count
                        input_position += 1
                        bit_count += 8
                    repeat = (11 if symbol == 18 else 3) + (bit_buffer & ((1 << extra) - 1))
                    bit_buffer >>= extra
                    bit_count -= extra
                    if symbol == 16 and i == 0:
                        raise InflateError("repeated code length without a previous length")
                    if i + repeat > count:
                        raise InflateError("too many code lengths")
                    value = lengths[i - 1] if symbol == 16 else 0
                    lengths[i : i + repeat] = bytes([value]) * repeat
                    i += repeat
                if lengths[256] == 0:
                    raise InflateError("missing end-of-block code")
                literals = _huffman(self._literals, lengths, 0, literal_count, False)
                distances = _huffman(self._distances, lengths, literal_count, count, False)
            else:
                raise InflateError("invalid block type")
            literal_table = literals.table
            literal_mask = literals.mask
            literal_bits = literals.bits
            distance_table = distances.table
            distance_mask = distances.mask
            distance_bits = distances.bits
            while True:  # symbols
                # Fast path: a symbol with its extra bits and distance takes at most 8
                # input bytes and writes at most 258, so no bounds checks are needed.
                # It reads only from the current chunk, and stops before the buffer
                # fills, which the slow path handles.
                fast_input_end = len(input_) - 8
                end_of_block = False
                while input_position <= fast_input_end and position < _FAST_OUTPUT_END:
                    if bit_count < 15:
                        bit_buffer |= (
                            input_[input_position] | (input_[input_position + 1] << 8)
                        ) << bit_count
                        input_position += 2
                        bit_count += 16
                    entry = literal_table[bit_buffer & literal_mask]
                    # With 15 bits held, a long code is complete or invalid
                    if entry == _LONG:
                        entry = _decode_long(literals, bit_buffer, bit_count)
                    if entry == 0:
                        raise InflateError("invalid literal or length code")
                    bit_buffer >>= entry & 15
                    bit_count -= entry & 15
                    symbol = entry >> 4
                    if symbol < 256:
                        buffer[position] = symbol
                        position += 1
                        continue
                    if symbol == 256:
                        end_of_block = True
                        break
                    length_index = symbol - 257
                    if length_index >= 29:
                        raise InflateError("invalid length code")
                    if bit_count < 15:
                        bit_buffer |= (
                            input_[input_position] | (input_[input_position + 1] << 8)
                        ) << bit_count
                        input_position += 2
                        bit_count += 16
                    length_extra = _LENGTH_EXTRA[length_index]
                    length = _LENGTH_BASE[length_index] + (bit_buffer & ((1 << length_extra) - 1))
                    bit_buffer >>= length_extra
                    bit_count -= length_extra
                    if bit_count < 15:
                        bit_buffer |= (
                            input_[input_position] | (input_[input_position + 1] << 8)
                        ) << bit_count
                        input_position += 2
                        bit_count += 16
                    entry = distance_table[bit_buffer & distance_mask]
                    if entry == _LONG:
                        entry = _decode_long(distances, bit_buffer, bit_count)
                    if entry == 0:
                        raise InflateError("invalid distance code")
                    bit_buffer >>= entry & 15
                    bit_count -= entry & 15
                    distance_index = entry >> 4
                    if distance_index >= 30:
                        raise InflateError("invalid distance code")
                    if bit_count < 13:
                        bit_buffer |= (
                            input_[input_position] | (input_[input_position + 1] << 8)
                        ) << bit_count
                        input_position += 2
                        bit_count += 16
                    distance_extra = _DISTANCE_EXTRA[distance_index]
                    distance = _DISTANCE_BASE[distance_index] + (
                        bit_buffer & ((1 << distance_extra) - 1)
                    )
                    bit_buffer >>= distance_extra
                    bit_count -= distance_extra
                    if distance > position - floor:
                        raise InflateError("distance is beyond the start of the data")
                    from_ = position - distance
                    end = position + length
                    if length < _COPY_WITHIN_LENGTH or distance < length:
                        # A match can repeat the bytes it writes: copy what is already
                        # written, which doubles each time
                        while position < end:
                            n = min(position - from_, end - position)
                            buffer[position : position + n] = buffer[from_ : from_ + n]
                            position += n
                    else:
                        buffer[position:end] = buffer[from_ : from_ + length]
                        position = end
                if end_of_block:
                    break
                entry = 0
                while True:
                    entry = literal_table[bit_buffer & literal_mask]
                    if entry > 0 and (entry & 15) <= bit_count:
                        break
                    if bit_count >= literal_bits:
                        if entry == _LONG:
                            entry = _decode_long(literals, bit_buffer, bit_count)
                        if entry != _LONG:
                            break
                    # A longer code means fewer than 15 bits are held, so two bytes fit
                    if input_position == len(input_):
                        if queue.length == 0:
                            yield position
                            continue
                        input_ = queue.take_some(queue.length)
                        input_position = 0
                    elif input_position + 1 < len(input_):
                        bit_buffer |= (
                            input_[input_position] | (input_[input_position + 1] << 8)
                        ) << bit_count
                        input_position += 2
                        bit_count += 16
                        continue
                    bit_buffer |= input_[input_position] << bit_count
                    input_position += 1
                    bit_count += 8
                if entry == 0:
                    raise InflateError("invalid literal or length code")
                bit_buffer >>= entry & 15
                bit_count -= entry & 15
                symbol = entry >> 4
                if symbol < 256:
                    buffer[position] = symbol
                    position += 1
                    if position == _BUFFER_SIZE:
                        yield position
                        position = _WINDOW_SIZE
                        floor = 0
                    continue
                if symbol == 256:
                    break
                length_index = symbol - 257
                if length_index >= 29:
                    raise InflateError("invalid length code")
                length = _LENGTH_BASE[length_index]
                length_extra = _LENGTH_EXTRA[length_index]
                if length_extra > 0:
                    while bit_count < length_extra:
                        if input_position == len(input_):
                            if queue.length == 0:
                                yield position
                                continue
                            input_ = queue.take_some(queue.length)
                            input_position = 0
                        bit_buffer |= input_[input_position] << bit_count
                        input_position += 1
                        bit_count += 8
                    length += bit_buffer & ((1 << length_extra) - 1)
                    bit_buffer >>= length_extra
                    bit_count -= length_extra
                while True:
                    entry = distance_table[bit_buffer & distance_mask]
                    if entry > 0 and (entry & 15) <= bit_count:
                        break
                    if bit_count >= distance_bits:
                        if entry == _LONG:
                            entry = _decode_long(distances, bit_buffer, bit_count)
                        if entry != _LONG:
                            break
                    # A longer code means fewer than 15 bits are held, so two bytes fit
                    if input_position == len(input_):
                        if queue.length == 0:
                            yield position
                            continue
                        input_ = queue.take_some(queue.length)
                        input_position = 0
                    elif input_position + 1 < len(input_):
                        bit_buffer |= (
                            input_[input_position] | (input_[input_position + 1] << 8)
                        ) << bit_count
                        input_position += 2
                        bit_count += 16
                        continue
                    bit_buffer |= input_[input_position] << bit_count
                    input_position += 1
                    bit_count += 8
                if entry == 0:
                    raise InflateError("invalid distance code")
                bit_buffer >>= entry & 15
                bit_count -= entry & 15
                distance_index = entry >> 4
                if distance_index >= 30:
                    raise InflateError("invalid distance code")
                distance = _DISTANCE_BASE[distance_index]
                distance_extra = _DISTANCE_EXTRA[distance_index]
                if distance_extra > 0:
                    while bit_count < distance_extra:
                        if input_position == len(input_):
                            if queue.length == 0:
                                yield position
                                continue
                            input_ = queue.take_some(queue.length)
                            input_position = 0
                        bit_buffer |= input_[input_position] << bit_count
                        input_position += 1
                        bit_count += 8
                    distance += bit_buffer & ((1 << distance_extra) - 1)
                    bit_buffer >>= distance_extra
                    bit_count -= distance_extra
                if distance > position - floor:
                    raise InflateError("distance is beyond the start of the data")
                while length > 0:
                    end = min(position + length, _BUFFER_SIZE)
                    length -= end - position
                    # A match can repeat the bytes it writes
                    from_ = position - distance
                    while position < end:
                        n = min(position - from_, end - position)
                        buffer[position : position + n] = buffer[from_ : from_ + n]
                        position += n
                    if position == _BUFFER_SIZE:
                        yield position
                        position = _WINDOW_SIZE
                        floor = 0
            if final:
                break
        queue.unread(input_[input_position - (bit_count >> 3) :])
        return position
