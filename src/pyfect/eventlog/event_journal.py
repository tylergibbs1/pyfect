"""The journal of an event log (Effect's ``eventlog/EventJournal``): the
entries written locally or received from remotes, ordered by id, and how
far each remote has seen them.

Entry ids are UUID version 7 bytes: 48 bits of milliseconds, then a
12-bit counter that keeps the ids of one process strictly ascending even
when the clock stalls or moves back. ``make_memory`` keeps the journal in
this process (``sql_event_journal`` keeps it in a database). Effect's
IndexedDB journal is browser-only and not ported.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from functools import cached_property
from typing import Any, Never, NewType, Protocol, cast

from pyfect import schema as S
from pyfect._core import Effect
from pyfect.clock import Clock, ClockService, now_millis_unsafe
from pyfect.context import Tag
from pyfect.crypto.secure_random import random_bytes_unsafe, uuid_v4_unsafe
from pyfect.date_time._epoch import from_epoch_millis
from pyfect.effect import gen, succeed, suspend, sync, try_
from pyfect.encoding.schema_binary import to_codec
from pyfect.errors import TaggedError
from pyfect.eventlog import _uuid
from pyfect.eventlog._conflicts import ConflictIndex
from pyfect.exit import Exit, Failure
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.logger._log import log_warning
from pyfect.option import Option, Some
from pyfect.pubsub import PubSub, Subscription
from pyfect.scope import Scope, acquire_use_release
from pyfect.semaphore import Semaphore

EntryId = NewType("EntryId", bytes)
"""An entry's id: UUID version 7 bytes."""

RemoteId = NewType("RemoteId", bytes)
"""A remote's id: UUID version 4 bytes."""

StoreId = NewType("StoreId", str)
"""The store of an identity an event log writes to (``"default"``)."""

EntryIdSchema: S.Codec[EntryId, bytes] = cast("S.Codec[EntryId, bytes]", S.Bytes)
RemoteIdSchema: S.Codec[RemoteId, bytes] = cast("S.Codec[RemoteId, bytes]", S.Bytes)
StoreIdSchema: S.Codec[StoreId, str] = cast("S.Codec[StoreId, str]", S.String)


@dataclass(eq=False)
class EventJournalError(TaggedError):
    """A journal ``method`` failed with ``cause``."""

    method: str
    cause: object = None


def make_remote_id_unsafe() -> RemoteId:
    """A new random remote id (Effect's ``makeRemoteIdUnsafe``)."""
    return RemoteId(uuid_v4_unsafe(format="bytes"))


_MAX_ENTRY_ID_MILLIS = 2**48 - 1
_MAX_CLOCK_SKEW_MILLIS = 24 * 60 * 60 * 1000


@dataclass(slots=True)
class _EntryIdSequence:
    """The millisecond and 12-bit counter of the last id in a sequence of
    local ids."""

    millis: int
    counter: int


_process_entry_ids = _EntryIdSequence(0, 0)


def now_millis() -> int:
    """The wall clock in milliseconds, which local entry ids follow
    (Effect's ``Date.now()``; not the ``Clock`` service)."""
    return time.time_ns() // 1_000_000


def _next_entry_id(sequence: _EntryIdSequence, now: int) -> EntryId:
    if now > sequence.millis:
        sequence.millis = now
        sequence.counter = 0
    else:
        sequence.counter += 1
        if sequence.counter > 0xFFF:
            sequence.millis += 1
            sequence.counter = 0
    # The sequence only moves forward, so once exhausted it stays exhausted.
    if sequence.millis > _MAX_ENTRY_ID_MILLIS:
        raise OverflowError("The entry id sequence has passed the last UUID v7 millisecond")
    raw = _uuid.v7_bytes(sequence.millis, random_bytes_unsafe(16))
    # The counter replaces the 12 random ``rand_a`` bits after the version.
    raw[6] = 0x70 | (sequence.counter >> 8)
    raw[7] = sequence.counter & 0xFF
    return EntryId(bytes(raw))


def _sequence_after(floor: EntryId | None) -> _EntryIdSequence:
    # The process sequence, or a copy advanced to ``floor`` when that is
    # later. The copy is never written back, so a floor read from
    # uncommitted rows leaves the process sequence alone.
    process = _process_entry_ids
    if floor is None:
        return process
    millis = entry_id_millis(floor)
    counter = ((floor[6] & 0x0F) << 8) | floor[7]
    if millis > process.millis or (millis == process.millis and counter > process.counter):
        return _EntryIdSequence(millis, counter)
    return process


