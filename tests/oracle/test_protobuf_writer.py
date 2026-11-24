"""Ports of Effect's ``protobuf/ProtobufWriter.test.ts``.

Each test's docstring is the Effect test title. A JavaScript number is a
``float`` or an ``int``, a ``bigint`` an ``int``; ``RangeError`` is
``ValueError``.
"""

from __future__ import annotations

import math
from collections.abc import Callable

import pytest

from pyfect.protobuf import writer as protobuf_writer
from pyfect.protobuf.writer import ProtobufWriter, WireType

type Write = Callable[[ProtobufWriter], object]


def write(f: Write) -> str:
    w = protobuf_writer.make()
    f(w)
    return w.finish().hex()


# Encodings from https://protobuf.dev/programming-guides/encoding/
WRITES: list[tuple[str, Write, str]] = [
    ("tag 16 len", lambda w: w.tag(16, WireType.Len), "8201"),
    ("uint32 max", lambda w: w.uint32(4294967295), "ffffffff0f"),
    ("int32 -1 as ten bytes", lambda w: w.int32(-1), "ffffffffffffffffff01"),
    ("int32 2^31, wrapped", lambda w: w.int32(2.0**31), "80808080f8ffffffff01"),
    ("int32 NaN as 0", lambda w: w.int32(math.nan), "00"),
    ("sint32 -2147483648", lambda w: w.sint32(-2147483648), "ffffffff0f"),
    ("int64 2^32 - 1 as number", lambda w: w.int64(2.0**32 - 1), "ffffffff0f"),
    ("int64 2^32 as number", lambda w: w.int64(2.0**32), "8080808010"),
    ("int64 -1 as number", lambda w: w.int64(-1.0), "ffffffffffffffffff01"),
    ("int64 -1 as string", lambda w: w.int64("-1"), "ffffffffffffffffff01"),
    ("int64 -2^32 - 0.5, truncated", lambda w: w.int64(-(2.0**32) - 0.5), "80808080f0ffffffff01"),
    ("uint64 max", lambda w: w.uint64(2**64 - 1), "ffffffffffffffffff01"),
    ("sint64 -2^63", lambda w: w.sint64(-(2**63)), "ffffffffffffffffff01"),
    ("bool true", lambda w: w.bool(True), "01"),
    ("fixed32 max", lambda w: w.fixed32(4294967295), "ffffffff"),
    ("sfixed32 -2", lambda w: w.sfixed32(-2), "feffffff"),
    ("fixed64 max as string", lambda w: w.fixed64("18446744073709551615"), "ffffffffffffffff"),
    ("sfixed64 -2n", lambda w: w.sfixed64(-2), "feffffffffffffff"),
    ("float 1", lambda w: w.float(1), "0000803f"),
    ("double 1", lambda w: w.double(1), "000000000000f03f"),
    ("bytes", lambda w: w.bytes(bytes([1, 2])), "020102"),
    ("raw bytes, without a length", lambda w: w.raw(bytes([1, 2])), "0102"),
    # Two-, three- and four-byte characters, then lone surrogates as U+FFFD
    ("string", lambda w: w.string("é日😀\udc00\ud800a"), "10c3a9e697a5f09f9880efbfbdefbfbd61"),
    ("string longer than the buffer", lambda w: w.string("é" * 1000), "d00f" + "c3a9" * 1000),
]


@pytest.mark.parametrize(("name", "f", "hex_text"), WRITES, ids=[w[0] for w in WRITES])
def test_writes(name: str, f: Write, hex_text: str) -> None:
    """ProtobufWriter / writes %s"""
    assert write(f) == hex_text, name


def test_nests_forks_growing_the_buffer_and_widening_length_prefixes() -> None:
    """ProtobufWriter / nests forks, growing the buffer and widening length prefixes"""

    def nest(w: ProtobufWriter) -> None:
        w.tag(1, WireType.Len).fork()
        w.tag(1, WireType.Len).fork().tag(1, WireType.Len).bytes(bytes(2000)).join()
        w.join()
        w.tag(2, WireType.Varint).uint32(7)

    assert write(nest) == "0ad60f0ad30f0ad00f" + "00" * 2000 + "1007"


def test_throws_for_a_join_without_a_fork_and_a_finish_without_a_join() -> None:
    """ProtobufWriter / throws for a join without a fork, and a finish without a join"""
    with pytest.raises(RuntimeError, match="join without a fork"):
        protobuf_writer.make().join()
    with pytest.raises(RuntimeError, match="not joined"):
        protobuf_writer.make().tag(1, WireType.Len).fork().finish()


def test_rejects_invalid_tags_without_changing_the_written_bytes() -> None:
    """ProtobufWriter / rejects invalid tags without changing the written bytes"""
    w = protobuf_writer.make().uint32(42)
    for number in [0, -1, 0.5, 536870912, math.nan, math.inf]:
        with pytest.raises(ValueError, match="field_number"):
            w.tag(number, WireType.Varint)  # pyright: ignore[reportArgumentType]
    for wire_type in [-1, 0.5, 6, 7, math.nan, math.inf]:
        with pytest.raises(ValueError, match="wire_type"):
            w.tag(1, wire_type)  # pyright: ignore[reportArgumentType]
    assert w.finish().hex() == "2a"
    assert write(lambda w: w.tag(536870911, WireType.I32)) == "fdffffff0f"


def test_writes_exact_lengths_at_prefix_width_boundaries() -> None:
    """ProtobufWriter / writes exact lengths at prefix-width boundaries"""
    for length, prefix in [
        (0, "00"),
        (127, "7f"),
        (128, "8001"),
        (16383, "ff7f"),
        (16384, "808001"),
    ]:
        assert write(lambda w, n=length: w.fork().raw(bytes(n)).join()) == prefix + "00" * length


def test_owns_its_output_across_input_mutation_and_buffer_reuse() -> None:
    """ProtobufWriter / owns its output across input mutation and buffer reuse"""
    data = bytearray([1, 2])
    w = protobuf_writer.make().bytes(data)
    data[:] = b"\x09\x09"
    output = w.finish()
    w.raw(bytes([8]) * 1000).finish()
    protobuf_writer.make().raw(bytes([7]) * 1000).finish()
    assert output == bytes([2, 1, 2])


def test_keeps_writers_apart_and_starts_over_after_finish() -> None:
    """ProtobufWriter / keeps writers apart and starts over after finish"""
    a = protobuf_writer.make().uint32(1)
    b = protobuf_writer.make().uint32(2)
    assert a.finish().hex() == "01"
    c = protobuf_writer.make().uint32(3)
    assert b.finish().hex() == "02"
    a.uint32(4)
    assert c.finish().hex() == "03"
    assert a.finish().hex() == "04"
