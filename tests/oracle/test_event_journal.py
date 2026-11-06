"""Ports of Effect's ``effect/test/eventlog/EventJournal.test.ts`` and the
shared ``EventJournalConflictsTest.ts`` suite (run on the memory journal).

Each test's docstring is the Effect test title. Entry ids are immutable
``bytes``, so "``id.fill(tail, 6)``" builds a new id. Effect's isolated
module instances (for the tests that exhaust the id clock at the maximum
timestamp) are a fresh process sequence, patched in. ``vi.spyOn(Date,
"now")`` is ``event_journal.now_millis``, patched.

Omitted: "memoizes idString per entry instance, not per id buffer" (ids
are immutable ``bytes``; there is no buffer to change under an entry);
"reads idString on a frozen entry" (entries are frozen dataclasses; every
test reads ``id_string`` on one).
"""

import json
import os
import uuid
from collections.abc import Callable, Sequence
from dataclasses import asdict
from typing import Never

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.eventlog import event_journal as J
from pyfect.eventlog.event_journal import Entry, EntryId, RemoteEntry


def _with_tail(entry_id: bytes, tail: int) -> EntryId:
    return EntryId(entry_id[:6] + bytes([tail]) * 10)


def entry(msecs: int, event: str = "Repro", primary_key: str = "key", tail: int | None = None):
    """``tail`` fixes the random id bytes, so entries sharing a millisecond
    sort in a known order by id."""
    entry_id = J.make_entry_id_unsafe(msecs=msecs)
    if tail is not None:
        entry_id = _with_tail(entry_id, tail)
    return Entry(id=entry_id, event=event, primary_key=primary_key, payload=b"")


def remote_entry_with_rand_a(msecs: int, rand_a: int) -> Entry:
    """Fixes the 12 ``rand_a`` bits, which local ids use for their counter."""
    raw = bytearray(J.make_entry_id_unsafe(msecs=msecs))
    raw[6] = 0x70 | (rand_a >> 8)
    raw[7] = rand_a & 0xFF
    return Entry(id=EntryId(bytes(raw)), event="Repro", primary_key="key", payload=b"")


def maximum_entry() -> Entry:
    """Saturated ``rand_a`` bits at the maximum timestamp leave no later
    local id."""
    raw = bytearray(J.make_entry_id_unsafe(msecs=2**48 - 1))
    raw[6] = 0x7F
    raw[7] = 0xFF
    return Entry(id=EntryId(bytes(raw)), event="Repro", primary_key="key", payload=b"")


def import_entry(journal: J.EventJournalService, item: Entry):
    return journal.write_from_remote(
        remote_id=J.make_remote_id_unsafe(),
        entries=[RemoteEntry(remote_sequence=0, entry=item)],
        effect=lambda _: fx.void,
    )


def id_strings(entries: Sequence[Entry]) -> list[str]:
    return [item.id_string for item in entries]


def remote_entries(entries: Sequence[Entry]) -> list[RemoteEntry]:
    return [RemoteEntry(remote_sequence=i, entry=item) for i, item in enumerate(entries)]


def legacy_stringify(data: bytes) -> str:
    """The original UUID formatter, the compatibility oracle."""
    segments = (data[0:4], data[4:6], data[6:8], data[8:10], data[10:16])
    return "-".join("".join(f"{byte:02x}" for byte in segment) for segment in segments)


def _write_local(journal: J.EventJournalService, primary_key: str = "key", payload: bytes = b""):
    return journal.write(event="Repro", primary_key=primary_key, payload=payload, effect=fx.succeed)


@pytest.fixture
def isolated_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    """A fresh process id sequence, as Effect's isolated module instance."""
    monkeypatch.setattr(J, "_process_entry_ids", J._EntryIdSequence(0, 0))  # pyright: ignore[reportPrivateUsage]


def _now(monkeypatch: pytest.MonkeyPatch, millis: int) -> Callable[[int], None]:
    monkeypatch.setattr(J, "now_millis", lambda: millis)
    return lambda later: monkeypatch.setattr(J, "now_millis", lambda: later)


# --- EventJournalConflictsTest.ts ---------------------------------------------------


def _conflict_entry(msecs: int, tail: int, payload: int) -> Entry:
    entry_id = _with_tail(J.make_entry_id_unsafe(msecs=msecs), tail)
    return Entry(id=entry_id, event="Repro", primary_key="key", payload=bytes([payload]))


