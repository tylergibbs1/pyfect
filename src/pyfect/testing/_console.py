"""``TestConsole``: a console that records every call instead of writing."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, NamedTuple, Never, final

from pyfect._core import Effect, _Succeed
from pyfect.console import Console, CurrentConsole
from pyfect.effect import die, sync
from pyfect.layer import Layer
from pyfect.layer import sync as layer_sync

type Method = Literal[
    "assert",
    "clear",
    "count",
    "count_reset",
    "debug",
    "dir",
    "error",
    "group",
    "group_collapsed",
    "group_end",
    "info",
    "log",
    "table",
    "time",
    "time_end",
    "time_log",
    "trace",
    "warn",
]


class Entry(NamedTuple):
    """One console call: the method and the arguments it was given."""

    method: Method
    parameters: tuple[object, ...]


@final
class TestConsole:
    """Records each call as an ``Entry``; writes nothing.

    ``@testing.effect`` tests run with a fresh one, so they read what they
    (and the console loggers) wrote with ``testing.log_lines``::

        @testing.effect
        def test_greets():
            yield from console.log("hello")
            assert (yield from testing.log_lines) == ["hello"]
    """

    __test__ = False  # not a pytest test class

    def __init__(self) -> None:
        self._entries: list[Entry] = []

    @staticmethod
    def layer() -> Layer[Never]:
        """Provide a fresh ``TestConsole`` as the ``CurrentConsole``."""
        return layer_sync(CurrentConsole, TestConsole)

    @property
    def entries(self) -> list[Entry]:
        """Every call so far, in order."""
        return list(self._entries)

    @property
    def log_lines(self) -> Effect[list[object]]:
        """Every argument given to ``log``, in order."""
        return sync(lambda: self._lines("log"))

    @property
    def error_lines(self) -> Effect[list[object]]:
        """Every argument given to ``error``, in order."""
        return sync(lambda: self._lines("error"))

    def _lines(self, method: Method) -> list[object]:
        return [p for e in self._entries if e.method == method for p in e.parameters]

    def _record(self, method: Method, *parameters: object) -> None:
        self._entries.append(Entry(method, parameters))

    def assert_(self, condition: bool, *args: object) -> None:
        self._record("assert", condition, *args)

    def clear(self) -> None:
        self._record("clear")

    def count(self, label: str = "default") -> None:
        self._record("count", label)

    def count_reset(self, label: str = "default") -> None:
        self._record("count_reset", label)

    def debug(self, *args: object) -> None:
        self._record("debug", *args)

    def dir(self, item: object) -> None:
        self._record("dir", item)

    def error(self, *args: object) -> None:
        self._record("error", *args)

    def group(self, *args: object) -> None:
        self._record("group", *args)

    def group_collapsed(self, *args: object) -> None:
        self._record("group_collapsed", *args)

    def group_end(self) -> None:
        self._record("group_end")

    def info(self, *args: object) -> None:
        self._record("info", *args)

    def log(self, *args: object) -> None:
        self._record("log", *args)

    def table(self, data: object, properties: Sequence[str] | None = None) -> None:
        self._record("table", data, properties)

    def time(self, label: str = "default") -> None:
        self._record("time", label)

    def time_end(self, label: str = "default") -> None:
        self._record("time_end", label)

    def time_log(self, label: str = "default", *args: object) -> None:
        self._record("time_log", label, *args)

    def trace(self, *args: object) -> None:
        self._record("trace", *args)

    def warn(self, *args: object) -> None:
        self._record("warn", *args)


def _check(console: Console) -> Effect[TestConsole]:
    if isinstance(console, TestConsole):
        return _Succeed(console)
    return die(
        TypeError(
            f"the current console is a {type(console).__name__}, not a TestConsole; run the "
            "effect with a pyfect.testing runner or provide TestConsole.layer()"
        )
    )


def test_console() -> Effect[TestConsole]:
    """The ``TestConsole`` the effect runs with; dies if another console
    is current."""
    return CurrentConsole().flat_map(_check)


log_lines: Effect[list[object]] = test_console().flat_map(lambda c: c.log_lines)
"""The current ``TestConsole``'s ``log_lines``."""

error_lines: Effect[list[object]] = test_console().flat_map(lambda c: c.error_lines)
"""The current ``TestConsole``'s ``error_lines``."""
