"""``Logger[O]``: a function from one log entry (``Options``) to an output.

Effect's ``Logger<Message, Output>`` also abstracts the message; every
logger the runtime calls receives the logged items, so here the message is
always that tuple and only the output varies.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any, Generic, NamedTuple, Never, Self, TypeVar

from pyfect.cause import Cause
from pyfect.logger._level import LogLevel

if TYPE_CHECKING:
    from pyfect._core import Effect
    from pyfect._fiber import Fiber
    from pyfect.console import Console
    from pyfect.duration import Duration
    from pyfect.file_system import FileSystem, OpenFlag
    from pyfect.platform_error import PlatformError
    from pyfect.scope import Scope

O_co = TypeVar("O_co", covariant=True)

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MILLISECOND = timedelta(milliseconds=1)


class LogSpan(NamedTuple):
    """A span opened by ``with_log_span``: its label and when it started,
    in whole milliseconds since the epoch."""

    label: str
    start: int


@dataclass(frozen=True, slots=True)
class Options:
    """One log entry, as each logger receives it."""

    message: tuple[object, ...]
    """The logged items, causes taken out."""
    log_level: LogLevel
    cause: Cause[object]
    """The causes logged with the items, merged; empty when there were none."""
    fiber: Fiber[Any, Any]
    """The logging fiber. Read the annotations and spans with
    ``fiber.get_ref(CurrentLogAnnotations)`` and ``CurrentLogSpans``."""
    date: datetime
    """When it was logged, by the fiber's ``Clock`` (aware, UTC)."""

    @property
    def millis(self) -> int:
        """``date`` in whole milliseconds since the epoch."""
        return (self.date - _EPOCH) // _MILLISECOND


class Logger(Generic[O_co]):
    """A logger producing ``O`` from each entry. Make one with
    ``Logger.make``; install it with ``logger.layer([...])`` or
    ``eff.with_logger(...)``."""

    __slots__ = ("_log",)

    def __init__(self, log: Callable[[Options], O_co]) -> None:
        self._log = log

    @staticmethod
    def make[O](log: Callable[[Options], O]) -> Logger[O]:
        return Logger(log)

    def log(self, options: Options) -> O_co:
        return self._log(options)

    def map[O2](self, f: Callable[[O_co], O2]) -> Logger[O2]:
        """A logger whose output is ``f`` of this one's."""
        log = self._log
        return Logger(lambda options: f(log(options)))

    def with_console_log(self) -> Logger[None]:
        """Write the output to the current console with ``log``."""
        return self._to_console(lambda console, _level: console.log)

    def with_console_error(self) -> Logger[None]:
        """Write the output to the current console with ``error``."""
        return self._to_console(lambda console, _level: console.error)

    def with_leveled_console(self) -> Logger[None]:
        """Write the output with the console method matching the level:
        ``debug``, ``info``, ``trace``, ``warn``, ``error`` (for ``ERROR``
        and ``FATAL``)."""

        def method(console: Console, level: LogLevel) -> Callable[..., None]:
            match level:
                case LogLevel.DEBUG:
                    return console.debug
                case LogLevel.INFO:
                    return console.info
                case LogLevel.TRACE:
                    return console.trace
                case LogLevel.WARN:
                    return console.warn
                case LogLevel.ERROR | LogLevel.FATAL:
                    return console.error
                case _:
                    return console.log

        return self._to_console(method)

    def _to_console(self, pick: Callable[[Console, LogLevel], Callable[..., None]]) -> Logger[None]:
        from pyfect.console import CurrentConsole

        log = self._log

        def write(options: Options) -> None:
            console = options.fiber.get_ref(CurrentConsole)
            pick(console, options.log_level)(log(options))

        return Logger(write)

    def batched(
        self, *, window: Duration, flush: Callable[[Sequence[O_co]], Effect[object]]
    ) -> Effect[Logger[None], Never, Scope]:
        """A logger that buffers this one's outputs and hands them to
        ``flush`` every ``window``, and once more when the scope closes
        (after any flush in progress)."""
        from pyfect.logger._batched import batched

        return batched(self, window, flush)

    def to_file(
        self: Logger[str],
        path: str,
        *,
        flag: OpenFlag = "a+",
        mode: int = 0o666,
        batch_window: Duration = 1.0,
    ) -> Effect[Logger[None], PlatformError, Scope | FileSystem]:
        """A logger appending this one's lines to the file at ``path``
        (opened with ``flag`` until the scope closes), written in batches
        every ``batch_window``; a failed write is dropped (Effect's
        ``Logger.toFile``)."""
        from pyfect.logger._file import to_file

        return to_file(self, path, flag=flag, mode=mode, batch_window=batch_window)

    def __repr__(self) -> str:
        return f"Logger({self._log!r})"

    def pipe[B](self, f: Callable[[Self], B], /) -> B:
        return f(self)
