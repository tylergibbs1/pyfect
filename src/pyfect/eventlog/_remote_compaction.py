"""The fold a remote compaction runs over a store's history (Effect's
``eventlog/internal/remoteCompaction.ts``)."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from pyfect._core import Effect
from pyfect.effect import fail, gen, succeed, sync
from pyfect.errors import TaggedError
from pyfect.eventlog._compactor import RegisteredCompactor
from pyfect.eventlog.event_journal import Entry
from pyfect.logger._log import log_warning
from pyfect.stream import Stream


@dataclass(eq=False)
class IdempotenceError(TaggedError):
    """A second pass over the kept set dropped ``entries``, so a compactor
    does not compose."""

    entries: Sequence[Entry]


def _drop(
    compactors: Mapping[str, RegisteredCompactor], entries: Sequence[Entry]
) -> Effect[list[Entry]]:
    """``entries`` without those the opted-in compactors drop, in order."""

    def body():
        kept: set[int] = set()
        calls: dict[int, tuple[RegisteredCompactor, list[Entry]]] = {}
        for entry in entries:
            compactor = compactors.get(entry.event)
            if compactor is None or not compactor.remote:
                kept.add(id(entry))
                continue
            calls.setdefault(id(compactor), (compactor, []))[1].append(entry)
        for compactor, given in calls.values():
            inputs = {id(entry) for entry in given}
            forwarded: set[int] = set()
            replaced = False

            def write(
                entry: Entry,
                _source: Entry | None,
                inputs: set[int] = inputs,
                forwarded: set[int] = forwarded,
            ) -> Effect[None]:
                def record() -> None:
                    nonlocal replaced
                    if id(entry) in inputs:
                        forwarded.add(id(entry))
                    else:
                        replaced = True

                return sync(record)

            yield from compactor.effect(given, write, remote=True)
            # Only forwarded input entries can be kept verbatim, so a call that
            # outputs anything else keeps its whole input.
            if replaced:
                yield from log_warning(
                    "A remote compactor wrote an entry it was not given, so its input is kept"
                ).annotate_logs({"events": sorted(compactor.events)})
                kept.update(inputs)
            else:
                kept.update(forwarded)
        return [entry for entry in entries if id(entry) in kept]

    return gen(body)


def run[E, R](
    compactors: Mapping[str, RegisteredCompactor],
    entries: Stream[Entry, E, R],
    chunk_size: int,
) -> Effect[list[Entry], E | IdempotenceError, R]:
    """Fold the opted-in compactors over ``entries`` (in input order, no id
    repeated) and give the kept entries in input order.

    Each step folds a chunk into the kept set; the chunk starts at
    ``chunk_size`` and grows to the size of the kept set, so a run stays
    linear when little is dropped and holds about twice the kept set. Fails
    with ``IdempotenceError`` when a second pass over the kept set drops
    more; a compactor defect fails the run."""

    def body():
        kept: list[Entry] = []
        pending: list[Entry] = []

        def fold(group: tuple[Entry, ...]) -> Effect[None]:
            nonlocal kept, pending
            pending.extend(group)
            if len(pending) < max(chunk_size, len(kept)):
                return succeed(None)
            given = kept + pending
            pending = []

            def keep(next_kept: list[Entry]) -> None:
                nonlocal kept
                kept = next_kept

            return _drop(compactors, given).map(keep)

        yield from entries.grouped(chunk_size).run_for_each(fold)
        if pending:
            kept = yield from _drop(compactors, kept + pending)
        again = yield from _drop(compactors, kept)
        if len(again) != len(kept):
            survivors = {id(entry) for entry in again}
            error = IdempotenceError([entry for entry in kept if id(entry) not in survivors])
            return (yield from fail(error))
        return kept

    return gen(body)
