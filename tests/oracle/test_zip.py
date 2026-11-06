"""Ports of Effect's ``encoding/Zip.test.ts``, every title. Each test's docstring is
the Effect test title; ``Uint8Array`` is ``bytes``, ``mkUint8Array`` is ``run_bytes``
and ``deflateRawSync`` is ``zlib``'s raw deflate. The fixtures are Effect's, copied to
``fixtures/zip``.

Adapted, with the reason:

- "fails on entries that cannot be written": ``new Date(NaN)`` is a naive ``datetime``,
  Python's date without an instant, and the stored entry without a size is a type
  error, so it goes through ``Any``.
- "dies when the runtime cannot deflate" makes ``zlib.compressobj`` raise, where Effect
  replaces ``CompressionStream``.
- "inflates deflate streams as zlib does" is the port of Effect's inflater test, on
  ``zlib`` itself (``docs/PARITY.md`` section 4); ``tests/oracle/test_archive_node.py``
  compares corrupt streams with what Effect's inflater did under Node.
"""

from __future__ import annotations

import struct
import zlib
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

import pyfect as fx
from pyfect import stream, testing
from pyfect.encoding import zip as Zip
from pyfect.encoding.zip import Entry, ZipError

FIXTURES = Path(__file__).parent / "fixtures" / "zip"
EPOCH_1980 = datetime(1980, 1, 1, tzinfo=UTC)


def utc(*parts: int) -> datetime:
    return datetime(*parts, tzinfo=UTC)


def text(data: bytes) -> str:
    return data.decode("utf-8", "replace")


def encode(items: Sequence[Any]) -> fx.Effect[bytes, Any]:
    source: Any = stream.from_iterable(items)
    return source.pipe_through_channel(Zip.encode()).run_bytes()


def entries(data: bytes, chunk_size: int) -> stream.Stream[Entry[ZipError], ZipError]:
    chunks = [data[i : i + chunk_size] for i in range(0, len(data), chunk_size)]
    return stream.from_iterable(chunks, chunk_size=1).pipe_through_channel(Zip.decode())


def decode(
    data: bytes, chunk_size: int = 4096
) -> fx.Effect[list[tuple[Zip.Header, bytes]], ZipError]:
    def read(entry: Entry[ZipError]) -> fx.Effect[tuple[Zip.Header, bytes], ZipError]:
        return entry.body.run_bytes().map(lambda body: (entry.header, body))

    return entries(data, chunk_size).map_effect(read).run_collect()


def failure(effect: fx.Effect[Any, Any]) -> fx.Effect[object]:
    return effect.flip().map(lambda error: error.kind if Zip.is_zip_error(error) else error)


def bodies_until_failure(data: bytes, chunk_size: int = 4096) -> fx.Effect[list[str]]:
    """Reads every body, and reports the error that ends the archive as its kind."""

    def read(entry: Entry[ZipError]) -> fx.Effect[str, ZipError]:
        return entry.body.run_bytes().map(text)

    return (
        entries(data, chunk_size)
        .map_effect(read)
        .catch_all(lambda error: stream.succeed(error.kind))
        .run_collect()
    )


def xorshift(seed: int) -> Callable[[], int]:
    """Xorshift, for reproducible noise."""
    x = seed

    def next_value() -> int:
        nonlocal x
        x ^= (x << 13) & 0xFFFFFFFF
        x ^= x >> 17
        x ^= (x << 5) & 0xFFFFFFFF
        return x

    return next_value


def le(value: int, length: int) -> bytes:
    return value.to_bytes(length, "little")


END_RECORD = le(0x06054B50, 4) + bytes(18)


def deflate_raw(content: bytes) -> bytes:
    compressor = zlib.compressobj(wbits=-15)
    return compressor.compress(content) + compressor.flush()


def bits(fields: Sequence[tuple[int, ...]]) -> bytes:
    """Deflate data: fields are written least significant bit first, Huffman codes
    most significant bit first, and the last byte is padded with zeros."""
    out = bytearray()
    count = 0
    for value, length, *code in fields:
        for i in range(length):
            if count % 8 == 0:
                out.append(0)
            shift = length - 1 - i if code else i
            out[-1] |= ((value >> shift) & 1) << (count % 8)
            count += 1
    return bytes(out)


