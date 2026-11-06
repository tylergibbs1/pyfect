"""The archive bytes ``encode`` writes."""

from __future__ import annotations

import struct
import zlib
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta

from pyfect._js import text_encode
from pyfect._json_text import quote as quoted
from pyfect.encoding.zip._format import (
    CENTRAL,
    DESCRIPTOR,
    END,
    END64,
    EPOCH,
    EXTRA_TIMESTAMP,
    EXTRA_ZIP64,
    FLAG_DESCRIPTOR,
    FLAG_UTF8,
    LOCAL,
    LOCATOR64,
    MAX16,
    MAX32,
    invalid_header,
    size_mismatch,
    to_dos,
)
from pyfect.encoding.zip._model import Header, ZipError

SLAB_SIZE = 64 * 1024

_VERSION = 20
_VERSION_ZIP64 = 45
_CREATOR_UNIX = 3
_S_IFDIR = 0o040000
_S_IFREG = 0o100000
_DOS_DIRECTORY = 0x10
_MAX_TIMESTAMP = 0x7FFFFFFF

_DEFLATE_HEADROOM = 16 * 1024 * 1024
"""Room for deflate to grow data that does not compress, when choosing ZIP64."""

_COPY_LIMIT = 16 * 1024
"""Chunks below this size are copied together instead of being handed out alone."""


@dataclass(slots=True)
class _Record:
    name: bytes
    flags: int
    method: int
    time: int
    date: int
    seconds: int | None
    external: int
    offset: int
    # Whether the local header has ZIP64 sizes, which then also follow the data
    zip64: bool = False
    crc: int = 0
    compressed_size: int = 0
    size: int = 0


def _timestamp(record: _Record) -> bytes:
    if record.seconds is None:
        return b""
    return struct.pack("<HHBI", EXTRA_TIMESTAMP, 5, 1, record.seconds)


def _local_header(record: _Record) -> bytes:
    zip64 = record.zip64
    extra = _timestamp(record)
    if zip64:
        extra = struct.pack("<HHQQ", EXTRA_ZIP64, 16, record.size, record.compressed_size) + extra
    return (
        struct.pack(
            "<IHHHHHIIIHH",
            LOCAL,
            _VERSION_ZIP64 if zip64 else _VERSION,
            record.flags,
            record.method,
            record.time,
            record.date,
            record.crc,
            MAX32 if zip64 else record.compressed_size,
            MAX32 if zip64 else record.size,
            len(record.name),
            len(extra),
        )
        + record.name
        + extra
    )


def _data_descriptor(record: _Record) -> bytes:
    return struct.pack(
        "<IIQQ" if record.zip64 else "<IIII",
        DESCRIPTOR,
        record.crc,
        record.compressed_size,
        record.size,
    )


def _central_header(record: _Record) -> bytes:
    # ZIP64 holds only the fields that overflow, in this order
    wide = [
        value for value in (record.size, record.compressed_size, record.offset) if value >= MAX32
    ]
    extra = _timestamp(record)
    if wide:
        extra = struct.pack(f"<HH{len(wide)}Q", EXTRA_ZIP64, 8 * len(wide), *wide) + extra
    version = _VERSION if not wide and not record.zip64 else _VERSION_ZIP64
    return (
        struct.pack(
            "<IHHHHHHIIIHHHHHII",
            CENTRAL,
            (_CREATOR_UNIX << 8) | version,
            version,
            record.flags,
            record.method,
            record.time,
            record.date,
            record.crc,
            min(record.compressed_size, MAX32),
            min(record.size, MAX32),
            len(record.name),
            len(extra),
            0,
            0,
            0,
            record.external,
            min(record.offset, MAX32),
        )
        + record.name
        + extra
    )


