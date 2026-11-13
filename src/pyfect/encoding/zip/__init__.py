"""Zip archives as streams (Effect's ``encoding/Zip``).

``encode`` writes each entry as it arrives and adds the central directory once the
input ends; ``decode`` reads entries in archive order from their local headers, so
an archive can be read as it arrives. ``decode`` never holds a whole body, at most 4
MiB of compressed input per entry, which is what these channels add to the blocking
``zipfile``, and ``encode`` only collects deflated bodies of at most 64 KiB.

Entries are stored or deflated, with ZIP64 fields when sizes, offsets or the entry
count need them. Encryption, other compression methods and archives split across
files are not supported.

Paths are returned as written in the archive: they can be absolute, contain ``..``,
drive letters, control characters or backslashes, and can repeat. Validate them
before writing entries to disk.
"""
# pyright: reportPrivateUsage=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownMemberType=false

from __future__ import annotations

import zlib
from datetime import datetime
from typing import Any, Literal, Never, TypeIs, overload

from pyfect._js import text_encode
from pyfect._primitives import _Succeed, _Suspend
from pyfect._public import publish
from pyfect.channel import Channel, from_transform
from pyfect.channel._base import AnyPull, end_with
from pyfect.effect import yield_now
from pyfect.encoding._archive import decode_channel
from pyfect.encoding.zip._decoder import Decoder
from pyfect.encoding.zip._format import MIN_MTIME, size_mismatch, validate
from pyfect.encoding.zip._model import (
    ContentEntry,
    Entry,
    EntryType,
    Header,
    Method,
    ZipError,
    ZipErrorKind,
)
from pyfect.encoding.zip._writer import SLAB_SIZE, Writer
from pyfect.exit import Success, void
from pyfect.exit import fail as fail_exit
from pyfect.pull import catch_done
from pyfect.scope import CloseableScope
from pyfect.stream import Stream
from pyfect.stream._base import require_stream

__all__ = [
    "ContentEntry",
    "Entry",
    "EntryType",
    "Header",
    "Method",
    "ZipError",
    "ZipErrorKind",
    "decode",
    "directory",
    "encode",
    "file",
    "file_stream",
    "is_zip_error",
]

_DEFLATE_PIECE = 64 * 1024
"""How much content is deflated between turns of other fibers, and the largest
body with a ``size`` collected and deflated in one piece."""


def is_zip_error(value: object) -> TypeIs[ZipError]:
    return isinstance(value, ZipError)


def _header(  # noqa: PLR0917
    path: str,
    kind: EntryType,
    method: Method,
    mtime: datetime | None,
    mode: int | None,
    size: int | None,
) -> Header:
    return Header(
        path=path,
        type=kind,
        method=method,
        mtime=MIN_MTIME if mtime is None else mtime,
        size=size,
        mode=(0o755 if kind == "Directory" else 0o644) if mode is None else mode,
    )


def file(
    path: str,
    content: str | bytes,
    *,
    method: Method = "Deflate",
    mtime: datetime | None = None,
    mode: int | None = None,
) -> ContentEntry:
    """A file from in-memory content; a ``str`` is encoded as UTF-8. Use
    ``method="Store"`` for content that is already compressed. Unset fields default
    to an mtime of 1980-01-01T00:00:00Z, the earliest a zip header holds, and mode
    ``0o644``, which makes archives reproducible."""
    data = text_encode(content) if isinstance(content, str) else content
    return ContentEntry(_header(path, "File", method, mtime, mode, len(data)), data)


