"""Assertions on ``Exit`` and ``Result`` that show the whole ``Cause``.

A failed ``assert ex == Success(1)`` only prints the reprs; these print
``Cause.pretty()``, tracebacks included."""

from __future__ import annotations

from typing import Any

from pyfect.cause import Cause
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
    """``ex`` is a ``Failure`` whose cause equals ``expected``."""
    if isinstance(ex, Failure) and ex.cause == expected:
        return
    raise AssertionError(
        f"expected Failure with cause:\n{_pretty(expected)}\ngot {describe_exit(ex)}"
    )


def assert_success[A](result: Result[A, Any], expected: A) -> None:
    """``result`` is ``Ok(expected)``."""
    if result != Ok(expected):
        raise AssertionError(f"expected Ok({expected!r}), got {result!r}")


def assert_failure[E](result: Result[Any, E], expected: E) -> None:
    """``result`` is ``Err(expected)``."""
    if result != Err(expected):
        raise AssertionError(f"expected Err({expected!r}), got {result!r}")
