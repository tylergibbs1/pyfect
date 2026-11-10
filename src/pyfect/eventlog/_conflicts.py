"""Which stored entries conflict with a batch of incoming ones (Effect's
``eventlog/internal/conflicts.ts``): those of the same event and primary
key with a greater id."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyfect.eventlog.event_journal import Entry, EntryWithConflicts

# Set during client replay only, so it never leaves the process: an
# attribute outside the entry's fields, so equality and encoding ignore it.
_ANCHOR = "_eventlog_anchor"


@dataclass(frozen=True, slots=True)
class _Anchor:
    entry: Entry
    index: int


def set_anchor(entry: Entry, source: Entry, index: int) -> None:
    """Order and conflict-check ``entry`` as ``source``, after the
    ``index`` outputs written for it before."""
    object.__setattr__(entry, _ANCHOR, _Anchor(source, index))


def anchor_entry(entry: Entry) -> Entry:
    anchor: _Anchor | None = getattr(entry, _ANCHOR, None)
    return entry if anchor is None else anchor.entry


def _anchor_key(entry: Entry) -> tuple[bytes, int]:
    # By anchor id, then by write order among one anchor's outputs.
    anchor: _Anchor | None = getattr(entry, _ANCHOR, None)
    return (entry.id, 0) if anchor is None else (anchor.entry.id, anchor.index)


@dataclass(slots=True)
class ConflictGroup:
    event: str
    primary_key: str
    oldest: Entry
    entries: list[Entry] = field(default_factory=list["Entry"])


class ConflictIndex:
    """A batch, ordered by anchor, and the stored entries of its keys."""

    __slots__ = ("_stored", "batch", "oldest", "oldest_millis")

    def __init__(self, batch: Sequence[Entry]) -> None:
        self.batch = sorted(batch, key=_anchor_key)
        self.oldest = anchor_entry(self.batch[0])
        self.oldest_millis = self.oldest.created_at_millis
        self._stored: dict[str, dict[str, ConflictGroup]] = {}
        for entry in self.batch:
            by_key = self._stored.setdefault(entry.event, {})
            if entry.primary_key not in by_key:
                by_key[entry.primary_key] = ConflictGroup(
                    entry.event, entry.primary_key, anchor_entry(entry)
                )

    def groups(self) -> Iterator[ConflictGroup]:
        for by_key in self._stored.values():
            yield from by_key.values()

    def add(self, entry: Entry) -> None:
        """Record a stored entry (ignored unless the batch has its key)."""
        group = self._stored.get(entry.event, {}).get(entry.primary_key)
        if group is not None:
            group.entries.append(entry)

    def to_batch(self) -> list[EntryWithConflicts]:
        from pyfect.eventlog.event_journal import EntryWithConflicts

        for group in self.groups():
            group.entries.sort(key=lambda entry: entry.id)
        result: list[EntryWithConflicts] = []
        for entry in self.batch:
            anchor = anchor_entry(entry).id
            stored = self._stored[entry.event][entry.primary_key].entries
            result.append(EntryWithConflicts(entry, tuple(s for s in stored if s.id > anchor)))
        return result


__all__ = ["ConflictGroup", "ConflictIndex", "anchor_entry", "set_anchor"]
