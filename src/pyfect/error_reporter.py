"""Error reporting: hand failures to reporters such as Sentry or a log
pipeline (Effect's ``ErrorReporter``).

``eff.with_error_reporting()`` sends the cause of each failure of ``eff``
to every reporter in ``CurrentErrorReporters``; ``report(cause)`` sends one
cause. With no reporters (the default) nothing happens. A reporter made
with ``make`` turns a cause into one ``Report`` per typed error or defect,
skipping interruptions, causes and errors it has seen already, and errors
that ask to be ignored.

An error controls its report through attributes (``TaggedError`` declares
them; any other object may set them):

- ``report_ignored``: ``True`` to skip it.
- ``report_severity``: the report's ``Severity`` (``INFO`` otherwise).
- ``report_attributes``: extra key/value metadata.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import weakref
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any, Never, Protocol, overload

from pyfect._core import Effect, _Gen, _Succeed, _WithFiber
from pyfect._fiber import Fiber
from pyfect.cause import Cause, Fail, Interrupt
from pyfect.clock import Clock
from pyfect.context import Reference
from pyfect.layer import Layer, effect
from pyfect.logger import LogLevel, Severity
from pyfect.scope import Scope

__all__ = [
    "CurrentErrorReporters",
    "ErrorReporter",
    "Report",
    "get_attributes",
    "get_severity",
    "is_ignored",
    "layer",
    "make",
    "report",
    "report_unsafe",
]


class ErrorReporter(Protocol):
    """Receives the causes of reported failures. ``timestamp`` is the
    fiber's ``Clock`` time in nanoseconds."""

    def report(self, *, cause: Cause[object], fiber: Fiber[Any, Any], timestamp: int) -> None: ...


@dataclass(frozen=True, slots=True)
class Report:
    """One typed error or defect of a reported cause, as ``make`` hands it
    to its function. ``error`` is the reason as an exception (a typed error
    that is not one is wrapped in ``UnhandledError``)."""

    cause: Cause[object]
    error: BaseException
    attributes: Mapping[str, object]
    severity: Severity
    fiber: Fiber[Any, Any]
    timestamp: int


class CurrentErrorReporters(Reference[tuple[ErrorReporter, ...]]):
    """The reporters failures are sent to, each once, in order. None by
    default."""

    @classmethod
    def default(cls) -> tuple[ErrorReporter, ...]:
        return ()


_NO_ATTRIBUTES: Mapping[str, object] = MappingProxyType({})
_SEVERITIES: frozenset[LogLevel] = frozenset(LogLevel) - {LogLevel.ALL, LogLevel.NONE}


def is_ignored(error: object) -> bool:
    """Whether ``error`` asks not to be reported (``report_ignored`` is
    ``True``)."""
    return getattr(error, "report_ignored", False) is True


def get_severity(error: object) -> Severity:
    """``error``'s ``report_severity`` when it is a ``Severity``, else
    ``LogLevel.INFO``."""
    severity = getattr(error, "report_severity", None)
    return severity if isinstance(severity, LogLevel) and severity in _SEVERITIES else LogLevel.INFO  # pyright: ignore[reportReturnType]


def get_attributes(error: object) -> Mapping[str, object]:
    """``error``'s ``report_attributes`` mapping, or an empty one."""
    attributes = getattr(error, "report_attributes", None)
    return attributes if isinstance(attributes, Mapping) else _NO_ATTRIBUTES  # pyright: ignore[reportUnknownVariableType]


