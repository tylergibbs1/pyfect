"""A multipart body is bounded by default, unlike Effect's: at most 1,000 parts, and
``to_persisted`` writes at most 100 files and 100 MiB. ``None`` removes a limit."""

from typing import Any, Never

import pytest

import pyfect as fx
from pyfect import byte_size, effect, sink, stream
from pyfect.exit import Failure, Success
from pyfect.file_system import FileSystem, NoopFileSystem
from pyfect.http import multipart as m
from pyfect.path import layer as path_layer
from pyfect.platform_error import PlatformError
from pyfect.scope import Scope, scoped
from pyfect.sink import Sink

BOUNDARY = "b"
HEADERS = {"content-type": f"multipart/form-data; boundary={BOUNDARY}"}


def _field(index: int) -> str:
    return f'--{BOUNDARY}\r\nContent-Disposition: form-data; name="f{index}"\r\n\r\nv\r\n'


def _file(index: int, content: str = "x") -> str:
    return (
        f"--{BOUNDARY}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{index}.txt"\r\n'
        f"Content-Type: text/plain\r\n\r\n{content}\r\n"
    )


def _body(parts: list[str]) -> stream.Stream[m.Part, m.MultipartError]:
    data = ("".join(parts) + f"--{BOUNDARY}--\r\n").encode()
    return stream.make(data).pipe_through_channel(m.make_channel(HEADERS))


def _exit[A](eff: fx.Effect[A, Any]) -> fx.Exit[A, Any]:
    return fx.run_blocking_exit(eff)


def _reason(exit: fx.Exit[Any, Any]) -> str:
    assert isinstance(exit, Failure), exit
    error = exit.cause.squash()
    assert isinstance(error, m.MultipartError), error
    return error.reason.tag


class _CountingFileSystem(NoopFileSystem):
    """A temporary directory and file sinks that only count what is written."""

    def __init__(self) -> None:
        self.files = 0
        self.bytes = 0

    def make_temp_directory_scoped(
        self, *, directory: str | None = None, prefix: str = ""
    ) -> fx.Effect[str, PlatformError, Scope]:
        return effect.succeed("/tmp/multipart")

    def sink(
        self, path: str, *, flag: Any = "w", mode: int = 0o666
    ) -> Sink[None, bytes, Never, PlatformError]:
        self.files += 1

        def write(chunk: bytes) -> fx.Effect[None]:
            self.bytes += len(chunk)
            return effect.void

        return sink.for_each(write)


def _persist(
    parts: list[str], file_system: _CountingFileSystem, **limits: Any
) -> fx.Exit[m.Persisted, Any]:
    eff: fx.Effect[m.Persisted, Any, Any] = m.to_persisted(_body(parts))
    if limits:
        eff = eff.pipe(effect.provide_context(m.limits_context(**limits)))
    eff = eff.pipe(effect.provide_service(FileSystem, file_system))
    return _exit(scoped(eff.pipe(fx.provide(path_layer))))


def test_the_default_limits_are_finite() -> None:
    assert m.MaxParts.default() == 1000
    assert m.MaxPersistedFiles.default() == 100
    assert m.MaxPersistedSize.default() == byte_size.mebibytes(100)


def test_a_body_of_more_than_1000_parts_fails_by_default() -> None:
    assert isinstance(_exit(_body([_field(i) for i in range(1000)]).run_drain()), Success)
    assert _reason(_exit(_body([_field(i) for i in range(1001)]).run_drain())) == "TooManyParts"


def test_max_parts_none_removes_the_limit() -> None:
    parts = _body([_field(i) for i in range(1001)]).run_drain()
    unlimited = parts.pipe(effect.provide_context(m.limits_context(max_parts=None)))
    assert isinstance(_exit(unlimited), Success)


def test_to_persisted_writes_at_most_100_files_by_default() -> None:
    file_system = _CountingFileSystem()
    assert isinstance(_persist([_file(i) for i in range(100)], file_system), Success)
    assert file_system.files == 100

    file_system = _CountingFileSystem()
    assert _reason(_persist([_file(i) for i in range(101)], file_system)) == "TooManyParts"
    assert file_system.files == 100


def test_fields_do_not_count_as_persisted_files() -> None:
    file_system = _CountingFileSystem()
    parts = [_field(i) for i in range(5)] + [_file(i) for i in range(2)]
    assert isinstance(_persist(parts, file_system, max_persisted_files=2), Success)


def test_persisted_bytes_stop_at_the_limit() -> None:
    file_system = _CountingFileSystem()
    parts = [_file(0, "a" * 600), _file(1, "a" * 600)]
    assert _reason(_persist(parts, file_system, max_persisted_size=1000)) == "BodyTooLarge"
    assert file_system.bytes <= 1000


@pytest.mark.parametrize(
    "limits",
    [
        {"max_persisted_files": None, "max_parts": None},
        {"max_persisted_files": 200, "max_persisted_size": None},
    ],
)
def test_the_persisted_limits_can_be_raised_or_removed(limits: dict[str, Any]) -> None:
    file_system = _CountingFileSystem()
    assert isinstance(_persist([_file(i) for i in range(150)], file_system, **limits), Success)
    assert file_system.files == 150
