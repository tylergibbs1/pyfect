"""Only session auth bindings made before the upgrade move a 0.6.5 store by
themselves. A key bound after it, which anyone can make by authenticating,
can neither take a store, nor lock its owner out, nor count on a database
0.6.6 or 0.6.7 opened first. Stores nothing shows the writer of, and stores
an earlier version gave away, are listed and go where the operator says.
On SQLite, PostgreSQL, MySQL and SQL Server (each server skipped without
one); the property runs on SQLite.
"""

from __future__ import annotations

import tempfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

import pyfect as fx
from pyfect.eventlog._sql_server_encrypted import legacy
from pyfect.eventlog.sql_event_log_server_encrypted import LegacyStore
from pyfect.sql.client import SqlClient

from ._legacy_eventlog import (
    DIALECTS,
    OTHER,
    OWNER,
    Earlier,
    LegacyDb,
    Pair,
    any_db,
    migration_refused,
    refusal,
    scope_hash,
    sqlite_db,
)


@pytest.fixture(params=DIALECTS)
def db(request: pytest.FixtureRequest, tmp_path: Path) -> LegacyDb:
    return any_db(request, tmp_path)


@pytest.fixture
def earlier(monkeypatch: pytest.MonkeyPatch) -> Callable[[str], Earlier]:
    return lambda version: Earlier(monkeypatch, version)


def test_an_identity_bound_after_the_upgrade_never_gets_a_store_no_key_had_bound(
    db: LegacyDb, earlier: Callable[[str], Earlier]
) -> None:
    with earlier("0.6.5"):
        db.write(OWNER, "owner")  # straight through the storage: no binding
    db.bind(OTHER[0])  # anyone, after the upgrade
    for pair in (OTHER, OWNER):
        refused = refusal(db, pair)
        assert (refused.authenticated, refused.other_keys) == (False, ())
    # Listed, with the owner's key named because nothing else knows it.
    assert db.report([OWNER[1]], public_keys=[OWNER[0]]) == [
        LegacyStore(*OTHER, "unbound", (), "after_upgrade"),
        LegacyStore(*OWNER, "unbound", (), "none"),
    ]
    assert "authenticated only since" in migration_refused(db.migrate(OTHER))
    assert "without_binding=True" in migration_refused(db.migrate(OWNER))
    assert "not_written_by=['Kq9']" in migration_refused(db.migrate(OWNER, without_binding=True))
    assert db.migrate(OWNER, [OTHER[0]], without_binding=True) == fx.Success(True)
    assert db.read(OWNER) == ["owner"]
    assert db.read(OTHER) == []
    assert db.report([OTHER[1]]) == [
        LegacyStore(*OTHER, "taken", (), "after_upgrade", "operator"),
        LegacyStore(*OWNER, "migrated", (), "none", "operator"),
    ]


def test_an_identity_bound_after_the_upgrade_cannot_lock_the_owner_out(
    db: LegacyDb, earlier: Callable[[str], Earlier]
) -> None:
    with earlier("0.6.5"):
        db.bind(OWNER[0])
        db.write(OWNER, "owner")
    db.bind(OTHER[0])
    assert db.report([OWNER[1]]) == [
        LegacyStore(*OTHER, "unbound", (OWNER[0],), "after_upgrade"),
        LegacyStore(*OWNER, "pending"),
    ]
    # The other pair, asking first, opens tables of its own.
    assert db.read(OTHER) == []
    assert db.read(OWNER) == ["owner"]


def test_the_record_of_the_upgrade_is_written_once(
    db: LegacyDb, earlier: Callable[[str], Earlier]
) -> None:
    with earlier("0.6.5"):
        db.write(OWNER, "owner")
    db.start()
    db.bind(OWNER[0])
    db.start()  # a restart does not record the newer binding
    assert not refusal(db, OWNER).authenticated


def test_after_0_6_7_the_server_moves_no_store_by_itself(
    db: LegacyDb, earlier: Callable[[str], Earlier]
) -> None:
    with earlier("0.6.5"):
        db.bind(OWNER[0])
        db.write(OWNER, "owner")
    with earlier("0.6.7"):
        db.start()
    refused = refusal(db, OWNER)
    assert (refused.authenticated, refused.automatic) == (True, False)
    assert "0.6.6 or 0.6.7 ran on this database" in refused.message
    # The others wait as well: the record cannot tell a binding from 0.6.7's time apart.
    assert not refusal(db, OTHER).authenticated
    assert db.report([OWNER[1]]) == [
        LegacyStore(*OTHER, "unbound", (OWNER[0],), "none"),
        LegacyStore(*OWNER, "unconfirmed"),
    ]
    assert db.migrate(OWNER) == fx.Success(True)
    assert db.read(OWNER) == ["owner"]


