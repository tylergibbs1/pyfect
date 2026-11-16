"""Only session auth bindings made before the upgrade move a 0.6.5 store by
themselves. A key bound after it, which anyone can make by authenticating,
can neither take a store, nor lock its owner out, nor count on a database
0.6.6 or 0.6.7 opened first. Stores nothing shows the writer of, and stores
an earlier version gave away, are listed and go where the operator says.
On SQLite, PostgreSQL, MySQL and SQL Server (each server skipped without
one); the property runs on SQLite.
"""

from __future__ import annotations

import ast
import tempfile
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import _source
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
    db.migration = "when_server_written"
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
    db.migration = "when_server_written"  # moves nothing after 0.6.7 either
    refused = refusal(db, OWNER)
    assert refused.state == "unconfirmed"
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
    # 0.6.7 recorded nothing that tells the batches the other pair wrote since apart.
    assert "through_sequence=1" in migration_refused(
        db.migrate(OWNER, [OTHER[0]], without_binding=True, taken_from=OTHER)
    )
    assert db.migrate(
        OWNER, [OTHER[0]], without_binding=True, taken_from=OTHER, through_sequence=1
    ) == fx.Success(True)
    assert db.read(OWNER) == ["owner"]
    assert db.read(OTHER) == []


def test_a_concurrent_first_start_records_the_upgrade_once(
    db: LegacyDb, earlier: Callable[[str], Earlier]
) -> None:
    db.migration = "when_server_written"
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


def _calls(name: str) -> dict[str, set[str]]:
    """For each module of the package, the functions that call ``name``
    (as a function or a method), with the functions enclosing them."""
    package = Path(legacy.__file__).parent
    found: dict[str, set[str]] = {}
    for path in _source.files(package, recursive=False):
        for function in _source.walk(path):
            if not isinstance(function, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for node in ast.walk(function):
                if isinstance(node, ast.Call):
                    callee = node.func
                    called = callee.attr if isinstance(callee, ast.Attribute) else None
                    called = callee.id if isinstance(callee, ast.Name) else called
                    if called == name:
                        found.setdefault(path.name, set()).add(function.name)
    return found


def test_only_the_servers_storage_records_the_upgrade() -> None:
    """The record says which keys had authenticated before the upgrade, so
    only a server's first start may write it: never an operator's call,
    which may run while 0.6.5 still serves."""
    assert _calls("prepare") == {"storage.py": {"make_storage", "build"}}
    assert _calls("_record") == {"upgrade.py": {"prepare", "body"}}


def test_every_alias_records_who_made_it_and_where_its_batches_end() -> None:
    """``taken_from`` tells the holder's batches apart by the bound
    ``record_alias`` writes with each alias."""
    package = Path(legacy.__file__).parent
    alias_tables = {"aliases", "alias_origins", "alias_bounds"}
    writers: set[str] = set()
    for path in _source.files(package, recursive=False):
        for function in _source.walk(path):
            if not isinstance(function, ast.FunctionDef):
                continue
            for node in ast.walk(function):
                if not isinstance(node, ast.Call) or not node.args:
                    continue
                first = node.args[0]
                text = first.value if isinstance(first, ast.Constant) else None
                tables = {a.attr for a in node.args if isinstance(a, ast.Attribute)} & alias_tables
                inserts = isinstance(text, str) and text.lstrip().upper().startswith("INSERT")
                insert_new = isinstance(node.func, ast.Attribute) and node.func.attr == "insert_new"
                if tables and (inserts or insert_new):
                    writers.add(f"{path.name}:{function.name}")
    assert writers == {"legacy.py:record_alias", "legacy.py:body"}
    source = (package / "legacy.py").read_text()
    record = source[source.index("def record_alias") : source.index("class Resolved")]
    assert all(f"db.{table}" in record for table in alias_tables)


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


_examples = settings(
    max_examples=40, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture]
)
_histories = given(
    writer=_keys,
    bound_before=st.sets(_keys),
    ran_067=st.booleans(),
    bound_on_067=st.sets(_keys),
    after=st.lists(st.tuples(st.sampled_from(["bind", "read", "start"]), _keys), max_size=8),
)