class _LastWriterWins:
    """An entry is applied only when no stored entry for its key is newer."""

    def __init__(self, journal: J.EventJournalService) -> None:
        self.journal = journal
        self.state: dict[str, list[int]] = {}

    def deliver(self, entries: Sequence[Entry]):
        def apply(batch: Sequence[J.EntryWithConflicts]) -> fx.Effect[None]:
            def run() -> None:
                for item in batch:
                    if not item.conflicts:
                        self.state[item.entry.primary_key] = list(item.entry.payload)

            return fx.sync(run)

        return self.journal.write_from_remote(
            remote_id=J.make_remote_id_unsafe(), entries=remote_entries(entries), effect=apply
        )


@testing.effect
def test_converges_when_same_key_entries_arrive_in_one_batch_out_of_id_order():
    """converges when same-key entries arrive in one batch out of id order"""
    newer = _conflict_entry(2_000, 0x10, 2)
    older = _conflict_entry(1_000, 0x10, 1)
    batched = _LastWriterWins((yield from J.make_memory))
    yield from batched.deliver([newer, older])
    separate = _LastWriterWins((yield from J.make_memory))
    yield from separate.deliver([newer])
    yield from separate.deliver([older])
    assert {"batched": batched.state.get("key"), "separate": separate.state.get("key")} == {
        "batched": [2],
        "separate": [2],
    }


@testing.effect
def test_reports_a_newer_id_in_the_same_millisecond_as_a_conflict_and_not_an_older_one():
    """reports a newer id in the same millisecond as a conflict, and not an older one"""
    journal = yield from J.make_memory
    lower = _conflict_entry(1_000, 0x01, 1)
    higher = _conflict_entry(1_000, 0x30, 3)
    yield from journal.write_from_remote(
        remote_id=J.make_remote_id_unsafe(),
        entries=remote_entries([lower, higher]),
        effect=lambda _: fx.void,
    )
    incoming = _conflict_entry(1_000, 0x10, 2)
    conflicts: list[str] = []
    yield from journal.write_from_remote(
        remote_id=J.make_remote_id_unsafe(),
        entries=remote_entries([incoming]),
        effect=lambda batch: fx.sync(
            lambda: conflicts.extend(c.id_string for item in batch for c in item.conflicts)
        ),
    )
    assert conflicts == [higher.id_string]


# --- EventJournal.test.ts -----------------------------------------------------------


@testing.effect
def test_deduplicates_overlapping_remote_entries_within_one_incoming_array():
    """EventJournal / deduplicates overlapping remote entries within one incoming array"""
    journal = yield from J.make_memory
    remote_id = J.make_remote_id_unsafe()
    a = entry(1_000)
    b = entry(2_000)
    handled: list[str] = []
    # Flattened overlapping batches [A] and [A, B], not separate journal writes.
    repeated_a = Entry(
        id=EntryId(bytes(a.id)), event=a.event, primary_key=a.primary_key, payload=a.payload
    )
    yield from journal.write_from_remote(
        remote_id=remote_id,
        entries=remote_entries([a, repeated_a, b]),
        effect=lambda batch: fx.sync(lambda: handled.extend(i.entry.id_string for i in batch)),
    )
    assert {
        "handled": handled,
        "stored": id_strings((yield from journal.entries)),
        "next_sequence": (yield from journal.next_remote_sequence(remote_id)),
    } == {
        "handled": [a.id_string, b.id_string],
        "stored": [a.id_string, b.id_string],
        "next_sequence": 3,
    }


@testing.effect
def test_advances_remote_progress_past_a_trailing_known_entry_in_a_partly_known_batch():
    """EventJournal / advances remote progress past a trailing known entry in a partly known batch"""  # noqa: E501
    journal = yield from J.make_memory
    remote_id = J.make_remote_id_unsafe()
    a = entry(1_000)
    b = entry(2_000)
    handled: list[str] = []

    def effect(batch: Sequence[J.EntryWithConflicts]) -> fx.Effect[None]:
        return fx.sync(lambda: handled.extend(i.entry.id_string for i in batch))

    yield from journal.write_from_remote(
        remote_id=remote_id, entries=[RemoteEntry(remote_sequence=0, entry=a)], effect=effect
    )
    yield from journal.write_from_remote(
        remote_id=remote_id,
        entries=[RemoteEntry(remote_sequence=1, entry=b), RemoteEntry(remote_sequence=2, entry=a)],
        effect=effect,
    )
    assert handled == [a.id_string, b.id_string]
    assert id_strings((yield from journal.entries)) == [a.id_string, b.id_string]
    assert (yield from journal.next_remote_sequence(remote_id)) == 3


