"""Mutated raw deflate streams for ``test_inflate_node.py``. The streams come from the
local zlib, so they are recorded in the fixture with Effect's results; regenerate both
together, under Node:
  uv run python tests/oracle/_inflate_corpus.py > corpus.json
  node tests/oracle/inflate_oracle.ts corpus.json > tests/oracle/fixtures/inflate_oracle.json
"""

from __future__ import annotations

import base64
import json
import random
import struct
import zlib
from typing import Any

COUNT = 1200


def zip_archive(data: bytes, crc: int, size: int) -> bytes:
    """A deflated entry ``f`` with ``data`` and sizes in its local header, a stored entry
    after it and an end record."""

    def local(name: bytes, method: int, crc: int, compressed: int, size: int) -> bytes:
        header = struct.pack(
            "<IHHHHHIIIHH", 0x04034B50, 20, 0, method, 0, 0x21, crc, compressed, size, 1, 0
        )
        return header + name

    end = struct.pack("<IHHHHIIH", 0x06054B50, 0, 0, 0, 0, 0, 0, 0)
    stored = local(b"g", 0, zlib.crc32(b"next"), 4, 4) + b"next"
    return local(b"f", 8, crc, len(data), size) + data + stored + end


class _Corpus:
    def __init__(self, seed: int) -> None:
        self.rng = random.Random(seed)

    def content(self) -> bytes:
        rng = self.rng
        size = rng.choice([0, 1, 3, 50, 300, 1500, 70000])
        kind = rng.randrange(5)
        if size == 70000 and kind in (0, 1, 3):
            kind = 4
        if kind == 0:
            return rng.randbytes(size)
        if kind == 1:
            return bytes(rng.randrange(4) for _ in range(size))
        if kind == 2:
            return (b"the quick brown fox jumps over the lazy dog " * (size // 40 + 1))[:size]
        if kind == 3:
            return bytes(rng.randrange(64) for _ in range(size))
        return bytes(size)

    def deflate(self, body: bytes) -> bytes:
        rng = self.rng
        strategy = rng.choice(
            [
                zlib.Z_DEFAULT_STRATEGY,
                zlib.Z_FILTERED,
                zlib.Z_HUFFMAN_ONLY,
                zlib.Z_RLE,
                zlib.Z_FIXED,
            ]
        )
        compressor = zlib.compressobj(
            rng.choice([0, 1, 6, 9] if len(body) < 5000 else [1, 6, 9]),
            zlib.DEFLATED,
            -rng.choice([9, 15]),
            8,
            strategy,
        )
        if rng.random() < 0.2 and len(body) > 10:
            cut = rng.randrange(len(body))
            return (
                compressor.compress(body[:cut])
                + compressor.flush(zlib.Z_SYNC_FLUSH)
                + compressor.compress(body[cut:])
                + compressor.flush()
            )
        return compressor.compress(body) + compressor.flush()

    def position(self, n: int) -> int:
        """Mostly near the start, where block headers are."""
        rng = self.rng
        if rng.random() < 0.6:
            return min(n - 1, int(rng.expovariate(1 / max(1, min(n, 200)))))
        return rng.randrange(n)

    def mutate(self, data: bytes) -> bytes:
        rng = self.rng
        out = bytearray(data)
        for _ in range(rng.choice([1, 1, 1, 2, 3])):
            n = len(out)
            kind = rng.randrange(8) if n else 6
            if kind <= 2:
                out[self.position(n)] ^= 1 << rng.randrange(8)
            elif kind == 3:
                out[self.position(n)] = rng.randrange(256)
            elif kind == 4:
                del out[rng.randrange(n + 1) :]
            elif kind == 5:
                at = self.position(n)
                del out[at : at + rng.randrange(1, 9)]
            elif kind == 6:
                at = rng.randrange(n + 1)
                out[at:at] = rng.randbytes(rng.randrange(1, 9))
            else:
                at = self.position(n)
                out[at : at + 4] = rng.randbytes(4)
        return bytes(out)

    def dynamic_header(self, body: bytes) -> bytes:
        """Random bits read as a dynamic block header, sometimes with a run of zeros (a
        code length code without codes), after a block that is not the last."""
        rng = self.rng
        head = b""
        if rng.random() < 0.3:
            compressor = zlib.compressobj(6, zlib.DEFLATED, -15)
            head = compressor.compress(body[:100]) + compressor.flush(zlib.Z_SYNC_FLUSH)
        tail = bytearray(rng.randbytes(rng.randrange(2, 200)))
        tail[0] = (tail[0] & ~7) | rng.choice([4, 5])
        if rng.random() < 0.5:
            zeros = rng.randrange(4, 60)
            tail[2 : 2 + zeros] = bytes(zeros)
        return head + bytes(tail)

    def splits(self, n: int) -> list[int]:
        rng = self.rng
        kind = rng.randrange(4)
        if kind == 0 or n == 0:
            return [n]
        out: list[int] = []
        left = n
        top = rng.choice([3, 50, 2000] if n <= 3000 else [500, 5000])
        while left > 0:
            size = min(left, rng.randrange(1, top + 1))
            out.append(size)
            left -= size
        return out

    def case(self, index: int) -> dict[str, Any]:
        rng = self.rng
        body = self.content()
        kind = rng.random()
        if kind < 0.03:
            data = rng.randbytes(rng.randrange(1, 64))
        elif kind < 0.2:
            data = self.dynamic_header(body)
        elif kind < 0.3:
            data = self.deflate(body)
        else:
            data = self.mutate(self.deflate(body))
        trailer = rng.choice([b"", b"PK\x03\x04trailer"])
        size = len(body) if rng.random() < 0.7 else rng.randrange(len(body) + 1)
        archive = zip_archive(data, zlib.crc32(body), size)
        return {
            "id": str(index),
            "data": base64.b64encode(data + trailer).decode(),
            "splits": self.splits(len(data + trailer)),
            # The deflate data without the trailer, entry ``f`` of the zip archive
            "compressed": len(data),
            "crc": zlib.crc32(body),
            "size": size,
            "zipSplits": self.splits(len(archive)),
        }


MESSAGES = (
    "over-subscribed Huffman code",
    "incomplete Huffman code",
    "stored block length is corrupt",
    "too many length or distance codes",
    "invalid code length code",
    "repeated code length without a previous length",
    "too many code lengths",
    "missing end-of-block code",
    "invalid block type",
    "invalid literal or length code",
    "invalid length code",
    "invalid distance code",
    "distance is beyond the start of the data",
)


class _Bits:
    """Deflate's bit order: values from their low bit, Huffman codes from their high bit."""

    def __init__(self) -> None:
        self.bits: list[int] = []

    def value(self, value: int, count: int) -> _Bits:
        self.bits += [(value >> i) & 1 for i in range(count)]
        return self

    def code(self, code: str) -> _Bits:
        self.bits += [int(bit) for bit in code]
        return self

    def bytes(self) -> bytes:
        bits = self.bits + [0] * (-len(self.bits) % 8)
        return bytes(
            sum(bit << i for i, bit in enumerate(bits[at : at + 8]))
            for at in range(0, len(bits), 8)
        )


_ORDER = (16, 17, 18, 0, 8, 7, 9, 6, 10, 5, 11, 4, 12, 3, 13, 2, 14, 1, 15)


def _dynamic(literals: int, distances: int, code_lengths: dict[int, int]) -> _Bits:
    """A final dynamic block header up to its code length code."""
    count = max([_ORDER.index(symbol) + 1 for symbol in code_lengths] + [4])
    bits = _Bits().value(1, 1).value(2, 2)
    bits.value(literals - 257, 5).value(distances - 1, 5).value(count - 4, 4)
    for symbol in _ORDER[:count]:
        bits.value(code_lengths.get(symbol, 0), 3)
    return bits


def per_message() -> list[bytes]:
    """A stream for each error of Effect's inflater, in the order of ``MESSAGES``."""
    # Code length codes 18 ("0"), 0 ("10") and 1 ("11")
    zeros = {18: 1, 0: 2, 1: 2}
    return [
        _dynamic(257, 1, {16: 1, 17: 1, 18: 1, 0: 1}).bytes(),
        _dynamic(257, 1, {16: 2}).bytes(),
        _Bits().value(1, 1).value(0, 2).value(0, 5).value(1, 16).value(0, 16).bytes(),
        _dynamic(287, 1, {}).bytes(),
        _dynamic(257, 1, {}).value(0, 16).bytes(),
        _dynamic(257, 1, {16: 1, 0: 1}).code("1").value(0, 2).bytes(),
        _dynamic(257, 1, zeros).code("0").value(127, 7).code("0").value(127, 7).bytes(),
        _dynamic(257, 1, zeros).code("0").value(127, 7).code("0").value(109, 7).bytes(),
        _Bits().value(1, 1).value(3, 2).bytes(),
        # Only the end-of-block code, "0", and one distance code, so "1" is unused
        _dynamic(257, 1, zeros)
        .code("0")
        .value(127, 7)
        .code("0")
        .value(107, 7)
        .code("11")
        .code("11")
        .code("1")
        .bytes(),
        _Bits().value(1, 1).value(1, 2).code("11000110").bytes(),
        _Bits().value(1, 1).value(1, 2).code("0000001").code("11110").bytes(),
        _Bits()
        .value(1, 1)
        .value(1, 2)
        .code(f"{0x30 + 97:08b}")
        .code("0000001")
        .code("00001")
        .bytes(),
    ]


def stored_then_match() -> bytes:
    """70,000 stored bytes, past the first 64 KiB of output, then a fixed block copying
    258 bytes from 1,000 back."""
    noise = random.Random(5).randbytes(70000)
    stored = b"".join(
        bytes([0]) + struct.pack("<HH", len(part), len(part) ^ 0xFFFF) + part
        for part in (noise[:65535], noise[65535:])
    )
    copy = _Bits().value(1, 1).value(1, 2).code("11000101").code("10011").value(231, 8)
    return stored + copy.code("0000000").bytes()


def corpus() -> list[dict[str, Any]]:
    cases = _Corpus(17)
    out = [cases.case(index) for index in range(COUNT)]
    special = [(f"message/{index}", data) for index, data in enumerate(per_message())]
    wrap = stored_then_match()
    special += [("wrap", wrap), ("wrap/corrupt", wrap[:-3] + bytes([wrap[-3] ^ 0x10]) + wrap[-2:])]
    for id_, data in special:
        out.append(
            {
                "id": id_,
                "data": base64.b64encode(data).decode(),
                "splits": [len(data)],
                "compressed": len(data),
                "crc": 0,
                "size": 0,
                "zipSplits": [len(zip_archive(data, 0, 0))],
            }
        )
    return out


if __name__ == "__main__":
    print(json.dumps(corpus()))
