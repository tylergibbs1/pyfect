"""Ports of ``sql-sqlite-node/test/SqlEventJournal.test.ts`` (with the
shared ``EventJournalConflictsTest.ts`` suite on the SQL journal) for
``pyfect.eventlog.sql_event_journal`` on SQLite.

Each test's docstring is the Effect test title. Effect's isolated module
instances ("another process") are a second client on the same database
file; the id clock they keep apart is patched with a fresh sequence where
a test exhausts it. ``Statement.Transformer`` is ``CurrentTransformer``.
"""

import itertools
import re
from collections.abc import Callable, Generator, Sequence
from pathlib import Path
from typing import Any, Never, TypedDict

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.eventlog import event as Ev
from pyfect.eventlog import event_group as G
from pyfect.eventlog import event_journal as J
from pyfect.eventlog import event_log as L
from pyfect.eventlog import sql_event_journal as SqlJ
from pyfect.eventlog.event_journal import Entry, EntryId, RemoteEntry
from pyfect.eventlog.event_log_encryption import layer_subtle
from pyfect.eventlog.event_log_remote import EventLogRemoteError, EventLogRemoteService
from pyfect.reactivity import Reactivity
from pyfect.reactivity import layer as reactivity_layer
from pyfect.sql import sqlite
from pyfect.sql.client import SqlClient, SqlClientService
from pyfect.sql.error import SqlError
from pyfect.sql.statement import CurrentTransformer

from .test_event_journal import (
    _conflict_entry,  # pyright: ignore[reportPrivateUsage]
    _LastWriterWins,  # pyright: ignore[reportPrivateUsage]
    entry,
    id_strings,
    maximum_entry,
    remote_entries,
)


def _client(filename: str = ":memory:", *, readonly: bool = False):
    return sqlite.make(sqlite.SqliteClientConfig(filename=filename, readonly=readonly))


def _open(client: SqlClientService, **options: Any) -> fx.Effect[J.EventJournalService, Any]:
    return SqlJ.make(**options).pipe(fx.provide_service(SqlClient, client))


def _make_journal():
    client = yield from _client()
    return (yield from _open(client))


make_journal: fx.Effect[J.EventJournalService, Any, Any] = fx.gen(_make_journal)


def _run(body: Callable[[], Generator[Any, Any, Any]]) -> fx.Effect[Any, Any, Any]:
    return fx.gen(body).pipe(fx.provide(reactivity_layer))


def _local(primary_key: str) -> J.EntryInput:
    return J.EntryInput("Repro", primary_key, b"")


def _write(journal: J.EventJournalService, primary_key: str = "key", payload: bytes = b""):
    return journal.write(event="Repro", primary_key=primary_key, payload=payload, effect=fx.succeed)


def _saturated(msecs: int) -> Entry:
    """Saturated ``rand_a`` bits sort the entry above every local id counter
    in the same millisecond."""
    raw = bytearray(J.make_entry_id_unsafe(msecs=msecs))
    raw[6] = 0x7F
    raw[7] = 0xFF
    return S.new(Entry, disable_checks=True)(
        id=EntryId(bytes(raw)), event="Repro", primary_key="key", payload=b""
    )


def _import(journal: J.EventJournalService, item: Entry, remote_id: J.RemoteId | None = None):
    return journal.write_from_remote(
        remote_id=remote_id or J.make_remote_id_unsafe(),
        entries=[RemoteEntry(remote_sequence=0, entry=item)],
        effect=lambda _: fx.void,
    )


def _upload(journal: J.EventJournalService, remote_id: J.RemoteId):
    return journal.with_remote_uncommitted(
        remote_id, lambda entries: fx.succeed(id_strings(entries))
    )


def _now_millis() -> int:
    return J.entry_id_millis(J.make_entry_id_unsafe())


class _User(TypedDict):
    id: str


UserCreated = Ev.make("UserCreated", primary_key=lambda p: p["id"], payload=S.Struct(_User))
UserGroup = G.empty.add(UserCreated)


def _identity_layer() -> fx.Layer[L.Identity]:
    return fx.layer.effect(L.Identity, L.make_identity).pipe(fx.layer.provide(layer_subtle))


def _user_entry(user_id: str) -> fx.Effect[Entry]:
    return (
        S.encode_effect(UserCreated.payload_codec)({"id": user_id})
        .or_die()
        .map(
            lambda payload: S.new(Entry, disable_checks=True)(
                id=J.make_entry_id_unsafe(),
                event="UserCreated",
                primary_key=user_id,
                payload=payload,
            )
        )
    )


def _merge(*layers: fx.Layer[Any, Any, Any]) -> fx.Layer[Never, Never, L.Registry]:
    """Merges group layers (their output type ``Never`` does not infer)."""
    return fx.layer.merge(*layers)


def _no_write(**_: object) -> fx.Effect[None]:
    return fx.void


