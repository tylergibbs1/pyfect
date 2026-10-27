"""``LiveConsole``: Node's ``console`` on ``sys.stdout`` / ``sys.stderr``."""

from __future__ import annotations

import math
import pprint
import sys
import threading
import time
import warnings
from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal
from typing import TextIO

from pyfect.console._table import format_table, text

# Node's cursorTo(0, 0) and clearScreenDown.
_CLEAR = "\x1b[1;1H\x1b[0J"


class LiveConsole:
    """Writes like Node's ``console``: ``log`` / ``info`` / ``debug`` /
    ``count`` / ``time_*`` / ``table`` / ``dir`` to stdout, ``warn`` /
    ``error`` / ``trace`` / ``assert_`` to stderr, each line indented two
    spaces per open group. Streams are read at each call, so pytest's
    capture and ``contextlib.redirect_stdout`` see the output. Misused
    counters and timers warn with ``RuntimeWarning`` (Node's process
    warnings)."""

    def __init__(self) -> None:
        self._indent = 0
        self._lock = threading.Lock()
        self._counts: dict[str, int] = {}
        self._timers: dict[str, int] = {}

    def _write(self, stream: TextIO, args: tuple[object, ...], prefix: str = "") -> None:
        pad = "  " * self._indent
        line = prefix + " ".join(text(a) for a in args)
        with self._lock:
            stream.write("".join(pad + part + "\n" for part in line.split("\n")))

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

    def assert_(self, condition: bool, *args: object) -> None:
        if condition:
            return
        if args and isinstance(args[0], str):
            self.warn(f"Assertion failed: {args[0]}", *args[1:])
        else:
            self.warn("Assertion failed", *args)

    def clear(self) -> None:
        if sys.stdout.isatty():
            with self._lock:
                sys.stdout.write(_CLEAR)

    def count(self, label: str = "default") -> None:
        n = self._counts.get(label, 0) + 1
        self._counts[label] = n
        self.log(f"{label}: {n}")

    def count_reset(self, label: str = "default") -> None:
        if self._counts.pop(label, None) is None:
            warnings.warn(f"Count for '{label}' does not exist", RuntimeWarning, stacklevel=2)

    def dir(self, item: object) -> None:
        self._write(sys.stdout, (pprint.pformat(item),))

    def group(self, *args: object) -> None:
        if args:
            self.log(*args)
        self._indent += 1

    def group_collapsed(self, *args: object) -> None:
        self.group(*args)

    def group_end(self) -> None:
        self._indent = max(0, self._indent - 1)

    def table(self, data: object, properties: Sequence[str] | None = None) -> None:
        drawn = format_table(data, properties)
        self.log(data if drawn is None else drawn)

    def time(self, label: str = "default") -> None:
        if label in self._timers:
            warnings.warn(
                f"Label '{label}' already exists for console.time()", RuntimeWarning, stacklevel=2
            )
            return
        self._timers[label] = time.perf_counter_ns()

    def time_end(self, label: str = "default") -> None:
        if self._log_time(label, "time_end", ()):
            del self._timers[label]

    def time_log(self, label: str = "default", *args: object) -> None:
        self._log_time(label, "time_log", args)

    def _log_time(self, label: str, method: str, args: tuple[object, ...]) -> bool:
        start = self._timers.get(label)
        if start is None:
            warnings.warn(
                f"No such label '{label}' for console.{method}()", RuntimeWarning, stacklevel=3
            )
            return False
        elapsed = (time.perf_counter_ns() - start) / 1e6
        self.log(f"{label}: {format_elapsed(elapsed)}", *args)
        return True


def format_elapsed(ms: float) -> str:
    """Node's ``console.timeEnd`` format: ``0.023ms``, ``1.500s``,
    ``1:05.000 (m:ss.mmm)``, ``1:01:05.000 (h:mm:ss.mmm)``."""
    hours = minutes = 0
    seconds = 0.0
    if ms >= 1000:
        if ms >= 60_000:
            if ms >= 3_600_000:
                hours = math.floor(ms / 3_600_000)
                ms %= 3_600_000
            minutes = math.floor(ms / 60_000)
            ms %= 60_000
        seconds = ms / 1000
    if hours or minutes:
        whole, millis = _to_fixed3(seconds).split(".")
        head = f"{hours}:{minutes:02d}" if hours else str(minutes)
        return f"{head}:{whole.zfill(2)}.{millis} ({'h:m' if hours else ''}m:ss.mmm)"
    if seconds:
        return f"{_to_fixed3(seconds)}s"
    return _to_fixed3(ms).rstrip("0").rstrip(".") + "ms"


def _to_fixed3(x: float) -> str:
    """JavaScript's ``x.toFixed(3)``: exact ties round up, where Python's
    ``f"{x:.3f}"`` rounds them to even."""
    return str(Decimal(x).quantize(Decimal("0.001"), ROUND_HALF_UP))
