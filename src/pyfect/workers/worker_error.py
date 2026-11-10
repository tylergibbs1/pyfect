"""The errors of workers (Effect's ``WorkerError``): a ``WorkerError``
wrapping why, a spawn, send, receive or unknown failure."""

from __future__ import annotations

from typing import TypeIs

from pyfect import schema as S


def _cause_field() -> object:
    return S.field(S.Union(S.Undefined, S.Defect()), default=None)


class WorkerSpawnError(S.TaggedError, identifier="effect/workers/WorkerError/WorkerSpawnError"):
    """A worker could not be spawned or set up."""

    message: str
    cause: object = _cause_field()


class WorkerSendError(S.TaggedError, identifier="effect/workers/WorkerError/WorkerSendError"):
    """A message could not be sent to a worker."""

    message: str
    cause: object = _cause_field()


class WorkerReceiveError(S.TaggedError, identifier="effect/workers/WorkerError/WorkerReceiveError"):
    """A message from a worker could not be received, or the worker went
    away (it exited, or raised)."""

    message: str
    cause: object = _cause_field()


class WorkerUnknownError(S.TaggedError, identifier="effect/workers/WorkerError/WorkerUnknownError"):
    """A worker failed in a way none of the other reasons cover."""

    message: str
    cause: object = _cause_field()


type WorkerErrorReason = (
    WorkerSpawnError | WorkerSendError | WorkerReceiveError | WorkerUnknownError
)

WORKER_ERROR_REASON = S.Union(
    WorkerSpawnError, WorkerSendError, WorkerReceiveError, WorkerUnknownError
)
"""The schema of every reason (Effect's ``WorkerErrorReason`` schema)."""


class WorkerError(S.TaggedError, identifier="~effect/workers/WorkerError"):
    """A worker failure; ``reason`` says which kind. Its message is the
    reason's, and its ``cause`` (and ``__cause__``) the reason's cause."""

    reason: WorkerErrorReason = S.field(WORKER_ERROR_REASON)

    def __post_init__(self) -> None:
        self.__cause__ = self.cause if isinstance(self.cause, BaseException) else None

    @property
    def cause(self) -> object:
        return self.reason.cause

    @property
    def message(self) -> str:
        return self.reason.message


def is_worker_error(value: object) -> TypeIs[WorkerError]:
    """Whether ``value`` is a ``WorkerError`` (not one of its reasons)."""
    return isinstance(value, WorkerError)


__all__ = [
    "WORKER_ERROR_REASON",
    "WorkerError",
    "WorkerErrorReason",
    "WorkerReceiveError",
    "WorkerSendError",
    "WorkerSpawnError",
    "WorkerUnknownError",
    "is_worker_error",
]