def local_header(
    name: bytes,
    *,
    flags: int = 0,
    method: int = 0,
    crc: int = 0,
    compressed_size: int = 0,
    size: int = 0,
    extra: bytes = b"",
) -> bytes:
    return (
        le(0x04034B50, 4)
        + le(20, 2)
        + le(flags, 2)
        + le(method, 2)
        + le(0, 2)
        + le(0x21, 2)
        + le(crc, 4)
        + le(compressed_size, 4)
        + le(size, 4)
        + le(len(name), 2)
        + le(len(extra), 2)
        + name
        + extra
    )


def stored_entry(name: bytes, content: bytes, **fields: Any) -> bytes:
    options: dict[str, Any] = {
        "crc": zlib.crc32(content),
        "compressed_size": len(content),
        "size": len(content),
        **fields,
    }
    return local_header(name, **options) + content


def deflated_entry(name: str, content: bytes, data: bytes | None = None) -> bytes:
    """A deflated entry with its sizes in the local header."""
    compressed = deflate_raw(content) if data is None else data
    return (
        local_header(
            name.encode(),
            method=8,
            crc=zlib.crc32(content),
            compressed_size=len(compressed),
            size=len(content),
        )
        + compressed
    )


def central_directory(data: bytes) -> list[dict[str, Any]]:
    """Fields of the central directory written by ``encode``."""
    end = len(data) - 22
    at = int.from_bytes(data[end + 16 : end + 20], "little")
    count = int.from_bytes(data[end + 10 : end + 12], "little")
    records: list[dict[str, Any]] = []
    for _ in range(count):
        name_length, extra_length, comment_length = struct.unpack_from("<HHH", data, at + 28)
        records.append(
            {
                "path": text(data[at + 46 : at + 46 + name_length]),
                "host": data[at + 5],
                "flags": struct.unpack_from("<H", data, at + 8)[0],
                "compressed_size": struct.unpack_from("<I", data, at + 20)[0],
                "external": struct.unpack_from("<I", data, at + 38)[0],
                "offset": struct.unpack_from("<I", data, at + 42)[0],
            }
        )
        at += 46 + name_length + extra_length + comment_length
    return records


@testing.effect
def test_round_trips_entries_in_any_chunk_size() -> Any:
    """round trips entries in any chunk size"""
    mtime = utc(2024, 1, 2, 3, 4, 6)
    big = bytes((i * i) % 251 for i in range(200_000))
    items = [
        Zip.directory("dir", mtime=mtime),
        Zip.file("dir/a.txt", "hello\n" * 100, mtime=mtime),
        Zip.file("stored.bin", big, method="Store"),
        Zip.file("empty.txt", ""),
        Zip.file("ünïcødé/文件.txt", "unicode"),
        Zip.file_stream("stream.bin", stream.make(big[:70_000], big[70_000:]), size=len(big)),
        Zip.file_stream(
            "stream-stored.bin", stream.make(big[:5], big[5:]), method="Store", size=len(big)
        ),
    ]
    data = yield from encode(items)
    for chunk_size in (7, len(data)):
        output = yield from decode(data, chunk_size)
        assert [
            (header.path, header.type, header.method, header.mtime, header.size)
            for header, _ in output
        ] == [
            ("dir/", "Directory", "Store", mtime, 0),
            ("dir/a.txt", "File", "Deflate", mtime, 600),
            ("stored.bin", "File", "Store", EPOCH_1980, len(big)),
            ("empty.txt", "File", "Deflate", EPOCH_1980, 0),
            ("ünïcødé/文件.txt", "File", "Deflate", EPOCH_1980, 7),
            # Deflated sizes that follow the data are not known up front
            ("stream.bin", "File", "Deflate", EPOCH_1980, None),
            ("stream-stored.bin", "File", "Store", EPOCH_1980, len(big)),
        ]
        assert [body for _, body in output] == [
            b"",
            b"hello\n" * 100,
            big,
            b"",
            b"unicode",
            big,
            big,
        ]