@overload
def file_stream[E = Never, R = Never](
    path: str,
    body: Stream[bytes, E, R],
    *,
    method: Literal["Deflate"] = ...,
    size: int | None = ...,
    mtime: datetime | None = ...,
    mode: int | None = ...,
) -> Entry[E, R]: ...
@overload
def file_stream[E = Never, R = Never](
    path: str,
    body: Stream[bytes, E, R],
    *,
    method: Literal["Store"],
    size: int,
    mtime: datetime | None = ...,
    mode: int | None = ...,
) -> Entry[E, R]: ...
def file_stream(
    path: str,
    body: Stream[bytes, Any, Any],
    *,
    method: Method = "Deflate",
    size: int | None = None,
    mtime: datetime | None = None,
    mode: int | None = None,
) -> Entry[Any, Any]:
    """A file streamed from ``body``, which runs when the entry is encoded, with its
    sizes and CRC-32 in a data descriptor after the data.

    ``size`` is the exact byte length: required for ``"Store"``, since streaming
    readers can only find the end of stored data from its size, and optional for
    ``"Deflate"``, where it is checked against the body.

    Non-empty stored entries are followed by a data descriptor, which some streaming
    readers mishandle: Java's ``ZipInputStream`` rejects them, and libarchive reading
    from a pipe can end them at bytes that look like a descriptor. Use ``"Deflate"``
    or an in-memory ``file`` for untrusted content and for those readers."""
    require_stream(body, "body")
    return Entry(_header(path, "File", method, mtime, mode, size), body)


def directory(path: str, *, mtime: datetime | None = None, mode: int | None = None) -> ContentEntry:
    """A directory (mode ``0o755`` by default). A trailing ``/`` is added to a
    non-empty ``path``; an empty one stays empty, so that ``encode`` rejects it."""
    named = path if path == "" or path.endswith("/") else f"{path}/"
    return ContentEntry(_header(named, "Directory", "Store", mtime, mode, 0), b"")


def decode[IE = Never, D = None]() -> Channel[
    tuple[Entry[ZipError | IE], ...], ZipError | IE, D, tuple[bytes, ...], IE, D
]:
    """A channel decoding archive bytes into entries, one entry per output chunk. Each
    body streams the uncompressed bytes and is checked against its CRC-32 and sizes;
    pulling the next entry skips what is left of the current body. Reading stops at the
    central directory, so ``mode``, comments and entries only it lists are not reported.

    Paths use the UTF-8 flag when set, otherwise the first Info-ZIP Unicode path field
    when it matches the name; other paths are UTF-8 when valid and CP437 otherwise.
    Times come from the extended timestamp when present, otherwise from the DOS fields,
    read as UTC.

    Read each body before pulling the next entry and while the entry stream runs, for
    example in ``map_effect``: a later read fails with ``"BodyConsumed"``, so operators
    that pull ahead cannot sit between ``decode`` and the reads. A body reads its bytes
    once: running it again continues where it stopped. Every ``ZipError`` ends the
    archive: later reads fail with the same error.

    Archives that do not start with an entry or a central directory, such as
    self-extracting ones, fail with ``"InvalidHeader"``. Stored entries whose sizes only
    follow their data fail with ``"Unsupported"``: searching for their end would let an
    entry's content forge the entries after it. A body growing past its ``size`` fails
    with ``"SizeMismatch"`` before the extra bytes are written. Deflated data can expand
    about a thousand times, and pulling the next entry inflates the rest of the current
    body to find its end: for untrusted archives check ``size``, count the bytes of
    bodies without one, and end the stream at an entry that is too large rather than
    skip it. Corrupt deflated data fails with ``"InvalidData"`` and the message of
    Effect's inflater: ``zlib`` inflates, and an entry it rejects, or that ends early or
    grows past its ``size``, is replayed through a port of Effect's inflater. Only the
    first 4 MiB of an entry's compressed input are kept for that: a corrupt entry
    longer than that fails with Effect's kind and ``zlib``'s message. Paths with a NUL
    character fail with ``"InvalidHeader"``. The channel ends only when its input ends:
    input after the central directory is read and discarded, so that the upstream's
    done value can be passed on."""
    return decode_channel(Decoder, Entry, ZipError)