def _max_entry_id(ids: Iterable[EntryId]) -> EntryId | None:
    return max(ids, default=None)


def make_entry_id_unsafe(*, msecs: float | None = None) -> EntryId:
    """A new entry id: the next local id, or with ``msecs`` a random id of
    that millisecond, truncated and clamped to the UUID v7 range (Effect's
    ``makeEntryIdUnsafe``)."""
    if msecs is not None:
        return EntryId(bytes(_uuid.v7_bytes(msecs, random_bytes_unsafe(16))))
    return _next_entry_id(_process_entry_ids, now_millis())


def entry_id_millis(entry_id: bytes) -> int:
    """The 48-bit millisecond timestamp of an entry id."""
    return int.from_bytes(entry_id[:6])


def warn_if_ahead(clock: ClockService, ids: Iterable[EntryId]) -> Effect[None]:
    """Log a warning when the latest of ``ids`` is more than a day ahead of
    ``clock`` (Effect's ``warnIfAhead``)."""
    latest = _max_entry_id(ids)
    if latest is None:
        return succeed(None)
    ahead = entry_id_millis(latest) - now_millis_unsafe(clock)
    if ahead <= _MAX_CLOCK_SKEW_MILLIS:
        return succeed(None)
    return log_warning(
        f"Imported an entry id {round(ahead / 3_600_000)} hours ahead of the local clock"
    ).annotate_logs({"service": "EventJournal", "entryId": _uuid.stringify(latest)})


class Entry(S.Class, identifier="effect/eventlog/EventJournal/Entry"):
    """A journal entry: an event's tag, primary key and encoded payload."""

    id: EntryId = S.field(EntryIdSchema)
    event: str
    primary_key: str = S.field(S.String, key="primaryKey")
    payload: bytes = S.field(S.Bytes)

    @cached_property
    def id_string(self) -> str:
        """The id in UUID text form."""
        return _uuid.stringify(self.id)

    @property
    def created_at_millis(self) -> int:
        return entry_id_millis(self.id)

    @property
    def created_at(self) -> datetime:
        return from_epoch_millis(self.created_at_millis)


def entry_order(entry: Entry) -> bytes:
    """The sort key of entries: their ids (Effect's ``Entry.Order``)."""
    return entry.id


class RemoteEntry(S.Class, identifier="effect/eventlog/EventJournal/RemoteEntry"):
    """An entry as a remote sent it, at ``remote_sequence``."""

    remote_sequence: int = S.field(S.Natural, key="remoteSequence")
    entry: Entry


@dataclass(frozen=True, slots=True)
class RemoteAck:
    """A remote stored ``entry_id`` at ``sequence``."""

    entry_id: EntryId
    sequence: int


type EntriesById = Callable[[Sequence[EntryId]], Effect[list[Entry | None], EventJournalError]]
"""A journal's ``entries_by_id``."""


@dataclass(frozen=True, slots=True)
class EntryInput:
    """An entry to write; the journal gives it its id."""

    event: str
    primary_key: str
    payload: bytes


@dataclass(frozen=True, slots=True)
class EntryWithConflicts:
    """An entry to replay with the stored entries of its event and primary
    key that have greater ids."""

    entry: Entry
    conflicts: tuple[Entry, ...]


ENTRY_ARRAY_CODEC = S.Array(to_codec(Entry))
"""Entries as one frame each (Effect's ``Entry.arraySchemaBinary``)."""


def make_entries(
    entries: Sequence[EntryInput], after: Iterable[EntryId]
) -> Effect[list[Entry], EventJournalError]:
    """Entries for ``entries`` with fresh ids greater than the ids
    ``after`` and every local id so far (Effect's ``makeEntries``)."""

    def build() -> list[Entry]:
        sequence = _sequence_after(_max_entry_id(after))
        return [
            Entry(
                id=_next_entry_id(sequence, now_millis()),
                event=e.event,
                primary_key=e.primary_key,
                payload=e.payload,
            )
            for e in entries
        ]

    return try_(build, lambda cause: EventJournalError("writeMany", cause))


def next_sequence_after(entries: Iterable[RemoteEntry], next: int = 0) -> int:
    """The remote sequence following ``entries`` and ``next``."""
    for remote_entry in entries:
        if remote_entry.remote_sequence >= next:
            next = remote_entry.remote_sequence + 1
    return next


