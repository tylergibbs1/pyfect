"""Stores the SQL encrypted event log server named ``publicKey/storeId`` up
to 0.6.5, which another (public key, store id) pair may share: only the
identity the session auth bindings from before the upgrade show wrote them
gets them, by itself when nothing else is possible and through the operator
otherwise; a refusal clears once the store is migrated, is logged and
reaches the client; and the stores waiting for a migration can be listed.
On SQLite, PostgreSQL, MySQL and SQL Server (each server skipped without
one). ``test_sql_event_log_legacy_evidence.py`` covers bindings made after
the upgrade and upgrades from 0.6.6 and 0.6.7.

0.6.5 is simulated by naming tables with the legacy key and creating only
its tables, as 0.6.5 did.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

import pytest

import pyfect as fx
from pyfect import logger
from pyfect.eventlog import event_journal as J
from pyfect.eventlog import event_log as L
from pyfect.eventlog import event_log_message as M
from pyfect.eventlog import event_log_server_encrypted as Server
from pyfect.eventlog._identity import IdentityService
from pyfect.eventlog.event_journal import Entry, StoreId
from pyfect.eventlog.event_log_encryption import EventLogEncryption, layer_subtle
from pyfect.eventlog.event_log_remote import (
    EventLogRemoteClient,
    EventLogRemoteService,
    make_encrypted,
)
from pyfect.eventlog.sql_event_log_server_encrypted import LegacyStore
from pyfect.redacted import make as redacted
from pyfect.rpc import test as rpc_test
from pyfect.schema import new
from pyfect.scope import Scope

from ._legacy_eventlog import (
    DIALECTS,
    OTHER,
    OWNER,
    Earlier,
    LegacyDb,
    any_db,
    migration_refused,
    refusal,
)


@pytest.fixture(params=DIALECTS)
def db(request: pytest.FixtureRequest, tmp_path: Path) -> LegacyDb:
    return any_db(request, tmp_path)


@pytest.fixture
def as_065(monkeypatch: pytest.MonkeyPatch) -> Callable[[], Earlier]:
    return lambda: Earlier(monkeypatch, "0.6.5")


# --- who gets the legacy tables ----------------------------------------------


def test_the_one_authenticated_identity_gets_its_store_with_no_operator_step(
    db: LegacyDb, as_065: Callable[[], Earlier]
) -> None:
    db.migration = "when_server_written"
    with as_065():
        db.bind(OWNER[0])
        db.write(OWNER, "owner")
    assert db.read(OWNER) == ["owner"]
    assert db.read(OTHER) == []
    assert db.migrate(OWNER) == fx.Success(True)  # already done; a no-op
    assert db.report([OWNER[1]]) == [
        LegacyStore(*OTHER, "taken", (OWNER[0],), "none", "server"),
        LegacyStore(*OWNER, "migrated", (), "before_upgrade", "server"),
    ]


def test_a_key_that_never_authenticated_cannot_take_another_identitys_store(
    db: LegacyDb, as_065: Callable[[], Earlier]
) -> None:
    db.migration = "when_server_written"
    with as_065():
        db.bind(OWNER[0])
        db.write(OWNER, "owner")
    # The other pair opens tables of its own, and the owner keeps its store.
    assert db.read(OTHER) == []
    assert "no session auth binding before the upgrade" in migration_refused(db.migrate(OTHER))
    assert db.read(OWNER) == ["owner"]
    assert db.read(OTHER) == []


def test_a_store_two_authenticated_identities_could_have_written_waits_for_the_operator(
    db: LegacyDb, as_065: Callable[[], Earlier]
) -> None:
    with as_065():
        db.bind(OWNER[0])
        db.write(OWNER, "owner")
        db.bind(OTHER[0])  # anyone may authenticate as the other split's key
    for pair, other in [(OWNER, OTHER), (OTHER, OWNER)]:
        refused = refusal(db, pair)
        # Worded around the asking pair, without telling the operator to migrate it.
        assert refused.message.startswith(f"Store {pair[1]!r} of {pair[0]!r} does not open")
        assert refused.authenticated
        assert refused.other_keys == (other[0],)
    assert db.report([OWNER[1], OTHER[1]]) == [
        LegacyStore(*OTHER, "ambiguous", (OWNER[0],)),
        LegacyStore(*OWNER, "ambiguous", (OTHER[0],)),
    ]
    # The operator must name the other identity, having checked it did not write them.
    assert "not_written_by=['Kq9']" in migration_refused(db.migrate(OWNER))
    assert "not_written_by" in migration_refused(db.migrate(OWNER, ["Kq9", "someone"]))
    assert "drop without_binding" in migration_refused(
        db.migrate(OWNER, [OTHER[0]], without_binding=True)
    )
    assert db.migrate(OWNER, [OTHER[0]]) == fx.Success(True)
    assert "given to store" in migration_refused(db.migrate(OTHER, [OWNER[0]]))
    assert db.read(OWNER) == ["owner"]
    assert db.read(OTHER) == []
    assert db.report([OWNER[1], OTHER[1]]) == [
        LegacyStore(*OTHER, "taken", (OWNER[0],), "before_upgrade", "operator"),
        LegacyStore(*OWNER, "migrated", (OTHER[0],), "before_upgrade", "operator"),
    ]


def test_without_a_binding_a_store_with_legacy_data_does_not_open_empty(
    db: LegacyDb, as_065: Callable[[], Earlier]
) -> None:
    pair = ("ab/cd+ef==", "notes")
    with as_065():
        db.write(pair, "data")
    assert not refusal(db, pair).authenticated
    # Authenticating after the upgrade shows nothing: the operator decides.
    db.bind(pair[0])
    assert "no key sharing that name had authenticated before" in refusal(db, pair).message
    assert db.migrate(pair, ["ab"], without_binding=True) == fx.Success(True)
    assert db.read(pair) == ["data"]


# --- a refusal clears, and is seen ---------------------------------------------


def test_a_refused_store_opens_on_the_same_server_once_migrated(
    db: LegacyDb, as_065: Callable[[], Earlier]
) -> None:
    with as_065():
        db.bind(OWNER[0])
        db.write(OWNER, "owner")
        db.bind(OTHER[0])

    def server():
        storage = yield from Server.Storage()
        refused = yield from storage.latest_sequence(*OWNER).exit()  # pyright: ignore[reportArgumentType]
        assert isinstance(refused, fx.Failure)
        assert db.migrate(OWNER, [OTHER[0]]) == fx.Success(True)
        return (yield from storage.latest_sequence(*OWNER))  # pyright: ignore[reportArgumentType]

    assert db.run(server) == fx.Success(1)


def test_a_refusal_is_logged_once_per_store(db: LegacyDb, as_065: Callable[[], Earlier]) -> None:
    with as_065():
        db.bind(OWNER[0])
        db.write(OWNER, "owner")
        db.bind(OTHER[0])
    entries: list[logger.Options] = []

    def server():
        storage = yield from Server.Storage()
        for _ in range(3):
            yield from storage.latest_sequence(*OWNER).exit()  # pyright: ignore[reportArgumentType]

    fx.run_blocking(
        fx.scoped(fx.gen(server))
        .pipe(fx.provide(db.storage()))
        .pipe(fx.provide(logger.layer([fx.Logger.make(entries.append)])))
    )
    warnings = [e for e in entries if e.log_level == fx.LogLevel.WARN]
    assert len(warnings) == 1
    assert str(warnings[0].message[0]).startswith(f"Store {OWNER[1]!r} of {OWNER[0]!r}")


# --- a 0.6.5 node writing after the upgrade --------------------------------------


def test_a_store_a_0_6_5_node_split_serves_its_own_tables_and_cannot_be_migrated(
    db: LegacyDb, as_065: Callable[[], Earlier]
) -> None:
    pair = ("roll/ing==", "s")
    with as_065():
        db.bind(pair[0])
    db.write(pair, "new")
    with as_065():
        db.write(pair, "old")
    assert db.read(pair) == ["new"]
    assert "cannot be merged" in migration_refused(db.migrate(pair))
    assert db.report([pair[1]]) == [
        LegacyStore("roll", "ing==/s", "unbound", (pair[0],), "none"),
        LegacyStore(*pair, "split"),
    ]


def test_the_report_lists_stores_waiting_for_their_next_request(
    db: LegacyDb, as_065: Callable[[], Earlier]
) -> None:
    uuid = "0b0d2f6e-5d1e-4c4f-9d43-3b0b7b0c9a10"
    with as_065():
        for pair in [OWNER, (uuid, "notes/2024"), (uuid, "notes"), ("pk", "main")]:
            db.bind(pair[0])
            db.write(pair, "x")
    db.start()
    assert db.report(["main", "notes/2024", "notes", "absent"]) == [
        LegacyStore(uuid, "notes/2024", "pending"),
        LegacyStore(f"{uuid}/notes", "2024", "unbound", (uuid,), "none"),
        LegacyStore(*OTHER, "unbound", (OWNER[0],), "none"),
        LegacyStore(*OWNER, "pending"),
    ]
    assert db.migrate(OWNER) == fx.Success(True)
    assert [s.state for s in db.report(["main"])] == ["taken", "migrated"]


# --- over the protocol -------------------------------------------------------------


def _entries(tag: str) -> list[Entry]:
    make = new(Entry, disable_checks=True)
    return [
        make(id=J.make_entry_id_unsafe(), event="Noted", primary_key=f"{tag}-{i}", payload=b"x")
        for i in range(2)
    ]


type _Steps = Callable[
    [EventLogRemoteService, Callable[[str], IdentityService]], fx.Effect[Any, Any, Scope]
]


def _over_rpc(db: LegacyDb, steps: _Steps) -> fx.Exit[Any, Any]:
    """``steps(remote, identity)`` against an encrypted server on ``db``;
    ``identity(public_key)`` gives an identity with that key."""

    def body():
        handlers = yield from Server.layer_rpc_handlers.build()
        client: Any = yield from rpc_test.make_client(M.EventLogRemoteRpcs).pipe(
            fx.provide(handlers)
        )
        encryption = yield from EventLogEncryption()
        remote = yield from (
            make_encrypted.pipe(fx.provide_service(EventLogRemoteClient, client))
            .pipe(fx.provide_service(EventLogEncryption, encryption))
            .pipe(fx.provide(L.layer_registry))
        )
        return (yield from steps(remote, lambda key: IdentityService(key, redacted(bytes(32)))))

    return fx.run_blocking(
        fx.scoped(fx.gen(body)).pipe(fx.provide(fx.layer.merge(db.storage(), layer_subtle))).exit()
    )


def _write_over_rpc(db: LegacyDb, pairs: Sequence[tuple[str, str]]) -> None:
    def steps(remote: EventLogRemoteService, identity: Callable[[str], IdentityService]):
        def body():
            for key, store in pairs:
                yield from remote.write(
                    identity=identity(key), store_id=StoreId(store), entries=_entries(key)
                )

        return fx.gen(body)

    assert isinstance(_over_rpc(db, steps), fx.Success)


def _changes_over_rpc(db: LegacyDb, pair: tuple[str, str]) -> fx.Exit[Any, Any]:
    def steps(remote: EventLogRemoteService, identity: Callable[[str], IdentityService]):
        def body():
            changes = yield from remote.changes(
                identity=identity(pair[0]), store_id=StoreId(pair[1]), start_sequence=0
            )
            return (yield from changes.take_n(2).timeout("3 seconds").exit())

        return fx.gen(body)

    ran = _over_rpc(db, steps)
    assert isinstance(ran, fx.Success)
    return ran.value


def test_a_store_written_through_a_0_6_5_server_syncs_after_the_upgrade(
    db: LegacyDb, as_065: Callable[[], Earlier]
) -> None:
    db.migration = "when_server_written"
    pairs = [OWNER, ("0b0d2f6e-5d1e-4c4f-9d43-3b0b7b0c9a10", "notes/2024")]
    with as_065():
        _write_over_rpc(db, pairs)
    for pair in pairs:
        found = _changes_over_rpc(db, pair)
        assert isinstance(found, fx.Success)
        assert len(found.value) == 2


def test_a_client_is_told_its_store_waits_for_the_operator(
    db: LegacyDb, as_065: Callable[[], Earlier]
) -> None:
    with as_065():
        _write_over_rpc(db, [OWNER])
        db.bind(OTHER[0])
    found = _changes_over_rpc(db, OWNER)
    assert isinstance(found, fx.Failure)
    error = found.cause.squash()
    protocol = getattr(error, "cause", None)
    assert isinstance(protocol, M.EventLogProtocolError)
    assert protocol.code == "InternalServerError"
    assert protocol.store_id == OWNER[1]
    assert "operator must migrate" in protocol.message
    assert OTHER[0] not in protocol.message.replace(OWNER[0], "")
