"""Tar archives as streams (Effect's ``encoding/Tar``).

``decode`` streams entry bodies from the archive input and ``encode`` streams them
back into archive bytes; neither holds a whole body, which is what these channels
add to the blocking ``tarfile``. The decoder reads v7, USTAR, PAX extended headers,
and GNU long names and base-256 numbers. The encoder writes USTAR, adding PAX
extended headers for fields that do not fit or for custom metadata. Neither touches
the file system or compresses.

Paths and link targets are returned as written in the archive, so they can be
absolute or contain ``..``, and a symlink entry can redirect a later entry outside
the target directory. Validate both before writing entries to disk.
"""
# pyright: reportPrivateUsage=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownMemberType=false

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
from typing import Any, Literal, Never, TypeIs

from pyfect._js import text_encode
from pyfect._primitives import _Succeed, _Suspend
from pyfect._public import publish
from pyfect.channel import Channel, from_transform
from pyfect.channel._base import AnyPull, end_with
from pyfect.encoding._archive import decode_channel
from pyfect.encoding.tar._decoder import Decoder
from pyfect.encoding.tar._encoder import SLAB_SIZE, Encoder
from pyfect.encoding.tar._header import EPOCH, TYPEFLAGS
from pyfect.encoding.tar._model import Entry, EntryType, FarDate, Header, TarError, TarErrorKind
from pyfect.exit import Success, void
from pyfect.exit import fail as fail_exit
from pyfect.pull import catch_done
from pyfect.scope import CloseableScope
from pyfect.stream import Stream, empty, succeed
from pyfect.stream._base import require_stream

__all__ = [
    "Entry",
    "EntryType",
    "FarDate",
    "Header",
    "TarError",
    "TarErrorKind",
    "decode",
    "directory",
    "encode",
    "file",
    "file_stream",
    "hardlink",
    "is_tar_error",
    "symlink",
]


def is_tar_error(value: object) -> TypeIs[TarError]:
    return isinstance(value, TarError)


class _Content(Stream[bytes]):
    """A body held in memory, which ``encode`` writes without running it. It is the
    ``body`` that says so, so replacing an entry's body leaves that path."""

    __slots__ = ("content",)

    def __init__(self, content: bytes) -> None:
        super().__init__(succeed(content)._channel)
        self.content = content


def _header(
    path: str,
    kind: Literal["File", "Directory", "Symlink", "Hardlink"],
    size: int,
    link_target: str | None,
    *,
    mode: int | None,
    uid: int | None,
    gid: int | None,
    uname: str | None,
    gname: str | None,
    mtime: datetime | FarDate | None,
    pax: Mapping[str, str] | None,
) -> Header:
    default_mode = 0o755 if kind == "Directory" else 0o777 if kind == "Symlink" else 0o644
    return Header(
        path=path,
        type=kind,
        typeflag=TYPEFLAGS[kind],
        size=size,
        mode=default_mode if mode is None else mode,
        uid=0 if uid is None else uid,
        gid=0 if gid is None else gid,
        uname="" if uname is None else uname,
        gname="" if gname is None else gname,
        mtime=EPOCH if mtime is None else mtime,
        link_target=link_target or None,
        pax={} if pax is None else pax,
    )


def file(
    path: str,
    content: str | bytes,
    *,
    mode: int | None = None,
    uid: int | None = None,
    gid: int | None = None,
    uname: str | None = None,
    gname: str | None = None,
    mtime: datetime | FarDate | None = None,
    pax: Mapping[str, str] | None = None,
) -> Entry:
    """A regular file from in-memory content; a ``str`` is encoded as UTF-8. Unset
    fields default to mode ``0o644``, uid and gid 0, empty names, an mtime at the
    epoch and no extra PAX records, which makes archives reproducible."""
    data = text_encode(content) if isinstance(content, str) else content
    header = _header(
        path,
        "File",
        len(data),
        None,
        mode=mode,
        uid=uid,
        gid=gid,
        uname=uname,
        gname=gname,
        mtime=mtime,
        pax=pax,
    )
    return Entry(header, _Content(data) if data else empty)


