"""A file whose bytes are already at hand rather than on disk (Effect's
``HttpBody.FileLike``, a Web ``File``): what ``file_web`` responses and
form uploads serve."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from pyfect.stream import Stream
from pyfect.stream import succeed as succeed_stream


class FileLike(Protocol):
    """A named file of ``size`` bytes, modified at ``last_modified``."""

    @property
    def name(self) -> str: ...
    @property
    def size(self) -> int: ...
    @property
    def content_type(self) -> str:
        """``""`` when unknown (the type is then read from ``name``)."""
        ...

    @property
    def last_modified(self) -> datetime: ...
    def stream(self) -> Stream[bytes, object]: ...


@dataclass(frozen=True, slots=True)
class BytesFile:
    """A ``FileLike`` holding its content."""

    content: bytes
    name: str
    content_type: str = ""
    last_modified: datetime = datetime(1970, 1, 1, tzinfo=UTC)

    @property
    def size(self) -> int:
        return len(self.content)

    def stream(self) -> Stream[bytes, object]:
        return succeed_stream(self.content)


__all__ = ["BytesFile", "FileLike"]