@testing.effect
def test_writes_unix_modes_directory_attributes_and_utf_8_flags() -> Any:
    """writes Unix modes, directory attributes and UTF-8 flags"""
    data = yield from encode(
        [
            Zip.directory("dir"),
            Zip.file("dir/run.sh", "", mode=0o755),
            Zip.file_stream("文件", stream.make(b"x")),
        ]
    )
    assert [
        (r["path"], r["host"], r["flags"], r["external"] >> 16, r["external"] & 0xFFFF)
        for r in central_directory(data)
    ] == [
        # Unix file type and permission bits, then MS-DOS attributes
        ("dir/", 3, 0, 0o40755, 0x10),
        ("dir/run.sh", 3, 0, 0o100755, 0),
        ("文件", 3, 0x0808, 0o100644, 0),
    ]


@testing.effect
def test_keeps_times_in_whole_seconds_and_clamps_them_to_the_dos_range() -> Any:
    """keeps times in whole seconds and clamps them to the DOS range"""
    times = [
        utc(1970, 1, 1, 0, 0, 5),
        datetime(2001, 2, 3, 4, 5, 6, 789000, tzinfo=UTC),
        # Outside the extended timestamp range, only the DOS time is written
        utc(2050, 6, 7, 8, 9, 11),
        utc(2200, 1, 1),
        utc(1969, 12, 31, 23, 59, 59),
    ]
    output = yield from decode(
        (yield from encode([Zip.file(time.isoformat(), "", mtime=time) for time in times]))
    )
    assert [header.mtime for header, _ in output] == [
        utc(1970, 1, 1, 0, 0, 5),
        utc(2001, 2, 3, 4, 5, 6),
        utc(2050, 6, 7, 8, 9, 10),
        utc(2107, 12, 31, 23, 59, 58),
        utc(1980, 1, 1),
    ]


@testing.effect
def test_fails_on_entries_that_cannot_be_written() -> Any:
    """fails on entries that cannot be written"""
    file_stream: Any = Zip.file_stream
    invalid: list[Any] = [
        Zip.directory(""),
        Zip.file("/etc/passwd", "x"),
        # libarchive and Windows tools read backslashes as separators, and drive letters as roots
        Zip.file("..\\x", "x"),
        Zip.file("C:x", "x"),
        Zip.file("a\0b", "x"),
        Zip.file("dir/", "x"),
        # A type error for checked callers, and a runtime error for the rest
        file_stream("f", stream.make(b"x"), method="Store"),
        Zip.file("f", "x", mode=0o10000),
        Zip.file("f", "x", mtime=datetime(2024, 1, 1)),
    ]
    for entry in invalid:
        assert (yield from failure(encode([entry]))) == "InvalidHeader", entry


def test_dies_when_the_runtime_cannot_deflate(monkeypatch: pytest.MonkeyPatch) -> None:
    """dies when the runtime cannot deflate"""

    def broken(*_: Any, **__: Any) -> Any:
        raise TypeError("unsupported format")

    monkeypatch.setattr(zlib, "compressobj", broken)
    for entry in (Zip.file("a", "a"), Zip.file_stream("a", stream.make(b"a"))):
        result = fx.run_blocking_exit(encode([entry]))
        assert isinstance(result, fx.Failure)
        assert result.cause.has_dies


@testing.effect
def test_fails_on_body_errors_and_bodies_that_do_not_match_their_size() -> Any:
    """fails on body errors and bodies that do not match their size"""
    body = stream.make(b"abc")
    file_stream: Any = Zip.file_stream
    for method in ("Store", "Deflate"):
        for size in (5, 2):
            entry = file_stream("f", body, method=method, size=size)
            assert (yield from failure(encode([entry]))) == "SizeMismatch"
        failing = body.concat(stream.fail("Boom"))
        assert (yield from failure(encode([file_stream("f", failing, method=method, size=4)]))) == (
            "Boom"
        )
    assert (yield from failure(encode([Entry(Zip.directory("d").header, body)]))) == "SizeMismatch"