def test_a_store_0_6_7_gave_away_is_flagged_and_can_be_taken_back(
    db: LegacyDb, earlier: Callable[[str], Earlier]
) -> None:
    with earlier("0.6.5"):
        db.write(OWNER, "owner")
    with earlier("0.6.7"):
        db.bind(OTHER[0])
        db.alias_as_067(OTHER)  # as 0.6.7 did on the other key's first request
    assert db.read(OTHER) == ["owner"]
    assert db.report([OWNER[1]], public_keys=[OWNER[0]]) == [
        LegacyStore(*OTHER, "migrated", (), "before_upgrade", "earlier_version"),
        LegacyStore(*OWNER, "taken", (OTHER[0],), "none", "earlier_version"),
    ]
    take_back = "taken_from=('Kq9', 'xT2+bQ==/main')"
    assert take_back in migration_refused(db.migrate(OWNER, [OTHER[0]], without_binding=True))
    assert "not given to another store" in migration_refused(
        db.migrate(("ab/cd", "x"), taken_from=OTHER)
    )
    assert db.migrate(OWNER, [OTHER[0]], without_binding=True, taken_from=OTHER) == fx.Success(True)
    assert db.read(OWNER) == ["owner"]
    assert db.read(OTHER) == []


def test_a_concurrent_first_start_records_the_upgrade_once(
    db: LegacyDb, earlier: Callable[[str], Earlier]
) -> None:
    with earlier("0.6.5"):
        db.bind(OWNER[0])
        db.write(OWNER, "owner")

    with ThreadPoolExecutor(4) as pool:
        for started in [pool.submit(db.start) for _ in range(4)]:
            started.result()
    # Several starts at once: the server still migrates by itself.
    assert db.read(OWNER) == ["owner"]


def test_legacy_decisions_read_bindings_only_through_the_upgrade_record() -> None:
    """Anyone can add a live binding, by authenticating: the modules that
    decide where a legacy store goes take ``upgrade.Evidence`` instead."""
    package = Path(legacy.__file__).parent
    for name in ("legacy.py", "legacy_report.py"):
        text = (package / name).read_text()
        assert "db.bindings" not in text, name
        assert "session_auth_bindings" not in text, name


# --- the property ----------------------------------------------------------------

_LEGACY = "a/b/c/d"
_PAIRS: list[Pair] = [(key, legacy.store_of(_LEGACY, key)) for key in legacy.split_keys(_LEGACY)]
"""Every pair whose 0.6.5 tables are named ``a/b/c/d``."""

_keys = st.sampled_from([key for key, _ in _PAIRS])


def _holder(db: LegacyDb) -> str | None:
    """The key of the pair given the legacy tables, if any."""

    def body():
        sql = (yield from SqlClient()).without_transforms()
        rows = yield from sql(
            "SELECT scope FROM {} WHERE legacy_scope = {}",
            sql.identifier(f"{db.prefix}_scope_aliases"),
            scope_hash(_LEGACY),
        )
        return str(rows[0]["scope"]) if rows else None

    found = db.tool(fx.gen(body))
    assert isinstance(found, fx.Success)
    scope = found.value
    for key, store_id in _PAIRS:
        if scope == scope_hash(legacy.scope_key(key, store_id)):
            return key
    assert scope is None
    return None


def _read_or_refused(db: LegacyDb, pair: Pair) -> list[str] | None:
    try:
        return db.read(pair)
    except legacy.LegacyStoreNeedsMigration:
        return None


@settings(
    max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
@given(
    writer=_keys,
    bound_before=st.sets(_keys),
    ran_067=st.booleans(),
    bound_on_067=st.sets(_keys),
    after=st.lists(st.tuples(st.sampled_from(["bind", "read"]), _keys), max_size=8),
)
def test_no_store_moves_to_a_key_bound_after_the_upgrade_by_itself(
    monkeypatch: pytest.MonkeyPatch,
    *,
    writer: str,
    bound_before: set[str],
    ran_067: bool,
    bound_on_067: set[str],
    after: list[tuple[str, str]],
) -> None:
    """Under any order of authentications and requests before and after the
    upgrade, the server gives the legacy tables only to the one key bound
    before it, never with 0.6.6 or 0.6.7 in between, and that key always
    gets them, whoever asks first."""
    pairs = dict(_PAIRS)
    with tempfile.TemporaryDirectory() as directory:
        db = sqlite_db(Path(directory) / "log.db")
        with Earlier(monkeypatch, "0.6.5"):
            for key in sorted(bound_before):
                db.bind(key)
            db.write((writer, pairs[writer]), "owner")
        if ran_067:
            with Earlier(monkeypatch, "0.6.7"):
                db.start()
                for key in sorted(bound_on_067):
                    db.bind(key)
        owner = next(iter(bound_before)) if len(bound_before) == 1 and not ran_067 else None

        def check(key: str) -> None:
            found = _read_or_refused(db, (key, pairs[key]))
            if key == owner:
                assert found == ["owner"]
            else:
                assert found in ([], None)  # its own tables, or refused
            assert _holder(db) in (None, owner)

        for op, key in after:
            if op == "bind":
                db.bind(key)
            else:
                check(key)
        for key in pairs:
            check(key)
        assert _holder(db) == owner
