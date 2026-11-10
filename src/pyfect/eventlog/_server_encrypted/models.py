"""The compaction models of the encrypted server's storage (Effect's
``StorageCompaction`` and the types around it in
``eventlog/EventLogServerEncrypted``)."""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, TypedDict, cast

from pyfect._core import Effect
from pyfect.duration import Duration, Seconds, to_millis, to_seconds
from pyfect.effect import die, succeed, suspend
from pyfect.errors import IllegalArgumentError, TaggedError
from pyfect.eventlog.event_journal import EntryId, StoreId
from pyfect.eventlog.event_log_encryption import EncryptedBatch, EncryptedRemoteBatch
from pyfect.stream import Stream


class CompactionOptions(TypedDict, total=False):
    """Tuning for encrypted remote compaction: ``grace`` keeps a superseded
    or withdrawn generation before it is pruned (default 30 days); ``lag``
    is how old data must be, by storage time, before it can be compacted
    (24 hours); ``stage_ttl`` is how long a stage claim lasts after its
    latest Part (10 minutes); ``threshold_floor`` is the fewest new entries
    that make compaction wanted (1,000); ``sweep_interval`` is how often
    pruning runs (1 hour)."""

    grace: Duration
    lag: Duration
    stage_ttl: Duration
    threshold_floor: int
    sweep_interval: Duration


@dataclass(frozen=True, slots=True, kw_only=True)
class CompactionConfig:
    """Resolved compaction tuning, shared by a storage and the server using
    it. Made only by ``make_compaction_config``, which checks it."""

    grace: Seconds
    lag: Seconds
    stage_ttl: Seconds
    threshold_floor: int
    sweep_interval: Seconds

    @property
    def grace_millis(self) -> float:
        return to_millis(self.grace)

    @property
    def lag_millis(self) -> float:
        return to_millis(self.lag)

    @property
    def stage_ttl_millis(self) -> float:
        return to_millis(self.stage_ttl)

    @property
    def sweep_interval_millis(self) -> float:
        return to_millis(self.sweep_interval)


_MAX_SAFE_INTEGER = 2**53 - 1


def make_compaction_config(options: CompactionOptions | None = None) -> Effect[CompactionConfig]:
    """``options`` resolved against their defaults. Dies with an
    ``IllegalArgumentError`` unless ``grace`` is longer than both ``lag``
    and ``stage_ttl``, ``stage_ttl`` and ``sweep_interval`` are positive, and
    ``threshold_floor`` is a non-negative integer."""
    given = options or {}

    def make() -> Effect[CompactionConfig]:
        config = CompactionConfig(
            grace=to_seconds(given.get("grace", "30 days")),
            lag=to_seconds(given.get("lag", "24 hours")),
            stage_ttl=to_seconds(given.get("stage_ttl", "10 minutes")),
            threshold_floor=given.get("threshold_floor", 1000),
            sweep_interval=to_seconds(given.get("sweep_interval", "1 hour")),
        )
        if not (config.grace > config.lag and config.grace > config.stage_ttl):
            return die(
                IllegalArgumentError("Compaction grace must be longer than lag and stageTtl")
            )
        if not config.stage_ttl > 0:
            return die(IllegalArgumentError("Compaction stageTtl must be positive"))
        if not config.sweep_interval > 0:
            return die(IllegalArgumentError("Compaction sweepInterval must be positive"))
        # Untyped callers can pass any value.
        floor = cast(object, config.threshold_floor)
        if not (
            isinstance(floor, int)
            and not isinstance(floor, bool)
            and 0 <= floor <= _MAX_SAFE_INTEGER
        ):
            return die(
                IllegalArgumentError("Compaction thresholdFloor must be a non-negative integer")
            )
        return succeed(config)

    return suspend(make)


@dataclass(frozen=True, slots=True)
class NoOpState:
    """The latest no-op run: the lag head it reached and how many no-ops
    ran in a row."""

    at: int
    count: int


@dataclass(frozen=True, slots=True, kw_only=True)
class CompactionStoreStatus:
    """The compaction state of one store: ``base`` is ``first_sequence - 1``
    while the originals are active; ``lag_head`` is the highest last
    sequence in a storage-time hour that ended before ``now - lag``."""

    head: int
    base: int
    active_kept_count: int
    lag_head: int
    no_op: NoOpState | None


@dataclass(frozen=True, slots=True)
class BeginStarted:
    """A stage was opened."""

    stage_id: str


@dataclass(frozen=True, slots=True)
class BeginBusy:
    """Another stage holds the store's claim until ``expires_at``."""

    expires_at: int


type CompactionBeginResult = BeginStarted | BeginBusy
"""The result of opening a compaction stage."""


@dataclass(frozen=True, slots=True)
class CompactionBatchHeader:
    """The header of one compaction input batch."""

    sequence: int
    entry_ids: tuple[EntryId, ...]


