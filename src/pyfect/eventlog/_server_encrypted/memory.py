"""The in-memory storage of an encrypted server, with compaction (Effect's
``makeStorageMemoryWith``).

Each store keeps its originals in sequence order, the storage-time hour
buckets of its writes, its activation log and at most one open stage. A
sweep on ``Clock`` closes expired stages and prunes generations past their
grace; it sleeps only while some store has something for it to do.
"""

from __future__ import annotations

import bisect
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Literal, Never

from pyfect._core import Effect
from pyfect.clock import Clock, now_millis_unsafe
from pyfect.effect import die, fail, gen, succeed, suspend, sync
from pyfect.errors import IllegalArgumentError
from pyfect.eventlog import _uuid
from pyfect.eventlog._server_encrypted.audit import (
    MAX_SEGMENTS,
    POSITIONS_PER_SEGMENT,
    hour_of,
    lag_hour,
    log_commit,
    log_no_op,
    log_rollback,
)
from pyfect.eventlog._server_encrypted.models import (
    BeginBusy,
    BeginStarted,
    CompactionActivation,
    CompactionBatchHeader,
    CompactionBeginResult,
    CompactionConfig,
    CompactionInvalidRequest,
    CompactionNotFound,
    CompactionOptions,
    CompactionRollbackError,
    CompactionStoreStatus,
    NoOpState,
    StagedHeader,
    StorageCompaction,
    make_compaction_config,
)
from pyfect.eventlog._server_encrypted.storage import StorageService
from pyfect.eventlog.event_journal import EntryId, RemoteId, StoreId, make_remote_id_unsafe
from pyfect.eventlog.event_log_encryption import EncryptedBatch, EncryptedRemoteBatch, remote_batch
from pyfect.eventlog.event_log_message import WriteAck
from pyfect.latch import Latch
from pyfect.pubsub import PubSub
from pyfect.rc_map import RcMap
from pyfect.scope import Scope, acquire_release, scoped
from pyfect.stream import Stream, from_iterable, from_subscription
from pyfect.stream import die as stream_die
from pyfect.stream import fail as stream_fail
from pyfect.stream import unwrap as stream_unwrap

type _Key = tuple[str, str]

_now: Effect[int] = Clock().map(now_millis_unsafe)


def _last(batch: EncryptedRemoteBatch) -> int:
    return batch.sequence + len(batch.entry_ids) - 1


@dataclass(eq=False, slots=True)
class _BatchSet:
    batches: list[EncryptedRemoteBatch]


@dataclass(eq=False, slots=True, kw_only=True)
class _Activation:
    id: str
    # None while the originals are active.
    set: _BatchSet | None
    base: int
    kept_count: int | None
    previous: _Activation | None
    superseded_at: int | None = None
    prune_started_at: int | None = None


@dataclass(eq=False, slots=True, kw_only=True)
class _Stage:
    id: str
    pinned: _Activation
    through: int
    expires_at: float
    # Staged batches by position.
    staged: dict[int, EncryptedBatch] = field(default_factory=dict[int, EncryptedBatch])

    def staged_in_order(self) -> list[tuple[int, EncryptedBatch]]:
        return sorted(self.staged.items())

    def kept_count(self) -> int:
        return sum(len(batch.entry_ids) for batch in self.staged.values())


def _new_id() -> str:
    return str(uuid.uuid4())