@testing.effect
def test_declares_zip64_in_the_local_header_of_streamed_entries_without_a_size() -> Any:
    """declares ZIP64 in the local header of streamed entries without a size"""
    content = b"a" * 300
    data = yield from encode(
        [
            Zip.file_stream("unknown", stream.make(content)),
            Zip.file_stream("known", stream.make(content), size=len(content)),
        ]
    )
    records = central_directory(data)
    central_offset = struct.unpack_from("<I", data, len(data) - 22 + 16)[0]
    ends = [record["offset"] for record in records[1:]] + [central_offset]
    layouts: list[tuple[int, bool, int]] = []
    for record, end in zip(records, ends, strict=True):
        offset = record["offset"]
        (version,) = struct.unpack_from("<H", data, offset + 4)
        name_length, extra_length = struct.unpack_from("<HH", data, offset + 26)
        extra = offset + 30 + name_length
        extra_end = extra + extra_length
        ids: list[int] = []
        at = extra
        while at < extra_end:
            field_id, field_length = struct.unpack_from("<HH", data, at)
            ids.append(field_id)
            at += 4 + field_length
        layouts.append((version, 0x0001 in ids, end - extra_end - record["compressed_size"]))
    assert layouts == [(45, True, 24), (20, False, 16)]


@testing.effect
def test_writes_zip64_end_records_for_65535_entries_or_more() -> Any:
    """writes ZIP64 end records for 65535 entries or more"""
    count = 65_535
    data = yield from encode([Zip.file(f"{i}", "", method="Store") for i in range(count)])
    end = len(data) - 22
    assert struct.unpack_from("<H", data, end + 10)[0] == 0xFFFF
    end64 = end - 20 - 56
    assert struct.unpack_from("<I", data, end64)[0] == 0x06064B50
    assert struct.unpack_from("<I", data, end64 + 32)[0] == count
    assert struct.unpack_from("<I", data, end - 20 + 8)[0] == end64


_TREE: list[tuple[str, str, str]] = [
    ("tree/", "Directory", ""),
    ("tree/dir/", "Directory", ""),
    ("tree/dir/hello.txt", "File", "Hello, zip!\n" * 50),
    ("tree/empty.txt", "File", ""),
    ("tree/ünïcødé.txt", "File", "unicode\n"),
    ("tree/script.sh", "File", "#!/bin/sh\necho hi\n"),
]
_DEFLATED: dict[str, Zip.Method] = {
    "tree/dir/hello.txt": "Deflate",
    "tree/ünïcødé.txt": "Deflate",
    "tree/script.sh": "Deflate",
}


def _expected(methods: dict[str, Zip.Method]) -> list[tuple[str, str, str, str]]:
    return [(path, kind, methods.get(path, "Store"), body) for path, kind, body in _TREE]


_FIXTURES: dict[str, list[tuple[str, str, str, str]]] = {
    "infozip": _expected({"tree/dir/hello.txt": "Deflate"}),
    # Info-ZIP streams empty files as stored entries without a size
    "infozip-stream": [e for e in _expected(_DEFLATED) if e[0] != "tree/empty.txt"],
    "7zip": sorted(_expected({"tree/dir/hello.txt": "Deflate"}), key=lambda e: e[0]),
    "python-zip64": [
        e for e in _expected(_DEFLATED) if e[0] in ("tree/dir/hello.txt", "tree/script.sh")
    ],
}


@pytest.mark.parametrize("name", list(_FIXTURES))
@testing.effect
def test_reads_archives_in_any_chunk_size(name: str) -> Any:
    """reads infozip archives in any chunk size
    reads infozip-stream archives in any chunk size
    reads 7zip archives in any chunk size
    reads python-zip64 archives in any chunk size"""
    data = (FIXTURES / f"{name}.zip").read_bytes()
    for chunk_size in (1, len(data)):
        output = yield from decode(data, chunk_size)
        assert [(h.path, h.type, h.method, text(body)) for h, body in output] == _FIXTURES[name]
        assert {h.mtime for h, _ in output} == {utc(2024, 1, 2, 3, 4, 6)}