def _deflate_bytes(content: bytes) -> Any:
    """``content`` deflated, in pieces that let other fibers run."""
    compressor = zlib.compressobj(wbits=-15)
    if len(content) <= _DEFLATE_PIECE:
        return _Succeed(compressor.compress(content) + compressor.flush())
    return _Suspend(_Deflation(content, compressor).step)


class _Deflation:
    """Deflates ``content`` one piece per step."""

    __slots__ = ("at", "compressor", "content", "parts")

    def __init__(self, content: bytes, compressor: zlib._Compress) -> None:
        self.content = content
        self.compressor = compressor
        self.parts: list[bytes] = []
        self.at = 0

    def step(self) -> Any:
        content = self.content
        if self.at >= len(content):
            self.parts.append(self.compressor.flush())
            return _Succeed(b"".join(self.parts))
        self.parts.append(self.compressor.compress(content[self.at : self.at + _DEFLATE_PIECE]))
        self.at += _DEFLATE_PIECE
        return yield_now().flat_map(self._resume)

    def _resume(self, _: object) -> Any:
        return _Suspend(self.step)


def encode[E = Never, R = Never, IE = Never, D = None]() -> Channel[
    tuple[bytes, ...],
    ZipError | IE | E,
    D,
    tuple[Entry[E, R] | ContentEntry, ...],
    IE,
    D,
    R,
]:
    """A channel encoding entries into archive bytes. Each entry is written as soon as
    it arrives: a local header, the stored or deflated body and, for a streamed body, a
    data descriptor. The central directory is written once the input ends. Paths are
    UTF-8, with the UTF-8 flag when they are not ASCII. ``mtime`` is written both as a
    DOS time in UTC (two-second resolution, 1980 to 2107) and, between 1970 and 2038, as
    an extended timestamp. ZIP64 fields are added when a size, offset or the entry count
    needs them, and to the local header of a deflated entry streamed without a ``size``
    or with one near 4 GiB.

    Output is written in chunks of about 64 KiB, and large body chunks pass through
    uncopied. A ``"Deflate"`` body with a ``size`` of at most 64 KiB is collected and
    compressed in one piece; omit ``size`` to stream it.

    A compressor failure is a defect. Deflated bytes come from ``zlib``, so they can
    differ from another implementation's; archives of stored entries are byte-identical
    to Effect's.

    A body whose byte count differs from a set ``size``, or any bytes for a directory,
    fail with ``"SizeMismatch"``. Empty paths, paths starting with ``/`` or a drive
    letter such as ``C:``, paths containing ``\\\\`` or NUL, ``File`` paths ending with
    ``/``, ``Directory`` paths not ending with ``/``, invalid modes or sizes and naive
    ``datetime`` values fail with ``"InvalidHeader"``. Other paths are written as given,
    including ``..`` segments, so validate untrusted paths before encoding them.

    Entries that differ in their bodies' errors or services do not infer one ``E`` and
    ``R``: annotate the stream, as ``Stream[Entry[E1 | E2, R1 | R2] | ContentEntry]``."""

    channel: Any = from_transform(
        lambda upstream, scope: _Suspend(
            lambda: _Succeed(_Suspend(_ZipEncoding(upstream, scope).step))
        )
    )
    return channel


