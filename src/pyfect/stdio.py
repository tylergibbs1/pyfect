"""Command-line arguments and standard input and output as a service
(Effect's ``Stdio``).

``StdioService`` holds the arguments, whether each standard stream is a
terminal, sinks writing to standard output and error, and standard input as
a byte stream::

    io = yield from Stdio()
    yield from stream.make("hello\\n").run(io.stdout())

``layer`` is the process's (``sys.argv[1:]``, ``sys.stdin`` / ``stdout`` /
``stderr``, read when used, so a replaced ``sys.stdout`` is seen);
``layer_test`` builds one for tests from the parts a test cares about.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import IO, Any, Literal, Never, Protocol

from pyfect import sink as sink_
from pyfect import stream as stream_
from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect._js import text_encode
from pyfect.context import Tag
from pyfect.effect import fail, succeed, sync, try_blocking
from pyfect.errors import Done
from pyfect.layer import Layer
from pyfect.layer import succeed as layer_succeed
from pyfect.platform_error import PlatformError, system_error
from pyfect.sink import Sink
from pyfect.stream import Stream
from pyfect.stream._base import require_stream

type Output = Sink[None, str | bytes, Never, PlatformError]


class OutputSink(Protocol):
    """Makes a sink writing to an output stream. With ``end_on_done`` the
    stream is closed once the sink's input ends."""

    def __call__(self, *, end_on_done: bool = False) -> Output: ...


def _false() -> Effect[bool]:
    return succeed(False)


@dataclass(frozen=True, slots=True, kw_only=True)
class StdioService:
    """Effect's ``Stdio``; the constructor is ``Stdio.make`` (terminal
    checks default to ``False``)."""

    args: Effect[tuple[str, ...]]
    stdout: OutputSink
    stderr: OutputSink
    stdin: Stream[bytes, PlatformError]
    stdin_is_terminal: Effect[bool] = field(default_factory=_false)
    stdout_is_terminal: Effect[bool] = field(default_factory=_false)
    stderr_is_terminal: Effect[bool] = field(default_factory=_false)

    def __post_init__(self) -> None:
        for name in ("args", "stdin_is_terminal", "stdout_is_terminal", "stderr_is_terminal"):
            require_effect(getattr(self, name), name)
        require_stream(self.stdin, "stdin")


class Stdio(Tag[StdioService]):
    """The standard input and output a program uses."""


def _drain(*, end_on_done: bool = False) -> Output:
    return sink_.drain


def layer_test(
    *,
    args: Effect[tuple[str, ...]] | None = None,
    stdout: OutputSink = _drain,
    stderr: OutputSink = _drain,
    stdin: Stream[bytes, PlatformError] | None = None,
    stdin_is_terminal: Effect[bool] | None = None,
    stdout_is_terminal: Effect[bool] | None = None,
    stderr_is_terminal: Effect[bool] | None = None,
) -> Layer[Stdio]:
    """A ``Stdio`` for tests: no arguments, output drained, empty input and
    no terminals, unless given."""
    return layer_succeed(
        Stdio,
        StdioService(
            args=succeed(()) if args is None else args,
            stdout=stdout,
            stderr=stderr,
            stdin=stream_.empty if stdin is None else stdin,
            stdin_is_terminal=_false() if stdin_is_terminal is None else stdin_is_terminal,
            stdout_is_terminal=_false() if stdout_is_terminal is None else stdout_is_terminal,
            stderr_is_terminal=_false() if stderr_is_terminal is None else stderr_is_terminal,
        ),
    )


# --- the process's standard streams ---------------------------------------------

type _Method = Literal["stdin", "stdout", "stderr"]


def _stream(method: _Method) -> IO[Any] | None:
    return getattr(sys, method)


def _is_terminal(method: _Method) -> Effect[bool]:
    def check() -> bool:
        target = _stream(method)
        try:
            return target is not None and target.isatty()
        except ValueError:
            return False

    return sync(check)


def _error(method: _Method) -> Callable[[Exception], PlatformError]:
    return lambda cause: system_error("Unknown", module="Stdio", method=method, cause=cause)


def _write(method: _Method, chunk: str | bytes) -> None:
    target = _stream(method)
    if target is None:
        return
    if isinstance(chunk, str):
        target.write(chunk)
    else:
        binary: IO[bytes] | None = getattr(target, "buffer", None)
        if binary is None:
            target.write(chunk.decode(errors="replace"))
        else:
            target.flush()
            binary.write(chunk)
            binary.flush()
    target.flush()


def _close(method: _Method) -> None:
    target = _stream(method)
    if target is not None:
        target.close()


def _output(method: Literal["stdout", "stderr"]) -> OutputSink:
    def make(*, end_on_done: bool = False) -> Output:
        def each(chunk: str | bytes) -> Effect[None, PlatformError]:
            return try_blocking(lambda: _write(method, chunk), _error(method))

        write: Output = sink_.for_each(each)
        if not end_on_done:
            return write
        return write.flat_map(
            lambda _: sink_.from_effect(try_blocking(lambda: _close(method), _error(method)))
        )

    return make


def _read_chunk() -> bytes:
    target = _stream("stdin")
    if target is None:
        return b""
    binary: IO[bytes] | None = getattr(target, "buffer", None)
    if binary is None:
        return text_encode(str(target.readline()))
    read1: Callable[[int], bytes] | None = getattr(binary, "read1", None)
    return binary.read(65536) if read1 is None else read1(65536)


def _next_input(data: bytes) -> Effect[tuple[bytes, ...], Done]:
    return succeed((data,)) if data else fail(Done())


live = StdioService(
    args=sync(lambda: tuple(sys.argv[1:])),
    stdout=_output("stdout"),
    stderr=_output("stderr"),
    stdin=stream_.from_pull(
        succeed(try_blocking(_read_chunk, _error("stdin")).flat_map(_next_input))
    ),
    stdin_is_terminal=_is_terminal("stdin"),
    stdout_is_terminal=_is_terminal("stdout"),
    stderr_is_terminal=_is_terminal("stderr"),
)
"""The process's arguments and standard streams. Reads and writes run on a
worker thread; an interrupted read leaves its thread waiting for input."""

layer: Layer[Stdio] = layer_succeed(Stdio, live)

__all__ = [
    "Output",
    "OutputSink",
    "Stdio",
    "StdioService",
    "layer",
    "layer_test",
    "live",
]
