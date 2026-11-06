"""What ``tar``, ``zip`` and ``xml`` do around their bodies and inputs: not Effect test
titles, but each value here is what Effect does under Node on the same program
(zip64 near 4 GiB, finalizer order, chunk shapes, repeated failures)."""
# pyright: reportUnknownVariableType=false, reportUnknownMemberType=false, reportUnknownArgumentType=false

from __future__ import annotations

import io
import os
import zipfile
import zlib
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

import pyfect as fx
from pyfect import channel, stream, testing
from pyfect.encoding import tar, xml
from pyfect.encoding import zip as Zip
from pyfect.encoding._archive import ByteQueue
from pyfect.encoding.zip._inflate import Inflater
from pyfect.scope import acquire_release


def error_of(result: Any) -> Any:
    return result.cause.find_error().value


def run(effect: Any) -> Any:
    return fx.run_blocking(effect)


def tar_bytes() -> bytes:
    items = [tar.file("a", "aaaa"), tar.file("b", "bbbb")]
    return run(stream.from_iterable(items).pipe_through_channel(tar.encode()).run_bytes())


def zip_bytes() -> bytes:
    items = [Zip.file("a", "aaaa", method="Store"), Zip.file("b", "bbbb")]
    source: Any = stream.from_iterable(items)
    return run(source.pipe_through_channel(Zip.encode()).run_bytes())


ARCHIVES: dict[str, tuple[Any, Any]] = {"tar": (tar, tar_bytes), "zip": (Zip, zip_bytes)}


def bytes_entry(name: str, path: str, body: Any) -> Any:
    if name == "tar":
        return tar.file_stream(path, 3, body)
    return Zip.file_stream(path, body, method="Store", size=3)


@pytest.mark.parametrize("name", list(ARCHIVES))
@testing.effect
def test_decode_passes_the_upstream_done_value_on(name: str) -> Any:
    module, make = ARCHIVES[name]
    source = channel.from_iterable([(make(),)]).concat(channel.end("finished"))
    result = yield from source.pipe_to(module.decode()).run_drain()
    assert result == "finished"


@pytest.mark.parametrize("name", list(ARCHIVES))
@testing.effect
def test_concurrent_bodies_pull_the_input_one_at_a_time(name: str) -> Any:
    """Effect's lock around the upstream: a second reader waits, then reuses the
    input the first one pulled."""
    module, make = ARCHIVES[name]
    data = make()
    pulling = 0
    most = 0

    def slow(chunk: bytes) -> fx.Effect[bytes]:
        @fx.gen
        def body():
            nonlocal pulling, most
            pulling += 1
            most = max(most, pulling)
            yield from fx.yield_now()
            yield from fx.yield_now()
            pulling -= 1
            return chunk

        return body

    def read(entry: Any) -> Any:
        return fx.all(entry.body.run_bytes(), entry.body.run_bytes(), concurrency=2)

    chunks = [data[i : i + 7] for i in range(0, len(data), 7)]
    source = stream.from_iterable(chunks, chunk_size=1).map_effect(slow)
    bodies = yield from source.pipe_through_channel(module.decode()).map_effect(read).run_collect()
    assert [first + second for first, second in bodies] == [b"aaaa", b"bbbb"]
    assert most == 1


@pytest.mark.parametrize("name", list(ARCHIVES))
@testing.effect
def test_a_body_is_released_before_the_next_entry_starts(name: str) -> Any:
    module, _ = ARCHIVES[name]
    log: list[str] = []

    def body(path: str) -> Any:
        resource = acquire_release(
            fx.sync(lambda: log.append(f"acquire {path}")),
            lambda _, __: fx.sync(lambda: log.append(f"release {path}")),
        )
        return stream.unwrap(resource.map(lambda _: stream.make(b"xxx")))

    def emitted(_: bytes) -> fx.Effect[None]:
        return fx.sync(lambda: log.append("emit"))

    items = [bytes_entry(name, "p", body("p")), bytes_entry(name, "q", body("q"))]
    source: Any = stream.from_iterable(items)
    yield from source.pipe_through_channel(module.encode()).tap(emitted).run_drain()
    assert log == ["acquire p", "release p", "acquire q", "release q", "emit", "emit"]


