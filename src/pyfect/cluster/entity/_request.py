"""What an entity handler receives (Effect's ``Entity.Request``)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pyfect.cluster import envelope as envelope_
from pyfect.cluster.reply import Chunk


@dataclass(frozen=True, slots=True, kw_only=True)
class Request[P](envelope_.Request[P]):
    """A request for one of the entity's RPCs, with its decoded ``payload``
    and the last chunk of a streamed reply already sent
    (``last_sent_chunk``), so a restarted handler can resume its
    sequence."""

    last_sent_chunk: Chunk[Any] | None = None

    @property
    def last_sent_chunk_value(self) -> Any | None:
        """The last item of the last chunk sent, if a chunk was sent."""
        chunk = self.last_sent_chunk
        return None if chunk is None else chunk.values[-1]

    @property
    def next_sequence(self) -> int:
        """The sequence number of the next chunk to send."""
        chunk = self.last_sent_chunk
        return 0 if chunk is None else chunk.sequence + 1


__all__ = ["Request"]
