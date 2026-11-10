"""How remote writes are packed (Effect's ``eventlog/internal/batches.ts``):
batches of at most 100 entries and 256 KiB of payload; a larger entry is a
batch on its own."""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyfect.eventlog.event_journal import Entry

MAX_BATCH_ENTRIES = 100
MAX_BATCH_PAYLOAD_BYTES = 256 * 1024


type Batch = tuple[Entry, *tuple[Entry, ...]]
"""A non-empty batch."""


def to_batches(entries: Sequence[Entry]) -> list[Batch]:
    """``entries`` in order, packed into batches."""
    batches: list[Batch] = []
    current: list[Entry] = []
    size = 0
    for entry in entries:
        payload = len(entry.payload)
        if current and (
            len(current) == MAX_BATCH_ENTRIES or size + payload > MAX_BATCH_PAYLOAD_BYTES
        ):
            batches.append((current[0], *current[1:]))
            current = []
            size = 0
        current.append(entry)
        size += payload
    if current:
        batches.append((current[0], *current[1:]))
    return batches


__all__ = ["MAX_BATCH_ENTRIES", "MAX_BATCH_PAYLOAD_BYTES", "Batch", "to_batches"]