def _remote(changes: Callable[..., fx.Effect[Any, Any, Any]]) -> EventLogRemoteService:
    return EventLogRemoteService(id=J.make_remote_id_unsafe(), changes=changes, write=_no_write)


# --- EventJournalConflictsTest.ts on the SQL journal ---------------------------------


@testing.effect
def test_converges_when_same_key_entries_arrive_in_one_batch_out_of_id_order():
    """converges when same-key entries arrive in one batch out of id order"""

    def body():
        newer = _conflict_entry(2_000, 0x10, 2)
        older = _conflict_entry(1_000, 0x10, 1)
        batched = _LastWriterWins((yield from make_journal))
        yield from batched.deliver([newer, older])
        separate = _LastWriterWins((yield from make_journal))
        yield from separate.deliver([newer])
        yield from separate.deliver([older])
        assert {"batched": batched.state.get("key"), "separate": separate.state.get("key")} == {
            "batched": [2],
            "separate": [2],
        }

    yield from _run(body)


@testing.effect
def test_reports_a_newer_id_in_the_same_millisecond_as_a_conflict_and_not_an_older_one():
    """reports a newer id in the same millisecond as a conflict, and not an older one"""

    def body():
        journal = yield from make_journal
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

    yield from _run(body)


# --- SqlEventJournal.test.ts ---------------------------------------------------------


@testing.effect
def test_deduplicates_overlapping_remote_entries_within_one_incoming_array():
    """SqlEventJournal / deduplicates overlapping remote entries within one incoming array"""

    def body():
        journal = yield from make_journal
        remote_id = J.make_remote_id_unsafe()
        a = entry(1_000)
        b = entry(2_000)
        repeated_a = Entry(id=a.id, event=a.event, primary_key=a.primary_key, payload=a.payload)
        handled: list[str] = []
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

    yield from _run(body)


@testing.effect
def test_advances_remote_progress_past_a_trailing_known_entry_in_a_partly_known_batch():
    """SqlEventJournal / advances remote progress past a trailing known entry in a partly known batch"""  # noqa: E501

    def body():
        journal = yield from make_journal
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
            entries=[
                RemoteEntry(remote_sequence=1, entry=b),
                RemoteEntry(remote_sequence=2, entry=a),
            ],
            effect=effect,
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

    yield from _run(body)


@testing.effect
def test_entries_by_id_preserves_order_repeated_ids_and_missing_entries():
    """SqlEventJournal / entriesById preserves order, repeated ids and missing entries"""

    def body():
        journal = yield from make_journal
        first = yield from _write(journal, "first", bytes([1]))
        second = yield from _write(journal, "second", bytes([2]))
        missing = J.make_entry_id_unsafe()
        found = yield from journal.entries_by_id([second.id, missing, first.id, second.id])
        assert found == [second, None, first, second]
        assert (yield from journal.entries_by_id([])) == []

    yield from _run(body)


@testing.effect
def test_replay_invalidation_observes_committed_entries_from_another_connection(tmp_path: Path):
    """SqlEventJournal / replay invalidation observes committed entries from another connection"""

    def body():
        filename = str(tmp_path / "journal.db")
        writer = yield from _client(filename)
        journal = yield from _open(writer)
        reader = yield from _client(filename, readonly=True)
        # A separate connection cannot see the replay transaction's
        # uncommitted rows.
        read_journal = yield from _open(reader)
        handlers = _merge(
            L.group(UserGroup, lambda h: h.handle(UserCreated, lambda _: fx.void)),
            L.group_reactivity(UserGroup, ["users"]),
        ).pipe(fx.layer.provide(L.layer_registry))
        layer = L.layer(L.schema(UserGroup), handlers).pipe(
            fx.layer.provide(
                fx.layer.merge(fx.layer.succeed(J.EventJournal, journal), _identity_layer())
            )
        )
        reactivity = yield from Reactivity()
        results = yield from reactivity.query(["users"], read_journal.entries)
        assert (yield from results.take()) == []
        user = yield from _user_entry("user-1")
        changes = yield from fx.Queue[RemoteEntry, EventLogRemoteError].unbounded()
        yield from changes.offer(RemoteEntry(remote_sequence=0, entry=user))

        def with_log():
            registry = yield from L.Registry()

            def open_changes(**_: object) -> fx.Effect[Any]:
                return fx.succeed(changes)

            yield from registry.register_remote(_remote(open_changes))
            assert id_strings((yield from results.take())) == [user.id_string]

        yield from fx.gen(with_log).pipe(fx.provide(layer))

    yield from _run(body)


@testing.effect
def test_write_many_generates_ids_after_entries_another_process_imported(tmp_path: Path):
    """SqlEventJournal / writeMany generates ids after entries another process imported into the shared database"""  # noqa: E501

    def body():
        filename = str(tmp_path / "journal.db")
        journal = yield from _open((yield from _client(filename)))
        # This process's clock lags the entry the other process imports.
        imported = _saturated(_now_millis() + 60_000)

        def other_process():
            other = yield from _open((yield from _client(filename)))
            yield from _import(other, imported)

        yield from fx.scoped(fx.gen(other_process))
        [local] = yield from journal.write_many([_local("key")], fx.succeed)
        assert imported.id < local.id

    yield from _run(body)


