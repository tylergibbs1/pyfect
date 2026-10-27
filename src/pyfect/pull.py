"""``Pull[A, E, L, R]``: one step of a pull-based producer (Effect's ``Pull``).

A pull is an effect that succeeds with the next item, fails with an ordinary
error ``E``, or fails with ``Done(leftover)`` when the producer has finished
normally. Keeping the end in the error channel lets a consumer tell normal
completion from failure while every effect combinator still applies::

    item = yield from pull          # Done(...) ends the surrounding loop

``filter_done`` and the helpers here separate ``Done`` from real failures:
``catch_done`` and ``match_effect`` handle it, ``done_exit_from_cause``
turns a cause into the producer's final ``Exit``.

Pyright cannot subtract ``Done`` from an error union, so the functions that
take ``Done`` out of a type are data-first (``catch_done(pull, f)``): their
overloads read ``E | Done[L]`` off the pull itself.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Never, TypeIs, overload

from pyfect._core import Effect, _FailCause, _MatchCause
from pyfect._effect_args import require_effect
from pyfect.cause import Cause, Fail, Reason
from pyfect.errors import Done, _is_done, filter_done
from pyfect.exit import Exit, Failure, Success
from pyfect.result import Err, Ok, Result

type Pull[A, E = Never, L = None, R = Never] = Effect[A, E | Done[L], R]
"""An effect producing one ``A``, failing with ``E``, or ending with
``Done[L]``."""


def is_done_failure(reason: Reason[object]) -> TypeIs[Fail[Done[Any]]]:
    """Whether ``reason`` is a ``Fail`` holding a ``Done``."""
    return _is_done(reason)


def is_done_cause(cause: Cause[object]) -> bool:
    """Whether ``cause`` holds any ``Done`` failure."""
    return any(_is_done(r) for r in cause.reasons)


def filter_no_done[E](cause: Cause[E]) -> Result[Cause[E], Cause[E]]:
    """``Ok(cause)`` when it holds no ``Done`` failure, else ``Err(cause)``."""
    return Err(cause) if is_done_cause(cause) else Ok(cause)


def filter_done_leftover[E](cause: Cause[E]) -> Result[Any, Cause[E]]:
    """``filter_done``, keeping only the ``Done``'s leftover value."""
    found = filter_done(cause)
    return Ok(found.value.value) if isinstance(found, Ok) else found


def done_exit_from_cause[E](cause: Cause[E]) -> Exit[Any, E]:
    """The producer's final exit: success with the leftover when ``Done``
    is the only failure, else a failure with the cause stripped of
    ``Done``."""
    found = filter_done(cause)
    return Success(found.value.value) if isinstance(found, Ok) else Failure(found.error)


@overload
def catch_done[A, L, B, EE = Never, RR = Never](
    pull: Effect[A, Done[L], RR], f: Callable[[L], Effect[B, EE, RR]]
) -> Effect[A | B, EE, RR]: ...
@overload
def catch_done[A, L, B, EE = Never, RR = Never](
    pull: Effect[A, EE | Done[L], RR], f: Callable[[L], Effect[B, EE, RR]]
) -> Effect[A | B, EE, RR]: ...
def catch_done(
    pull: Effect[Any, Any, Any], f: Callable[[Any], Effect[Any, Any, Any]]
) -> Effect[Any, Any, Any]:
    """Recover from ``Done`` with ``f(leftover)``; other failures pass
    through (a ``Done`` merged with a real failure is dropped from it)."""
    require_effect(pull, "pull")

    def on_failure(cause: Cause[Any]) -> Effect[Any, Any, Any]:
        found = filter_done(cause)
        return f(found.value.value) if isinstance(found, Ok) else _FailCause(found.error)

    return _MatchCause(pull, on_failure, None)


@overload
def match_effect[A, L, B, EE = Never, RR = Never](
    pull: Effect[A, Done[L], RR],
    *,
    on_success: Callable[[A], Effect[B, EE, RR]],
    on_failure: Callable[[Cause[Never]], Effect[B, EE, RR]],
    on_done: Callable[[L], Effect[B, EE, RR]],
) -> Effect[B, EE, RR]: ...
@overload
def match_effect[A, E, L, B, EE = Never, RR = Never](
    pull: Effect[A, E | Done[L], RR],
    *,
    on_success: Callable[[A], Effect[B, EE, RR]],
    on_failure: Callable[[Cause[E]], Effect[B, EE, RR]],
    on_done: Callable[[L], Effect[B, EE, RR]],
) -> Effect[B, EE, RR]: ...
def match_effect(
    pull: Effect[Any, Any, Any],
    *,
    on_success: Callable[[Any], Effect[Any, Any, Any]],
    on_failure: Callable[[Cause[Any]], Effect[Any, Any, Any]],
    on_done: Callable[[Any], Effect[Any, Any, Any]],
) -> Effect[Any, Any, Any]:
    """Handle each outcome of ``pull``: an item, a failure (without
    ``Done``), or the end with its leftover."""
    require_effect(pull, "pull")

    def failed(cause: Cause[Any]) -> Effect[Any, Any, Any]:
        found = filter_done(cause)
        return on_done(found.value.value) if isinstance(found, Ok) else on_failure(found.error)

    return _MatchCause(pull, failed, on_success)


__all__ = [
    "Pull",
    "catch_done",
    "done_exit_from_cause",
    "filter_done",
    "filter_done_leftover",
    "filter_no_done",
    "is_done_cause",
    "is_done_failure",
    "match_effect",
]
