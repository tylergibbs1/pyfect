"""Entries to tar archive bytes."""

from __future__ import annotations

from pyfect._json_text import quote as quoted
from pyfect.encoding.tar._header import BLOCK, encode_header, padding
from pyfect.encoding.tar._model import Header, TarError

SLAB_SIZE = 64 * 1024

_COPY_LIMIT = 16 * 1024
"""Bodies below this size are copied next to their header instead of being handed
out as chunks of their own."""


def _size_mismatch(header: Header, written: int) -> TarError:
    return TarError(
        "SizeMismatch",
        f"body of {quoted(header.path)} has {'at least' if written > header.size else 'only'} "
        f"{written} bytes, but its size is {header.size}",
    )


class Encoder:
    """Packs headers, padding and small body chunks into runs of up to 64 KiB,
    and passes large chunks through without copying."""

    __slots__ = ("_chunks", "_header", "_run", "_written", "buffered")

    def __init__(self) -> None:
        self._run = bytearray()
        self._chunks: list[bytes] = []
        self.buffered = 0
        # The entry whose body is being written, and the body bytes written so far
        self._header: Header | None = None
        self._written = 0

    def begin(self, header: Header) -> None:
        self._add(encode_header(header))
        self._header = header
        self._written = 0

    def body(self, chunk: bytes) -> None:
        header = self._header
        assert header is not None
        self._written += len(chunk)
        if self._written > header.size:
            raise _size_mismatch(header, self._written)
        if len(chunk) < _COPY_LIMIT:
            self._add(chunk)
            return
        self._cut()
        self._chunks.append(chunk)
        self.buffered += len(chunk)

    def end(self) -> None:
        header = self._header
        assert header is not None
        self._header = None
        if self._written != header.size:
            raise _size_mismatch(header, self._written)
        self._add(bytes(padding(header.size)))

    def finish(self) -> None:
        self._add(bytes(BLOCK * 2))

    def flush(self) -> tuple[bytes, ...]:
        self._cut()
        chunks = tuple(self._chunks)
        self._chunks = []
        self.buffered = 0
        return chunks

    def _cut(self) -> None:
        if self._run:
            self._chunks.append(bytes(self._run))
            self._run.clear()

    def _add(self, data: bytes) -> None:
        if len(self._run) + len(data) > SLAB_SIZE:
            self._cut()
        self._run += data
        self.buffered += len(data)