@dataclass(frozen=True, slots=True)
class StagedHeader:
    """A staged batch's position (segment, then index) and its ids."""

    position: int
    entry_ids: tuple[EntryId, ...]


@dataclass(frozen=True, slots=True, kw_only=True)
class CompactionActivation:
    """One entry of a store's activation log: ``kept_count`` is ``None`` for
    the originals; ``restorable`` is ``False`` once the generation's prune
    has started."""

    activation_id: str
    base: int
    kept_count: int | None
    active: bool
    superseded_at: int | None
    restorable: bool


@dataclass(eq=False)
class CompactionNotFound(TaggedError):
    """The stage expired, was aborted or committed, or is unknown to the
    store."""

    stage_id: str


@dataclass(eq=False)
class CompactionInvalidRequest(TaggedError):
    """A compaction Part or commit failed validation."""

    stage_id: str
    message: str


type RollbackRefusal = Literal["NotActive", "NoPrevious", "PruneStarted"]


@dataclass(eq=False)
class CompactionRollbackError(TaggedError):
    """A rollback was refused: the expected activation is not the active one
    (``NotActive``), there is no earlier generation (``NoPrevious``), or the
    previous generation has started to be pruned (``PruneStarted``)."""

    reason: RollbackRefusal


class StorageCompaction(ABC):
    """Storage primitives for encrypted remote compaction (Effect's
    ``StorageCompaction``). The server owns the policy; each primitive is
    atomic per store.

    A store always has one active activation, the originals (base
    ``first_sequence - 1``) before the first commit. ``begin`` opens a stage
    pinned to it and to ``through``; the claim expires ``stage_ttl`` after
    begin or the latest stored Part, and ``begin`` takes over an expired
    one. Stage primitives fail with ``CompactionNotFound`` once the stage
    expired, was aborted or committed, or belongs to another store.
    ``rollback`` reactivates the previous generation and re-appends, at the
    head, the input of the stage that built the withdrawn one. A sweep
    prunes a generation, and the originals it replaced, ``grace`` after it
    was superseded or withdrawn."""

    config: CompactionConfig

    @abstractmethod
    def status(self, public_key: str, store_id: StoreId, /) -> Effect[CompactionStoreStatus]: ...

    @abstractmethod
    def begin(
        self, public_key: str, store_id: StoreId, /, *, through: int
    ) -> Effect[CompactionBeginResult]: ...

    @abstractmethod
    def input_headers(
        self, public_key: str, store_id: StoreId, stage_id: str, /
    ) -> Stream[CompactionBatchHeader, CompactionNotFound]:
        """Batch headers in input order: the pinned batch set, then the
        originals in ``(base, through]``."""

    @abstractmethod
    def fetch(
        self, public_key: str, store_id: StoreId, stage_id: str, sequences: Sequence[int], /
    ) -> Stream[EncryptedRemoteBatch, CompactionNotFound]:
        """Input batches by input sequence: snapshot batches at or below the
        pinned base, originals above it."""

    @abstractmethod
    def stage_part(
        self,
        public_key: str,
        store_id: StoreId,
        stage_id: str,
        segment: int,
        batches: Sequence[EncryptedBatch],
        /,
    ) -> Effect[Literal["Stored", "AlreadyStored"], CompactionInvalidRequest | CompactionNotFound]:
        """Store one segment of snapshot batches (non-empty), or answer
        ``AlreadyStored`` for a segment already staged. A segment index or
        size out of range closes the stage."""

    @abstractmethod
    def staged_headers(
        self, public_key: str, store_id: StoreId, stage_id: str, /
    ) -> Stream[StagedHeader, CompactionNotFound]:
        """Staged batch headers in position order."""

    @abstractmethod
    def commit(
        self, public_key: str, store_id: StoreId, stage_id: str, virtual_sequences: Sequence[int], /
    ) -> Effect[Literal["Committed", "Superseded"], CompactionNotFound]:
        """Activate the staged set, each batch at its virtual start
        sequence, if the pinned activation is still active; logs the
        outcome with this commit's own activation id."""

    @abstractmethod
    def record_no_op(
        self, public_key: str, store_id: StoreId, stage_id: str, /
    ) -> Effect[None, CompactionNotFound]:
        """Record a no-op for the stage and log it."""

    @abstractmethod
    def abort(self, public_key: str, store_id: StoreId, stage_id: str, /) -> Effect[None]:
        """Release an open stage and discard what it staged; a no-op for a
        stage that is no longer open."""

    @abstractmethod
    def rollback(
        self, public_key: str, store_id: StoreId, expected_activation_id: str, /
    ) -> Effect[str, CompactionRollbackError]:
        """Reactivate the previous generation; the new activation's id."""

    @abstractmethod
    def history(
        self, public_key: str, store_id: StoreId, /
    ) -> Effect[tuple[CompactionActivation, ...]]:
        """Every activation of the store, oldest first."""