def _replay(
    monkeypatch: pytest.MonkeyPatch,
    db: LegacyDb,
    *,
    writer: str,
    bound_before: set[str],
    ran_067: bool,
    bound_on_067: set[str],
    after: list[tuple[str, str]],
    check: Callable[[str], None],
) -> None:
    """Writes the store as ``writer`` on 0.6.5 (straight through the storage
    unless its key is in ``bound_before``), then runs ``after`` on this
    version, checking each pair it reads and every pair at the end."""
    pairs = dict(_PAIRS)
    with Earlier(monkeypatch, "0.6.5"):
        for key in sorted(bound_before):
            db.bind(key)
        db.write((writer, pairs[writer]), "owner")
    if ran_067:
        with Earlier(monkeypatch, "0.6.7"):
            db.start()
            for key in sorted(bound_on_067):
                db.bind(key)
    for op, key in after:
        if op == "bind":
            db.bind(key)
        elif op == "start":
            db.start()
        else:
            check(key)
    for key in pairs:
        check(key)


@_examples
@_histories
def test_with_migration_on_no_store_moves_to_a_key_bound_after_the_upgrade_by_itself(
    monkeypatch: pytest.MonkeyPatch,
    *,
    writer: str,
    bound_before: set[str],
    ran_067: bool,
    bound_on_067: set[str],
    after: list[tuple[str, str]],
) -> None:
    """With ``migrate_legacy_stores="when_server_written"``, under any order
    of authentications and requests before and after the upgrade, the
    server gives the legacy tables only to the one key bound before it,
    never with 0.6.6 or 0.6.7 in between, and that key always gets them,
    whoever asks first. (It is the writer only if no store was written
    straight through the storage, which the option promises.)"""
    pairs = dict(_PAIRS)
    owner = next(iter(bound_before)) if len(bound_before) == 1 and not ran_067 else None
    with tempfile.TemporaryDirectory() as directory:
        db = sqlite_db(Path(directory) / "log.db")
        db.migration = "when_server_written"

        def check(key: str) -> None:
            found = _read_or_refused(db, (key, pairs[key]))
            if key == owner:
                assert found == ["owner"]
            else:
                assert found in ([], None)  # its own tables, or refused
            assert _holder(db) in (None, owner)

        _replay(
            monkeypatch,
            db,
            writer=writer,
            bound_before=bound_before,
            ran_067=ran_067,
            bound_on_067=bound_on_067,
            after=after,
            check=check,
        )
        assert _holder(db) == owner


@_examples
@_histories
def test_by_default_no_store_moves_without_the_operator(
    monkeypatch: pytest.MonkeyPatch,
    *,
    writer: str,
    bound_before: set[str],
    ran_067: bool,
    bound_on_067: set[str],
    after: list[tuple[str, str]],
) -> None:
    """With the default ``migrate_legacy_stores``, under any order of
    authentications, starts and requests, no pair gets the legacy tables
    and none opens tables of its own beside them, until the operator
    migrates the store; then exactly the pair named gets them."""
    pairs = dict(_PAIRS)
    with tempfile.TemporaryDirectory() as directory:
        db = sqlite_db(Path(directory) / "log.db")

        def check(key: str) -> None:
            assert _read_or_refused(db, (key, pairs[key])) is None
            assert _holder(db) is None

        _replay(
            monkeypatch,
            db,
            writer=writer,
            bound_before=bound_before,
            ran_067=ran_067,
            bound_on_067=bound_on_067,
            after=after,
            check=check,
        )
        others = sorted(k for k in pairs if k != writer)
        confirmed = db.migrate((writer, pairs[writer]), others, without_binding=True)
        if isinstance(confirmed, fx.Failure):  # its key was bound: name the bound ones
            evidence = [k for k in others if k in bound_before or (ran_067 and k in bound_on_067)]
            db.migrate((writer, pairs[writer]), evidence)
        assert _holder(db) == writer
        for key, store_id in pairs.items():
            assert _read_or_refused(db, (key, store_id)) == (["owner"] if key == writer else [])
