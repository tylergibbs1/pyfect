"""The server's compaction policy: when compaction is wanted, and the
commit checks that turn a stage's staged batches into virtual sequences
(Effect's ``isCompactionWanted`` and ``checkSnapshot``)."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

from pyfect._core import Effect
from pyfect.effect import fail, gen, succeed
from pyfect.eventlog import _uuid
from pyfect.eventlog._server_encrypted.audit import POSITIONS_PER_SEGMENT
from pyfect.eventlog._server_encrypted.models import (
    CompactionBatchHeader,
    CompactionInvalidRequest,
    CompactionNotFound,
    CompactionStoreStatus,
    StagedHeader,
    StorageCompaction,
)
from pyfect.eventlog.event_journal import StoreId
from pyfect.pull import Pull, catch_done
from pyfect.scope import scoped


def is_compaction_wanted(status: CompactionStoreStatus, threshold_floor: int) -> bool:
    """The input past the lag must reach the threshold. After ``k``
    consecutive no-ops, the lag head must also have moved
    ``threshold * 2^(k-1)`` past the latest one."""
    threshold = max(status.active_kept_count, threshold_floor)
    pending = status.lag_head - status.base
    if pending <= 0 or pending < threshold:
        return False
    if status.no_op is None:
        return True
    return status.lag_head - status.no_op.at >= threshold * 2 ** (status.no_op.count - 1)


def _ended(_: None) -> Effect[None]:
    return succeed(None)


class _InputCursor:
    """Walks a stage's input entries in order, remembering the last
    sequence it reached."""

    def __init__(self, pull: Pull[tuple[CompactionBatchHeader, ...], CompactionNotFound]) -> None:
        self._pull = pull
        self._headers: tuple[CompactionBatchHeader, ...] = ()
        self._header = 0
        self._entry = 0
        self.last_sequence = -1

    def next(self) -> Generator[Any, Any, tuple[str, int] | None]:
        while True:
            if self._header == len(self._headers):
                chunk: tuple[CompactionBatchHeader, ...] | None = yield from catch_done(
                    self._pull, _ended
                )
                if chunk is None:
                    return None
                self._headers = chunk
                self._header = 0
                continue
            header = self._headers[self._header]
            if self._entry == len(header.entry_ids):
                self._header += 1
                self._entry = 0
                continue
            sequence = header.sequence + self._entry
            entry_id = _uuid.stringify(header.entry_ids[self._entry])
            self._entry += 1
            self.last_sequence = sequence
            return entry_id, sequence


def check_snapshot(
    compaction: StorageCompaction,
    public_key: str,
    store_id: StoreId,
    stage_id: str,
    segment_count: int,
) -> Effect[list[int], CompactionInvalidRequest | CompactionNotFound]:
    """Each staged batch's virtual start sequence, checking the staged
    batches against the stage's input in one pass over both: the kept ids,
    read in segments ``0`` to ``segment_count - 1``, must be a non-empty,
    repeat-free subsequence of the input's ids."""

    def invalid(message: str) -> Effect[Any, CompactionInvalidRequest]:
        return fail(CompactionInvalidRequest(stage_id, message))

    def body():
        pull = yield from compaction.input_headers(public_key, store_id, stage_id).to_pull()
        cursor = _InputCursor(pull)
        # The input sequence of each batch's last kept entry, and its size.
        ends: list[int] = []
        sizes: list[int] = []
        segment = -1

        def check(header: StagedHeader) -> Effect[None, CompactionInvalidRequest | Any]:
            def visit():
                nonlocal segment
                header_segment = header.position // POSITIONS_PER_SEGMENT
                if header_segment != segment:
                    if header_segment != segment + 1 or header_segment >= segment_count:
                        return (yield from invalid("Unexpected segment"))
                    segment = header_segment
                last = -1
                for entry_id in header.entry_ids:
                    wanted = _uuid.stringify(entry_id)
                    found = yield from cursor.next()
                    while found is not None and found[0] != wanted:
                        found = yield from cursor.next()
                    if found is None:
                        return (
                            yield from invalid("Kept entry is not in the input, or is out of order")
                        )
                    last = found[1]
                ends.append(last)
                sizes.append(len(header.entry_ids))

            return gen(visit)

        yield from compaction.staged_headers(public_key, store_id, stage_id).run_for_each(check)
        if not ends:
            return (yield from invalid("Snapshot is empty"))
        if segment != segment_count - 1:
            return (yield from invalid("Missing segment"))
        # Drain the input to learn its last sequence.
        while (yield from cursor.next()) is not None:
            pass
        # Each batch ends at its last kept entry's input sequence, and the
        # final one at the end of the input, so no batch starts below its
        # entries' input.
        last_index = len(ends) - 1
        return [
            (cursor.last_sequence if i == last_index else end) - sizes[i] + 1
            for i, end in enumerate(ends)
        ]

    return scoped(gen(body))