class _Journal:
    __slots__ = (
        "activations",
        "active",
        "batches",
        "buckets",
        "known_ids",
        "next_sequence",
        "next_sweep_at",
        "no_op",
        "open_stage",
    )

    def __init__(self) -> None:
        originals = _Activation(id=_new_id(), set=None, base=-1, kept_count=None, previous=None)
        # Entry id to the sequence it was first stored at. Never pruned.
        self.known_ids: dict[str, int] = {}
        # Originals, in sequence order.
        self.batches: list[EncryptedRemoteBatch] = []
        self.next_sequence = 0
        # Storage-time hour to the highest last sequence stored in it.
        self.buckets: dict[int, int] = {}
        self.activations: list[_Activation] = [originals]
        self.active = originals
        self.no_op: NoOpState | None = None
        self.open_stage: _Stage | None = None
        self.next_sweep_at: float | None = None

    def close_stage(self, stage: _Stage) -> None:
        if self.open_stage is stage:
            self.open_stage = None

    def originals_between(self, base: int, through: int) -> list[EncryptedRemoteBatch]:
        return [b for b in self.batches if b.sequence > base and _last(b) <= through]

    def input_batches(self, stage: _Stage) -> list[EncryptedRemoteBatch]:
        """The input of a stage: its pinned batch set, then the originals in
        ``(base, through]``."""
        pinned = stage.pinned
        snapshot = pinned.set.batches if pinned.set is not None else []
        return [*snapshot, *self.originals_between(pinned.base, stage.through)]

    def lag_head(self, now: int, lag_millis: float) -> int:
        past_lag = lag_hour(now, int(lag_millis))
        return max((last for hour, last in self.buckets.items() if hour <= past_lag), default=-1)

    def record_bucket(self, now: int, last_sequence: int, lag_millis: float) -> None:
        hour = hour_of(now)
        existing = self.buckets.get(hour)
        if existing is not None:
            self.buckets[hour] = max(existing, last_sequence)
            return
        self.buckets[hour] = last_sequence
        # Only the newest bucket past the lag matters for the lag head.
        past_lag = [b for b in self.buckets if b <= lag_hour(now, int(lag_millis))]
        if past_lag:
            newest = max(past_lag)
            for bucket in past_lag:
                if bucket < newest:
                    del self.buckets[bucket]


def _find_batch(
    batches: Sequence[EncryptedRemoteBatch], sequence: int
) -> EncryptedRemoteBatch | None:
    index = bisect.bisect_left(batches, sequence, key=lambda b: b.sequence)
    if index < len(batches) and batches[index].sequence == sequence:
        return batches[index]
    return None


def _open_pubsub(_key: _Key) -> Effect[PubSub[EncryptedRemoteBatch], Never, Scope]:
    return acquire_release(PubSub[EncryptedRemoteBatch].unbounded(), lambda p, _: p.shutdown())