@testing.effect
def test_entries_by_id_preserves_order_repeated_ids_and_missing_entries():
    """EventJournal / entriesById preserves order, repeated ids and missing entries"""
    journal = yield from J.make_memory
    first = yield from _write_local(journal, "first", b"\x01")
    second = yield from _write_local(journal, "second", b"\x02")
    missing = J.make_entry_id_unsafe()
    found = yield from journal.entries_by_id(
        [EntryId(bytes(second.id)), missing, EntryId(bytes(first.id)), second.id]
    )
    assert found == [second, None, first, second]
    assert (yield from journal.entries_by_id([])) == []


def test_formats_schema_accepted_ids_identically_to_the_original_uuid_formatter():
    """EventJournal / formats schema-accepted ids identically to the original UUID formatter"""
    from pyfect import schema as S

    ids: list[bytes] = [bytes(16), b"\xff" * 16]
    ids.extend(bytes(range(1, length + 1)) for length in range(16))
    # Exercise every byte value, including bytes that need a leading zero.
    ids.extend(bytes(range(start, start + 16)) for start in range(0, 256, 16))
    for i in range(100):
        ids.extend([os.urandom(16), J.make_remote_id_unsafe(), J.make_entry_id_unsafe(msecs=i)])
    for entry_id in ids:
        item = Entry(
            id=S.decode_unknown_sync(J.EntryIdSchema)(entry_id),
            event="Repro",
            primary_key="key",
            payload=b"",
        )
        assert item.id_string == legacy_stringify(entry_id)
        if len(entry_id) == 16:
            assert item.id_string == str(uuid.UUID(bytes=entry_id))


def test_keeps_equality_hashing_and_json_independent_of_id_string_access():
    """EventJournal / keeps equality, hashing and JSON independent of idString access"""
    first = entry(1_000)
    second = Entry(
        id=first.id, event=first.event, primary_key=first.primary_key, payload=first.payload
    )
    encoded = json.dumps(asdict(first), default=bytes.hex)
    assert first.id_string == legacy_stringify(first.id)
    assert {
        "equal": first == second,
        "same_hash": hash(first) == hash(second),
        "json": json.dumps(asdict(first), default=bytes.hex),
    } == {"equal": True, "same_hash": True, "json": encoded}


def test_decodes_the_48_bit_uuid_v7_timestamp_from_entry_ids():
    """EventJournal / decodes the 48-bit UUID v7 timestamp from entry ids"""
    cases = [
        ([0x00, 0x00, 0x00, 0x00, 0x00, 0x00], 0),
        ([0x00, 0x00, 0x00, 0x00, 0x00, 0x01], 1),
        ([0x00, 0x00, 0x80, 0x00, 0x00, 0x00], 2_147_483_648),
        ([0x01, 0x02, 0x03, 0x04, 0x05, 0x06], 1_108_152_157_446),
        ([0x01, 0x99, 0xC8, 0x2C, 0xC0, 0x00], 1_760_000_000_000),
        ([0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF], 281_474_976_710_655),
    ]
    for prefix, millis in cases:
        entry_id = bytes(prefix) + b"\xab" * 10
        assert J.entry_id_millis(entry_id) == millis
        assert entry(millis).created_at_millis == millis


def test_generates_strictly_ascending_entry_ids_when_the_clock_stalls_or_moves_backwards(
    monkeypatch: pytest.MonkeyPatch,
):
    """EventJournal / generates strictly ascending entry ids when the clock stalls or moves backwards"""  # noqa: E501
    # Later than any id generated or observed so far in this process.
    start = J.entry_id_millis(J.make_entry_id_unsafe()) + 1_000_000
    set_now = _now(monkeypatch, start)
    ids = [J.make_entry_id_unsafe() for _ in range(10_000)]
    set_now(start - 60_000)
    ids.append(J.make_entry_id_unsafe())
    for i in range(1, len(ids)):
        assert ids[i - 1] < ids[i], f"id {i} does not sort after id {i - 1}"
    # Exhausting a millisecond may move timestamps ahead slightly, never back.
    millis = [J.entry_id_millis(entry_id) for entry_id in ids]
    assert min(millis) >= start
    assert max(millis) <= start + 3


