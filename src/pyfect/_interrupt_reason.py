"""Why the runtime interrupted a fiber, when it knows (pyfect's addition to
Effect's interrupt annotations).

Effect interrupts a fiber forked into, or run through, a closed ``Scope``,
``FiberMap``, ``FiberSet`` or ``FiberHandle``; pyfect does the same and
annotates the interruption with ``InterruptReason``, which ``Interrupted``
shows in its notes, so the closed owner is named where the run fails.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from typing import Any, Never

from pyfect._core import Effect, _FailCause, _WithFiber
from pyfect.cause import interrupt as interrupt_cause
from pyfect.context import Context, Tag


class InterruptReason(Tag[str]):
    """The annotation an interruption the runtime sends gets: why."""


def closed(owner: str, annotations: Context[Any] | None = None) -> Context[Any]:
    """``annotations`` with the reason "``owner`` is closed"."""
    reason = Context.make(
        InterruptReason, f"the {owner} is closed (used after the scope that owns it closed)"
    )
    return reason if annotations is None else annotations.merge(reason)


def interrupt_closed(owner: str) -> Effect[Never]:
    """Interrupt the current fiber because ``owner`` is closed."""
    return _WithFiber(lambda fiber: _FailCause(interrupt_cause(fiber.id).annotate(closed(owner))))