class _MemoryCompaction(StorageCompaction):
    def __init__(self, storage: _MemoryStorage, config: CompactionConfig) -> None:
        self._storage = storage
        self.config = config
        # Open while any store has something for the sweep to do, so an
        # idle storage never sleeps on the clock.
        self.sweep_pending = Latch(False)

    # The sweep.

    def schedule_prune(self, journal: _Journal, at: float) -> None:
        journal.next_sweep_at = (
            at if journal.next_sweep_at is None else min(journal.next_sweep_at, at)
        )
        self.sweep_pending.open_unsafe()

    def sweep(self, now: int) -> None:
        pending = False
        for journal in self._storage.journals.values():
            stage = journal.open_stage
            if stage is not None and stage.expires_at <= now:
                journal.close_stage(stage)
            if journal.next_sweep_at is not None and journal.next_sweep_at <= now:
                self._prune(journal, now)
            pending = pending or journal.open_stage is not None or journal.next_sweep_at is not None
        if not pending:
            self.sweep_pending.close_unsafe()

    def _prune(self, journal: _Journal, now: int) -> None:
        """Keeps what the active generation and every generation still within
        grace need: their batch sets and the originals above their bases."""
        grace = self.config.grace_millis

        def is_kept(activation: _Activation) -> bool:
            if activation is journal.active:
                return True
            superseded = activation.superseded_at
            return (
                activation.prune_started_at is None
                and superseded is not None
                and superseded + grace > now
            )

        kept = [a for a in journal.activations if is_kept(a)]
        kept_sets = {id(a.set) for a in kept}
        for activation in journal.activations:
            if is_kept(activation) or activation.prune_started_at is not None:
                continue
            activation.prune_started_at = now
            if activation.set is not None and id(activation.set) not in kept_sets:
                activation.set.batches = []
        kept_base = min(a.base for a in kept)
        journal.batches = [b for b in journal.batches if _last(b) > kept_base]
        journal.next_sweep_at = None
        for activation in journal.activations:
            if activation is not journal.active and activation.prune_started_at is None:
                assert activation.superseded_at is not None
                self.schedule_prune(journal, activation.superseded_at + grace)

    @property
    def run_sweeps(self) -> Effect[Never]:
        def once() -> Effect[None]:
            return (
                self.sweep_pending.wait()
                .and_then(Clock().flat_map(lambda c: c.sleep(self.config.sweep_interval)))
                .and_then(_now)
                .flat_map(lambda now: sync(lambda: self.sweep(now)))
            )

        return once().forever()

    # Stage lookups.

    def _find_open_stage(
        self, public_key: str, store_id: StoreId, stage_id: str, now: int
    ) -> tuple[_Journal, _Stage] | None:
        """A stage that Part, NoOp and Commit can act on."""
        journal = self._storage.journals.get((public_key, store_id))
        stage = journal.open_stage if journal is not None else None
        if journal is None or stage is None or stage.id != stage_id:
            return None
        if stage.expires_at <= now:
            journal.close_stage(stage)
            return None
        return journal, stage

    def _find_input_stage(
        self, public_key: str, store_id: StoreId, stage_id: str, now: int
    ) -> tuple[_Journal, _Stage] | None:
        found = self._find_open_stage(public_key, store_id, stage_id, now)
        if found is None or found[1].pinned.prune_started_at is not None:
            return None
        return found

    # The primitives.

    def status(self, public_key: str, store_id: StoreId, /) -> Effect[CompactionStoreStatus]:
        def read(now: int) -> CompactionStoreStatus:
            journal = self._storage.journal((public_key, store_id))
            return CompactionStoreStatus(
                head=journal.next_sequence - 1,
                base=journal.active.base,
                active_kept_count=journal.active.kept_count or 0,
                lag_head=journal.lag_head(now, self.config.lag_millis),
                no_op=journal.no_op,
            )

        return _now.map(read)

    def begin(
        self, public_key: str, store_id: StoreId, /, *, through: int
    ) -> Effect[CompactionBeginResult]:
        def open_stage(now: int) -> CompactionBeginResult:
            journal = self._storage.journal((public_key, store_id))
            current = journal.open_stage
            if current is not None:
                if current.expires_at > now:
                    return BeginBusy(int(current.expires_at))
                journal.close_stage(current)
            stage = _Stage(
                id=_new_id(),
                pinned=journal.active,
                through=through,
                expires_at=now + self.config.stage_ttl_millis,
            )
            journal.open_stage = stage
            self.sweep_pending.open_unsafe()
            return BeginStarted(stage.id)

        return _now.map(open_stage)

    def input_headers(
        self, public_key: str, store_id: StoreId, stage_id: str, /
    ) -> Stream[CompactionBatchHeader, CompactionNotFound]:
        def read(now: int) -> Stream[CompactionBatchHeader, CompactionNotFound]:
            found = self._find_input_stage(public_key, store_id, stage_id, now)
            if found is None:
                return stream_fail(CompactionNotFound(stage_id))
            journal, stage = found
            return from_iterable(
                [
                    CompactionBatchHeader(b.sequence, b.entry_ids)
                    for b in journal.input_batches(stage)
                ]
            )

        return stream_unwrap(_now.map(read))

    def fetch(
        self, public_key: str, store_id: StoreId, stage_id: str, sequences: Sequence[int], /
    ) -> Stream[EncryptedRemoteBatch, CompactionNotFound]:
        def read(now: int) -> Stream[EncryptedRemoteBatch, CompactionNotFound]:
            found = self._find_input_stage(public_key, store_id, stage_id, now)
            if found is None:
                return stream_fail(CompactionNotFound(stage_id))
            journal, stage = found
            snapshot = stage.pinned.set.batches if stage.pinned.set is not None else []
            fetched: list[EncryptedRemoteBatch] = []
            for sequence in sequences:
                if sequence <= stage.pinned.base:
                    batch = _find_batch(snapshot, sequence)
                elif sequence <= stage.through:
                    batch = _find_batch(journal.batches, sequence)
                else:
                    batch = None
                if batch is not None:
                    fetched.append(batch)
            return from_iterable(fetched)

        return stream_unwrap(_now.map(read))

    def stage_part(
        self,
        public_key: str,
        store_id: StoreId,
        stage_id: str,
        segment: int,
        batches: Sequence[EncryptedBatch],
        /,
    ) -> Effect[Literal["Stored", "AlreadyStored"], CompactionInvalidRequest | CompactionNotFound]:
        def store(
            now: int,
        ) -> Effect[
            Literal["Stored", "AlreadyStored"], CompactionInvalidRequest | CompactionNotFound
        ]:
            found = self._find_open_stage(public_key, store_id, stage_id, now)
            if found is None:
                return fail(CompactionNotFound(stage_id))
            journal, stage = found

            def reject(message: str) -> Effect[Never, CompactionInvalidRequest]:
                journal.close_stage(stage)
                return fail(CompactionInvalidRequest(stage_id, message))

            if not 0 <= segment < MAX_SEGMENTS:
                return reject("Invalid segment index")
            if len(batches) > POSITIONS_PER_SEGMENT:
                return reject("Too many batches in a segment")
            # Positions are the staged rows' key, so a retried segment
            # inserts nothing.
            inserted = 0
            for i, batch in enumerate(batches):
                position = segment * POSITIONS_PER_SEGMENT + i
                if position not in stage.staged:
                    stage.staged[position] = batch
                    inserted += 1
            if inserted == 0:
                return succeed("AlreadyStored")
            stage.expires_at = now + self.config.stage_ttl_millis
            return succeed("Stored")

        return _now.flat_map(store)

    def staged_headers(
        self, public_key: str, store_id: StoreId, stage_id: str, /
    ) -> Stream[StagedHeader, CompactionNotFound]:
        def read(now: int) -> Stream[StagedHeader, CompactionNotFound]:
            found = self._find_open_stage(public_key, store_id, stage_id, now)
            if found is None:
                return stream_fail(CompactionNotFound(stage_id))
            return from_iterable(
                [StagedHeader(position, b.entry_ids) for position, b in found[1].staged_in_order()]
            )

        return stream_unwrap(_now.map(read))

    def commit(
        self, public_key: str, store_id: StoreId, stage_id: str, virtual_sequences: Sequence[int], /
    ) -> Effect[Literal["Committed", "Superseded"], CompactionNotFound]:
        def activate(now: int) -> Effect[Literal["Committed", "Superseded"], CompactionNotFound]:
            found = self._find_open_stage(public_key, store_id, stage_id, now)
            if found is None:
                return fail(CompactionNotFound(stage_id))
            journal, stage = found
            kept_count = stage.kept_count()
            if stage.pinned is not journal.active:
                journal.close_stage(stage)
                return log_commit(
                    public_key=public_key,
                    store_id=store_id,
                    result="Superseded",
                    through=stage.through,
                    kept_count=kept_count,
                    activation_id=None,
                ).as_("Superseded")
            staged = stage.staged_in_order()
            if len(staged) != len(virtual_sequences):
                return die(IllegalArgumentError("Expected one virtual sequence per staged batch"))
            activation = _Activation(
                id=_new_id(),
                set=_BatchSet(
                    [
                        remote_batch(sequence, batch)
                        for (_, batch), sequence in zip(staged, virtual_sequences, strict=True)
                    ]
                ),
                base=stage.through,
                kept_count=kept_count,
                previous=journal.active,
            )
            journal.active.superseded_at = now
            journal.activations.append(activation)
            journal.active = activation
            journal.no_op = None
            self.schedule_prune(journal, now + self.config.grace_millis)
            journal.close_stage(stage)
            # Log this commit's activation id: a concurrent rollback could
            # change the active one before the logger runs.
            return log_commit(
                public_key=public_key,
                store_id=store_id,
                result="Committed",
                through=stage.through,
                kept_count=kept_count,
                activation_id=activation.id,
            ).as_("Committed")

        return _now.flat_map(activate)

    def record_no_op(
        self, public_key: str, store_id: StoreId, stage_id: str, /
    ) -> Effect[None, CompactionNotFound]:
        def record(now: int) -> Effect[None, CompactionNotFound]:
            found = self._find_open_stage(public_key, store_id, stage_id, now)
            if found is None:
                return fail(CompactionNotFound(stage_id))
            journal, stage = found
            # A rollback since begin cleared the no-op state, so a stale run
            # leaves it.
            if stage.pinned is journal.active:
                count = journal.no_op.count if journal.no_op is not None else 0
                journal.no_op = NoOpState(stage.through, count + 1)
            journal.close_stage(stage)
            return log_no_op(
                public_key=public_key, store_id=store_id, stage_id=stage_id, through=stage.through
            )

        return _now.flat_map(record)

    def abort(self, public_key: str, store_id: StoreId, stage_id: str, /) -> Effect[None]:
        def run() -> None:
            journal = self._storage.journals.get((public_key, store_id))
            stage = journal.open_stage if journal is not None else None
            if journal is not None and stage is not None and stage.id == stage_id:
                journal.close_stage(stage)

        return sync(run)

    def rollback(
        self, public_key: str, store_id: StoreId, expected_activation_id: str, /
    ) -> Effect[str, CompactionRollbackError]:
        key = (public_key, store_id)

        def body():
            pubsub = yield from self._storage.pubsubs.get(key)
            now = yield from _now
            return (
                yield from suspend(lambda: self._rollback(key, pubsub, now, expected_activation_id))
            )

        return scoped(gen(body))

    def _rollback(
        self,
        key: _Key,
        pubsub: PubSub[EncryptedRemoteBatch],
        now: int,
        expected_activation_id: str,
    ) -> Effect[str, CompactionRollbackError]:
        journal = self._storage.journal(key)
        withdrawn = journal.active
        if withdrawn.id != expected_activation_id:
            return fail(CompactionRollbackError("NotActive"))
        target = withdrawn.previous
        if target is None:
            return fail(CompactionRollbackError("NoPrevious"))
        if target.prune_started_at is not None:
            return fail(CompactionRollbackError("PruneStarted"))
        activation = replace(target, id=_new_id(), superseded_at=None, prune_started_at=None)
        # The input of the stage that built the withdrawn generation.
        snapshot = target.set.batches if target.set is not None else []
        reappend = [*snapshot, *journal.originals_between(target.base, withdrawn.base)]
        withdrawn.superseded_at = now
        journal.activations.append(activation)
        journal.active = activation
        journal.no_op = None
        self.schedule_prune(journal, now + self.config.grace_millis)
        for batch in reappend:
            copy = EncryptedRemoteBatch(
                sequence=journal.next_sequence,
                entry_ids=batch.entry_ids,
                iv=batch.iv,
                encrypted_batch=batch.encrypted_batch,
            )
            journal.next_sequence += len(batch.entry_ids)
            journal.batches.append(copy)
            pubsub.publish_unsafe(copy)
        if reappend:
            journal.record_bucket(now, journal.next_sequence - 1, self.config.lag_millis)
        return log_rollback(
            public_key=key[0],
            store_id=key[1],
            activation_id=activation.id,
            base=activation.base,
            kept_count=activation.kept_count,
            withdrawn_id=withdrawn.id,
            withdrawn_base=withdrawn.base,
            withdrawn_kept_count=withdrawn.kept_count,
        ).as_(activation.id)

    def history(
        self, public_key: str, store_id: StoreId, /
    ) -> Effect[tuple[CompactionActivation, ...]]:
        def read() -> tuple[CompactionActivation, ...]:
            journal = self._storage.journal((public_key, store_id))
            return tuple(
                CompactionActivation(
                    activation_id=a.id,
                    base=a.base,
                    kept_count=a.kept_count,
                    active=a is journal.active,
                    superseded_at=None if a is journal.active else a.superseded_at,
                    restorable=a.prune_started_at is None,
                )
                for a in journal.activations
            )

        return sync(read)