def test_generates_local_ids_after_imported_ids_from_the_same_or_a_later_millisecond(
    monkeypatch: pytest.MonkeyPatch,
):
    """EventJournal / generates local ids after imported ids from the same or a later millisecond"""
    journal = fx.run_blocking(J.make_memory)
    millis = J.entry_id_millis(J.make_entry_id_unsafe()) + 1
    _now(monkeypatch, millis)
    # Saturated ``rand_a`` bits sort above every local id counter in the
    # same millisecond.
    for remote in [
        remote_entry_with_rand_a(millis, 0xFFF),
        remote_entry_with_rand_a(millis + 1, 0xFFF),
    ]:
        fx.run_blocking(import_entry(journal, remote).or_die())
        local = fx.run_blocking(_write_local(journal).or_die())
        assert remote.id < local.id


def test_continues_the_local_id_counter_after_a_low_imported_rand_a_in_the_same_millisecond(
    monkeypatch: pytest.MonkeyPatch,
):
    """EventJournal / continues the local id counter after a low imported rand_a in the same millisecond"""  # noqa: E501
    journal = fx.run_blocking(J.make_memory)
    millis = J.entry_id_millis(J.make_entry_id_unsafe()) + 1
    remote = remote_entry_with_rand_a(millis, 5)
    _now(monkeypatch, millis)
    fx.run_blocking(import_entry(journal, remote).or_die())
    local = fx.run_blocking(_write_local(journal).or_die())
    assert remote.id < local.id
    # Only a saturated counter needs the next millisecond.
    assert J.entry_id_millis(local.id) == millis


@pytest.mark.usefixtures("isolated_ids")
def test_never_commits_a_local_id_below_an_imported_id_at_the_maximum_timestamp():
    """EventJournal / never commits a local id below an imported id at the maximum timestamp"""
    journal = fx.run_blocking(J.make_memory)
    remote = maximum_entry()
    fx.run_blocking(import_entry(journal, remote).or_die())
    # No later id exists, so the write may fail, but it must not commit an
    # id that sorts before the imported one.
    fx.run_blocking_exit(_write_local(journal))
    below = [item for item in fx.run_blocking(journal.entries.or_die()) if item.id < remote.id]
    assert id_strings(below) == []


@pytest.mark.usefixtures("isolated_ids")
def test_keeps_local_writes_working_after_a_failed_import_of_an_id_at_the_maximum_timestamp():
    """EventJournal / keeps local writes working after a failed import of an id at the maximum timestamp"""  # noqa: E501
    journal = fx.run_blocking(J.make_memory)
    failed = fx.run_blocking_exit(
        journal.write_from_remote(
            remote_id=J.make_remote_id_unsafe(),
            entries=[RemoteEntry(remote_sequence=0, entry=maximum_entry())],
            effect=lambda _: fx.fail(J.EventJournalError("test", "rejected")),
        )
    )
    written = fx.run_blocking_exit(_write_local(journal))
    assert isinstance(failed, fx.Failure)
    assert isinstance(written, fx.Success), "the local write failed after the import was rejected"
    assert id_strings(fx.run_blocking(journal.entries.or_die())) == [written.value.id_string]


_HOUR = 60 * 60 * 1000


def _counting_warnings() -> tuple[list[int], fx.Layer[Never]]:
    warnings = [0]

    def record(options: fx.logger.Options) -> None:
        if options.log_level == fx.LogLevel.WARN:
            warnings[0] += 1

    return warnings, fx.logger.layer([fx.Logger.make(record)])


@testing.effect
def test_logs_skew_warnings_relative_to_the_supplied_clock_service():
    """EventJournal / logs skew warnings relative to the supplied Clock service"""
    journal = yield from J.make_memory
    # Both imports advance the id clock and are over 24 hours ahead of wall time.
    millis = J.entry_id_millis(J.make_entry_id_unsafe()) + 48 * _HOUR
    yield from testing.set_time((millis - 25 * _HOUR) / 1000)
    warnings, logger = _counting_warnings()
    yield from import_entry(journal, entry(millis - 2 * _HOUR)).pipe(fx.provide(logger))
    within_24_hours = warnings[0]
    yield from import_entry(journal, entry(millis)).pipe(fx.provide(logger))
    assert (within_24_hours, warnings[0]) == (0, 1)


