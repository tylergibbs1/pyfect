"""The SQL encrypted event log server keeps every (public key, store id)
pair in its own scope, and stores written by 0.6.5 upgrade without losing
data: a pair whose 0.6.5 key (``publicKey/storeId``) splits back to it
alone keeps its tables; any other pair with 0.6.5 batches gets them once
the bindings show it wrote them, never opening empty
(``tests/oracle/test_sql_event_log_legacy_stores.py`` covers who gets
them)."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from oracle._legacy_eventlog import Earlier

import pyfect as fx
from pyfect import layer
from pyfect.eventlog import event_log_server_encrypted, sql_event_log_server_encrypted
from pyfect.eventlog._sql_server_encrypted import legacy
from pyfect.eventlog.event_journal import StoreId, make_entry_id_unsafe
from pyfect.eventlog.event_log_encryption import EncryptedBatch
from pyfect.eventlog.event_log_server_encrypted import Storage
from pyfect.eventlog.sql_event_log_server_encrypted import (
    LegacyStoreMigrationError,
    LegacyStoreNeedsMigration,
    migrate_legacy_store,
)
from pyfect.layer import Layer
from pyfect.sql import sqlite

PAIRS = [
    ("victim", "notes/2024"),
    ("victim/notes", "2024"),
    ("a/b", "c"),
    ("a", "b/c"),
    ("a/b/c", ""),
    ("", "a/b/c"),
    ("pk", "store"),
]


def test_scope_keys_are_injective() -> None:
    keys = [legacy.scope_key(public_key, store_id) for public_key, store_id in PAIRS]
    assert len(set(keys)) == len(keys)


def test_a_pair_whose_legacy_key_splits_back_to_it_alone_keeps_its_key() -> None:
    # Tables are named from this key: such stores keep theirs.
    uuid = "0b0d2f6e-5d1e-4c4f-9d43-3b0b7b0c9a10"
    assert legacy.scope_key(uuid, "notes") == f"{uuid}/notes"
    table = hashlib.sha256(b"pk/store").hexdigest()[:16]
    assert hashlib.sha256(legacy.scope_key("pk", "store").encode()).hexdigest()[:16] == table
    for public_key, store_id in PAIRS:
        key = legacy.scope_key(public_key, store_id)
        assert ("/" not in key) == (f"{public_key}/{store_id}".count("/") != 1)


def _batch() -> EncryptedBatch:
    return EncryptedBatch(
        entry_ids=(make_entry_id_unsafe(),), iv=bytes(12), encrypted_batch=b"x" * 32
    )


def _sql(path: Path) -> Layer[Storage, Any, Any]:
    client = sqlite.layer(sqlite.SqliteClientConfig(filename=str(path)))
    return sql_event_log_server_encrypted.layer_storage_subtle().pipe(layer.provide(client))


def _run(path: Path, body: Any) -> Any:
    return fx.run_blocking(fx.scoped(fx.gen(body)).pipe(fx.provide(_sql(path))).or_die())


def _migrate(
    path: Path,
    public_key: str,
    store_id: str,
    not_written_by: tuple[str, ...] | list[str] = (),
    *,
    without_binding: bool = False,
) -> fx.Effect[bool, Any]:
    from pyfect.crypto.digest import layer_web_crypto

    client = sqlite.layer(sqlite.SqliteClientConfig(filename=str(path)))
    return (
        migrate_legacy_store(
            public_key, store_id, not_written_by=not_written_by, without_binding=without_binding
        )
        .pipe(fx.provide(layer_web_crypto))
        .pipe(fx.provide(client))
    )


def _write(
    path: Path,
    monkeypatch: pytest.MonkeyPatch,
    pairs: list[tuple[str, str]],
    *,
    authenticated: bool = True,
) -> dict[Any, Any]:
    """Write one batch per pair as 0.6.5 did, authenticating each key first
    as its server did (unless not ``authenticated``: written straight
    through the storage); their entry ids."""
    written: dict[Any, Any] = {}
    with Earlier(monkeypatch, "0.6.5"):

        def body():
            storage = yield from Storage()
            for pair in pairs:
                if authenticated:
                    yield from storage.get_or_create_session_auth_binding(pair[0], bytes(32))
                batch = _batch()
                yield from storage.write(pair[0], StoreId(pair[1]), [batch])
                written[pair] = batch.entry_ids

        _run(path, body)
    return written


def _read(path: Path, public_key: str, store_id: str) -> tuple[int | None, int]:
    def body():
        storage = yield from Storage()
        latest = yield from storage.latest_sequence(public_key, StoreId(store_id))
        if latest is None:
            return latest, 0
        # ``changes`` stays open for live batches: take the stored ones.
        batches = (
            yield from storage.changes(public_key, StoreId(store_id), 1).take(latest).run_collect()
        )
        return latest, len(batches)

    return _run(path, body)


def test_a_store_whose_key_splits_back_to_it_reads_its_0_6_5_data(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "log.db"
    _write(db, monkeypatch, [("pk", "store"), ("0b0d2f6e", "notes")])
    assert _read(db, "pk", "store") == (1, 1)
    assert _read(db, "0b0d2f6e", "notes") == (1, 1)


def _bind(path: Path, public_key: str) -> None:
    """Authenticates ``public_key`` once, as a server does."""

    def body():
        storage = yield from Storage()
        yield from storage.get_or_create_session_auth_binding(public_key, bytes(32))

    _run(path, body)


@pytest.mark.parametrize(
    ("pair", "other"), [(("ab/cd+ef==", "notes"), "ab"), (("victim", "notes/2024"), "victim/notes")]
)
def test_a_store_with_ambiguous_0_6_5_data_does_not_open_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, pair: tuple[str, str], other: str
) -> None:
    db = tmp_path / "log.db"
    written = _write(db, monkeypatch, [pair], authenticated=False)
    # Nothing shows who wrote them, even once the key authenticates.
    _bind(db, pair[0])
    with pytest.raises(LegacyStoreNeedsMigration) as raised:
        _read(db, *pair)
    assert "no key sharing that name had authenticated" in raised.value.message
    assert fx.run_blocking(_migrate(db, *pair, [other], without_binding=True)) is True
    assert _read(db, *pair) == (1, 1)
    assert fx.run_blocking(_migrate(db, *pair)) is True  # done already; a no-op

    def acks():
        storage = yield from Storage()
        return (yield from storage.entry_sequences(pair[0], StoreId(pair[1]), written[pair]))

    assert len(_run(db, acks)) == 1


def test_only_one_pair_can_claim_shared_0_6_5_tables(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "log.db"
    owner, other = ("a/b", "c"), ("a", "b/c")
    _write(db, monkeypatch, [owner])
    assert fx.run_blocking(_migrate(db, *owner)) is True
    _bind(db, other[0])
    with pytest.raises(LegacyStoreMigrationError):
        fx.run_blocking(_migrate(db, *other, not_written_by=[owner[0]]))
    # The other pair now opens a store of its own, apart from the owner's.
    assert _read(db, *other) == (None, 0)
    assert _read(db, *owner) == (1, 1)


def test_a_store_with_no_0_6_5_data_opens_and_needs_no_migration(tmp_path: Path) -> None:
    db = tmp_path / "log.db"
    assert _read(db, "ab/cd", "notes") == (None, 0)
    assert fx.run_blocking(_migrate(db, "ab/cd", "notes")) is False


@fx.fn
def _program():
    storage = yield from Storage()
    batch = _batch()
    yield from storage.write("victim", StoreId("notes/2024"), [batch])
    victim = yield from storage.latest_sequence("victim", StoreId("notes/2024"))
    other = yield from storage.latest_sequence("victim/notes", StoreId("2024"))
    seen = yield from storage.entry_sequences("victim/notes", StoreId("2024"), batch.entry_ids)
    return victim, other, len(seen)


@pytest.mark.parametrize("storage", ["sql", "memory"])
def test_pairs_joining_to_one_string_stay_apart(storage: str) -> None:
    provided: Layer[Any, Any, Any] = (
        sql_event_log_server_encrypted.layer_storage_subtle().pipe(
            layer.provide(sqlite.layer(sqlite.SqliteClientConfig(filename=":memory:")))
        )
        if storage == "sql"
        else event_log_server_encrypted.layer_storage_memory
    )
    program = fx.scoped(_program()).pipe(fx.provide(provided)).or_die()
    result: tuple[int | None, int | None, int] = fx.run_blocking(program)
    victim, other, seen = result
    assert victim is not None
    assert other is None
    assert seen == 0


# A lone surrogate (a client can send ``"\ud800"`` in JSON) and U+FFFD in its
# place: UTF-8 with replacement would give both pairs the same bytes.
SURROGATE_PAIRS = [
    (("victim", "notes\ufffd"), ("victim", "notes\ud800")),
    (("victim\ufffd", "notes"), ("victim\ud800", "notes")),
    (("a\ufffd/b", "c/d"), ("a\ud800/b", "c/d")),
]


@pytest.mark.parametrize("storage", ["sql", "memory"])
@pytest.mark.parametrize(("victim", "other"), SURROGATE_PAIRS)
def test_a_lone_surrogate_and_its_replacement_name_different_stores(
    storage: str, victim: tuple[str, str], other: tuple[str, str]
) -> None:
    provided: Layer[Any, Any, Any] = (
        sql_event_log_server_encrypted.layer_storage_subtle().pipe(
            layer.provide(sqlite.layer(sqlite.SqliteClientConfig(filename=":memory:")))
        )
        if storage == "sql"
        else event_log_server_encrypted.layer_storage_memory
    )

    @fx.fn
    def program():
        storage = yield from Storage()
        batch = _batch()
        yield from storage.write(victim[0], StoreId(victim[1]), [batch])
        seen = yield from storage.latest_sequence(other[0], StoreId(other[1]))
        acked = yield from storage.entry_sequences(other[0], StoreId(other[1]), batch.entry_ids)
        return seen, len(acked)

    assert fx.run_blocking(fx.scoped(program()).pipe(fx.provide(provided)).or_die()) == (None, 0)


def test_a_lone_surrogate_pair_gets_no_0_6_5_tables_of_its_replacement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    db = tmp_path / "log.db"
    victim, other = ("a\ufffd/b", "c"), ("a\ud800/b", "c")
    _write(db, monkeypatch, [victim])  # the victim authenticated, as a real server records
    assert fx.run_blocking(_migrate(db, *other)) is False  # no 0.6.5 tables are its
    assert _read(db, *other) == (None, 0)
    assert fx.run_blocking(_migrate(db, *victim)) is True
    assert _read(db, *victim) == (1, 1)
