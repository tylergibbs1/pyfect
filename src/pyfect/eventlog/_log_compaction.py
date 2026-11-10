"""How an event log runs remote compaction (the compaction part of Effect's
``eventlog/EventLog`` ``make``).

A run opens a stage, reads the input (taking entries from the journal
where it can and fetching the rest), folds the opted-in compactors over it
and uploads what they keep. The server's busy claim keeps runs on a store
apart, so the journal lock is held only for id lookups.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, Never

from pyfect._catch import catch_tag
from pyfect._core import Effect
from pyfect.clock import sleep
from pyfect.duration import millis
from pyfect.effect import die, gen, succeed
from pyfect.eventlog import _remote_compaction
from pyfect.eventlog._batches import MAX_BATCH_ENTRIES
from pyfect.eventlog._compactor import RegisteredCompactor
from pyfect.eventlog._identity import IdentityService
from pyfect.eventlog._remote_compaction import IdempotenceError
from pyfect.eventlog._remote_compaction_client import CompactionStage, EventLogRemoteCompaction
from pyfect.eventlog._remote_error import EventLogRemoteError
from pyfect.eventlog._uuid import stringify
from pyfect.eventlog.event_journal import (
    Entry,
    EventJournalError,
    EventJournalService,
    RemoteId,
    StoreId,
)
from pyfect.eventlog.event_log_message import (
    CompactionBusy,
    CompactionInputHeader,
    CompactionNoOp,
    CompactionNotWanted,
    CompactionSnapshot,
    CompactionStarted,
    EventLogProtocolError,
)
from pyfect.fiber_handle import FiberHandle
from pyfect.logger._log import log_debug, log_error, log_warning
from pyfect.random import next_int_between
from pyfect.schedule import jittered, spaced
from pyfect.scope import Scope

if TYPE_CHECKING:
    from pyfect.eventlog.event_log_remote import EventLogRemoteService

type CompactResult = Literal["Committed", "Superseded", "NoOp", "NotWanted", "Busy", "Aborted"]
"""How a compaction run ended: ``Committed`` and ``Superseded`` uploaded a
snapshot, ``NoOp`` dropped nothing, ``NotWanted`` and ``Busy`` come from the
server, and ``Aborted`` uploaded nothing and released the stage (a
compactor died, the idempotence check failed, every entry was dropped or
the input was pruned during the run)."""


@dataclass(frozen=True, slots=True)
class CompactOutcome:
    """How ``EventLogService.compact`` ended on one remote."""

    remote_id: RemoteId
    result: CompactResult


_STATUS_POLL = "1 hour"

# Spreads out devices that see ``wanted`` at the same time.
_DELAY_MILLIS = (60 * 1000, 5 * 60 * 1000)

# How many input batch headers share one journal lookup and one fetch.
_LOOKUP_BATCHES = 16


def has_remote_compactor(compactors: Mapping[str, RegisteredCompactor]) -> bool:
    return any(compactor.remote for compactor in compactors.values())


def _is_input_pruned(error: object) -> bool:
    return (
        isinstance(error, EventLogRemoteError)
        and isinstance(error.cause, EventLogProtocolError)
        and error.cause.code == "NotFound"
    )


@dataclass(frozen=True, slots=True)
class LogCompaction:
    """What a log's compaction runs over: its journal, store, identity and
    the registry's compactors."""

    journal: EventJournalService
    store_id: StoreId
    identity: IdentityService
    compactors: Mapping[str, RegisteredCompactor]

    def _resolve_input(
        self,
        compaction: EventLogRemoteCompaction,
        stage: CompactionStage,
        headers: Sequence[CompactionInputHeader],
        seen: set[str],
    ) -> Effect[list[Entry], EventJournalError | EventLogRemoteError]:
        """The headers' entries in input order, skipping ids seen at a lower
        input sequence. Only batches with an id the journal lacks are
        fetched."""

        def body():
            ids = [entry_id for header in headers for entry_id in header.entry_ids]
            known = yield from self.journal.entries_by_id(ids).pipe(
                self.journal.with_lock(self.store_id)
            )
            missing: list[int] = []
            offset = 0
            for header in headers:
                if any(known[offset + i] is None for i in range(len(header.entry_ids))):
                    missing.append(header.sequence)
                offset += len(header.entry_ids)
            fetched: dict[int, Entry] = {}
            if missing:
                yield from compaction.fetch(stage, missing).run_for_each(
                    lambda remote: succeed(
                        fetched.__setitem__(remote.remote_sequence, remote.entry)
                    )
                )
            entries: list[Entry] = []
            offset = 0
            for header in headers:
                for i in range(len(header.entry_ids)):
                    stored = known[offset + i]
                    entry = stored if stored is not None else fetched.get(header.sequence + i)
                    if entry is None:
                        message = f"Compaction input sequence {header.sequence + i} was not fetched"
                        return (yield from die(RuntimeError(message)))
                    if entry.id_string in seen:
                        continue
                    seen.add(entry.id_string)
                    entries.append(entry)
                offset += len(header.entry_ids)
            return entries

        return gen(body)

    def _run_stage(
        self, compaction: EventLogRemoteCompaction, stage: CompactionStage
    ) -> Effect[CompactResult, EventJournalError | EventLogRemoteError | IdempotenceError]:
        def body():
            seen: set[str] = set()
            entries = (
                compaction.input(stage)
                .grouped(_LOOKUP_BATCHES)
                .map_effect(lambda headers: self._resolve_input(compaction, stage, headers, seen))
                .flatten_iterable()
            )
            kept = yield from _remote_compaction.run(self.compactors, entries, MAX_BATCH_ENTRIES)
            if len(kept) == len(seen):
                committed = yield from compaction.commit(stage, CompactionNoOp())
                return "NoOp" if committed == "Committed" else committed
            if not kept:
                yield from log_warning(
                    "Remote compaction dropped every entry, so nothing is uploaded"
                )
                yield from compaction.abort(stage)
                return "Aborted"
            segment_count = yield from compaction.upload(stage, kept)
            result = yield from compaction.commit(
                stage, CompactionSnapshot(segment_count=segment_count)
            )
            yield from log_debug(
                f"Remote compaction kept {len(kept)} of {len(seen)} entries: {result}"
            )
            return result

        return gen(body)

    def run(
        self, remote_id: RemoteId, compaction: EventLogRemoteCompaction
    ) -> Effect[CompactResult, EventJournalError | EventLogRemoteError]:
        """One run on ``compaction``, shared by the background trigger and
        ``EventLogService.compact``."""

        def idempotence_failed(error: IdempotenceError) -> Effect[CompactResult]:
            return log_error(
                f"A remote compactor dropped {len(error.entries)} more entries from its own"
                " output, so nothing is uploaded"
            ).as_("Aborted")

        def input_pruned(error: object) -> Effect[CompactResult]:
            return log_warning("The compaction input was pruned during the run", error).as_(
                "Aborted"
            )

        def died(defect: object) -> Effect[CompactResult]:
            return log_error("Remote compaction died, so nothing is uploaded", defect).as_(
                "Aborted"
            )

        def body():
            begun = yield from compaction.begin(identity=self.identity, store_id=self.store_id)
            match begun:
                case CompactionBusy():
                    return "Busy"
                case CompactionNotWanted():
                    return "NotWanted"
                case CompactionStarted(stage_id=stage_id):
                    stage = CompactionStage(self.identity, self.store_id, stage_id)
                    return (
                        yield from self._run_stage(compaction, stage)
                        .on_error(lambda _: compaction.abort(stage))
                        .pipe(catch_tag(IdempotenceError, idempotence_failed))
                        .catch_if(_is_input_pruned, input_pruned)
                        .catch_defect(died)
                    )

        return gen(body).annotate_logs(
            {"service": "EventLog", "effect": "compact", "remoteId": stringify(remote_id)}
        )

    def poll_status(
        self, remote: EventLogRemoteService, trigger: FiberHandle[None, object]
    ) -> Effect[None]:
        """When ``remote`` offers compaction, the server wants it and the
        journal holds the remote up to the status head, start a background
        run after a random delay of a few minutes, unless one is waiting or
        running."""
        compaction = remote.compaction
        if compaction is None:
            return succeed(None)

        def start() -> Effect[None]:
            low, high = _DELAY_MILLIS
            return (
                next_int_between(low, high)
                .flat_map(lambda delay: sleep(millis(delay)))
                .and_then(self.run(remote.id, compaction))
                .flat_map(lambda result: log_debug(f"Remote compaction finished: {result}"))
                .catch_cause(log_warning)
            )

        def body():
            if not has_remote_compactor(self.compactors):
                return
            status = yield from compaction.status(identity=self.identity, store_id=self.store_id)
            if not status.wanted:
                return
            if (yield from self.journal.next_remote_sequence(remote.id)) <= status.head:
                return
            yield from trigger.run(start(), only_if_missing=True)

        return (
            gen(body)
            .catch_cause(log_warning)
            .annotate_logs({"service": "EventLog", "effect": "runRemote compaction status"})
        )

    def poll_hourly(
        self, remote: EventLogRemoteService, trigger: FiberHandle[None, object]
    ) -> Effect[None, Never, Scope]:
        """Poll the status about hourly, jittered, for as long as the scope
        lasts (the log also polls on each connect); nothing when ``remote``
        offers no compaction."""
        if remote.compaction is None:
            return succeed(None)
        polls = self.poll_status(remote, trigger).schedule(jittered(spaced(_STATUS_POLL)))
        return polls.fork_scoped().as_void()

    def compact(
        self, remotes: Sequence[EventLogRemoteService], remote_id: RemoteId | None
    ) -> Effect[list[CompactOutcome], EventJournalError | EventLogRemoteError]:
        """One run now on each of ``remotes`` that offers compaction, or only
        on ``remote_id``; none when no compactor opted in."""
        from pyfect._concurrency import for_each

        if not has_remote_compactor(self.compactors):
            return succeed([])
        targets: list[tuple[RemoteId, EventLogRemoteCompaction]] = [
            (remote.id, remote.compaction)
            for remote in remotes
            if remote.compaction is not None and (remote_id is None or remote.id == remote_id)
        ]

        def run(
            target: tuple[RemoteId, EventLogRemoteCompaction],
        ) -> Effect[CompactOutcome, EventJournalError | EventLogRemoteError]:
            return self.run(*target).map(lambda result: CompactOutcome(target[0], result))

        return for_each(targets, run)