@testing.effect
def test_output_chunks_gather_small_pieces_and_pass_large_ones_through() -> Any:
    def sizes(chunk: tuple[bytes, ...]) -> list[int]:
        return [len(piece) for piece in chunk]

    def shape(source: Any, encode: Any) -> Any:
        return (source.pipe_through_channel(encode).chunks().map(sizes)).run_collect()

    tar_items = [tar.file("a", bytes(70_000)), tar.file("b", bytes(10))]
    assert (yield from shape(stream.from_iterable(tar_items), tar.encode())) == [
        [512, 70_000, 144],
        [1024],
        [1024],
    ]
    zip_items = [
        Zip.file("a", bytes(70_000), method="Store"),
        Zip.file("b", bytes(10), method="Store"),
    ]
    assert (yield from shape(stream.from_iterable(zip_items), Zip.encode())) == [
        [40, 70_000],
        [50],
        [134],
    ]


def test_every_zip_error_ends_the_archive() -> None:
    """A later read of the same body, and the next entry, fail with the same error."""
    data = bytearray(zip_bytes())
    data[14] ^= 0xFF  # the CRC-32 of the first entry
    seen: list[Any] = []

    def read(entry: Any) -> Any:
        @fx.gen
        def body():
            seen.append((yield from entry.body.run_bytes().exit()))
            seen.append((yield from entry.body.run_bytes().exit()))

        return body

    source = stream.make(bytes(data)).pipe_through_channel(Zip.decode())
    last = fx.run_blocking_exit(source.map_effect(read).run_drain())
    errors = [error_of(result) for result in [*seen, last]]
    assert [error.kind for error in errors] == ["Checksum"] * 3
    assert errors[0] is errors[1] is errors[2]


def test_the_inflater_takes_bounded_pieces_of_a_large_chunk() -> None:
    """An archive held in one chunk must not cost a copy of what is left of it per
    entry and per 64 KiB of output, which is quadratic: Effect's views copy nothing."""
    taken: list[int] = []

    class Spy(ByteQueue):
        def take_some(self, most: int) -> bytes:
            out = super().take_some(most)
            taken.append(len(out))
            return out

    compressor = zlib.compressobj(wbits=-15)
    body = os.urandom(300_000)
    data = compressor.compress(body) + compressor.flush()
    rest = b"what follows the stream"
    queue = Spy()
    queue.push(data + rest)
    inflater = Inflater(queue)
    out = bytearray()
    while (piece := inflater.pull()) is not None:
        assert isinstance(piece, bytes)
        out += piece
    assert bytes(out) == body
    assert max(taken) <= 64 * 1024
    # What the stream did not use is back on the queue, in place and counted
    assert queue.length == len(rest)
    assert queue.consumed == len(data)
    assert queue.peek(len(rest)) == rest
    assert queue.take(len(rest)) == rest


def test_output_zlib_still_holds_after_the_last_input_is_read() -> None:
    """The first 64 KiB of these zeros use up the input with the rest of the output
    and the end of the stream still inside ``zlib``, so the body is complete and only
    the entry after it is missing."""
    items = [Zip.file("zeros", bytes(65_540))]
    source: Any = stream.from_iterable(items)
    data = run(source.pipe_through_channel(Zip.encode()).run_bytes())
    compressed = int.from_bytes(data[18:22], "little")
    start = 30 + int.from_bytes(data[26:28], "little") + int.from_bytes(data[28:30], "little")
    bodies: list[int] = []

    def keep(body: bytes) -> None:
        bodies.append(len(body))

    def read(entry: Any) -> Any:
        return entry.body.run_bytes().map(keep)

    entries = stream.make(data[: start + compressed]).pipe_through_channel(Zip.decode())
    result = fx.run_blocking_exit(entries.map_effect(read).run_drain())
    assert bodies == [65_540]
    assert error_of(result).kind == "Truncated"