def file_stream[E = Never, R = Never](
    path: str,
    size: int,
    body: Stream[bytes, E, R],
    *,
    mode: int | None = None,
    uid: int | None = None,
    gid: int | None = None,
    uname: str | None = None,
    gname: str | None = None,
    mtime: datetime | FarDate | None = None,
    pax: Mapping[str, str] | None = None,
) -> Entry[E, R]:
    """A regular file streamed from ``body``, which runs when the entry is encoded.
    ``size`` is its exact byte length: ``encode`` fails with ``"SizeMismatch"``
    otherwise."""
    require_stream(body, "body")
    header = _header(
        path,
        "File",
        size,
        None,
        mode=mode,
        uid=uid,
        gid=gid,
        uname=uname,
        gname=gname,
        mtime=mtime,
        pax=pax,
    )
    return Entry(header, body)


def directory(
    path: str,
    *,
    mode: int | None = None,
    uid: int | None = None,
    gid: int | None = None,
    uname: str | None = None,
    gname: str | None = None,
    mtime: datetime | FarDate | None = None,
    pax: Mapping[str, str] | None = None,
) -> Entry:
    """A directory (mode ``0o755`` by default). A trailing ``/`` is added to a
    non-empty ``path``; an empty one stays empty, so that ``encode`` rejects it."""
    named = path if path == "" or path.endswith("/") else f"{path}/"
    header = _header(
        named,
        "Directory",
        0,
        None,
        mode=mode,
        uid=uid,
        gid=gid,
        uname=uname,
        gname=gname,
        mtime=mtime,
        pax=pax,
    )
    return Entry(header, empty)


def symlink(
    path: str,
    target: str,
    *,
    mode: int | None = None,
    uid: int | None = None,
    gid: int | None = None,
    uname: str | None = None,
    gname: str | None = None,
    mtime: datetime | FarDate | None = None,
    pax: Mapping[str, str] | None = None,
) -> Entry:
    """A symbolic link to ``target`` (mode ``0o777`` by default)."""
    header = _header(
        path,
        "Symlink",
        0,
        target,
        mode=mode,
        uid=uid,
        gid=gid,
        uname=uname,
        gname=gname,
        mtime=mtime,
        pax=pax,
    )
    return Entry(header, empty)


def hardlink(
    path: str,
    target: str,
    *,
    mode: int | None = None,
    uid: int | None = None,
    gid: int | None = None,
    uname: str | None = None,
    gname: str | None = None,
    mtime: datetime | FarDate | None = None,
    pax: Mapping[str, str] | None = None,
) -> Entry:
    """A hard link to ``target``, the archive path of an entry written earlier."""
    header = _header(
        path,
        "Hardlink",
        0,
        target,
        mode=mode,
        uid=uid,
        gid=gid,
        uname=uname,
        gname=gname,
        mtime=mtime,
        pax=pax,
    )
    return Entry(header, empty)


def decode[IE = Never, D = None]() -> Channel[
    tuple[Entry[TarError | IE], ...], TarError | IE, D, tuple[bytes, ...], IE, D
]:
    """A channel decoding archive bytes into entries, one entry per output chunk,
    each body streaming ``header.size`` bytes straight from the input. Pulling the
    next entry skips what is left of the current body. A PAX global header's records
    apply to every entry after it, except ``path``, ``linkpath`` and ``size``.

    Read each body before pulling the next entry and while the entry stream runs,
    for example in ``map_effect``: a later read fails with ``"BodyConsumed"``, so
    operators that pull ahead cannot sit between ``decode`` and the reads. A body
    reads its bytes once: running it again continues where it stopped.

    Directories, links, devices and FIFOs have no body and a ``size`` of 0. Names
    that are not UTF-8 get replacement characters. PAX headers and GNU long names
    past 1 MiB fail with ``"InvalidHeader"``, and GNU sparse entries with
    ``"Unsupported"``. The channel ends only when its input ends: input after the
    end-of-archive marker is read and discarded, so that the upstream's done value
    can be passed on.

    An mtime ``datetime`` cannot hold (outside years 1 to 9999) fails with
    ``"InvalidHeader"``."""
    return decode_channel(Decoder, Entry, TarError)


