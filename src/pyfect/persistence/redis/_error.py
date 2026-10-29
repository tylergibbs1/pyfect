"""``RedisError``: a Redis command failed."""

from __future__ import annotations

from pyfect import schema as S


class RedisError(S.TaggedError, identifier="~effect/persistence/Redis/RedisError"):
    """A Redis command, connection or subscription failed; ``cause`` is
    what the client raised (also the error's ``__cause__``)."""

    cause: BaseException = S.field(S.Defect())