@testing.effect
def test_logs_skew_warnings_relative_to_the_supplied_clock_service_when_local_ids_are_later():
    """EventJournal / logs skew warnings relative to the supplied Clock service when local ids are later"""  # noqa: E501
    journal = yield from J.make_memory
    # Local ids follow wall time, which is ahead of the supplied Clock here.
    millis = J.entry_id_millis(J.make_entry_id_unsafe())
    yield from testing.set_time((millis - 48 * _HOUR) / 1000)
    warnings, logger = _counting_warnings()
    # 25 hours ahead of the supplied Clock, though behind the local ids.
    yield from import_entry(journal, entry(millis - 23 * _HOUR)).pipe(fx.provide(logger))
    assert warnings[0] == 1


@testing.effect
def test_orders_imported_entries_by_id_and_reports_conflicts_with_greater_ids_per_event_and_key():
    """EventJournal / orders imported entries by id and reports conflicts with greater ids per event and key"""  # noqa: E501
    journal = yield from J.make_memory
    peer = J.make_remote_id_unsafe()
    yield from journal.next_remote_sequence(peer)
    a1 = entry(1_000, "A", "k1")
    a2 = entry(3_000, "A", "k1", 0x20)
    other_key = entry(3_000, "A", "k2", 0x30)
    other_event = entry(3_000, "B", "k1", 0x10)
    same_millis = entry(2_000, "A", "k1", 0x80)
    yield from journal.write_from_remote(
        remote_id=J.make_remote_id_unsafe(),
        entries=remote_entries([a1, a2, other_key, other_event, same_millis]),
        effect=lambda _: fx.void,
    )
    x = entry(2_000, "A", "k1", 0x10)
    y = entry(1_500, "A", "k1")
    z = entry(3_000, "B", "k1", 0x80)
    replayed: list[tuple[str, list[str]]] = []
    callbacks = [0]

    def record(batch: Sequence[J.EntryWithConflicts]) -> fx.Effect[None]:
        def run() -> None:
            callbacks[0] += 1
            replayed.extend((i.entry.id_string, id_strings(i.conflicts)) for i in batch)

        return fx.sync(run)

    yield from journal.write_from_remote(
        remote_id=J.make_remote_id_unsafe(), entries=remote_entries([x, y, z]), effect=record
    )
    assert callbacks[0] == 1
    # The batch replays in id order. ``x`` shares a millisecond with
    # ``same_millis`` and ``z`` with ``other_event``; only greater ids conflict.
    assert replayed == [
        (y.id_string, [same_millis.id_string, a2.id_string]),
        (x.id_string, [same_millis.id_string, a2.id_string]),
        (z.id_string, []),
    ]
    expected = id_strings([a1, y, x, same_millis, other_event, a2, other_key, z])
    assert id_strings((yield from journal.entries)) == expected
    missing = yield from journal.with_remote_uncommitted(
        peer, lambda entries: fx.succeed(id_strings(entries))
    )
    assert missing == fx.Some(expected)


@testing.effect
def test_orders_local_write_after_future_import_and_reports_conflict_for_older_imports():
    """EventJournal / orders a local write after a future import and reports it as a conflict for older imports"""  # noqa: E501
    journal = yield from J.make_memory
    peer = J.make_remote_id_unsafe()
    source = J.make_remote_id_unsafe()
    yield from journal.next_remote_sequence(peer)
    yield from journal.next_remote_sequence(source)
    # Ahead of the clock and of any id generated or observed so far.
    future_millis = J.entry_id_millis(J.make_entry_id_unsafe()) + 60_000
    future = entry(future_millis)
    yield from import_entry(journal, future)
    local = yield from _write_local(journal)
    imported = entry(future_millis - 1)
    conflicts: list[str] = []
    yield from journal.write_from_remote(
        remote_id=source,
        entries=[RemoteEntry(remote_sequence=0, entry=imported)],
        effect=lambda batch: fx.sync(
            lambda: conflicts.extend(c.id_string for i in batch for c in i.conflicts)
        ),
    )
    assert conflicts == id_strings([future, local])
    expected = id_strings([imported, future, local])
    assert id_strings((yield from journal.entries)) == expected
    missing = yield from journal.with_remote_uncommitted(peer, lambda e: fx.succeed(id_strings(e)))
    assert missing == fx.Some(expected)
    source_missing = yield from journal.with_remote_uncommitted(
        source, lambda e: fx.succeed(id_strings(e))
    )
    assert source_missing == fx.Some(id_strings([future, local]))


