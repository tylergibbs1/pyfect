"""Ports of Effect's ``protobuf/ProtobufReader.test.ts``.

Each test's docstring is the Effect test title. A ``bigint`` is an ``int``,
a JavaScript number from a ``*Number`` method a ``float``.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest

from pyfect.protobuf import reader as protobuf_reader
from pyfect.protobuf import writer as protobuf_writer
from pyfect.protobuf.reader import ProtobufReader, ProtobufReaderError, WireType

type Read = Callable[[ProtobufReader], object]


def reader(hex_text: str) -> ProtobufReader:
    return protobuf_reader.make(bytes.fromhex(hex_text))


def failure(hex_text: str, f: Read) -> str:
    with pytest.raises(ProtobufReaderError) as caught:
        f(reader(hex_text))
    return caught.value.message


def _nested(name: str, hex_text: str, message: str) -> list[tuple[str, str, Read, str]]:
    """A varint read after the tag of a nested message, as a uint32 and an int64."""

    def read_with(read: Read) -> Read:
        def run(r: ProtobufReader) -> None:
            r.tag()
            child = r.delimited()
            child.tag()
            read(child)

        return run

    reads: list[tuple[str, Read]] = [
        ("uint32", ProtobufReader.uint32),
        ("int64", ProtobufReader.int64),
    ]
    return [
        (f"{name} the end of a nested message ({label})", hex_text, read_with(read), message)
        for label, read in reads
    ]


READS: list[tuple[str, str, Read, object]] = [
    ("uint32 150", "9601", ProtobufReader.uint32, 150),
    (
        "uint32 of a ten-byte varint, truncated",
        "ffffffffffffffffff01",
        ProtobufReader.uint32,
        4294967295,
    ),
    ("int32 -1", "ffffffffffffffffff01", ProtobufReader.int32, -1),
    ("sint32 -2147483648", "ffffffff0f", ProtobufReader.sint32, -2147483648),
    ("int64 -1n", "ffffffffffffffffff01", ProtobufReader.int64, -1),
    ("uint64 max", "ffffffffffffffffff01", ProtobufReader.uint64, 2**64 - 1),
    ("sint64 -2^63", "ffffffffffffffffff01", ProtobufReader.sint64, -(2**63)),
    ("sint64 2^63 - 1", "feffffffffffffffff01", ProtobufReader.sint64, 2**63 - 1),
    ("bool of a nonzero high half", "8080808010", ProtobufReader.bool, True),
    ("fixed32 max", "ffffffff", ProtobufReader.fixed32, 4294967295),
    ("sfixed32 -2", "feffffff", ProtobufReader.sfixed32, -2),
    ("fixed64 max", "ffffffffffffffff", ProtobufReader.fixed64, 2**64 - 1),
    ("sfixed64 -2n", "feffffffffffffff", ProtobufReader.sfixed64, -2),
    ("uint64Number max, rounded", "ffffffffffffffffff01", ProtobufReader.uint64_number, 2.0**64),
    ("int64Number -1", "ffffffffffffffffff01", ProtobufReader.int64_number, -1.0),
    ("sint64Number -2^63", "ffffffffffffffffff01", ProtobufReader.sint64_number, -(2.0**63)),
    ("sint64Number 1", "02", ProtobufReader.sint64_number, 1.0),
    ("fixed64Number max, rounded", "ffffffffffffffff", ProtobufReader.fixed64_number, 2.0**64),
    ("sfixed64Number -2", "feffffffffffffff", ProtobufReader.sfixed64_number, -2.0),
    ("float 1", "0000803f", ProtobufReader.float, 1.0),
    ("double -0.5", "000000000000e0bf", ProtobufReader.double, -0.5),
    ("string", "09c3a9e697a5f09f9880", ProtobufReader.string, "é日😀"),
]


@pytest.mark.parametrize(("name", "hex_text", "read", "expected"), READS, ids=[r[0] for r in READS])
def test_reads(name: str, hex_text: str, read: Read, expected: object) -> None:
    """ProtobufReader / reads %s"""
    r = reader(hex_text)
    value = read(r)
    assert value == expected
    assert type(value) is type(expected), name
    assert r.is_done()


def test_rounds_64_bit_numbers_as_number_rounds_a_bigint() -> None:
    """ProtobufReader / rounds 64-bit numbers as Number rounds a bigint"""
    values = [2**53 + 1, 2**53 + 3, 2**63 - 1, -(2**53) - 3, 2**60 + 2**8 + 1, -(2**63)]
    for n in values:
        data = protobuf_writer.make().int64(n).sint64(n).sfixed64(n).finish()
        r = protobuf_reader.make(data)
        assert r.int64_number() == float(n)
        assert r.sint64_number() == float(n)
        assert r.sfixed64_number() == float(n)


def test_reads_bytes_as_a_copy() -> None:
    """ProtobufReader / reads bytes as a copy"""
    data = bytearray([2, 1, 2])
    copied = protobuf_reader.make(data).bytes()
    data[1] = 9
    assert copied == bytes([1, 2])


def test_exposes_borrowed_bytes_explicitly_and_respects_nested_limits() -> None:
    """ProtobufReader / exposes borrowed bytes explicitly and respects nested limits"""
    data = bytearray([3, 2, 1, 2, 7])
    r = protobuf_reader.make(data)
    child = r.delimited()
    view = child.bytes_view()
    assert child.is_done()
    data[2] = 9
    assert bytes(view) == bytes([9, 2])
    view[1] = 8
    assert data[3] == 8
    assert r.uint32() == 7


def test_replaces_malformed_utf_8_only_when_requested() -> None:
    """ProtobufReader / replaces malformed UTF-8 only when requested"""
    r = reader("02ff6110")
    assert r.string(validate_utf8=False) == "�a"
    assert r.uint32() == 16
    with pytest.raises(ProtobufReaderError, match="complete value"):
        reader("03ff61").string(validate_utf8=False)


def test_skips_deep_groups_with_a_caller_supplied_bound() -> None:
    """ProtobufReader / skips deep groups with a caller-supplied bound"""
    r = reader("0b" * 4096 + "0c" * 4096 + "082a")
    r.skip(r.tag(), 4096)
    assert r.tag() == 8
    assert r.uint32() == 42
    shallow = reader("0b0c")
    with pytest.raises(ProtobufReaderError, match="groups nested at most 0"):
        shallow.skip(shallow.tag(), 0)
    deeper = reader("0b0b0c0c")
    with pytest.raises(ProtobufReaderError, match="groups nested at most 1"):
        deeper.skip(deeper.tag(), 1)


def test_splits_a_tag_into_its_field_number_and_wire_type() -> None:
    """ProtobufReader / splits a tag into its field number and wire type"""
    tag = reader("8201").tag()
    assert protobuf_reader.field_number(tag) == 16
    assert protobuf_reader.wire_type(tag) is WireType.Len


def test_bounds_child_readers_independently_of_the_parent() -> None:
    """ProtobufReader / bounds child readers independently of the parent"""
    # { 1: { 1: 150 }, 2: { 1: 150 }, 3: 7 }
    r = reader("0a0308960112030896011807")
    r.tag()
    first = r.delimited()
    assert first.offset == 2
    assert r.offset == 5
    assert protobuf_reader.field_number(first.tag()) == 1
    assert first.uint32() == 150
    assert first.is_done()
    with pytest.raises(ProtobufReaderError, match="complete value at offset 5"):
        first.uint32()
    r.tag()
    second = r.delimited()
    assert protobuf_reader.field_number(r.tag()) == 3
    assert r.uint32() == 7
    assert r.is_done()
    # The child remains readable after the parent has advanced.
    assert second.tag() == 8
    assert second.uint32() == 150
    assert second.is_done()


def test_keeps_absolute_offsets_across_several_child_readers() -> None:
    """ProtobufReader / keeps absolute offsets across several child readers"""
    root = reader("03020196")
    child = root.delimited().delimited().delimited()
    assert child.offset == 3
    with pytest.raises(ProtobufReaderError, match="complete value at offset 4"):
        child.uint32()
    assert root.is_done()


def test_skips_every_wire_type_including_nested_groups() -> None:
    """ProtobufReader / skips every wire type, including nested groups"""
    r = reader(
        "08ffffffffffffffffff01"  # 1: varint
        "11000000000000f03f"  # 2: i64
        "1a0161"  # 3: len
        "232b0d010000002c24"  # 4: group { 5: group { 1: i32 } }
        "302a"  # 6: 42
    )
    for _ in range(4):
        r.skip(r.tag())
    assert protobuf_reader.field_number(r.tag()) == 6
    assert r.uint32() == 42
    assert r.is_done()


def _read_nested_string(r: ProtobufReader) -> None:
    r.tag()
    child = r.delimited()
    child.tag()
    child.string()


def _skip_next(r: ProtobufReader) -> None:
    r.skip(r.tag())


_TAG = "Expected a tag with a nonzero field number and a wire type up to 5 at offset 1"
REJECTS: list[tuple[str, str, Read, str]] = [
    ("a truncated varint", "96", ProtobufReader.uint32, "Expected a complete value at offset 1"),
    (
        "a uint32 varint longer than ten bytes",
        "ffffffffffffffffffff01",
        ProtobufReader.uint32,
        "Expected a varint of at most 10 bytes at offset 10",
    ),
    (
        "an int64 varint longer than ten bytes",
        "ffffffffffffffffffff01",
        ProtobufReader.int64,
        "Expected a varint of at most 10 bytes at offset 10",
    ),
    (
        "a truncated fixed64",
        "01020304",
        ProtobufReader.fixed64,
        "Expected a complete value at offset 0",
    ),
    (
        "a length past the end",
        "0561",
        ProtobufReader.string,
        "Expected a complete value at offset 1",
    ),
    # { 1: { 1: <truncated> }, 2: 7, ... }
    *_nested(
        "a varint running past",
        "0a02089610071007100710071007",
        "Expected a complete value at offset 4",
    ),
    # { 1: { 1: <missing> }, 2: 7 }
    *_nested("a varint after", "0a01081007", "Expected a complete value at offset 3"),
    (
        "a length past the end of a nested message",
        # { 1: { 1: "abcde" } } with a nested length of 2
        "0a020a056162636465",
        _read_nested_string,
        "Expected a complete value at offset 4",
    ),
    (
        "a length over 32 bits",
        "ffffffff1f",
        ProtobufReader.bytes,
        "Expected a varint of at most 32 bits at offset 5",
    ),
    ("invalid UTF-8", "01ff", ProtobufReader.string, "Expected valid UTF-8 at offset 1"),
    ("field number 0", "00", ProtobufReader.tag, _TAG),
    ("wire type 6", "0e", ProtobufReader.tag, _TAG),
    (
        "an end group tag without a start",
        "0c",
        _skip_next,
        "Expected a start group tag before the end group tag of field 1 at offset 1",
    ),
    (
        "a mismatched end group tag",
        "0b14",
        _skip_next,
        "Expected an end group tag for field 1 at offset 2",
    ),
    ("an unterminated group", "0b", _skip_next, "Expected a complete value at offset 1"),
    (
        "groups nested deeper than 512",
        "0b" * 513,
        _skip_next,
        "Expected groups nested at most 512 deep at offset 513",
    ),
]


@pytest.mark.parametrize(
    ("name", "hex_text", "read", "message"), REJECTS, ids=[r[0] for r in REJECTS]
)
def test_rejects(name: str, hex_text: str, read: Read, message: str) -> None:
    """ProtobufReader / rejects %s"""
    assert failure(hex_text, read) == message, name
