"""Stores with 0.6.5 tables under a shared name wait for the operator unless
``migrate_legacy_stores="when_server_written"`` promises that no 0.6.5
store was written straight through the storage. The operator's tools
record nothing before a server's first start. Tables taken back from a
pair leave the batches it wrote since with it, and running servers follow.
Splits and stores opening beside their legacy tables are reported and
logged. On SQLite, PostgreSQL, MySQL and SQL Server (each server skipped
without one).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

import pyfect as fx
from pyfect.eventlog import event_log_server_encrypted as Server
from pyfect.eventlog.event_journal import StoreId
from pyfect.eventlog.sql_event_log_server_encrypted import LegacyStore

from ._legacy_eventlog import (
    DIALECTS,
    OTHER,
    OWNER,
    Earlier,
    LegacyDb,
    any_db,
    batch,
    migration_refused,
    read_tags,
    refusal,
)


@pytest.fixture(params=DIALECTS)
def db(request: pytest.FixtureRequest, tmp_path: Path) -> LegacyDb:
    return any_db(request, tmp_path)


@pytest.fixture
def earlier(monkeypatch: pytest.MonkeyPatch) -> Callable[[str], Earlier]:
    return lambda version: Earlier(monkeypatch, version)


def _beside(logs: list[str], name: str) -> bool:
    return any("opens tables of its own" in m and repr(name) in m for m in logs)


# --- by default, nothing moves by itself ------------------------------------------


@pytest.mark.parametrize("other_store", [None, "x"], ids=["signed-in", "own-store"])
def test_a_store_written_straight_through_the_storage_goes_to_no_other_pair(
    db: LegacyDb, earlier: Callable[[str], Earlier], other_store: str | None
) -> None:
    """The owner wrote straight through the storage, so its key has no
    binding; the other split's key authenticated on 0.6.5, by itself or
    while using a store of its own."""
    with earlier("0.6.5"):
        db.write(OWNER, "owner")
        db.bind(OTHER[0])
        if other_store is not None:
            db.write((OTHER[0], other_store), "other")
    # The other pair asks first, then the owner: both wait.
    assert refusal(db, OTHER).state == "pending"
    refused = refusal(db, OWNER)
    assert (refused.state, refused.other_keys) == ("unbound", (OTHER[0],))
    assert "straight through the storage" in refused.message
    assert db.report([OWNER[1]], public_keys=[OWNER[0]]) == [
        LegacyStore(*OTHER, "pending"),
        LegacyStore(*OWNER, "unbound", (OTHER[0],), "none"),
    ]
    assert db.migrate(OWNER, [OTHER[0]], without_binding=True) == fx.Success(True)
    assert db.read(OWNER) == ["owner"]
    logs: list[str] = []
    assert db.read(OTHER, logs) == []
    # The operator gave the tables to their writer: nothing is left to warn about.
    assert not _beside(logs, "Kq9/xT2+bQ==/main")


def test_a_pending_store_waits_and_opens_once_migrated_on_the_same_server(
    db: LegacyDb, earlier: Callable[[str], Earlier]
) -> None:
    with earlier("0.6.5"):
        db.bind(OWNER[0])
        db.write(OWNER, "owner")

    def server():
        storage = yield from Server.Storage()
        refused = yield from storage.latest_sequence(OWNER[0], StoreId(OWNER[1])).exit()
        assert isinstance(refused, fx.Failure)
        assert db.migrate(OWNER) == fx.Success(True)
        return (yield from read_tags(OWNER))

    assert db.run(server) == fx.Success(["owner"])


# --- the operator's tools before the first start ------------------------------------


def test_listing_before_the_first_start_records_nothing_and_migrating_is_refused(
    db: LegacyDb, earlier: Callable[[str], Earlier]
) -> None:
    late = ("Lt/k7+Q==", "main")
    with earlier("0.6.5"):
        db.bind(OWNER[0])
        db.write(OWNER, "owner")
    created = db.tables()
    # A preview while 0.6.5 still serves.
    assert db.report([OWNER[1]]) == [
        LegacyStore(*OTHER, "unbound", (OWNER[0],), "none", upgrade_recorded=False),
        LegacyStore(*OWNER, "pending", upgrade_recorded=False),
    ]
    assert "No server of pyfect 0.6.8 or later has started" in migration_refused(db.migrate(OWNER))
    assert db.tables() == created
    # Someone signs in on 0.6.5 after the preview, before the upgrade.
    with earlier("0.6.5"):
        db.bind(late[0])
        db.write(late, "late")
    db.start()
    assert [s for s in db.report(["main"]) if s.public_key == late[0]] == [
        LegacyStore(*late, "pending")
    ]
    assert db.migrate(late) == fx.Success(True)
    assert db.read(late) == ["late"]


def test_listing_a_database_no_server_ever_opened_is_empty(db: LegacyDb) -> None:
    assert db.report(["main"]) == []
    assert db.tables() == set()


# --- taking tables back -------------------------------------------------------------


def test_tables_an_earlier_version_gave_away_come_back_without_the_takers_batches(
    db: LegacyDb, earlier: Callable[[str], Earlier]
) -> None:
    with earlier("0.6.5"):
        db.write(OWNER, "owner")
    with earlier("0.6.7"):
        db.bind(OTHER[0])
        db.alias_as_067(OTHER)
        db.write(OTHER, "taker")
    db.start()

    def take_back(through_sequence: int | None = None) -> fx.Exit[bool, object]:
        return db.migrate(
            OWNER,
            [OTHER[0]],
            without_binding=True,
            taken_from=OTHER,
            through_sequence=through_sequence,
        )

    refused = migration_refused(take_back())
    assert "through_sequence=2" in refused
    assert "next_remote_sequence" in refused
    assert "between 1 and 2" in migration_refused(take_back(3))
    assert "goes with taken_from" in migration_refused(db.migrate(OWNER, through_sequence=1))
    assert take_back(1) == fx.Success(True)
    assert db.read(OWNER) == ["owner"]
    assert db.read(OTHER) == ["taker"]

    def sequences():
        storage = yield from Server.Storage()
        owner = yield from storage.latest_sequence(OWNER[0], StoreId(OWNER[1]))
        other = yield from storage.latest_sequence(OTHER[0], StoreId(OTHER[1]))
        yield from storage.write(OWNER[0], StoreId(OWNER[1]), [batch("owner-2")])
        return owner, other, (yield from read_tags(OWNER))

    # The taker's batch keeps its sequence; the owner's store goes on from its own.
    assert db.run(sequences) == fx.Success((1, 2, ["owner", "owner-2"]))


@pytest.mark.parametrize("through_sequence", [0, -1])
def test_tables_are_not_taken_back_through_a_sequence_before_the_first_batch(
    db: LegacyDb, earlier: Callable[[str], Earlier], through_sequence: int
) -> None:
    """``taken_from`` says the store taking them back wrote the first batch,
    so no sequence before its end can be the last it wrote."""
    with earlier("0.6.5"):
        db.write(OWNER, "owner")
    with earlier("0.6.7"):
        db.bind(OTHER[0])
        db.alias_as_067(OTHER)
        db.write(OTHER, "taker")
    db.start()
    refused = migration_refused(
        db.migrate(
            OWNER,
            [OTHER[0]],
            without_binding=True,
            taken_from=OTHER,
            through_sequence=through_sequence,
        )
    )
    assert "through_sequence must be 1 or more" in refused
    assert db.read(OTHER) == ["owner", "taker"]
    assert db.read(OWNER) == []


def test_tables_the_server_gave_away_come_back_without_the_takers_batches(
    db: LegacyDb, earlier: Callable[[str], Earlier]
) -> None:
    """With the option on, a store written straight through the storage
    goes to the bound split; the alias records where its batches end."""
    with earlier("0.6.5"):
        db.write(OWNER, "owner")
        db.bind(OTHER[0])
    db.migration = "when_server_written"
    assert db.read(OTHER) == ["owner"]
    db.write(OTHER, "taker")
    db.migration = "never"
    assert db.report([OWNER[1]], public_keys=[OWNER[0]]) == [
        LegacyStore(*OTHER, "migrated", (), "before_upgrade", "server"),
        LegacyStore(*OWNER, "taken", (OTHER[0],), "none", "server"),
    ]
    assert "drop through_sequence" in migration_refused(
        db.migrate(OWNER, [OTHER[0]], without_binding=True, taken_from=OTHER, through_sequence=2)
    )
    assert db.migrate(OWNER, [OTHER[0]], without_binding=True, taken_from=OTHER) == fx.Success(True)
    assert db.read(OWNER) == ["owner"]
    assert db.read(OTHER) == ["taker"]


def test_taking_tables_back_takes_effect_on_a_running_server(
    db: LegacyDb, earlier: Callable[[str], Earlier]
) -> None:
    with earlier("0.6.5"):
        db.write(OWNER, "owner")
        db.bind(OTHER[0])
    db.migration = "when_server_written"

    def server():
        storage = yield from Server.Storage()
        assert (yield from read_tags(OTHER)) == ["owner"]
        assert (yield from read_tags(OWNER)) == []
        assert db.migrate(
            OWNER, [OTHER[0]], without_binding=True, taken_from=OTHER, through_sequence=None
        ) == fx.Success(True)
        yield from storage.write(OTHER[0], StoreId(OTHER[1]), [batch("after")])
        return (yield from read_tags(OWNER)), (yield from read_tags(OTHER))

    assert db.run(server) == fx.Success((["owner"], ["after"]))


# --- what is reported and logged ------------------------------------------------------


def test_a_split_store_whose_key_never_authenticated_is_reported_and_logged(
    db: LegacyDb, earlier: Callable[[str], Earlier]
) -> None:
    pair = ("roll/ing==", "s")
    db.write(pair, "new")
    with earlier("0.6.5"):
        db.write(pair, "old")
    logs: list[str] = []
    assert db.read(pair, logs) == ["new"]
    assert any("a 0.6.5 node wrote to it" in m for m in logs)
    assert db.report([pair[1], "ing==/s"], public_keys=[pair[0]]) == [
        LegacyStore("roll", "ing==/s", "unbound", (), "none"),
        LegacyStore(*pair, "split", (), "none"),
    ]
    assert "cannot be merged" in migration_refused(db.migrate(pair, ["roll"], without_binding=True))


def test_a_store_opening_beside_tables_another_pair_was_given_is_logged(
    db: LegacyDb, earlier: Callable[[str], Earlier]
) -> None:
    with earlier("0.6.5"):
        db.write(OWNER, "owner")
    with earlier("0.6.7"):
        db.bind(OTHER[0])
        db.alias_as_067(OTHER)
    logs: list[str] = []
    assert db.read(OWNER, logs) == []
    assert _beside(logs, "Kq9/xT2+bQ==/main")


def test_a_store_beside_tables_taken_back_for_their_writer_is_not_logged(
    db: LegacyDb, earlier: Callable[[str], Earlier]
) -> None:
    with earlier("0.6.5"):
        db.write(OWNER, "owner")
    with earlier("0.6.7"):
        db.bind(OTHER[0])
        db.alias_as_067(OTHER)
        db.write(OTHER, "taker")
    db.start()
    assert db.migrate(
        OWNER, [OTHER[0]], without_binding=True, taken_from=OTHER, through_sequence=1
    ) == fx.Success(True)
    logs: list[str] = []
    assert db.read(OTHER, logs) == ["taker"]
    assert db.read(OTHER, logs) == ["taker"]
    assert not _beside(logs, "Kq9/xT2+bQ==/main")


def test_a_store_beside_tables_nobody_confirmed_is_logged_once_per_process(
    db: LegacyDb, earlier: Callable[[str], Earlier]
) -> None:
    """Each ``read`` starts a server: one warning in all of them."""
    with earlier("0.6.5"):
        db.write(OWNER, "owner")
    with earlier("0.6.7"):
        db.bind(OTHER[0])
        db.alias_as_067(OTHER)
    logs: list[str] = []
    assert db.read(OWNER, logs) == []
    assert db.read(OWNER, logs) == []
    assert db.read(OWNER, logs) == []
    assert sum("opens tables of its own" in m for m in logs) == 1