class _MemoryStorage(StorageService):
    def __init__(
        self,
        pubsubs: RcMap[_Key, PubSub[EncryptedRemoteBatch]],
        config: CompactionConfig,
    ) -> None:
        self.journals: dict[_Key, _Journal] = {}
        # A pubsub per store, shut down a minute after its last user or
        # when the storage's scope closes.
        self.pubsubs = pubsubs
        self._bindings: dict[str, bytes] = {}
        self._remote_id = make_remote_id_unsafe()
        self.memory_compaction = _MemoryCompaction(self, config)
        self.compaction = self.memory_compaction

    def journal(self, key: _Key) -> _Journal:
        found = self.journals.get(key)
        if found is None:
            found = self.journals[key] = _Journal()
        return found

    @property
    def get_id(self) -> Effect[RemoteId]:
        return succeed(self._remote_id)

    def get_or_create_session_auth_binding(
        self, public_key: str, signing_public_key: bytes, /
    ) -> Effect[bytes]:
        return sync(lambda: self._bindings.setdefault(public_key, signing_public_key))

    def write(
        self, public_key: str, store_id: StoreId, batches: Sequence[EncryptedBatch], /
    ) -> Effect[list[EncryptedRemoteBatch]]:
        key = (public_key, store_id)
        lag_millis = self.memory_compaction.config.lag_millis

        def body():
            pubsub = yield from self.pubsubs.get(key)
            now = yield from _now
            journal = self.journal(key)
            stored: list[EncryptedRemoteBatch] = []
            for batch in batches:
                ids = [_uuid.stringify(i) for i in batch.entry_ids]
                if all(i in journal.known_ids for i in ids):
                    continue
                for offset, i in enumerate(ids):
                    journal.known_ids.setdefault(i, journal.next_sequence + offset)
                stored_batch = remote_batch(journal.next_sequence, batch)
                journal.next_sequence += len(ids)
                journal.batches.append(stored_batch)
                stored.append(stored_batch)
                pubsub.publish_unsafe(stored_batch)
            if stored:
                journal.record_bucket(now, journal.next_sequence - 1, lag_millis)
            return stored

        return scoped(gen(body))

    def entry_sequences(
        self, public_key: str, store_id: StoreId, entry_ids: Sequence[EntryId], /
    ) -> Effect[list[WriteAck]]:
        def read() -> list[WriteAck]:
            known = self.journal((public_key, store_id)).known_ids
            acks: list[WriteAck] = []
            for entry_id in entry_ids:
                sequence = known.get(_uuid.stringify(entry_id))
                if sequence is not None:
                    acks.append(WriteAck(entry_id=entry_id, sequence=sequence))
            return acks

        return sync(read)

    def changes(
        self, public_key: str, store_id: StoreId, start_sequence: int, /
    ) -> Stream[EncryptedRemoteBatch]:
        key = (public_key, store_id)

        def open_changes():
            pubsub = yield from self.pubsubs.get(key)
            subscription = yield from pubsub.subscribe()
            journal = self.journal(key)
            active = journal.active
            live = from_subscription(subscription)
            # Below the base an active snapshot replaces the originals.
            if active.set is not None and start_sequence <= active.base:
                if not active.set.batches:
                    return stream_die(
                        RuntimeError(
                            f"The active compaction snapshot of store {store_id} has no batches"
                        )
                    )
                snapshot = [b for b in active.set.batches if _last(b) >= start_sequence]
                tail = [b for b in journal.batches if b.sequence > active.base]
                return from_iterable([*snapshot, *tail]).concat(live)
            backlog = [b for b in journal.batches if _last(b) >= start_sequence]
            return from_iterable(backlog).concat(live)

        return stream_unwrap(gen(open_changes))

    def latest_sequence(self, public_key: str, store_id: StoreId, /) -> Effect[int | None]:
        def read() -> int | None:
            head = self.journal((public_key, store_id)).next_sequence - 1
            return None if head < 0 else head

        return sync(read)


def make_storage_memory_with(
    compaction: CompactionOptions | None = None,
) -> Effect[StorageService, Never, Scope]:
    """Storage kept in memory, with ``compaction`` tuning; its pubsubs and
    sweep stop when the scope closes. Dies on invalid compaction options
    (see ``make_compaction_config``)."""

    def build():
        config = yield from make_compaction_config(compaction)
        pubsubs = yield from RcMap.make(_open_pubsub, idle_time_to_live="60 seconds")
        storage = _MemoryStorage(pubsubs, config)
        yield from storage.memory_compaction.run_sweeps.fork_scoped()
        return storage

    return gen(build)