def advance_sequence(next: int, acks: Iterable[RemoteAck], first_sequence: int = 0) -> int:
    """``next`` moved past the acknowledged sequences that follow it
    without a gap, starting no lower than ``first_sequence``."""
    next = max(next, first_sequence)
    for sequence in sorted(ack.sequence for ack in acks):
        if sequence == next:
            next += 1
        elif sequence > next:
            break
    return next


type Compact = Callable[[Sequence[RemoteEntry]], Effect[Sequence[Entry], EventJournalError]]
type ReplayBatch = Callable[[Sequence[EntryWithConflicts]], Effect[None, EventJournalError]]


class EventJournalService(ABC):
    """What a journal does (Effect's ``EventJournal`` service)."""

    @property
    @abstractmethod
    def entries(self) -> Effect[list[Entry], EventJournalError]:
        """Every entry, in id order."""

    @abstractmethod
    def entries_by_id(
        self, ids: Sequence[EntryId], /
    ) -> Effect[list[Entry | None], EventJournalError]:
        """The entry of each id, ``None`` when unknown, in the ids' order."""

    def write[A, E, R](
        self,
        *,
        event: str,
        primary_key: str,
        payload: bytes,
        effect: Callable[[Entry], Effect[A, E, R]],
    ) -> Effect[A, EventJournalError | E, R]:
        """Write one entry, committed only when ``effect`` succeeds."""
        return self.write_many(
            [EntryInput(event, primary_key, payload)], lambda written: effect(written[0])
        )

    @abstractmethod
    def write_many[A, E, R](
        self,
        entries: Sequence[EntryInput],
        effect: Callable[[list[Entry]], Effect[A, E, R]],
        /,
    ) -> Effect[A, EventJournalError | E, R]:
        """Write the (non-empty) ``entries``, committed only when
        ``effect`` succeeds."""

    @abstractmethod
    def write_from_remote(
        self,
        *,
        remote_id: RemoteId,
        entries: Sequence[RemoteEntry],
        effect: ReplayBatch,
        compact: Compact | None = None,
    ) -> Effect[list[Entry], EventJournalError]:
        """Import a remote's entries: the new ones (compacted by
        ``compact``) are replayed by ``effect`` in one batch with their
        conflicts, then committed with the remote's sequence. Succeeds
        with the entries that were already stored."""

    @abstractmethod
    def with_remote_uncommitted[A, E, R](
        self, remote_id: RemoteId, f: Callable[[list[Entry]], Effect[A, E, R]], /
    ) -> Effect[Option[A], EventJournalError | E, R]:
        """Run ``f`` on the entries ``remote_id`` has not seen, if any; they
        count as seen when it succeeds (Effect's ``withRemoteUncommited``)."""

    @abstractmethod
    def write_remote_acks(
        self, *, remote_id: RemoteId, acks: Sequence[RemoteAck], first_sequence: int | None = None
    ) -> Effect[None, EventJournalError]:
        """Record the sequences ``remote_id`` acknowledged."""

    @abstractmethod
    def next_remote_sequence(self, remote_id: RemoteId, /) -> Effect[int, EventJournalError]:
        """The next sequence to read from ``remote_id``."""

    @property
    @abstractmethod
    def changes(self) -> Effect[Subscription[Entry], Never, Scope]:
        """A subscription to the entries written locally."""

    @property
    @abstractmethod
    def destroy(self) -> Effect[None, EventJournalError]:
        """Remove every entry and every remote's progress."""

    @abstractmethod
    def with_lock(self, store_id: StoreId, /) -> WithLock:
        """Run an effect holding the lock of ``store_id``."""


class WithLock(Protocol):
    """``with_lock(store_id)``: runs an effect holding a store's lock."""

    def __call__[A, E, R](self, effect: Effect[A, E, R], /) -> Effect[A, E, R]: ...


class _WithLock:
    """``with_lock(store_id)``: an effect run holding a store's lock."""

    __slots__ = ("_semaphore",)

    def __init__(self, semaphore: Semaphore) -> None:
        self._semaphore = semaphore

    def __call__[A, E, R](self, effect: Effect[A, E, R], /) -> Effect[A, E, R]:
        return self._semaphore.with_permits(effect)


