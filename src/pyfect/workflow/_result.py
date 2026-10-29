"""Workflow results: ``Complete`` (an ``Exit``) or ``Suspended``."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Generic, Never, TypeVar

from pyfect.cause import Cause
from pyfect.exit import Exit

A_co = TypeVar("A_co", covariant=True)
E_co = TypeVar("E_co", covariant=True)


@dataclass(frozen=True, slots=True)
class Complete(Generic[A_co, E_co]):
    """A finished execution and its ``Exit``."""

    exit: Exit[A_co, E_co]


@dataclass(frozen=True, slots=True)
class Suspended:
    """A suspended execution, with the cause that suspended it, if any.

    ``failed`` marks this execution's own ``SuspendOnFailure``, which only
    an explicit ``resume`` or ``interrupt`` replays; a child's failure the
    execution inherited does not set it."""

    cause: Cause[Never] | None = None
    failed: bool = False


type Result[A, E] = Complete[A, E] | Suspended
"""What running a workflow (or an activity) gives."""


def is_result(value: object) -> bool:
    """Whether ``value`` is a ``Complete`` or a ``Suspended``."""
    return isinstance(value, Complete | Suspended)


__all__ = ["Complete", "Result", "Suspended", "is_result"]