@testing.effect
def test_reads_zip64_sizes_and_data_descriptors_without_a_signature() -> Any:
    """reads ZIP64 sizes and data descriptors without a signature"""
    content = b"descriptor " * 40
    data = deflate_raw(content)
    name = b"f"
    zip64 = le(0x0001, 2) + le(16, 2) + le(len(content), 8) + le(len(data), 8)
    variants = [
        (
            local_header(
                name,
                method=8,
                crc=zlib.crc32(content),
                compressed_size=0xFFFFFFFF,
                size=0xFFFFFFFF,
                extra=zip64,
            ),
            b"",
        ),
        (
            local_header(name, flags=8, method=8),
            le(zlib.crc32(content), 4) + le(len(data), 4) + le(len(content), 4),
        ),
        (
            local_header(name, flags=8, method=8),
            le(0x08074B50, 4) + le(zlib.crc32(content), 4) + le(len(data), 8) + le(len(content), 8),
        ),
    ]
    for header, descriptor in variants:
        output = yield from decode(header + data + descriptor + END_RECORD, 5)
        assert [body for _, body in output] == [content]


@testing.effect
def test_fails_on_stored_entries_whose_sizes_follow_their_data() -> Any:
    """fails on stored entries whose sizes follow their data"""
    # Searching for the descriptor would let this content forge an entry
    forged = (
        b"data"
        + le(0x08074B50, 4)
        + le(zlib.crc32(b"data"), 4)
        + le(4, 4)
        + le(4, 4)
        + local_header(b"../evil.sh")
    )
    archive = (
        stored_entry(b"ok", b"ok")
        + local_header(b"upload.bin", flags=8)
        + forged
        + le(0x08074B50, 4)
        + le(zlib.crc32(forged), 4)
        + le(len(forged), 4)
        + le(len(forged), 4)
        + END_RECORD
    )

    def read(entry: Entry[ZipError]) -> fx.Effect[str, ZipError]:
        return entry.body.run_bytes().map(lambda _: entry.header.path)

    output = yield from (
        entries(archive, 4096)
        .map_effect(read)
        .catch_all(lambda error: stream.succeed(error.kind))
        .run_collect()
    )
    assert output == ["ok", "Unsupported"]


@testing.effect
def test_decodes_names_as_cp437_or_from_a_unicode_path_field() -> Any:
    """decodes names as CP437 or from a Unicode path field"""

    def unicode_path(name: str, crc: int) -> bytes:
        encoded = name.encode()
        return le(0x7075, 2) + le(5 + len(encoded), 2) + b"\x01" + le(crc, 4) + encoded

    archive = (
        stored_entry(bytes((0x81, 0x41)), b"")
        + stored_entry(b"x", b"", extra=unicode_path("ÿ.txt", zlib.crc32(b"x")))
        # The field applies only when its CRC-32 matches the name
        + stored_entry(b"y", b"", extra=unicode_path("ignored", 0))
        + END_RECORD
    )
    assert [header.path for header, _ in (yield from decode(archive))] == ["üA", "ÿ.txt", "y"]


@testing.effect
def test_inflates_deflate_streams_as_zlib_does() -> Any:
    """inflates deflate streams as zlib does"""
    random = xorshift(7)
    # Noise, which deflate stores, then copies from it at distances that are rarer
    # the nearer they are, so that some codes are long
    sparse: list[int] = [random() & 0xFF for _ in range(32_768)]
    for _ in range(4000):
        leading = 32 - random().bit_length()
        distance_bits = 14 - min(leading, 12)
        distance: int = 2**distance_bits + random() % 2**distance_bits
        for _ in range(8):
            sparse.append(sparse[len(sparse) - distance])
        sparse.append(random() & 0xFF)
    block = bytes(random() & 0xFF for _ in range(32_500))
    contents = [bytes(sparse)]
    for size in (65_536, 131_073):
        contents += [
            bytes(random() & 0xFF for _ in range(size)),
            bytes(random() & 63 for _ in range(size)),
            bytes(block[i % len(block)] for i in range(size)),
        ]
    archive = b"".join(deflated_entry("f", content) for content in contents) + END_RECORD
    for chunk_size in (7, len(archive)):
        assert [body for _, body in (yield from decode(archive, chunk_size))] == contents