class StoreLocks:
    """A semaphore per store, made on first use."""

    __slots__ = ("_semaphores",)

    def __init__(self) -> None:
        self._semaphores: dict[StoreId, Semaphore] = {}

    def __call__(self, store_id: StoreId) -> _WithLock:
        semaphore = self._semaphores.get(store_id)
        if semaphore is None:
            semaphore = self._semaphores[store_id] = Semaphore(1)
        return _WithLock(semaphore)


class EventJournal(Tag[EventJournalService], key="effect/eventlog/EventJournal"):
    """The journal of the event log."""


def _insert_ordered(entries: list[Entry], is_sorted: bool, additions: Sequence[Entry]) -> None:
    # Same result as appending ``additions`` and sorting by id.
    i = len(entries) - 1
    entries.extend(additions)
    if not is_sorted:
        entries.sort(key=entry_order)
        return
    # Merge from the back, so additions sorting after the whole list cost
    # O(additions).
    j = len(additions) - 1
    k = len(entries) - 1
    while j >= 0:
        if i >= 0 and entries[i].id > additions[j].id:
            entries[k] = entries[i]
            i -= 1
        else:
            entries[k] = additions[j]
            j -= 1
        k -= 1


@dataclass(slots=True)
class _Remote:
    sequence: int
    missing: list[Entry]


