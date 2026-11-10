"""Zip archive bytes to entries, pulled, from the local headers alone."""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

from pyfect._js import js_number
from pyfect._json_text import quote as quoted
from pyfect.encoding._archive import NEED_INPUT, ByteQueue, NeedInput
from pyfect.encoding.zip._format import (
    CENTRAL,
    DESCRIPTOR,
    END,
    END64,
    EPOCH,
    EXTRA_TIMESTAMP,
    EXTRA_UNICODE_PATH,
    EXTRA_ZIP64,
    FLAG_DESCRIPTOR,
    FLAG_ENCRYPTED,
    FLAG_STRONG_ENCRYPTION,
    FLAG_UTF8,
    LOCAL,
    MAX32,
    MAX_SAFE_INTEGER,
    decode_name,
    from_dos,
    invalid_header,
    size_mismatch,
)
from pyfect.encoding.zip._inflate import InflateError, Inflater
from pyfect.encoding.zip._model import Header, ZipError

_DESCRIPTOR_PEEK = 28
"""A ZIP64 data descriptor with its signature, and the signature after it."""

_LOCAL_SIZE = 30


def _hex(n: int) -> str:
    return f"0x{n:08x}"


def _u16(data: bytes, at: int) -> int:
    return int.from_bytes(data[at : at + 2], "little")


def _u32(data: bytes, at: int) -> int:
    return int.from_bytes(data[at : at + 4], "little")


def _u64(data: bytes, at: int) -> int:
    value = struct.unpack_from("<Q", data, at)[0]
    if value > MAX_SAFE_INTEGER:
        raise invalid_header("a 64-bit field exceeds 2^53 - 1")
    return value


def _is_header_signature(signature: int) -> bool:
    return signature in (LOCAL, CENTRAL, END, END64)


def _truncated(at: int) -> ZipError:
    return ZipError("Truncated", f"unexpected end of zip archive at byte {at}")


@dataclass(slots=True)
class _Current:
    header: Header
    inflater: Inflater | None
    descriptor: bool
    zip64: bool
    # The values of the local header; sizes are unknown when they follow the data
    crc: int
    compressed_size: int | None
    size: int | None
    # Queue position where the data starts
    start: int
    remaining: int
    data_done: bool = False
    actual_crc: int = 0
    actual_size: int = 0
    actual_compressed_size: int = 0


