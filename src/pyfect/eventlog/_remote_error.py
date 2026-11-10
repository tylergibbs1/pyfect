"""The error of remote operations (Effect's ``EventLogRemoteError``),
here so the remote and its compaction client share it."""

from __future__ import annotations

from dataclasses import dataclass

from pyfect.errors import TaggedError


@dataclass(eq=False)
class EventLogRemoteError(TaggedError):
    """A remote ``method`` failed."""

    method: str
    cause: object