@testing.effect
def test_reports_conflicts_in_id_order_after_a_local_write_following_a_future_import():
    """EventJournal / reports conflicts in id order after a local write following a future import"""
    journal = yield from J.make_memory
    future_millis = J.entry_id_millis(J.make_entry_id_unsafe()) + 60_000
    future = entry(future_millis)
    yield from import_entry(journal, future)
    local = yield from _write_local(journal)
    conflicts: list[str] = []
    yield from journal.write_from_remote(
        remote_id=J.make_remote_id_unsafe(),
        entries=[RemoteEntry(remote_sequence=0, entry=entry(1_000))],
        effect=lambda batch: fx.sync(
            lambda: conflicts.extend(c.id_string for i in batch for c in i.conflicts)
        ),
    )
    # The local id continues from the imported one, so it sorts after it.
    assert conflicts == id_strings([future, local])


@testing.effect
def test_relays_an_imported_entry_to_another_remote():
    """EventJournal / relays an imported entry to another remote"""
    journal = yield from J.make_memory
    source = J.make_remote_id_unsafe()
    target = J.make_remote_id_unsafe()
    yield from journal.next_remote_sequence(target)
    item = Entry(id=J.make_entry_id_unsafe(), event="Repro", primary_key="key", payload=b"")
    yield from journal.write_from_remote(
        remote_id=source,
        entries=[RemoteEntry(remote_sequence=0, entry=item)],
        effect=lambda _: fx.void,
    )
    calls = {"target": 0, "source": 0}

    def count(name: str, value: object) -> fx.Effect[object]:
        def run() -> object:
            calls[name] += 1
            return value

        return fx.sync(run)

    missing = yield from journal.with_remote_uncommitted(target, lambda e: count("target", e))
    assert isinstance(missing, fx.Some)
    assert id_strings(missing.value) == [item.id_string]  # pyright: ignore[reportArgumentType]
    assert calls["target"] == 1
    source_missing = yield from journal.with_remote_uncommitted(
        source, lambda _: count("source", "called")
    )
    assert source_missing is None
    assert calls["source"] == 0


@testing.effect
def test_returns_the_next_unused_remote_sequence():
    """EventJournal / returns the next unused remote sequence"""
    journal = yield from J.make_memory
    remote_id = J.make_remote_id_unsafe()
    item = Entry(id=J.make_entry_id_unsafe(), event="Repro", primary_key="key", payload=b"")

    def acks(*sequences: int) -> list[J.RemoteAck]:
        return [J.RemoteAck(item.id, sequence) for sequence in sequences]

    def remote_write(sequence: int):
        return journal.write_from_remote(
            remote_id=remote_id,
            entries=[RemoteEntry(remote_sequence=sequence, entry=item)],
            effect=lambda _: fx.void,
        )

    yield from journal.write_remote_acks(remote_id=remote_id, acks=acks(2))
    assert (yield from journal.next_remote_sequence(remote_id)) == 0
    yield from remote_write(0)
    assert (yield from journal.next_remote_sequence(remote_id)) == 1
    yield from journal.write_remote_acks(remote_id=remote_id, acks=acks(2, 1, 0))
    assert (yield from journal.next_remote_sequence(remote_id)) == 3
    yield from remote_write(5)
    yield from journal.write_remote_acks(remote_id=remote_id, acks=acks(2))
    assert (yield from journal.next_remote_sequence(remote_id)) == 6


@testing.effect
def test_records_entries_in_memory_and_publishes_local_changes():
    """EventJournal / records entries in memory and publishes local changes"""

    def body():
        journal = yield from J.EventJournal()
        created = [0]

        def record(written: Entry) -> fx.Effect[None]:
            return fx.sync(lambda: created.__setitem__(0, written.created_at_millis))

        yield from journal.write(
            event="test", primary_key="pk-1", payload=b"\x01\x02\x03", effect=record
        )
        entries = yield from journal.entries
        assert len(entries) == 1
        assert entries[0].event == "test"
        assert entries[0].primary_key == "pk-1"
        assert entries[0].created_at_millis == created[0]

    yield from fx.gen(body).pipe(fx.provide(J.layer_memory))