@testing.effect
def test_inflates_matches_that_end_at_an_output_buffer_boundary() -> Any:
    """inflates matches that end at an output buffer boundary"""
    content = b"abc" + bytes(65_533) + b"b" + b"hello world " * 100
    archive = deflated_entry("f", content) + END_RECORD
    assert [body for _, body in (yield from decode(archive, len(archive)))] == [content]


@testing.effect
def test_ends_deflate_streams_that_close_with_a_stored_block_at_their_last_byte() -> Any:
    """ends deflate streams that close with a stored block at their last byte"""
    # A fixed Huffman block with "ab" and a stored block with "c". The end code reads
    # input ahead of the stored block, which starts at a byte boundary.
    data = (
        bits(((0, 1), (1, 2), (0x30 + 97, 8, 1), (0x30 + 98, 8, 1), (0, 7, 1), (1, 1), (0, 2)))
        + le(1, 2)
        + le(0xFFFE, 2)
        + b"c"
    )
    archive = deflated_entry("f", b"abc", data) + stored_entry(b"g", b"next") + END_RECORD
    for chunk_size in (1, len(archive)):
        assert [text(body) for _, body in (yield from decode(archive, chunk_size))] == [
            "abc",
            "next",
        ]


@testing.effect
def test_does_not_resolve_matches_against_the_output_of_earlier_entries() -> Any:
    """does not resolve matches against the output of earlier entries"""
    # "b" is one fixed-code block copying 258 bytes from 1000 bytes back, which only
    # the output of "a" could supply
    a = bytes((i * i) % 251 for i in range(65_536))
    b = a[-1000 : -1000 + 258]
    copy = bits(((1, 1), (1, 2), (0xC5, 8, 1), (19, 5, 1), (1000 - 769, 8), (0, 7, 1)))
    archive = deflated_entry("a", a) + deflated_entry("b", b, copy) + END_RECORD
    for chunk_size in (7, len(archive)):
        assert (yield from bodies_until_failure(archive, chunk_size)) == [text(a), "InvalidData"]


@testing.effect
def test_stops_a_body_that_grows_past_its_size_and_the_archive_with_it() -> Any:
    """stops a body that grows past its size and the archive with it"""
    content = bytes(1_000_000)
    data = deflate_raw(content)
    archive = (
        local_header(b"a", method=8, crc=zlib.crc32(content), compressed_size=len(data), size=10)
        + data
        + stored_entry(b"b", b"b")
        + END_RECORD
    )
    read = 0

    def count(chunk: bytes) -> fx.Effect[None]:
        def add() -> None:
            nonlocal read
            read += len(chunk)

        return fx.sync(add)

    output = entries(archive, 4096).map_effect(lambda entry: entry.body.run_for_each(count))
    assert (yield from failure(output.run_collect())) == "SizeMismatch"
    assert read <= 10


@testing.effect
def test_emits_body_bytes_before_the_rest_of_the_archive_arrives() -> Any:
    """emits body bytes before the rest of the archive arrives"""
    data = yield from encode([Zip.file("f", "z" * 2000, method="Store")])
    # Local header: 30 bytes, the name and an extended timestamp field
    header = 30 + 1 + 9
    source = yield from fx.Queue[bytes, fx.Done].unbounded()
    yield from source.offer(data[: header + 100])
    pull_entry = yield from stream.from_queue(source).pipe_through_channel(Zip.decode()).to_pull()
    (entry,) = yield from pull_entry
    pull_body = yield from entry.body.to_pull()
    assert text((yield from pull_body)[0]) == "z" * 100

    yield from source.offer(data[header + 100 :])
    yield from source.end()
    rest = 0
    while True:
        result = yield from pull_body.exit()
        if not isinstance(result, fx.Success):
            break
        rest += sum(map(len, result.value))
    assert rest == 1900