@pytest.mark.usefixtures("isolated_ids")
def test_keeps_local_writes_working_after_an_enclosing_transaction_rolls_back_an_import():
    """SqlEventJournal / keeps local writes working after an enclosing transaction rolls back an import at the maximum timestamp and a write after it"""  # noqa: E501

    def body() -> Generator[Any, Any, tuple[bool, str | None, list[str]]]:
        client = yield from _client()
        journal = yield from _open(client)
        # The import itself succeeds, and a local write in the same
        # transaction reads it before it commits. The transaction around
        # both then fails.
        rolled_back = yield from client.with_transaction(
            _import(journal, maximum_entry())
            .and_then(_write(journal).exit())
            .and_then(fx.fail("rolled back"))
        ).exit()
        written = yield from _write(journal).option()
        written_id = None if written is None else written.value.id_string
        failed = isinstance(rolled_back, fx.Failure)
        return failed, written_id, id_strings((yield from journal.entries))

    rolled_back, written_id, entries = fx.run_blocking(fx.scoped(_run(body)))
    assert rolled_back
    assert written_id is not None, "the local write failed after the import was rolled back"
    assert entries == [written_id]


@pytest.fixture
def isolated_ids(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(J, "_process_entry_ids", J._EntryIdSequence(0, 0))  # pyright: ignore[reportPrivateUsage]


@testing.effect
def test_orders_a_local_write_after_an_import_earlier_in_the_same_transaction():
    """SqlEventJournal / orders a local write after an import earlier in the same transaction"""

    def body():
        client = yield from _client()
        journal = yield from _open(client)
        # Ahead of this process's clock, with saturated ``rand_a`` bits.
        remote = _saturated(_now_millis() + 60_000)
        local = yield from client.with_transaction(
            _import(journal, remote).and_then(_write(journal))
        )
        assert remote.id < local.id

    yield from _run(body)


@testing.effect
def test_rolls_back_a_failed_same_client_handler_transaction_and_redelivers_the_batch():
    """SqlEventJournal / rolls back a failed same-client handler transaction with the journal and redelivers the batch"""  # noqa: E501

    def body():
        client = yield from _client()
        yield from client("CREATE TABLE projection (id TEXT PRIMARY KEY)")
        journal = yield from _open(client)
        handlers = _merge(
            L.group(
                UserGroup,
                # The primary key turns a missing rollback into a failed redelivery.
                lambda h: h.handle(
                    UserCreated,
                    lambda i: (
                        client("INSERT INTO projection (id) VALUES ({})", i.payload["id"])
                        .or_die()
                        .as_void()
                    ),
                ),
            ),
            L.group_reactivity(UserGroup, ["users"]),
        ).pipe(fx.layer.provide(L.layer_registry))
        attempts = [0]

        def abort_first(_: object) -> fx.Effect[None]:
            # Abort the first attempt after the handler transaction
            # completes, so only the enclosing journal transaction can roll
            # it back.
            attempts[0] += 1
            return fx.die(RuntimeError("aborted")) if attempts[0] == 1 else fx.void

        def transaction(effect: fx.Effect[Any, Any, Any]) -> fx.Effect[Any, Any, Any]:
            return (
                client.with_transaction(effect)
                .catch_if(lambda e: isinstance(e, SqlError), fx.die)
                .tap(abort_first)
            )

        layer = L.layer(L.schema(UserGroup), handlers).pipe(
            fx.layer.provide(
                fx.layer.merge(
                    fx.layer.succeed(J.EventJournal, journal),
                    _identity_layer(),
                    fx.layer.succeed(L.HandlerTransaction, transaction),
                )
            )
        )
        reactivity = yield from Reactivity()

        def snapshot():
            rows = yield from client("SELECT id FROM projection ORDER BY id")
            entries = yield from journal.entries
            return {
                "projection": [row["id"] for row in rows],
                "journal": [e.primary_key for e in entries],
            }

        # Queries re-run after the replay releases the journal lock and
        # transaction.
        results = yield from reactivity.query(["users"], fx.gen(snapshot))
        assert (yield from results.take()) == {"projection": [], "journal": []}
        entries: list[RemoteEntry] = []
        for i, user_id in enumerate(["user-1", "user-2"]):
            entries.append(RemoteEntry(remote_sequence=i, entry=(yield from _user_entry(user_id))))

        def changes(*, start_sequence: int, **_: object):
            # Every subscription redelivers from the requested sequence.
            def make():
                queue = yield from fx.Queue[RemoteEntry, EventLogRemoteError].unbounded()
                yield from queue.offer_all(
                    [e for e in entries if e.remote_sequence >= start_sequence]
                )
                return queue

            return fx.gen(make)

        def with_log():
            registry = yield from L.Registry()
            yield from registry.register_remote(_remote(changes))
            after_failure = yield from results.take()
            yield from testing.adjust("200 millis")
            after_redelivery = yield from results.take()
            assert {
                "after_failure": after_failure,
                "after_redelivery": after_redelivery,
                "attempts": attempts[0],
            } == {
                "after_failure": {"projection": [], "journal": []},
                "after_redelivery": {
                    "projection": ["user-1", "user-2"],
                    "journal": ["user-1", "user-2"],
                },
                "attempts": 2,
            }

        yield from fx.gen(with_log).pipe(fx.provide(layer))

    yield from _run(body)


@testing.effect
def test_replays_each_remote_batch_in_one_callback_with_greater_id_conflicts():
    """SqlEventJournal / replays each remote batch in one callback with same-event-and-key conflicts that have greater ids"""  # noqa: E501

    def body():
        journal = yield from make_journal
        newer = entry(2000, "Repro", "key", 0x80)
        other_event = entry(3000, "Other", "key", 0x10)
        other_key = entry(3000, "Repro", "other", 0x20)
        older = entry(1000)
        same_batch = entry(1500)
        same_millis = entry(2000, "Repro", "key", 0x10)
        batches: list[list[tuple[str, list[str]]]] = []

        def write_batch(entries: list[Entry]):
            return journal.write_from_remote(
                remote_id=J.make_remote_id_unsafe(),
                entries=remote_entries(entries),
                effect=lambda batch: fx.sync(
                    lambda: batches.append(
                        [(i.entry.id_string, id_strings(i.conflicts)) for i in batch]
                    )
                ),
            )

        yield from write_batch([newer, other_event, other_key])
        yield from write_batch([older, same_batch, same_millis])
        # Conflicts exclude the incoming batch and other event/key pairs. A
        # stored entry in the same millisecond with a greater id conflicts.
        assert batches == [
            [(newer.id_string, []), (other_event.id_string, []), (other_key.id_string, [])],
            [
                (older.id_string, [newer.id_string]),
                (same_batch.id_string, [newer.id_string]),
                (same_millis.id_string, [newer.id_string]),
            ],
        ]

    yield from _run(body)


@testing.effect
def test_journal_queries_use_indexes():
    """SqlEventJournal / journal queries use indexes"""

    def body():
        client = yield from _client()
        yield from _open(client)

        def plan(query: str) -> fx.Effect[list[str], SqlError]:
            return client.unsafe(f"EXPLAIN QUERY PLAN {query}").map(
                lambda rows: [
                    re.sub(r"INDEX \S+", "INDEX <index>", str(row["detail"])) for row in rows
                ]
            )

        assert {
            "conflicts": (
                yield from plan(
                    "SELECT * FROM effect_event_journal WHERE event IN ('a', 'b') "
                    "AND primary_key IN ('a', 'b') AND timestamp > 0"
                )
            ),
            "entries": (
                yield from plan("SELECT * FROM effect_event_journal ORDER BY timestamp ASC")
            ),
            "source": (
                yield from plan(
                    "SELECT remote_id FROM effect_event_journal_sources WHERE entry_id = x'00'"
                )
            ),
        } == {
            "conflicts": [
                "SEARCH effect_event_journal USING INDEX <index> "
                "(event=? AND primary_key=? AND timestamp>?)"
            ],
            "entries": ["SCAN effect_event_journal USING INDEX <index>"],
            "source": ["SEARCH effect_event_journal_sources USING INDEX <index> (entry_id=?)"],
        }

    yield from _run(body)


_LEGACY_ENTRIES = (
    "CREATE TABLE effect_event_journal (id BLOB PRIMARY KEY, event TEXT NOT NULL, "
    "primary_key TEXT NOT NULL, payload BLOB NOT NULL, timestamp INTEGER NOT NULL)"
)
_LEGACY_REMOTES = (
    "CREATE TABLE effect_event_remotes (remote_id BLOB NOT NULL, entry_id BLOB NOT NULL, "
    "sequence INT NOT NULL, PRIMARY KEY (remote_id, entry_id))"
)


def _insert_legacy_entry(client: SqlClientService, item: Entry) -> fx.Effect[Any, SqlError]:
    return client(
        "INSERT INTO effect_event_journal {}",
        client.insert(
            {
                "id": item.id,
                "event": item.event,
                "primary_key": item.primary_key,
                "payload": item.payload,
                "timestamp": item.created_at_millis,
            }
        ),
    )


@testing.effect
def test_opens_and_keeps_working_on_a_database_created_before_upload_checkpoints():
    """SqlEventJournal / opens and keeps working on a database created before upload checkpoints"""

    def body():
        client = yield from _client()
        # The schema as created by the first release of SqlEventJournal.
        yield from client(_LEGACY_ENTRIES)
        yield from client(_LEGACY_REMOTES)
        remote_id = J.make_remote_id_unsafe()
        local = entry(1000, "Repro", "local")
        imported = entry(2000, "Repro", "imported")
        for item in (local, imported):
            yield from _insert_legacy_entry(client, item)
        yield from client(
            "INSERT INTO effect_event_remotes {}",
            client.insert({"remote_id": remote_id, "entry_id": imported.id, "sequence": 0}),
        )
        journal = yield from _open(client)
        assert {
            "remote": (yield from _upload(journal, remote_id)),
            "other_remote": (yield from _upload(journal, J.make_remote_id_unsafe())),
        } == {
            "remote": fx.Some([local.id_string]),
            "other_remote": fx.Some([local.id_string, imported.id_string]),
        }

    yield from _run(body)


@testing.effect
def test_replaces_per_entry_remote_rows_with_entry_sources_in_one_restartable_migration(
    tmp_path: Path,
):
    """SqlEventJournal / replaces per-entry remote rows with entry sources in one restartable migration"""  # noqa: E501

    def body():
        filename = str(tmp_path / "journal.db")
        client = yield from _client(filename)
        # A journal written by an unreleased build with upload checkpoints and cursors.
        yield from client(_LEGACY_ENTRIES)
        yield from client(_LEGACY_REMOTES)
        yield from client(
            "CREATE TABLE effect_event_journal_sequence "
            "(sequence INTEGER PRIMARY KEY, entry_id BLOB NOT NULL UNIQUE)"
        )
        yield from client(
            "CREATE TABLE effect_event_remotes_checkpoints "
            "(remote_id BLOB PRIMARY KEY, sequence INTEGER NOT NULL)"
        )
        yield from client(
            "CREATE TABLE effect_event_remotes_cursors "
            "(remote_id BLOB PRIMARY KEY, next_sequence INT NOT NULL)"
        )
        yield from client(
            "CREATE INDEX effect_event_journal_event_idx "
            "ON effect_event_journal (event, primary_key, timestamp)"
        )
        yield from client(
            "CREATE INDEX effect_event_journal_timestamp_idx ON effect_event_journal (timestamp)"
        )
        yield from client(
            "CREATE INDEX effect_event_remotes_sequence_idx "
            "ON effect_event_remotes (remote_id, sequence)"
        )
        remote_a = J.make_remote_id_unsafe()
        remote_b = J.make_remote_id_unsafe()
        uploaded = entry(1000, "Repro", "uploaded")
        from_a = entry(2000, "Repro", "fromA")
        # Acknowledged by A, but the upload checkpoint was not saved before a restart.
        acked = entry(3000, "Repro", "acked")
        from_b = entry(4000, "Repro", "fromB")
        # Written offline; no remote has it.
        pending = entry(5000, "Repro", "pending")
        for item in (uploaded, from_a, acked, from_b, pending):
            yield from _insert_legacy_entry(client, item)
            yield from client(
                "INSERT INTO effect_event_journal_sequence {}", client.insert({"entry_id": item.id})
            )
        yield from client(
            "INSERT INTO effect_event_remotes {}",
            client.insert(
                [
                    {"remote_id": remote_a, "entry_id": from_a.id, "sequence": 0},
                    {"remote_id": remote_a, "entry_id": acked.id, "sequence": 1},
                    {"remote_id": remote_b, "entry_id": from_b.id, "sequence": 3},
                ]
            ),
        )
        yield from client(
            "INSERT INTO effect_event_remotes_checkpoints {}",
            client.insert({"remote_id": remote_a, "sequence": 1}),
        )
        # B has no cursor row, so its download progress is only in the remotes table.
        yield from client(
            "INSERT INTO effect_event_remotes_cursors {}",
            client.insert({"remote_id": remote_a, "next_sequence": 2}),
        )

        def fail_drop(statement: Any, *_: object) -> fx.Effect[Any]:
            if "DROP TABLE" in statement.compile()[0]:
                return fx.die(RuntimeError("interrupted migration"))
            return fx.succeed(statement)

        interrupted = yield from (
            _open(client).pipe(fx.provide_service(CurrentTransformer, fail_drop)).exit()
        )
        journal = yield from _open(client)
        readonly = yield from _open((yield from _client(filename, readonly=True)))

        def state(j: J.EventJournalService) -> Generator[Any, Any, dict[str, object]]:
            return {
                "entries": id_strings((yield from j.entries)),
                "next_a": (yield from j.next_remote_sequence(remote_a)),
                "next_b": (yield from j.next_remote_sequence(remote_b)),
            }

        migrated = yield from state(journal)
        reopened = yield from state(readonly)
        tables = yield from client(
            "SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name"
        )
        fresh = entry(6000, "Repro", "fresh")
        yield from journal.write_from_remote(
            remote_id=remote_b,
            entries=[RemoteEntry(remote_sequence=4, entry=fresh)],
            effect=lambda _: fx.void,
        )
        expected = {
            "entries": id_strings([uploaded, from_a, acked, from_b, pending]),
            "next_a": 2,
            "next_b": 4,
        }
        assert {
            "interrupted": isinstance(interrupted, fx.Failure),
            "migrated": migrated,
            "reopened": reopened,
            "tables": [row["name"] for row in tables],
            "next_b": (yield from journal.next_remote_sequence(remote_b)),
            "upload_a": (yield from _upload(journal, remote_a)),
            "upload_b": (yield from _upload(journal, remote_b)),
            "upload_late": (yield from _upload(journal, J.make_remote_id_unsafe())),
        } == {
            "interrupted": True,
            "migrated": expected,
            "reopened": expected,
            "tables": [
                "effect_event_journal",
                "effect_event_journal_sequence",
                "effect_event_journal_sources",
                "effect_event_remotes_checkpoints",
                "effect_event_remotes_cursors",
            ],
            "next_b": 5,
            # Never back to the source, and nothing at or below a checkpoint.
            "upload_a": fx.Some(id_strings([from_b, pending, fresh])),
            "upload_b": fx.Some(id_strings([uploaded, from_a, acked, pending])),
            "upload_late": fx.Some(id_strings([uploaded, from_a, acked, from_b, pending, fresh])),
        }

    yield from _run(body)


_JOURNALS = pytest.mark.parametrize(
    "make",
    [pytest.param(make_journal, id="SQL"), pytest.param(J.make_memory, id="memory")],
)


@_JOURNALS
@testing.effect
def test_with_remote_uncommitted_uploads_each_entry_once(make: fx.Effect[Any, Any, Any]):
    """SqlEventJournal / withRemoteUncommited uploads each entry once, retries failures and forwards older imports"""  # noqa: E501

    def body():
        journal: J.EventJournalService = yield from make
        remote_id = J.make_remote_id_unsafe()
        a = yield from _write(journal, "a")
        failed = yield from journal.with_remote_uncommitted(
            remote_id, lambda _: fx.fail("upload failed")
        ).exit()
        retried = yield from _upload(journal, remote_id)
        # No echo from the remote: a successful upload alone must advance it.
        b = yield from _write(journal, "b")
        next_ = yield from _upload(journal, remote_id)
        older = entry(a.created_at_millis - 1)
        yield from journal.write_from_remote(
            remote_id=J.make_remote_id_unsafe(),
            entries=remote_entries([older]),
            effect=lambda _: fx.void,
        )
        forwarded = yield from _upload(journal, remote_id)
        idle = yield from _upload(journal, remote_id)
        assert {
            "failed": isinstance(failed, fx.Failure),
            "retried": retried,
            "next": next_,
            "forwarded": forwarded,
            "idle": idle,
        } == {
            "failed": True,
            "retried": fx.Some([a.id_string]),
            "next": fx.Some([b.id_string]),
            "forwarded": fx.Some([older.id_string]),
            "idle": None,
        }

    yield from _run(body)


@_JOURNALS
@testing.effect
def test_write_many_commits_and_publishes_a_batch_in_order_only_when_its_callback_succeeds(
    make: fx.Effect[Any, Any, Any],
):
    """SqlEventJournal / writeMany commits and publishes a batch in order only when its callback succeeds"""  # noqa: E501

    def body():
        journal: J.EventJournalService = yield from make
        changes = yield from journal.changes
        entries = [_local("a"), _local("b"), _local("c")]
        failed = yield from journal.write_many(entries, lambda _: fx.fail("callback failed")).exit()
        after_failure = {
            "failed": isinstance(failed, fx.Failure),
            "entries": len((yield from journal.entries)),
            "published": (yield from changes.remaining()),
        }
        written = yield from journal.write_many(entries, fx.succeed)
        ids = id_strings(written)
        assert {
            "after_failure": after_failure,
            "keys": [e.primary_key for e in written],
            "ascending": all(x.id < y.id for x, y in itertools.pairwise(written)),
            "committed": id_strings((yield from journal.entries)),
            "uncommitted": (yield from _upload(journal, J.make_remote_id_unsafe())),
            "published": id_strings((yield from changes.take_all())),
        } == {
            "after_failure": {"failed": True, "entries": 0, "published": 0},
            "keys": ["a", "b", "c"],
            "ascending": True,
            "committed": ids,
            "uncommitted": fx.Some(ids),
            "published": ids,
        }

    yield from _run(body)


@_JOURNALS
@testing.effect
def test_failed_remote_callbacks_persist_nothing_and_allow_redelivery(
    make: fx.Effect[Any, Any, Any],
):
    """SqlEventJournal / failed remote callbacks persist nothing and allow redelivery"""

    def body():
        journal: J.EventJournalService = yield from make
        remote_id = J.make_remote_id_unsafe()
        stored = entry(500)
        yield from journal.write_from_remote(
            remote_id=J.make_remote_id_unsafe(),
            entries=remote_entries([stored]),
            effect=lambda _: fx.void,
        )
        added = entry(1000)
        # A new entry followed by an echo of an entry the journal already has.
        entries = remote_entries([added, stored])
        exit_ = yield from journal.write_from_remote(
            remote_id=remote_id,
            entries=entries,
            effect=lambda _: fx.fail(J.EventJournalError("writeFromRemote", "callback failed")),
        ).exit()
        assert isinstance(exit_, fx.Failure)
        after_failure = {
            "entries": id_strings((yield from journal.entries)),
            "sequence": (yield from journal.next_remote_sequence(remote_id)),
        }
        retried: list[str] = []
        yield from journal.write_from_remote(
            remote_id=remote_id,
            entries=entries,
            effect=lambda batch: fx.sync(lambda: retried.extend(i.entry.id_string for i in batch)),
        )
        assert {"after_failure": after_failure, "retried": retried} == {
            "after_failure": {"entries": [stored.id_string], "sequence": 0},
            "retried": [added.id_string],
        }
        assert id_strings((yield from journal.entries)) == [stored.id_string, added.id_string]
        assert (yield from journal.next_remote_sequence(remote_id)) == 2

    yield from _run(body)


@testing.effect
def test_preserves_write_callback_error_identity():
    """SqlEventJournal / preserves write callback error identity"""

    def body():
        journal = yield from make_journal
        error = RuntimeError("callback failed")
        actual = yield from journal.write(
            event="Repro", primary_key="key", payload=bytes([1]), effect=lambda _: fx.fail(error)
        ).flip()
        assert actual is error

    yield from _run(body)


@testing.effect
def test_preserves_remote_callback_error_identity():
    """SqlEventJournal / preserves remote callback error identity"""

    def body():
        journal = yield from make_journal
        yield from journal.write(
            event="Repro", primary_key="key", payload=bytes([1]), effect=lambda _: fx.void
        )
        error = RuntimeError("callback failed")
        actual = yield from journal.with_remote_uncommitted(
            J.make_remote_id_unsafe(), lambda _: fx.fail(error)
        ).flip()
        assert actual is error

    yield from _run(body)


@testing.effect
def test_commits_only_after_the_write_callback_succeeds():
    """SqlEventJournal / commits only after the write callback succeeds"""

    def body():
        journal = yield from make_journal
        yield from journal.write(
            event="Repro",
            primary_key="key",
            payload=bytes([1]),
            effect=lambda _: fx.fail("callback failed"),
        ).exit()
        assert (yield from journal.entries) == []

    yield from _run(body)


@testing.effect
def test_writes_and_reads_entries():
    """SqlEventJournal / writes and reads entries"""

    def body():
        journal = yield from make_journal
        created_at = [0]

        def record(item: Entry) -> fx.Effect[None]:
            return fx.sync(lambda: created_at.__setitem__(0, item.created_at_millis))

        yield from journal.write(
            event="UserCreated", primary_key="user-1", payload=bytes([1]), effect=record
        )
        entries = yield from journal.entries
        assert len(entries) == 1
        assert entries[0].event == "UserCreated"
        assert entries[0].created_at_millis == created_at[0]

    yield from _run(body)


@testing.effect
def test_writes_remote_entries_and_sequences():
    """SqlEventJournal / writes remote entries and sequences"""

    def body():
        journal = yield from make_journal
        remote_id = J.make_remote_id_unsafe()
        assert (yield from journal.next_remote_sequence(remote_id)) == 0
        entry_a = S.new(Entry, disable_checks=True)(
            id=J.make_entry_id_unsafe(), event="UserCreated", primary_key="user-2", payload=b"\2"
        )
        entry_b = S.new(Entry, disable_checks=True)(
            id=J.make_entry_id_unsafe(), event="UserCreated", primary_key="user-3", payload=b"\3"
        )
        seen_conflicts: list[tuple[Entry, ...]] = []
        yield from journal.write_from_remote(
            remote_id=remote_id,
            entries=remote_entries([entry_a, entry_b]),
            effect=lambda batch: fx.sync(lambda: seen_conflicts.extend(i.conflicts for i in batch)),
        )
        assert (yield from journal.next_remote_sequence(remote_id)) == 2
        empty_calls = [0]

        def count_empty(_: object) -> fx.Effect[str]:
            def call() -> str:
                empty_calls[0] += 1
                return "called"

            return fx.sync(call)

        empty_result = yield from journal.with_remote_uncommitted(remote_id, count_empty)
        assert empty_result is None
        assert empty_calls[0] == 0
        yield from journal.write(
            event="LocalCreated", primary_key="local-1", payload=b"\4", effect=lambda _: fx.void
        )
        uncommitted_calls = [0]

        def count(entries: list[Entry]) -> fx.Effect[list[Entry]]:
            def call() -> list[Entry]:
                uncommitted_calls[0] += 1
                return entries

            return fx.sync(call)

        uncommitted = yield from journal.with_remote_uncommitted(remote_id, count)
        assert isinstance(uncommitted, fx.Some), "Expected the callback result"
        assert len(uncommitted.value) == 1
        assert uncommitted.value[0].event == "LocalCreated"
        assert uncommitted_calls[0] == 1
        assert seen_conflicts == [(), ()]

    yield from _run(body)


@testing.effect
def test_advances_the_remote_sequence_only_across_acknowledgements_that_follow_it():
    """SqlEventJournal / advances the remote sequence only across acknowledgements that follow it"""

    def body():
        client = yield from _client()
        remote_id = J.make_remote_id_unsafe()

        def ack(sequence: int, entry_id: EntryId | None = None) -> J.RemoteAck:
            return J.RemoteAck(entry_id or J.make_entry_id_unsafe(), sequence)

        # A database from before the cursors table: every remote row was downloaded.
        yield from client(_LEGACY_REMOTES)
        yield from client(
            "INSERT INTO effect_event_remotes {}",
            client.insert(
                {"remote_id": remote_id, "entry_id": J.make_entry_id_unsafe(), "sequence": 4}
            ),
        )
        journal = yield from _open(client)
        assert (yield from journal.next_remote_sequence(remote_id)) == 5
        # Sequence 5, written by another replica, has not been downloaded.
        local = yield from _write(journal, "local-1")
        yield from journal.write_remote_acks(remote_id=remote_id, acks=[ack(6, local.id)])
        assert (yield from journal.next_remote_sequence(remote_id)) == 5
        yield from journal.write_from_remote(
            remote_id=remote_id,
            entries=[RemoteEntry(remote_sequence=5, entry=entry(1_000))],
            effect=lambda _: fx.void,
        )
        assert (yield from journal.next_remote_sequence(remote_id)) == 6
        yield from journal.write_remote_acks(
            remote_id=remote_id, acks=[ack(7), ack(6, local.id), ack(3)]
        )
        assert (yield from journal.next_remote_sequence(remote_id)) == 8
        assert (yield from (yield from _open(client)).next_remote_sequence(remote_id)) == 8
        # A remote that numbers from 1 can be acknowledged before any download.
        other_remote_id = J.make_remote_id_unsafe()
        yield from journal.write_remote_acks(
            remote_id=other_remote_id, acks=[ack(2), ack(1)], first_sequence=1
        )
        assert (yield from journal.next_remote_sequence(other_remote_id)) == 3

    yield from _run(body)


def _limit_parameters[A, E, R](effect: fx.Effect[A, E, R]) -> fx.Effect[A, E, R]:
    """Durable Object SQLite binds at most 100 parameters per statement;
    rejecting larger statements makes oversized batches fail whatever the
    local SQLite build."""

    def limit(statement: Any, *_: object) -> fx.Effect[Any]:
        if len(statement.compile()[1]) > 100:
            return fx.die("too many parameters")
        return fx.succeed(statement)

    return effect.pipe(fx.provide_service(CurrentTransformer, limit))


@testing.effect
def test_write_many_commits_a_batch_over_the_statement_parameter_limit():
    """writeMany commits a batch over the statement parameter limit"""

    def body():
        journal = yield from make_journal
        written = yield from journal.write_many([_local(str(i)) for i in range(101)], fx.succeed)
        assert [e.id_string for e in (yield from journal.entries)] == [e.id_string for e in written]

    yield from _limit_parameters(_run(body))


@testing.effect
def test_write_from_remote_reports_each_conflict_once_over_the_parameter_limit():
    """writeFromRemote reports each conflict once for a batch over the statement parameter limit"""

    def body():
        journal = yield from make_journal
        remote_id = J.make_remote_id_unsafe()
        # Two events sharing 101 keys: as 101 is prime, conflict lookups split
        # into chunks that mix both events, so a stored row matches several.
        incoming = [
            entry(1_000 + e * 101 + i, event, str(i))
            for e, event in enumerate(["A", "B"])
            for i in range(101)
        ]
        newer = [
            entry(stored.created_at_millis + 1_000, stored.event, stored.primary_key)
            for stored in incoming
        ]
        yield from journal.write_from_remote(
            remote_id=J.make_remote_id_unsafe(),
            entries=remote_entries(newer),
            effect=lambda _: fx.void,
        )
        batches: list[list[tuple[str, list[str]]]] = []

        def record(batch: Sequence[J.EntryWithConflicts]) -> fx.Effect[None]:
            return fx.sync(
                lambda: batches.append(
                    [(e.entry.id_string, [c.id_string for c in e.conflicts]) for e in batch]
                )
            )

        yield from journal.write_from_remote(
            remote_id=remote_id, entries=remote_entries(incoming), effect=record
        )
        assert {
            "batches": batches,
            "next_sequence": (yield from journal.next_remote_sequence(remote_id)),
        } == {
            "batches": [
                [(item.id_string, [newer[i].id_string]) for i, item in enumerate(incoming)]
            ],
            "next_sequence": 202,
        }

    yield from _limit_parameters(_run(body))