class Writer:
    __slots__ = ("_chunks", "_current", "_offset", "_records", "buffered")

    def __init__(self) -> None:
        self._chunks: list[bytes] = []
        self.buffered = 0
        self._offset = 0
        self._records: list[_Record] = []
        # An entry whose data is being written, its record and whether a data
        # descriptor follows
        self._current: tuple[Header, _Record, bool] | None = None

    def flush(self) -> tuple[bytes, ...]:
        """Hands out the buffered output, joining runs of small chunks; needs
        ``buffered > 0``."""
        out: list[bytes] = []
        run: list[bytes] = []
        for chunk in self._chunks:
            if len(chunk) >= _COPY_LIMIT:
                if run:
                    out.append(b"".join(run))
                    run = []
                out.append(chunk)
            else:
                run.append(chunk)
        if run:
            out.append(b"".join(run))
        self._chunks = []
        self.buffered = 0
        return tuple(out)

    def _push(self, data: bytes) -> None:
        if data:
            self._chunks.append(data)
            self._offset += len(data)
            self.buffered += len(data)

    def _record(self, header: Header, flags: int) -> _Record:
        name = text_encode(header.path)
        if len(name) > MAX16:
            raise invalid_header(f"path {quoted(header.path)} is longer than 65535 bytes")
        time, date = to_dos(header.mtime)
        seconds = (header.mtime - EPOCH) // timedelta(seconds=1)
        directory = header.type == "Directory"
        mode = (0o755 if directory else 0o644) if header.mode is None else header.mode
        return _Record(
            name=name,
            flags=flags if header.path.isascii() else flags | FLAG_UTF8,
            method=8 if header.type == "File" and header.method == "Deflate" else 0,
            time=time,
            date=date,
            seconds=seconds if 0 <= seconds <= _MAX_TIMESTAMP else None,
            external=(
                ((_S_IFDIR if directory else _S_IFREG) | mode) * 0x10000
                + (_DOS_DIRECTORY if directory else 0)
            )
            & MAX32,
            offset=self._offset,
        )

    def entry(self, header: Header, content: bytes, data: bytes) -> None:
        """Writes an entry whose content is known, with its sizes in the local header."""
        size = 0 if header.type == "Directory" else header.size
        if size is not None and size != len(content):
            raise size_mismatch(header.path, len(content), size)
        record = self._record(header, 0)
        record.crc = zlib.crc32(content)
        record.size = len(content)
        record.compressed_size = len(data)
        record.zip64 = record.size >= MAX32 or record.compressed_size >= MAX32
        self._push(_local_header(record))
        self._push(data)
        self._records.append(record)

    def begin(self, header: Header) -> None:
        """Starts an entry whose sizes and CRC-32 follow its data."""
        directory = header.type == "Directory"
        stored = directory or header.method == "Store"
        size = 0 if directory else header.size
        if stored and size is None:
            raise invalid_header(f"stored file {quoted(header.path)} is streamed without a size")
        # An empty stored entry needs no descriptor: readers would take its zero
        # sizes for missing ones
        descriptor = not (stored and size == 0)
        record = self._record(header, FLAG_DESCRIPTOR if descriptor else 0)
        # Streaming readers find the end of stored data from its size
        if stored and size is not None:
            record.size = size
            record.compressed_size = size
        # The local header fixes the width of the sizes after the data, so declare
        # ZIP64 whenever they could reach 4 GiB
        record.zip64 = size is None or size >= (MAX32 if stored else MAX32 - _DEFLATE_HEADROOM)
        self._push(_local_header(record))
        record.size = 0
        record.compressed_size = 0
        self._current = (header, record, descriptor)

    def update(self, chunks: Sequence[bytes]) -> None:
        """Accounts for uncompressed body bytes."""
        assert self._current is not None
        record = self._current[1]
        for chunk in chunks:
            record.crc = zlib.crc32(chunk, record.crc)
            record.size += len(chunk)

    def data(self, chunks: Sequence[bytes]) -> None:
        """Writes stored or compressed body bytes."""
        assert self._current is not None
        header, record, _ = self._current
        for chunk in chunks:
            self._push(chunk)
            record.compressed_size += len(chunk)
        size = 0 if header.type == "Directory" else header.size
        if size is not None and record.size > size:
            raise size_mismatch(header.path, record.size, size)
        if not record.zip64 and record.compressed_size >= MAX32:
            raise ZipError(
                "SizeMismatch",
                f"compressed data of {quoted(header.path)} reached 4 GiB, "
                "but its local header has no ZIP64 sizes",
            )

    def end(self) -> None:
        assert self._current is not None
        header, record, descriptor = self._current
        self._current = None
        if header.size is not None and record.size != header.size:
            raise size_mismatch(header.path, record.size, header.size)
        if descriptor:
            self._push(_data_descriptor(record))
        self._records.append(record)

    def finish(self) -> None:
        start = self._offset
        for record in self._records:
            self._push(_central_header(record))
        size = self._offset - start
        count = len(self._records)
        if count >= MAX16 or size >= MAX32 or start >= MAX32:
            end64_offset = self._offset
            self._push(
                struct.pack(
                    "<IQHHIIQQQQ",
                    END64,
                    44,
                    (_CREATOR_UNIX << 8) | _VERSION_ZIP64,
                    _VERSION_ZIP64,
                    0,
                    0,
                    count,
                    count,
                    size,
                    start,
                )
            )
            self._push(struct.pack("<IIQI", LOCATOR64, 0, end64_offset, 1))
        self._push(
            struct.pack(
                "<IHHHHIIH",
                END,
                0,
                0,
                min(count, MAX16),
                min(count, MAX16),
                min(size, MAX32),
                min(start, MAX32),
                0,
            )
        )
