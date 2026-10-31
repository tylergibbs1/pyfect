"""Abandoning a request (Effect's ``internal/clusterAbandon``): the caller
is interrupted with the ``Abandon`` annotation, so the request is left for
the next owner instead of being answered."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Never

from pyfect._core import Effect
from pyfect._fiber import Fiber
from pyfect.cause import Cause, Interrupt
from pyfect.cluster.cluster_schema import ABANDON_ANNOTATION, Abandon
from pyfect.effect import callback, current_fiber


def _abandon(fiber: Fiber[Any, Any]) -> Effect[Never]:
    def register(_resume: Callable[[Effect[Never]], None]) -> None:
        fiber.interrupt_as_unsafe(fiber.id, ABANDON_ANNOTATION)

    return callback(register).interruptible()


interrupt: Effect[Never] = current_fiber().flat_map(_abandon)
"""Interrupt the current fiber as abandoned."""


def is_cause(cause: Cause[Any]) -> bool:
    """Whether ``cause`` holds an abandoning interruption."""
    return any(
        isinstance(reason, Interrupt) and Abandon in reason.annotations for reason in cause.reasons
    )


__all__ = ["interrupt", "is_cause"]
