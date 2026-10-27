"""``Take[A, E, L]``: one stored pull result (Effect's ``Take``).

A take is a non-empty tuple of items, a ``Failure`` holding the producer's
error, or a ``Success`` holding its ``Done`` leftover. Store or send takes
(through a queue, say) and replay them later with ``to_pull``.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from typing import Never

from pyfect._core import Effect, _FailCause, _Succeed
from pyfect.cause import fail
from pyfect.errors import Done
from pyfect.exit import Exit, Failure, Success
from pyfect.pull import Pull

type Take[A, E = Never, L = None] = tuple[A, ...] | Exit[L, E]
"""Items (never an empty tuple), a failure, or the end with its leftover."""


def to_pull[A = Never, E = Never, L = None](take: Take[A, E, L]) -> Pull[tuple[A, ...], E, L]:
    """The pull step ``take`` stands for: succeed with its items, fail with
    its failure, or end with ``Done(leftover)``."""
    match take:
        case Success(value):
            return _FailCause(fail(Done(value)))
        case Failure(cause):
            fails: Effect[Never, E] = _FailCause(cause)
            return fails
        case items:
            return _Succeed(items)


__all__ = ["Take", "to_pull"]
