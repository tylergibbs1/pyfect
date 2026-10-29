"""``PersistenceError``: a persistence store failed."""

from __future__ import annotations

from pyfect import schema as S


class PersistenceError(S.TaggedError, identifier="effect/persistence/Persistence/PersistenceError"):
    """A persistence store could not read or write; ``cause`` is what its
    backend raised. A schema class, so a persisted request may fail with
    it and have the failure stored."""

    message: str
    cause: BaseException | None = S.field(S.Union(S.Null, S.Defect()), default=None)