@testing.effect
def test_skips_unread_bodies_when_moving_to_the_next_entry() -> Any:
    """skips unread bodies when moving to the next entry"""
    data = yield from encode(
        [
            Zip.file("a", "a" * 100_000),
            Zip.file_stream("b", stream.make(b"b" * 700), method="Store", size=700),
            Zip.file_stream("c", stream.make(b"c" * 700)),
            Zip.file("d", "d"),
        ]
    )

    def first_byte(entry: Entry[ZipError]) -> fx.Effect[int, ZipError]:
        return entry.body.take(1).run_bytes().map(lambda body: body[0])

    for chunk_size in (1, len(data)):
        output = yield from entries(data, chunk_size).map_effect(first_byte).run_collect()
        assert output == [ord(c) for c in "abcd"]


@testing.effect
def test_fails_body_reads_after_the_next_entry_is_pulled_or_the_entries_end() -> Any:
    """fails body reads after the next entry is pulled or the entries end"""
    data = yield from encode([Zip.file("a", "a"), Zip.file("b", "b")])
    pull = yield from entries(data, 512).to_pull()
    (a,) = yield from pull
    yield from pull
    assert (yield from failure(a.body.run_drain())) == "BodyConsumed"
    (first,) = yield from entries(data, 512).take(1).run_collect()
    assert (yield from failure(first.body.run_drain())) == "BodyConsumed"


@testing.effect
def test_reads_empty_archives_and_ignores_input_after_the_central_directory() -> Any:
    """reads empty archives and ignores input after the central directory"""
    assert (yield from decode(END_RECORD)) == []
    data = (yield from encode([Zip.file("a", "a")])) + b"trailing comment"
    assert [text(body) for _, body in (yield from decode(data))] == ["a"]


@testing.effect
def test_fails_on_truncated_or_corrupt_archives() -> Any:
    """fails on truncated or corrupt archives"""
    streamed = yield from encode(
        [
            Zip.file_stream("a", stream.make(b"a" * 300)),
            Zip.file_stream("b", stream.make(b"b"), method="Store", size=1),
        ]
    )
    central_offset = struct.unpack_from("<I", streamed, len(streamed) - 6)[0]
    for length in range(central_offset + 4):
        assert (yield from failure(decode(streamed[:length], 16))) == "Truncated", length
    data = yield from encode([Zip.file("a", "a" * 600, method="Store")])
    assert (yield from failure(decode(b"\0" + data))) == "InvalidHeader"
    corrupt = bytearray(data)
    corrupt[100] ^= 1
    assert (yield from failure(decode(bytes(corrupt)))) == "Checksum"

    content = b"deflated"
    deflated_data = deflate_raw(content)

    def deflated(**fields: Any) -> bytes:
        options: dict[str, Any] = {
            "method": 8,
            "crc": zlib.crc32(content),
            "compressed_size": len(deflated_data),
            "size": len(content),
            **fields,
        }
        return local_header(b"f", **options) + deflated_data + END_RECORD

    assert (yield from failure(decode(deflated(size=len(content) + 1)))) == "SizeMismatch"
    assert (yield from failure(decode(deflated(flags=1)))) == "Unsupported"
    assert (yield from failure(decode(deflated(method=12)))) == "Unsupported"
    # Stored entries need equal sizes
    assert (yield from failure(decode(deflated(method=0)))) == "InvalidHeader"
    assert (
        yield from failure(decode(deflated_entry("a", content, b"\xff") + END_RECORD))
    ) == "InvalidData"
    # Other tools end names at a NUL character, or reject them
    nul = stored_entry(b"a.txt\0../b", b"") + END_RECORD
    assert (yield from failure(decode(nul))) == "InvalidHeader"
