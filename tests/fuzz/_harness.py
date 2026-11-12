"""Fuzz targets: functions of untrusted bytes that fail only in documented ways.

A target feeds its bytes to one parser and lets only that parser's documented
errors through (``raises_only``, ``settle``); anything else (an ``IndexError``, a
``RecursionError``, a defect) escapes and is a crash. ``check`` also fails an input
that runs longer than ``LIMIT`` seconds (a hang). The same targets run under
Hypothesis in pytest (test_fuzz.py) and under Atheris (``python -m fuzz``).
"""

from __future__ import annotations

import signal
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import Any

import pyfect as fx
from pyfect import stream
from pyfect.exit import Exit, Success
from pyfect.result import Ok

CORPUS = Path(__file__).parent / "corpus"
LIMIT = 5.0
"""Seconds one input may run: a parser of a few kilobytes takes milliseconds."""


class Crash(AssertionError):
    """An input made a target fail in an undocumented way."""


class Hang(Crash):
    """An input ran longer than ``LIMIT``."""


@dataclass(frozen=True, slots=True)
class Target:
    name: str
    run: Callable[[bytes], object]


TARGETS: dict[str, Target] = {}


def target(name: str) -> Callable[[Callable[[bytes], object]], Callable[[bytes], object]]:
    def register(run: Callable[[bytes], object]) -> Callable[[bytes], object]:
        assert name not in TARGETS, name
        TARGETS[name] = Target(name, run)
        return run

    return register


def raises_only[A](run: Callable[[], A], *documented: type[BaseException]) -> A | None:
    """``run()``, or ``None`` when it raises one of ``documented``."""
    try:
        return run()
    except documented:
        return None


def settle(eff: fx.Effect[Any, Any, Any], *documented: type[object]) -> Any:
    """The value ``eff`` succeeds with, or ``None`` when it fails with one of
    ``documented``; a defect, an interruption or another error is a ``Crash``."""
    return outcome(fx.run_blocking_exit(eff), *documented)


def outcome(exit: Exit[Any, Any], *documented: type[object]) -> Any:
    """``settle`` of an ``Exit``."""
    if isinstance(exit, Success):
        return exit.value
    cause = exit.cause
    defect = cause.find_defect()
    if isinstance(defect, Ok):
        found = defect.value
        raise Crash(f"defect: {found!r}") from (found if isinstance(found, BaseException) else None)
    error = cause.find_error()
    if not isinstance(error, Ok):
        raise Crash(f"no typed failure: {cause.pretty()}")
    if not isinstance(error.value, documented):
        raise Crash(f"undocumented failure: {error.value!r}")
    return None


def chunks(data: bytes) -> list[bytes]:
    """``data[1:]`` cut into pieces of a size the first byte picks (1 to 16
    bytes, or whole from 128 up), so parsers see every split."""
    if not data:
        return []
    size = data[0] % 16 + 1 if data[0] < 128 else max(len(data), 1)
    body = data[1:]
    return [body[i : i + size] for i in range(0, len(body), size)]


def run_channel(pieces: list[Any], channel: Any) -> Any:
    """``pieces`` (one chunk each) through ``channel``, collected."""
    return stream.from_iterable(pieces, chunk_size=1).pipe_through_channel(channel).run_collect()


def text(data: bytes) -> str:
    """``data`` as text: UTF-8 with lone surrogates kept (``surrogateescape``),
    so every string a socket or file could hand over is reachable."""
    return data.decode("utf-8", "surrogateescape")


def check(found: Target, data: bytes, limit: float = LIMIT) -> None:
    """Run ``found`` on ``data``; any exception escaping it, or a run past
    ``limit`` seconds, is a ``Crash``. An enclosing timer is kept running."""

    def on_alarm(signum: int, frame: FrameType | None) -> None:
        raise Hang(f"{found.name}: still running after {limit:g}s")

    previous = signal.signal(signal.SIGALRM, on_alarm)
    outer, _ = signal.setitimer(signal.ITIMER_REAL, limit)
    start = time.monotonic()
    try:
        found.run(data)
    except Crash:
        raise
    except BaseException as error:
        if isinstance(error, KeyboardInterrupt):
            raise
        raise Crash(f"{found.name}: {type(error).__name__}: {error}") from error
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous)
        if outer:
            signal.setitimer(signal.ITIMER_REAL, max(outer - (time.monotonic() - start), 0.001))


def corpus(name: str) -> Iterator[Path]:
    folder = CORPUS / name
    return iter(sorted(folder.iterdir())) if folder.is_dir() else iter(())
