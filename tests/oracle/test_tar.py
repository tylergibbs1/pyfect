"""Ports of Effect's ``encoding/Tar.test.ts``, every title. Each test's docstring
is the Effect test title; ``Uint8Array`` is ``bytes`` and ``mkUint8Array`` is
``run_bytes``. The fixtures are Effect's, copied to ``fixtures/tar``."""

from __future__ import annotations

import gzip
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

import pyfect as fx
from pyfect import stream, testing
from pyfect.encoding import tar
from pyfect.encoding.tar import Entry, TarError

FIXTURES = Path(__file__).parent / "fixtures" / "tar"


def fixture(name: str) -> bytes:
    return gzip.decompress((FIXTURES / f"{name}.tar.gz").read_bytes())


def text(data: bytes) -> str:
    return data.decode("utf-8", "replace")


def encode(items: list[Any]) -> fx.Effect[bytes, Any]:
    source: Any = stream.from_iterable(items)
    return source.pipe_through_channel(tar.encode()).run_bytes()


def entries(data: bytes, chunk_size: int) -> stream.Stream[Entry[TarError], TarError]:
    chunks = [data[i : i + chunk_size] for i in range(0, len(data), chunk_size)]
    return stream.from_iterable(chunks, chunk_size=1).pipe_through_channel(tar.decode())


def decode(
    data: bytes, chunk_size: int = 4096
) -> fx.Effect[list[tuple[tar.Header, bytes]], TarError]:
    def read(entry: Entry[TarError]) -> fx.Effect[tuple[tar.Header, bytes], TarError]:
        return entry.body.run_bytes().map(lambda body: (entry.header, body))

    return entries(data, chunk_size).map_effect(read).run_collect()


def failure(effect: fx.Effect[Any, Any]) -> fx.Effect[object]:
    return effect.flip().map(lambda error: error.kind if tar.is_tar_error(error) else error)


@testing.effect
def test_round_trips_entries() -> Any:
    """round trips entries"""
    items: list[Entry] = [
        tar.directory("dir"),
        tar.file("dir/a.txt", "hello\n"),
        tar.file_stream("dir/b.bin", 3, stream.make(bytes((0, 1)), bytes((255,)))),
        tar.symlink(
            "dir/link",
            "a.txt",
            uid=1000,
            uname="user",
            mtime=datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC),
        ),
        tar.hardlink("dir/hard", "dir/a.txt"),
    ]
    output = yield from decode((yield from encode(items)))
    assert [header for header, _ in output] == [item.header for item in items]
    assert [body for _, body in output] == [b"", b"hello\n", bytes((0, 1, 255)), b"", b""]


@testing.effect
def test_round_trips_headers_that_do_not_fit_ustar_fields() -> Any:
    """round trips headers that do not fit USTAR fields"""
    items = [
        tar.file(f"{'a' * 120}/{'b' * 90}.txt", "x"),
        tar.file(f"{'c' * 300}.txt", "y"),
        tar.file("ids", "", uid=3_000_000, gname="grüppe", pax={"SCHILY.xattr.user.k": "v"}),
    ]
    output = yield from decode((yield from encode(items)))
    assert [header for header, _ in output] == [item.header for item in items]
    assert [text(body) for _, body in output] == ["x", "y", ""]


@testing.effect
def test_fails_when_a_body_does_not_match_its_declared_size() -> Any:
    """fails when a body does not match its declared size"""
    short = tar.file_stream("f", 5, stream.make(b"abc"))
    assert (yield from failure(encode([short]))) == "SizeMismatch"
    long = tar.file_stream("f", 2, stream.make(b"abc"))
    assert (yield from failure(encode([long]))) == "SizeMismatch"


_TREE: list[tuple[str, str, int, str]] = [
    ("tree/", "Directory", 3_000_000, ""),
    (f"tree/{'a' * 80}/", "Directory", 3_000_000, ""),
    (f"tree/{'a' * 80}/{'b' * 60}/", "Directory", 3_000_000, ""),
    (f"tree/{'a' * 80}/{'b' * 60}/{'c' * 90}.txt", "File", 3_000_000, "split\n"),
    (f"tree/{'d' * 120}/", "Directory", 3_000_000, ""),
    (f"tree/{'d' * 120}/{'e' * 120}/", "Directory", 3_000_000, ""),
    (f"tree/{'d' * 120}/{'e' * 120}/{'f' * 30}.txt", "File", 3_000_000, "long\n"),
    ("tree/dir/", "Directory", 3_000_000, ""),
    ("tree/dir/hello.txt", "File", 3_000_000, "hello\n"),
    ("tree/fifo", "Fifo", 3_000_000, ""),
    ("tree/hardlink.txt", "Hardlink", 3_000_000, "tree/dir/hello.txt"),
    ("tree/héllo-wörld-日本.txt", "File", 3_000_000, "unicode\n"),
    ("tree/longlink", "Symlink", 3_000_000, f"{'x' * 150}/target"),
    ("tree/shortlink", "Symlink", 3_000_000, "dir/hello.txt"),
]
_FIXTURES: dict[str, list[tuple[str, str, int, str]]] = {
    "gnu": _TREE,
    "pax": _TREE,
    "ustar": [
        ("small/", "Directory", 0, ""),
        (f"small/{'a' * 80}/", "Directory", 0, ""),
        (f"small/{'a' * 80}/{'b' * 60}/", "Directory", 0, ""),
        (f"small/{'a' * 80}/{'b' * 60}/{'c' * 90}.txt", "File", 0, "split\n"),
        ("small/dir/", "Directory", 0, ""),
        ("small/dir/hello.txt", "File", 0, "hello\n"),
        ("small/dir/link", "Symlink", 0, "hello.txt"),
    ],
    "v7": [
        ("small/dir/", "Directory", 0, ""),
        ("small/dir/hello.txt", "File", 0, "hello\n"),
        ("small/dir/link", "Symlink", 0, "hello.txt"),
    ],
}