class _ZipEncoding:
    """One run of ``encode``: entries in, archive bytes out."""

    __slots__ = (
        "body",
        "body_scope",
        "compressor",
        "done",
        "entries",
        "index",
        "scope",
        "upstream",
        "writer",
    )

    def __init__(self, upstream: AnyPull, scope: CloseableScope) -> None:
        self.upstream = upstream
        self.scope = scope
        self.writer = Writer()
        self.entries: tuple[Any, ...] = ()
        self.index = 0
        self.done: tuple[Any] | None = None
        self.body: AnyPull | None = None
        self.body_scope: CloseableScope | None = None
        self.compressor: Any = None

    @property
    def pull(self) -> AnyPull:
        return _Suspend(self.step)

    def on_body(self, chunks: tuple[bytes, ...] | None) -> Any:
        writer = self.writer
        try:
            if chunks is not None:
                writer.update(chunks)
                compressor = self.compressor
                if compressor is None:
                    writer.data(chunks)
                else:
                    writer.data(tuple(compressor.compress(chunk) for chunk in chunks))
                return self.pull
            if self.compressor is not None:
                writer.data((self.compressor.flush(),))
                self.compressor = None
        except ZipError as error:
            return fail_exit(error)
        self.body = None
        assert self.body_scope is not None
        closing = self.body_scope.close(void)
        self.body_scope = None
        return closing.flat_map(self.on_body_closed)

    def on_body_closed(self, _: None) -> Any:
        try:
            self.writer.end()
        except ZipError as error:
            return fail_exit(error)
        return self.pull

    def write_content(self, entry: ContentEntry, compress: bool) -> Any:
        def written(data: bytes) -> Any:
            try:
                self.writer.entry(entry.header, entry.content, data)
            except ZipError as error:
                return fail_exit(error)
            return self.pull

        return (
            _deflate_bytes(entry.content).flat_map(written) if compress else written(entry.content)
        )

    def collect_and_deflate(self, entry: Entry[Any, Any], size: int) -> Any:
        """A small body costs less to deflate in one piece than as a stream."""
        writer = self.writer
        chunks: list[bytes] = []
        length = 0

        def collect(array: tuple[bytes, ...]) -> Any:
            nonlocal length
            chunks.extend(array)
            length += sum(map(len, array))
            if length > size:
                return fail_exit(size_mismatch(entry.header.path, length, size))
            writer.update(array)
            return _Succeed(None)

        def deflated(data: bytes) -> Any:
            try:
                writer.data((data,))
                writer.end()
            except ZipError as error:
                return fail_exit(error)
            return self.pull

        return (
            entry.body.run_for_each_array(collect)
            .flat_map(lambda _: _deflate_bytes(b"".join(chunks)))
            .flat_map(deflated)
        )

    def begin(self, entry: Any) -> Any:
        header = entry.header
        try:
            validate(header)
            compress = header.type == "File" and header.method == "Deflate"
            if isinstance(entry, ContentEntry):
                return self.write_content(entry, compress)
            self.writer.begin(header)
        except ZipError as error:
            return fail_exit(error)
        if compress and header.size is not None and header.size <= _DEFLATE_PIECE:
            return self.collect_and_deflate(entry, header.size)
        # A compressor failure is a defect, as a raise here makes it
        self.compressor = zlib.compressobj(wbits=-15) if compress else None
        body_scope = self.body_scope = self.scope.fork_unsafe()
        return entry.body._channel.to_pull_scoped(body_scope).flat_map(self.opened)

    def opened(self, opened_pull: AnyPull) -> Any:
        self.body = opened_pull
        return self.pull

    def upstream_done(self, value: object) -> AnyPull:
        self.done = (value,)
        return _Succeed(None)

    def on_upstream(self, next_entries: tuple[Any, ...] | None) -> Any:
        if next_entries is None:
            self.writer.finish()
        else:
            self.entries = next_entries
            self.index = 0
        return self.pull

    def step(self) -> Any:
        writer = self.writer
        if writer.buffered >= SLAB_SIZE:
            return Success(writer.flush())
        if self.body is not None:
            return catch_done(self.body, _void_done).flat_map(self.on_body)
        if self.index < len(self.entries):
            entry = self.entries[self.index]
            self.index += 1
            return self.begin(entry)
        if writer.buffered > 0:
            return Success(writer.flush())
        if self.done is not None:
            return end_with(self.done[0])
        return catch_done(self.upstream, self.upstream_done).flat_map(self.on_upstream)


def _void_done(_: object) -> AnyPull:
    return _Succeed(None)


publish(globals())
