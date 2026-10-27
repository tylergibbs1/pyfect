"""Reason errors: an error that wraps a more specific error as ``reason``.

Effect v4's ``catchReason`` / ``catchReasons`` / ``unwrapReason`` work on
any error with a ``reason`` field, usually a ``TaggedError`` dataclass::

    @dataclass
    class AiError(fx.TaggedError):
        reason: RateLimitError | QuotaExceededError

``HasReason`` is the protocol those combinators use to read the reason's
type off the parent error's class. ``ReasonCatch`` is the runtime half
shared by the Effect, Stream and Channel versions.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Protocol

type ReasonHandler[H] = Callable[[Any, Any], H]


class HasReason[RE](Protocol):
    """An error carrying a ``reason`` of type ``RE`` (Effect's errors with a
    tagged ``reason``; ``TagsWithReason`` is ``type[HasReason[Any]]``)."""

    @property
    def reason(self) -> RE: ...


class ReasonCatch[H]:
    """Decides which errors a reason combinator catches and runs the handler.

    An instance of ``tag`` is caught when its reason is an instance of one of
    the ``cases`` classes, or always when there is an ``or_else``. A caught
    error goes to the first matching case's handler, else to ``or_else``;
    both get ``(reason, error)``."""

    __slots__ = ("cases", "or_else", "refail", "tag")

    def __init__(
        self,
        tag: type[Any],
        cases: Sequence[tuple[type[Any], ReasonHandler[H]]],
        or_else: ReasonHandler[H] | None,
        refail: Callable[[Any], H],
    ) -> None:
        self.tag = tag
        self.cases = tuple(cases)
        self.or_else = or_else
        self.refail = refail

    def accepts(self, error: Any) -> bool:
        if not isinstance(error, self.tag):
            return False
        reason = error.reason
        return self.or_else is not None or any(isinstance(reason, cls) for cls, _ in self.cases)

    def __call__(self, error: Any) -> H:
        reason = error.reason
        for cls, f in self.cases:
            if isinstance(reason, cls):
                return f(reason, error)
        return self.refail(error) if self.or_else is None else self.or_else(reason, error)