class _MemoryJournal(EventJournalService):
    def __init__(self, clock: ClockService, pubsub: PubSub[Entry]) -> None:
        self._clock = clock
        self._pubsub = pubsub
        self._journal: list[Entry] = []
        # Local writes append in commit order, which unserialized direct
        # callers can make differ from id order, leaving the journal
        # unordered until the next import re-sorts it. Remote backlogs are
        # subsequences of the journal, so one flag covers them too.
        self._sorted = True
        # The latest committed id, the floor for local ids.
        self._latest: EntryId | None = None
        self._by_id: dict[bytes, Entry] = {}
        self._remotes: dict[bytes, _Remote] = {}
        self._locks = StoreLocks()

    def _commit_latest(self, ids: Iterable[EntryId]) -> None:
        latest = _max_entry_id(ids)
        if latest is not None and (self._latest is None or latest > self._latest):
            self._latest = latest

    def _ensure_remote(self, remote_id: RemoteId) -> _Remote:
        remote = self._remotes.get(remote_id)
        if remote is None:
            remote = self._remotes[remote_id] = _Remote(0, list(self._journal))
        return remote

    @property
    def entries(self) -> Effect[list[Entry], EventJournalError]:
        return sync(lambda: list(self._journal))

    def entries_by_id(self, ids: Sequence[EntryId], /) -> Effect[list[Entry | None], Any]:
        return sync(lambda: [self._by_id.get(entry_id) for entry_id in ids])

    def write_many[A, E, R](
        self,
        entries: Sequence[EntryInput],
        effect: Callable[[list[Entry]], Effect[A, E, R]],
        /,
    ) -> Effect[A, EventJournalError | E, R]:

        def release(written: list[Entry], exit: Exit[A, Any]) -> Effect[object]:
            if isinstance(exit, Failure):
                return succeed(None)
            for entry in written:
                if self._journal and self._journal[-1].id > entry.id:
                    self._sorted = False
                self._journal.append(entry)
                self._by_id[entry.id] = entry
                for remote in self._remotes.values():
                    remote.missing.append(entry)
            self._commit_latest(entry.id for entry in written)
            return self._pubsub.publish_all(written)

        acquire = suspend(
            lambda: make_entries(entries, [] if self._latest is None else [self._latest])
        )
        return acquire_use_release(acquire, effect, release)

    def write_from_remote(
        self,
        *,
        remote_id: RemoteId,
        entries: Sequence[RemoteEntry],
        effect: ReplayBatch,
        compact: Compact | None = None,
    ) -> Effect[list[Entry], EventJournalError]:
        def body():
            remote = self._ensure_remote(remote_id)
            uncommitted: list[RemoteEntry] = []
            duplicates: list[Entry] = []
            # Overlapping batches can repeat an entry; the first copy wins.
            incoming: set[bytes] = set()
            for remote_entry in entries:
                entry_id = remote_entry.entry.id
                if entry_id in self._by_id:
                    duplicates.append(remote_entry.entry)
                elif entry_id not in incoming:
                    incoming.add(entry_id)
                    uncommitted.append(remote_entry)
            compacted = (
                (yield from compact(uncommitted))
                if compact is not None
                else [remote_entry.entry for remote_entry in uncommitted]
            )
            if compacted:
                index = ConflictIndex(compacted)
                oldest = index.oldest.id
                journal = self._journal
                # Only the suffix with greater ids can conflict, unless local
                # writes left the journal unordered.
                i = len(journal) if self._sorted else 0
                while i > 0 and journal[i - 1].id > oldest:
                    i -= 1
                for stored in journal[i:]:
                    index.add(stored)
                yield from effect(index.to_batch())
            for remote_entry in uncommitted:
                self._by_id[remote_entry.entry.id] = remote_entry.entry
            # Sequences advance with the commit, so a failed batch is redelivered.
            remote.sequence = next_sequence_after(entries, remote.sequence)
            imported = sorted((remote_entry.entry for remote_entry in uncommitted), key=entry_order)
            _insert_ordered(self._journal, self._sorted, imported)
            for target in self._remotes.values():
                if target is not remote:
                    _insert_ordered(target.missing, self._sorted, imported)
                elif not self._sorted:
                    target.missing.sort(key=entry_order)
            self._sorted = True
            self._commit_latest(entry.id for entry in imported)
            yield from warn_if_ahead(self._clock, (entry.id for entry in imported))
            return duplicates

        return gen(body)

    def with_remote_uncommitted[A, E, R](
        self, remote_id: RemoteId, f: Callable[[list[Entry]], Effect[A, E, R]], /
    ) -> Effect[Option[A], EventJournalError | E, R]:

        def use(missing: list[Entry]) -> Effect[Option[A], E, R]:
            if not missing:
                return succeed(None)
            return f(missing).map(Some)

        def release(missing: list[Entry], exit: Exit[Option[A], Any]) -> Effect[None]:
            def trim() -> None:
                if isinstance(exit, Failure) or not missing:
                    return
                last = missing[-1]
                remote = self._ensure_remote(remote_id)
                for i in range(len(remote.missing) - 1, -1, -1):
                    if remote.missing[i].id == last.id:
                        remote.missing = remote.missing[i + 1 :]
                        break

            return sync(trim)

        acquire = sync(lambda: list(self._ensure_remote(remote_id).missing))
        return acquire_use_release(acquire, use, release)

    def write_remote_acks(
        self, *, remote_id: RemoteId, acks: Sequence[RemoteAck], first_sequence: int | None = None
    ) -> Effect[None, EventJournalError]:
        def advance() -> None:
            remote = self._ensure_remote(remote_id)
            remote.sequence = advance_sequence(remote.sequence, acks, first_sequence or 0)

        return sync(advance)

    def next_remote_sequence(self, remote_id: RemoteId, /) -> Effect[int, EventJournalError]:
        return sync(lambda: self._ensure_remote(remote_id).sequence)

    @property
    def changes(self) -> Effect[Subscription[Entry], Never, Scope]:
        return self._pubsub.subscribe()

    @property
    def destroy(self) -> Effect[None, EventJournalError]:
        def clear() -> None:
            self._journal.clear()
            self._sorted = True
            self._latest = None
            self._by_id.clear()
            self._remotes.clear()

        return sync(clear)

    def with_lock(self, store_id: StoreId, /) -> _WithLock:
        return self._locks(store_id)


def _make_memory():
    clock = yield from Clock()
    pubsub = yield from PubSub[Entry].unbounded()
    return _MemoryJournal(clock, pubsub)


make_memory: Effect[EventJournalService] = gen(_make_memory)
"""A journal in this process (Effect's ``makeMemory``)."""

layer_memory: Layer[EventJournal] = layer_effect(EventJournal, make_memory)
"""The ``EventJournal`` of ``make_memory``."""


__all__ = [
    "ENTRY_ARRAY_CODEC",
    "Compact",
    "EntriesById",
    "Entry",
    "EntryId",
    "EntryIdSchema",
    "EntryInput",
    "EntryWithConflicts",
    "EventJournal",
    "EventJournalError",
    "EventJournalService",
    "RemoteAck",
    "RemoteEntry",
    "RemoteId",
    "RemoteIdSchema",
    "ReplayBatch",
    "StoreId",
    "StoreIdSchema",
    "StoreLocks",
    "WithLock",
    "advance_sequence",
    "entry_id_millis",
    "entry_order",
    "layer_memory",
    "make_entries",
    "make_entry_id_unsafe",
    "make_memory",
    "make_remote_id_unsafe",
    "next_sequence_after",
    "now_millis",
    "warn_if_ahead",
]
