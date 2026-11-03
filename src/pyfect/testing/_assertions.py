"""Assertions on ``Exit`` and ``Result`` that show the whole ``Cause``.

A failed ``assert ex == Success(1)`` only prints the reprs; these print
``Cause.pretty()``, tracebacks included."""

from __future__ import annotations

from dataclasses import replace
from types import MappingProxyType
from typing import Any

from pyfect.cause import Cause, Fail, Reason
from pyfect.exit import Exit, Failure, Success
from pyfect.result import Err, Ok, Result


def describe_exit(ex: Exit[Any, Any]) -> str:
    """``Success(value)``, or ``Failure`` followed by the pretty cause."""
    if isinstance(ex, Success):
        return repr(ex)
    return f"Failure with cause:\n{_pretty(ex.cause)}"


def _pretty(cause: Cause[Any]) -> str:
    return cause.pretty() or "(empty cause)"


def assert_exit_success[A](ex: Exit[A, Any], expected: A) -> None:
    """``ex`` is ``Success(expected)``."""
    if isinstance(ex, Failure):
        raise AssertionError(f"expected Success({expected!r}), got {describe_exit(ex)}")
    if ex.value != expected:
        raise AssertionError(f"expected Success({expected!r}), got Success({ex.value!r})")


def assert_exit_failure[E](ex: Exit[Any, E], expected: Cause[E]) -> None:
    """``ex`` is a ``Failure`` whose cause equals ``expected``, annotations
    included (``assert_exit_fail`` compares by error)."""
    if isinstance(ex, Failure) and ex.cause == expected:
        return
    lines = [f"expected Failure with cause:\n{_pretty(expected)}\ngot {describe_exit(ex)}"]
    if isinstance(ex, Failure):
        lines.extend(annotation_difference(ex.cause, expected, ("got", "expected")))
    raise AssertionError("\n".join(lines))


def assert_exit_fail[E](ex: Exit[Any, E], expected: E) -> None:
    """``ex`` failed with ``expected`` and nothing else: ``exit.fail(expected)``,
    compared without annotations such as the span the failure happened in."""
    want: Cause[E] = Cause((Fail(expected),))
    if isinstance(ex, Failure) and _bare(ex.cause) == want:
        return
    raise AssertionError(f"expected Failure with cause:\n{_pretty(want)}\ngot {describe_exit(ex)}")


_NONE: MappingProxyType[Any, object] = MappingProxyType({})


def _bare[E](cause: Cause[E]) -> Cause[E]:
    reasons: tuple[Reason[E], ...] = tuple(replace(r, annotations=_NONE) for r in cause.reasons)
    return Cause(reasons)


def _annotations(reason: Reason[Any]) -> str:
    items = reason.annotations.items()
    return ", ".join(f"{key.__name__}: {value!r}" for key, value in items) or "none"


def annotation_difference(
    left: Cause[Any], right: Cause[Any], sides: tuple[str, str] = ("left", "right")
) -> list[str]:
    """When two unequal causes are equal but for their reasons' annotations,
    lines showing each side's annotations; else no lines."""
    if left == right or _bare(left) != _bare(right):
        return []
    lines = ["The causes are equal but for their annotations:"]
    for side, cause in zip(sides, (left, right), strict=True):
        lines.extend(f"  {side} {r!r} annotations: {_annotations(r)}" for r in cause.reasons)
    lines.append("Compare by error with testing.assert_exit_fail(exit, error).")
    return lines


def assert_success[A](result: Result[A, Any], expected: A) -> None:
    """``result`` is ``Ok(expected)``."""
    if result != Ok(expected):
        raise AssertionError(f"expected Ok({expected!r}), got {result!r}")


def assert_failure[E](result: Result[Any, E], expected: E) -> None:
    """``result`` is ``Err(expected)``."""
    if result != Err(expected):
        raise AssertionError(f"expected Err({expected!r}), got {result!r}")