def encode[E = Never, R = Never, IE = Never, D = None]() -> Channel[  # noqa: PLR0915
    tuple[bytes, ...], TarError | IE | E, D, tuple[Entry[E, R], ...], IE, D, R
]:
    """A channel encoding entries into archive bytes: a USTAR header per entry, a
    PAX header only for what USTAR cannot hold (a long or non-ASCII path, link target
    or name, a size of 8 GiB or more, a uid or gid above ``2097151``, an mtime outside
    USTAR's range, or custom ``pax`` records), and two zero blocks at the end.

    Output is written in chunks of about 64 KiB, and large body chunks pass through
    uncopied, so bodies stream without being held in memory.

    A body with any byte count but ``header.size`` fails with ``"SizeMismatch"``.
    ``header.pax`` holds custom metadata: the keys of header fields and
    ``GNU.sparse.*`` fail with ``"InvalidHeader"``, as does a ``File`` path ending in
    ``/``, a non-zero size on an entry other than ``File`` and ``Other``, or a device
    number above ``2097151``. ``mtime`` is rounded down to whole seconds, and a naive
    ``datetime`` fails with ``"InvalidHeader"``. ``typeflag`` is only written for
    ``Other`` entries.

    Entries that differ in their bodies' errors or services do not infer one ``E`` and
    ``R``: annotate the stream, as ``Stream[Entry[E1 | E2, R1 | R2]]``."""

    def transform(upstream: AnyPull, scope: CloseableScope) -> AnyPull:  # noqa: PLR0915
        encoder = Encoder()
        entries: tuple[Entry[Any, Any], ...] = ()
        index = 0
        done: tuple[Any] | None = None
        body: AnyPull | None = None
        body_scope: CloseableScope | None = None

        def on_body(chunks: tuple[bytes, ...] | None) -> Any:
            nonlocal body, body_scope
            try:
                if chunks is not None:
                    for chunk in chunks:
                        encoder.body(chunk)
                    return pull
            except TarError as error:
                return fail_exit(error)
            body = None
            assert body_scope is not None
            closing = body_scope.close(void)
            body_scope = None
            return closing.flat_map(on_body_closed)

        def on_body_closed(_: None) -> Any:
            try:
                encoder.end()
            except TarError as error:
                return fail_exit(error)
            return pull

        def begin(entry: Entry[Any, Any]) -> Any:
            nonlocal body, body_scope
            # Directories, links and in-memory files have nothing to stream
            source = entry.body
            data = (
                b"" if source is empty else source.content if isinstance(source, _Content) else None
            )
            try:
                encoder.begin(entry.header)
                if data is not None:
                    encoder.body(data)
                    encoder.end()
            except TarError as error:
                return fail_exit(error)
            if data is not None:
                return pull
            body_scope = scope.fork_unsafe()

            def opened(opened_pull: AnyPull) -> Any:
                nonlocal body
                body = opened_pull
                return pull

            return source._channel.to_pull_scoped(body_scope).flat_map(opened)

        def upstream_done(value: object) -> AnyPull:
            nonlocal done
            done = (value,)
            encoder.finish()
            return _Succeed(None)

        def on_upstream(next_entries: tuple[Entry[Any, Any], ...] | None) -> Any:
            nonlocal entries, index
            if next_entries is not None:
                entries = next_entries
                index = 0
            return pull

        def step() -> Any:
            nonlocal index
            if encoder.buffered >= SLAB_SIZE:
                return Success(encoder.flush())
            if body is not None:
                return catch_done(body, lambda _: _Succeed(None)).flat_map(on_body)
            if index < len(entries):
                entry = entries[index]
                index += 1
                return begin(entry)
            if encoder.buffered > 0:
                return Success(encoder.flush())
            if done is not None:
                return end_with(done[0])
            return catch_done(upstream, upstream_done).flat_map(on_upstream)

        pull: AnyPull = _Suspend(step)
        return _Succeed(pull)

    channel: Any = from_transform(
        lambda upstream, scope: _Suspend(lambda: transform(upstream, scope))
    )
    return channel


publish(globals())