@pytest.mark.parametrize("name", list(_FIXTURES))
@testing.effect
def test_reads_gnu_tar_archives_in_any_chunk_size(name: str) -> Any:
    """reads GNU tar --format=gnu archives in any chunk size
    reads GNU tar --format=pax archives in any chunk size
    reads GNU tar --format=ustar archives in any chunk size
    reads GNU tar --format=v7 archives in any chunk size"""
    data = fixture(name)
    for chunk_size in (1, len(data)):
        output = yield from decode(data, chunk_size)
        assert [
            (
                header.path,
                header.type,
                header.uid,
                text(body) if header.link_target is None else header.link_target,
            )
            for header, body in output
        ] == _FIXTURES[name]


@testing.effect
def test_emits_body_bytes_before_the_rest_of_the_archive_arrives() -> Any:
    """emits body bytes before the rest of the archive arrives"""
    data = yield from encode([tar.file("f", "z" * 2000)])
    source = yield from fx.Queue[bytes, fx.Done].unbounded()
    yield from source.offer(data[: 512 + 100])
    pull_entry = yield from (stream.from_queue(source).pipe_through_channel(tar.decode()).to_pull())
    (entry,) = yield from pull_entry
    pull_body = yield from entry.body.to_pull()
    assert text((yield from pull_body)[0]) == "z" * 100

    yield from source.offer(data[512 + 100 :])
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
    data = yield from encode([tar.file("a", "a" * 1000), tar.file("b", "b" * 700)])

    def first_byte(entry: Entry[TarError]) -> fx.Effect[int, TarError]:
        return entry.body.take(1).run_bytes().map(lambda body: body[0])

    for chunk_size in (1, len(data)):
        output = yield from entries(data, chunk_size).map_effect(first_byte).run_collect()
        assert output == [ord("a"), ord("b")]


@testing.effect
def test_fails_body_reads_after_the_next_entry_is_pulled() -> Any:
    """fails body reads after the next entry is pulled"""
    data = yield from encode([tar.file("a", "a"), tar.file("b", "b")])
    pull = yield from entries(data, 512).to_pull()
    (a,) = yield from pull
    yield from pull
    assert (yield from failure(a.body.run_drain())) == "BodyConsumed"


@testing.effect
def test_keeps_leading_byte_order_marks_in_pax_paths_link_targets_and_keys() -> Any:
    """keeps leading byte order marks in PAX paths, link targets and keys"""
    name = "﻿/etc/passwd"
    pax = {"﻿path": "other"}
    ((header, _),) = yield from decode((yield from encode([tar.symlink(name, name, pax=pax)])))
    assert header.path == name
    assert header.link_target == name
    assert header.pax == pax


@testing.effect
def test_keeps_a_leading_byte_order_mark_in_a_ustar_name() -> Any:
    """keeps a leading byte order mark in a USTAR name"""
    ustar = bytearray((yield from encode([tar.file("___/etc/passwd", "")])))
    ustar[0:3] = b"\xef\xbb\xbf"
    ustar[148:156] = b" " * 8
    ustar[148:156] = f"{sum(ustar[:512]):06o}\0 ".encode()
    ((header, _),) = yield from decode(bytes(ustar))
    assert header.path == "﻿/etc/passwd"


@testing.effect
def test_fails_on_truncated_or_corrupt_archives() -> Any:
    """fails on truncated or corrupt archives"""
    data = bytearray((yield from encode([tar.file("a", "a" * 600)])))
    assert (yield from failure(decode(bytes(data[: 512 + 300])))) == "Truncated"
    data[0] = ord("b")
    assert (yield from failure(decode(bytes(data)))) == "InvalidHeader"


@testing.effect
def test_fails_on_gnu_sparse_files() -> Any:
    """fails on GNU sparse files"""
    assert (yield from failure(decode(fixture("sparse-gnu")))) == "Unsupported"
    assert (yield from failure(decode(fixture("sparse-pax")))) == "Unsupported"
