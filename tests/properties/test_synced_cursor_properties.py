"""``EventLog.synced`` waits until the sequence it has seen of a remote passes the remote's
latest. Its uploads' acks and the replays of other devices' entries commit in any order, so
for every order that sequence must never pass one this log lacks (sound) and must reach the
end once everything has committed (live). Quill hung when an ack committed before the replay
of the entry before it: the journal's cursor does not cross an ack it was not adjacent to,
and the remote never sends this log's own writes back on its connection."""

from __future__ import annotations

from collections.abc import Callable, Generator
from dataclasses import dataclass
from typing import Any

import pytest
from hypothesis import example, given
from hypothesis import strategies as st

import pyfect as fx
from pyfect.eventlog import event_journal as J
from pyfect.eventlog import sql_event_journal as SqlJ
from pyfect.eventlog._own_acks import OwnAcks
from pyfect.eventlog.event_journal import Entry, RemoteAck, RemoteEntry
from pyfect.reactivity import layer as reactivity_layer
from pyfect.sql import sqlite
from pyfect.sql.client import SqlClient


@dataclass(frozen=True)
class _History:
    own: tuple[bool, ...]
    """Whether this log wrote each sequence of the remote (else another device did)."""
    echoed: frozenset[int]
    """This log's sequences the change stream sends back (as after a reconnect)."""
    steps: tuple[tuple[str, tuple[int, ...]], ...]
    """Ack and replay batches in commit order; replays keep sequence order."""


def _chunks(draw: st.DrawFn, items: list[int]) -> list[tuple[int, ...]]:
    chunks: list[tuple[int, ...]] = []
    while items:
        size = draw(st.integers(1, len(items)))
        chunks.append(tuple(items[:size]))
        items = items[size:]
    return chunks


@st.composite
def _histories(draw: st.DrawFn) -> _History:
    own = draw(st.lists(st.booleans(), min_size=1, max_size=8))
    mine = [s for s, is_own in enumerate(own) if is_own]
    echoed = frozenset(draw(st.sets(st.sampled_from(mine))) if mine else ())
    acks = _chunks(draw, draw(st.permutations(mine)))
    replays = _chunks(draw, [s for s, is_own in enumerate(own) if not is_own or s in echoed])
    steps: list[tuple[str, tuple[int, ...]]] = []
    while acks or replays:
        if acks and (not replays or draw(st.booleans())):
            steps.append(("ack", acks.pop(0)))
        else:
            steps.append(("replay", replays.pop(0)))
    return _History(tuple(own), echoed, tuple(steps))


def _sql_journal() -> fx.Effect[J.EventJournalService, Any, Any]:
    client = sqlite.make(sqlite.SqliteClientConfig(filename=":memory:"))
    journal = client.flat_map(lambda c: SqlJ.make().pipe(fx.provide_service(SqlClient, c)))
    return journal.pipe(fx.provide(reactivity_layer))


JOURNALS: dict[str, Callable[[], fx.Effect[J.EventJournalService, Any, Any]]] = {
    "memory": lambda: J.make_memory,
    "sql": _sql_journal,
}


def _seen_sequences(
    journal: J.EventJournalService, history: _History
) -> Generator[Any, Any, list[tuple[int, int]]]:
    """Commits ``history`` as the log's uploader and consumer do, giving after each step the
    sequence ``synced`` has seen and the first one this log does not hold yet."""
    remote = J.make_remote_id_unsafe()
    own_acks = OwnAcks()
    entries: dict[int, Entry] = {}
    for sequence, is_own in enumerate(history.own):
        if is_own:
            written = yield from journal.write(
                event="E", primary_key=str(sequence), payload=b"", effect=fx.succeed
            )
            entries[sequence] = written
        else:
            entry = Entry(id=J.make_entry_id_unsafe(), event="E", primary_key="", payload=b"")
            entries[sequence] = entry
    # This log holds its own entries from the start; the others once they are replayed.
    held = {s for s, is_own in enumerate(history.own) if is_own}
    seen: list[tuple[int, int]] = []
    for kind, sequences in history.steps:
        if kind == "ack":
            acks = [RemoteAck(entries[s].id, s) for s in sequences]
            yield from journal.write_remote_acks(remote_id=remote, acks=acks)
            own_acks.advance(remote, (yield from journal.next_remote_sequence(remote)), sequences)
        else:
            batch = [RemoteEntry(remote_sequence=s, entry=entries[s]) for s in sequences]
            yield from journal.write_from_remote(
                remote_id=remote, entries=batch, effect=lambda _: fx.void
            )
            held.update(sequences)
        sequence = own_acks.advance(remote, (yield from journal.next_remote_sequence(remote)))
        first_missing = next(s for s in range(len(history.own) + 1) if s not in held)
        seen.append((sequence, first_missing))
    return seen


_ACK_BEFORE_REPLAY = _History((False, True), frozenset(), (("ack", (1,)), ("replay", (0,))))
"""Quill's order: this log's sequence 1 is acknowledged before 0 is replayed."""


@pytest.mark.parametrize("journal", JOURNALS)
@given(history=_histories())
@example(history=_ACK_BEFORE_REPLAY)
def test_synced_sees_every_sequence_once_all_commit_and_none_early(journal: str, history: _History):
    @fx.fn
    def body():
        return (yield from _seen_sequences((yield from JOURNALS[journal]()), history))

    seen = fx.run_blocking(fx.scoped(body()))
    assert all(sequence <= first_missing for sequence, first_missing in seen), seen
    assert seen[-1][0] == len(history.own), seen