class Decoder:
    """``next`` skips the rest of the current body; ``read`` consumes it. Both keep
    their progress across ``NEED_INPUT``."""

    def __init__(self) -> None:
        self._queue = ByteQueue()
        self._ended = False
        self._finished = False
        self._closed = False
        # Incremented whenever the current body is invalidated
        self.generation = 0
        self._current: _Current | None = None
        # The error that ended the archive, repeated by every later call
        self._failure: ZipError | None = None

    def push(self, chunk: bytes) -> None:
        if not self._finished:
            self._queue.push(chunk)

    def end(self) -> None:
        self._ended = True

    def close(self) -> None:
        self._closed = True
        self.generation += 1
        self._queue.clear()

    def next(self) -> Header | NeedInput | None:
        """The next entry header, or ``None`` once the entries and the input have
        ended. Input after the entries is discarded."""
        self.generation += 1
        return self._guard(self._advance)

    def _guard(self, run: Any) -> Any:
        if self._failure is not None:
            raise self._failure
        try:
            return run()
        except ZipError as error:
            self._failure = error
            raise

    def _advance(self) -> Header | NeedInput | None:  # noqa: PLR0911
        while self._current is not None:
            if self._read_current() is NEED_INPUT:
                return NEED_INPUT
        if self._finished:
            return self._finish()
        queue = self._queue
        if queue.length < 4:
            return self._need_input()
        at = queue.consumed
        head = queue.peek(min(queue.length, _LOCAL_SIZE))
        signature = _u32(head, 0)
        if signature in (CENTRAL, END, END64):
            return self._finish()
        if signature != LOCAL:
            raise invalid_header(f"unexpected signature {_hex(signature)} at byte {at}")
        if len(head) < _LOCAL_SIZE:
            return self._need_input()
        length = _LOCAL_SIZE + _u16(head, 26) + _u16(head, 28)
        if queue.length < length:
            return self._need_input()
        try:
            current = self._parse_local(queue.take(length))
        except ZipError as error:
            raise ZipError(error.kind, f"{error.message} (header at byte {at})") from None
        self._current = current
        return current.header

    def read(self, generation: int) -> tuple[bytes, ...] | NeedInput | None:
        """The buffered body bytes of the entry from ``generation``, or ``None``
        once the whole body has been read and checked."""
        if generation != self.generation:
            raise ZipError(
                "BodyConsumed",
                "zip entry body read after the archive stream ended"
                if self._closed
                else "zip entry body read after moving to the next entry",
            )
        return self._guard(self._read_current)

    def _read_current(self) -> tuple[bytes, ...] | NeedInput | None:  # noqa: PLR0911, PLR0912
        current = self._current
        if current is None:
            return None
        queue = self._queue
        if not current.data_done:
            if current.inflater is None:
                if current.remaining > 0:
                    if queue.length == 0:
                        return self._need_input()
                    chunks: list[bytes] = []
                    while current.remaining > 0 and queue.length > 0:
                        chunk = queue.take_some(current.remaining)
                        current.remaining -= len(chunk)
                        current.actual_crc = zlib.crc32(chunk, current.actual_crc)
                        current.actual_size += len(chunk)
                        chunks.append(chunk)
                    current.actual_compressed_size = current.actual_size
                    return tuple(chunks)
            else:
                try:
                    inflated = current.inflater.pull()
                except InflateError as error:
                    raise ZipError("InvalidData", str(error)) from None
                if inflated is NEED_INPUT:
                    # Effect's inflater may reject the input zlib took, before the end
                    if self._ended and current.inflater.fall_back(current.actual_size):
                        return self._read_current()
                    return self._need_input()
                if inflated is not None:
                    # Fail before handing out bytes past the reported size, so that
                    # consumers can limit what a small compressed entry inflates to
                    size = current.header.size
                    if size is not None and current.actual_size + len(inflated) > size:
                        # unless Effect's inflater rejects the data first
                        if current.inflater.fall_back(current.actual_size):
                            return self._read_current()
                        raise size_mismatch(
                            current.header.path, current.actual_size + len(inflated), size
                        )
                    current.actual_size += len(inflated)
                    current.actual_crc = zlib.crc32(inflated, current.actual_crc)
                    return (inflated,)
                current.actual_compressed_size = queue.consumed - current.start
            current.data_done = True
        if current.descriptor:
            descriptor = self._descriptor(current)
            if descriptor is NEED_INPUT:
                return NEED_INPUT
            self._check(current, *descriptor)
        else:
            assert current.compressed_size is not None
            assert current.size is not None
            self._check(current, current.crc, current.compressed_size, current.size)
        self._current = None
        return None

    def _check(self, current: _Current, crc: int, compressed_size: int, size: int) -> None:
        if (
            current.actual_crc == crc
            and current.actual_compressed_size == compressed_size
            and current.actual_size == size
        ):
            return
        path = quoted(current.header.path)
        if current.actual_crc != crc:
            raise ZipError(
                "Checksum",
                f"CRC-32 of {path} is {_hex(current.actual_crc)}, "
                f"but the archive records {_hex(crc)}",
            )
        raise ZipError(
            "SizeMismatch",
            f"{path} has {current.actual_size} bytes "
            f"({current.actual_compressed_size} compressed), "
            f"but the archive records {js_number(float(size))} "
            f"({js_number(float(compressed_size))} compressed)",
        )

    def _descriptor(self, current: _Current) -> tuple[int, int, int] | NeedInput:
        """Reads a data descriptor, whose signature is optional and whose sizes are
        4 bytes unless the local header has a ZIP64 field. Writers that widen the
        sizes only on overflow are handled by matching each layout against the data
        read; among several matches, one followed by a header signature wins."""
        queue = self._queue
        if queue.length < _DESCRIPTOR_PEEK and not self._ended:
            return NEED_INPUT
        data = queue.peek(min(queue.length, _DESCRIPTOR_PEEK))
        candidates: list[tuple[int, int, int, int]] = []
        offsets = (4, 0) if len(data) >= 4 and _u32(data, 0) == DESCRIPTOR else (0,)
        for offset in offsets:
            for wide in (True, False) if current.zip64 else (False, True):
                length = offset + (20 if wide else 12)
                if length > len(data):
                    continue
                crc = _u32(data, offset)
                if wide:
                    compressed, size = struct.unpack_from("<QQ", data, offset + 4)
                else:
                    compressed, size = struct.unpack_from("<II", data, offset + 4)
                candidates.append((length, crc, compressed, size))
        actual = (current.actual_crc, current.actual_compressed_size, current.actual_size)
        matches = [candidate for candidate in candidates if candidate[1:] == actual]
        match = next(
            (
                candidate
                for candidate in matches
                if candidate[0] + 4 <= len(data) and _is_header_signature(_u32(data, candidate[0]))
            ),
            matches[0] if matches else None,
        )
        if match is not None:
            queue.skip(match[0])
            return match[1:]
        # A complete archive has at least an end record after the descriptor
        if not candidates or (self._ended and len(data) < _DESCRIPTOR_PEEK):
            raise _truncated(queue.consumed + queue.length)
        queue.skip(candidates[0][0])
        return candidates[0][1:]

    def _parse_local(self, data: bytes) -> _Current:  # noqa: PLR0912, PLR0915
        flags = _u16(data, 6)
        method = _u16(data, 8)
        time = _u16(data, 10)
        date = _u16(data, 12)
        crc = _u32(data, 14)
        compressed_size = _u32(data, 18)
        size = _u32(data, 22)
        name_length = _u16(data, 26)
        raw_name = data[_LOCAL_SIZE : _LOCAL_SIZE + name_length]
        utf8 = flags & FLAG_UTF8 != 0
        path = decode_name(raw_name, utf8)
        # As in Info-ZIP and 7-Zip, only the first Unicode path field is read, and
        # only without the UTF-8 flag
        read_unicode_path = not utf8
        seconds: int | None = None
        zip64 = False
        at = _LOCAL_SIZE + name_length
        while at + 4 <= len(data):
            field_id = _u16(data, at)
            start = at + 4
            end = start + _u16(data, at + 2)
            if end > len(data):
                raise invalid_header("extra field overflows the header")
            if field_id == EXTRA_ZIP64:
                zip64 = True
                field = start
                if size == MAX32 and field + 8 <= end:
                    size = _u64(data, field)
                    field += 8
                if compressed_size == MAX32 and field + 8 <= end:
                    compressed_size = _u64(data, field)
            elif field_id == EXTRA_TIMESTAMP and end - start >= 5 and data[start] & 1 != 0:
                # Info-ZIP writes times before 1970 as negative numbers, and others
                # write times after 2038 as unsigned ones; the DOS date tells them apart
                value = _u32(data, start + 1)
                seconds = (
                    value - 0x100000000
                    if value >= 0x80000000 and (date >> 9) + 1980 < 2038
                    else value
                )
            elif field_id == EXTRA_UNICODE_PATH and read_unicode_path:
                read_unicode_path = False
                if (
                    end - start >= 5
                    and data[start] == 1
                    and _u32(data, start + 1) == zlib.crc32(raw_name)
                ):
                    path = data[start + 5 : end].decode("utf-8", "replace")
            at = end
        name = quoted(path)
        # Other tools end the name at a NUL character, or reject it
        if "\0" in path:
            raise invalid_header(f"path {name} contains a NUL character")
        if flags & (FLAG_ENCRYPTED | FLAG_STRONG_ENCRYPTION) != 0:
            raise ZipError("Unsupported", f"entry {name} is encrypted")
        if method not in (0, 8):
            raise ZipError("Unsupported", f"entry {name} uses compression method {method}")
        descriptor = flags & FLAG_DESCRIPTOR != 0
        # Writers that put sizes after the data usually leave zeros here
        known = not descriptor or compressed_size != 0 or size != 0
        # Searching for the descriptor of stored data would let its content forge
        # the entries after it
        if method == 0 and not known:
            raise ZipError("Unsupported", f"stored entry {name} has no size before its data")
        if method == 0 and compressed_size != size:
            raise invalid_header(f"stored entry {name} has different sizes")
        header = Header(
            path=path,
            type="Directory" if path.endswith("/") else "File",
            method="Deflate" if method == 8 else "Store",
            mtime=from_dos(time, date) if seconds is None else EPOCH + timedelta(seconds=seconds),
            size=size if known and (method == 0 or not descriptor) else None,
        )
        return _Current(
            header=header,
            inflater=Inflater(self._queue) if method == 8 else None,
            descriptor=descriptor,
            zip64=zip64,
            crc=crc,
            compressed_size=compressed_size if known else None,
            size=size if known else None,
            start=self._queue.consumed,
            remaining=compressed_size if method == 0 else 0,
        )

    def _need_input(self) -> NeedInput:
        if self._ended:
            raise _truncated(self._queue.consumed + self._queue.length)
        return NEED_INPUT

    def _finish(self) -> NeedInput | None:
        self._finished = True
        self._queue.clear()
        return None if self._ended else NEED_INPUT