def test_many_entries_in_one_chunk_read_as_when_split() -> None:
    items = [Zip.file(f"f{i}", os.urandom(200 + i)) for i in range(300)]
    items.append(Zip.file("big", os.urandom(200_000)))
    source: Any = stream.from_iterable(items)
    data = run(source.pipe_through_channel(Zip.encode()).run_bytes())

    def read(entry: Any) -> Any:
        def named(body: bytes) -> tuple[str, bytes]:
            return entry.header.path, body

        return entry.body.run_bytes().map(named)

    decoded = stream.make(data).pipe_through_channel(Zip.decode()).map_effect(read).run_collect()
    assert run(decoded) == [(item.header.path, item.content) for item in items]


@testing.effect
def test_deflating_large_content_lets_other_fibers_run() -> Any:
    finished = False
    turns = 0

    @fx.gen
    def count():
        nonlocal turns
        while not finished:
            turns += 1
            yield from fx.yield_now()

    def done(_: int) -> None:
        nonlocal finished
        finished = True

    items = [Zip.file("big", bytes(1_000_000))]
    source: Any = stream.from_iterable(items)
    encoding = source.pipe_through_channel(Zip.encode()).run_count().map(done)
    yield from fx.all(encoding, count, concurrency=2)
    assert turns > 1_000_000 // (64 * 1024)


@pytest.mark.parametrize(
    ("size", "zip64"),
    [
        (0xFFFFFFFF - 16 * 1024 * 1024 - 1, False),
        (0xFFFFFFFF - 16 * 1024 * 1024, True),
    ],
)
def test_a_deflated_entry_near_4_gib_declares_zip64_with_room_to_grow(
    size: int, zip64: bool
) -> None:
    """As Effect's ``DEFLATE_HEADROOM``. The body fails right after the local header has
    gone out, so nothing near that size is written."""
    written: list[bytes] = []

    def keep(chunk: bytes) -> fx.Effect[None]:
        return fx.sync(lambda: written.append(chunk))

    # Incompressible, so that deflate writes past the 64 KiB the writer holds
    body = stream.make(os.urandom(200_000)).concat(stream.fail("stop"))
    items = [Zip.file_stream("f", body, size=size)]
    source: Any = stream.from_iterable(items)
    fx.run_blocking_exit(source.pipe_through_channel(Zip.encode()).run_for_each(keep))
    header = b"".join(written)
    version = int.from_bytes(header[4:6], "little")
    assert version == (45 if zip64 else 20)


def test_an_mtime_past_2107_in_any_offset_is_the_last_dos_time() -> None:
    """``astimezone`` overflows on the last day ``datetime`` holds, and Effect's ``Date``
    has no such edge."""
    mtime = datetime(9999, 12, 31, 23, 59, tzinfo=timezone(timedelta(hours=-5)))
    entries: Any = stream.make(Zip.file("a", "x", mtime=mtime, method="Store"))
    data = run(entries.pipe_through_channel(Zip.encode()).run_bytes())
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert archive.getinfo("a").date_time == (2107, 12, 31, 23, 59, 58)


def test_an_mtime_in_another_offset_is_written_in_utc() -> None:
    mtime = datetime(2024, 1, 1, 22, 0, tzinfo=timezone(timedelta(hours=-5)))
    assert mtime.astimezone(UTC).day == 2
    entries: Any = stream.make(Zip.file("a", "x", mtime=mtime, method="Store"))
    data = run(entries.pipe_through_channel(Zip.encode()).run_bytes())
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert archive.getinfo("a").date_time == (2024, 1, 2, 3, 0, 0)


def test_elements_refuses_a_path_given_as_one_string() -> None:
    """``Sequence[str]`` admits a ``str``, which would match one letter per level and so
    nothing, with no error."""
    with pytest.raises(TypeError, match="path must be a sequence of names"):
        xml.elements("feed")
