"""Stack frames: where spans and traced functions were written, recorded on
the causes of failures inside them (Effect's ``References.CurrentStackFrame``
and ``Cause.StackTrace`` / ``InterruptorStackTrace``).

Apart from ``pyfect.tracer`` so the fiber runtime can read the current frame
without importing the span functions.
"""

from __future__ import annotations

import re
import sys
from collections.abc import Callable
from dataclasses import dataclass
from types import CodeType
from typing import final

from pyfect.context import Reference, Tag

type CaptureStackTrace = bool | Callable[[], str | None]
"""Effect's ``captureStackTrace``: ``True`` records the call site, ``False``
records nothing, a function gives the location when it is first read."""


@dataclass(frozen=True, slots=True, eq=False)
class StackFrame:
    """One frame: a name, its location (read lazily, ``None`` if unknown, in
    the form ``"at function (file:line)"``) and the frame it runs inside."""

    name: str
    stack: Callable[[], str | None]
    parent: StackFrame | None = None


class CurrentStackFrame(Reference[StackFrame | None]):
    """The innermost frame the fiber runs in: a span from ``with_span`` or a
    call of an ``@fx.fn`` function. ``None`` outside every frame."""

    @classmethod
    def default(cls) -> StackFrame | None:
        return None


class StackTrace(Tag[StackFrame]):
    """The annotation a failure's reasons get: the frame it happened in."""


class InterruptorStackTrace(Tag[StackFrame]):
    """The annotation an interruption gets: the frame of the fiber that
    interrupted."""


def _no_location() -> None:
    return None


@final
class _CallSite:
    """A call site, rendered when first read. Keeps the code object and the
    line, never the frame, so the caller's locals are not kept alive."""

    __slots__ = ("_code", "_line", "_text")

    def __init__(self, code: CodeType, line: int) -> None:
        self._code = code
        self._line = line
        self._text: str | None = None

    def __call__(self) -> str:
        if self._text is None:
            code = self._code
            self._text = f"at {code.co_qualname} ({code.co_filename}:{self._line})"
        return self._text


def call_site(depth: int) -> Callable[[], str | None]:
    """The location of the caller ``depth`` frames above the function
    calling this one (1 is that function's caller)."""
    frame = sys._getframe(depth + 1)  # pyright: ignore[reportPrivateUsage]
    return _CallSite(frame.f_code, frame.f_lineno)


def stack_of(capture: CaptureStackTrace, depth: int) -> Callable[[], str | None]:
    """The location a frame records for ``capture``: the call site ``depth``
    frames above the caller when ``True``."""
    if capture is True:
        return call_site(depth + 1)
    if capture is False:
        return _no_location
    return capture


def push(name: str, stack: Callable[[], str | None]) -> Callable[[StackFrame | None], StackFrame]:
    """The update that runs inside a new frame ``name``."""
    return lambda parent: StackFrame(name, stack, parent)


_LOCATION = re.compile(r"\((.*)\)")


def render(frame: StackFrame | None) -> list[str]:
    """Effect's trace lines for ``frame`` and its parents (ten at most):
    ``    at name (location)``."""
    lines: list[str] = []
    while frame is not None and len(lines) < 10:
        location = frame.stack()
        if location is None:
            lines.append(f"    at {frame.name}")
        else:
            inner = _LOCATION.search(location)
            where = inner.group(1) if inner else location.removeprefix("at ")
            lines.append(f"    at {frame.name} ({where})")
        frame = frame.parent
    return lines
