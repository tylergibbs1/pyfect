"""The console loggers write to: a ``Console`` read from the
``CurrentConsole`` reference, so tests can swap it.

``LiveConsole`` behaves like Node's ``console``: ``log`` / ``info`` /
``debug`` print to stdout and ``warn`` / ``error`` / ``trace`` to stderr,
arguments joined by spaces (strings as they are, anything else by
``repr``), and every line indented two spaces per open ``group``.
"""

from __future__ import annotations

import sys
import threading
from typing import Protocol, TextIO

from pyfect.context import Reference


class Console(Protocol):
    """What loggers write through. Each method writes one entry made of
    ``args``."""

    def log(self, *args: object) -> None: ...
    def info(self, *args: object) -> None: ...
    def debug(self, *args: object) -> None: ...
    def warn(self, *args: object) -> None: ...
    def error(self, *args: object) -> None: ...
    def trace(self, *args: object) -> None: ...
    def group(self, *args: object) -> None:
        """Write ``args`` (if any) and indent what follows until
        ``group_end``."""
        ...

    def group_end(self) -> None: ...


def _text(value: object) -> str:
    return value if isinstance(value, str) else repr(value)


class LiveConsole:
    """Writes to ``sys.stdout`` / ``sys.stderr`` as they are at each call,
    so pytest's capture and ``contextlib.redirect_stdout`` see it."""

    def __init__(self) -> None:
        self._indent = 0
        self._lock = threading.Lock()

    def _write(self, stream: TextIO, args: tuple[object, ...], prefix: str = "") -> None:
        pad = "  " * self._indent
        text = prefix + " ".join(_text(a) for a in args)
        with self._lock:
            stream.write("".join(pad + line + "\n" for line in text.split("\n")))

    def log(self, *args: object) -> None:
        self._write(sys.stdout, args)

    def info(self, *args: object) -> None:
        self._write(sys.stdout, args)

    def debug(self, *args: object) -> None:
        self._write(sys.stdout, args)

    def warn(self, *args: object) -> None:
        self._write(sys.stderr, args)

    def error(self, *args: object) -> None:
        self._write(sys.stderr, args)

    def trace(self, *args: object) -> None:
        self._write(sys.stderr, args, "Trace: ")

    def group(self, *args: object) -> None:
        if args:
            self.log(*args)
        self._indent += 1

    def group_end(self) -> None:
        self._indent = max(0, self._indent - 1)


class CurrentConsole(Reference[Console]):
    """The console in use; ``LiveConsole()`` unless provided."""

    @classmethod
    def default(cls) -> Console:
        return LiveConsole()
