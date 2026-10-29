"""``PersistedQueueError``, and ``DeadLetter``: how the factory tells a
store that a taken element can never be processed."""

from __future__ import annotations

from typing import Any

from pyfect import schema as S
from pyfect.cause import Cause, Fail


class PersistedQueueError(
    S.TaggedError, identifier="effect/persistence/PersistedQueue/PersistedQueueError"
):
    """A queue store could not offer, take, settle or clean up; ``cause``
    is what its backend raised."""

    message: str
    cause: BaseException | None = S.field(S.Union(S.Null, S.Defect()), default=None)


class DeadLetter:
    """A taken element whose stored payload fails to decode: the store
    marks it failed instead of retrying it, and the factory takes the next
    one."""

    __slots__ = ("cause",)

    def __init__(self, cause: Cause[Any]) -> None:
        self.cause = cause


def is_dead_letter(error: object) -> bool:
    return isinstance(error, DeadLetter)


def dead_letter_from_cause(cause: Cause[Any]) -> DeadLetter | None:
    """The ``DeadLetter`` a take's exit failed with, if any."""
    for reason in cause.reasons:
        if isinstance(reason, Fail) and isinstance(reason.error, DeadLetter):
            return reason.error
    return None