class _SeenOnce:
    """Remembers objects by identity while they live (Effect's ``WeakSet``).
    An object Python cannot weakly reference but that has a ``__dict__``
    (a built-in exception such as ``ValueError``) is marked in it instead.
    Values with neither (``str``, ``int``, ``tuple``, ``dict``...) are never
    remembered, as Effect never remembers its primitives."""

    __slots__ = ("_mark", "_seen")

    def __init__(self) -> None:
        self._seen: dict[int, weakref.ref[object]] = {}
        self._mark = object()

    def first_time(self, value: object) -> bool:
        key = id(value)
        known = self._seen.get(key)
        if known is not None and known() is value:
            return False
        try:
            self._seen[key] = weakref.ref(value, lambda ref: self._forget(key, ref))
        except TypeError:
            return self._first_mark(value)
        return True

    def _first_mark(self, value: object) -> bool:
        try:
            marks: list[object] = vars(value).setdefault(_MARKS, [])
        except TypeError:
            return True
        if any(mark is self._mark for mark in marks):
            return False
        marks.append(self._mark)
        return True

    def _forget(self, key: int, ref: weakref.ref[object]) -> None:
        if self._seen.get(key) is ref:
            del self._seen[key]


_MARKS = "__pyfect_error_reporters__"


class _Reporter:
    __slots__ = ("_report", "_seen")

    def __init__(self, f: Callable[[Report], object]) -> None:
        self._report = f
        self._seen = _SeenOnce()

    def report(self, *, cause: Cause[object], fiber: Fiber[Any, Any], timestamp: int) -> None:
        if not self._seen.first_time(cause):
            return
        for reason in cause.reasons:
            if isinstance(reason, Interrupt):
                continue
            original = reason.error if isinstance(reason, Fail) else reason.defect
            if not self._seen.first_time(original) or is_ignored(original):
                continue
            (error,) = Cause((reason,)).pretty_errors()
            self._report(
                Report(
                    cause=cause,
                    error=error,
                    attributes=get_attributes(original),
                    severity=get_severity(original),
                    fiber=fiber,
                    timestamp=timestamp,
                )
            )


def make(f: Callable[[Report], object]) -> ErrorReporter:
    """A reporter calling ``f`` once per typed error or defect of each
    cause. Interruptions, ignored errors, and causes or errors this
    reporter has already seen (by identity) are skipped."""
    return _Reporter(f)


type _Reporters[E, R] = Sequence[ErrorReporter | Effect[ErrorReporter, E, R]]


@overload
def layer[E = Never](
    reporters: Sequence[ErrorReporter | Effect[ErrorReporter, E, Scope]],
    *,
    merge_with_existing: bool = False,
) -> Layer[Never, E]: ...
@overload
def layer[E = Never, R = Never](
    reporters: Sequence[ErrorReporter | Effect[ErrorReporter, E, Scope | R]],
    *,
    merge_with_existing: bool = False,
) -> Layer[Never, E, R]: ...
def layer(
    reporters: _Reporters[Any, Any], *, merge_with_existing: bool = False
) -> Layer[Any, Any, Any]:
    """A layer that replaces the current reporters with ``reporters`` (or
    adds them, with ``merge_with_existing``). An item may be an effect
    making a reporter; it runs when the layer builds."""
    given = list(reporters)

    def build():
        current: list[ErrorReporter] = (
            list((yield from CurrentErrorReporters())) if merge_with_existing else []
        )
        for item in given:
            made: ErrorReporter = (yield from item) if isinstance(item, Effect) else item
            if all(made is not existing for existing in current):
                current.append(made)
        return tuple(current)

    return effect(CurrentErrorReporters, _Gen(build))


_VOID: Effect[None] = _Succeed(None)


def report_unsafe(
    fiber: Fiber[Any, Any], cause: Cause[object], *, defects_only: bool = False
) -> None:
    """Send ``cause`` to ``fiber``'s reporters now (with ``defects_only``,
    only if it has a defect)."""
    reporters = fiber.get_ref(CurrentErrorReporters)
    if not reporters or (defects_only and not cause.defects):
        return
    timestamp = fiber.get_ref(Clock).now_nanos_unsafe()
    for reporter in reporters:
        reporter.report(cause=cause, fiber=fiber, timestamp=timestamp)


def report(cause: Cause[object]) -> Effect[None]:
    """Send ``cause`` to the current reporters."""

    def body(fiber: Fiber[Any, Any]) -> Effect[None]:
        report_unsafe(fiber, cause)
        return _VOID

    return _WithFiber(body)
