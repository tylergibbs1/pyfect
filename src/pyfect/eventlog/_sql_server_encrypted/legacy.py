"""Which tables hold a store, and the stores 0.6.5 and earlier named ambiguously.

Up to 0.6.5 a (public key, store id) pair named its tables by
``publicKey/storeId`` (as Effect does), which two pairs can share when the
text has more than one ``/``: ``("a/b", "c")`` and ``("a", "b/c")``. Text
with exactly one ``/`` splits back to one pair, so such a pair keeps that
key and its tables. Every other pair has a key that holds no ``/``.

The tables a legacy key named may hold either pair's batches, and the
server cannot read them. What shows who wrote them is a session auth
binding made before the upgrade (``upgrade.py``): a key that wrote through
a server had authenticated. When exactly one key splitting the legacy text
had one, its pair gets the tables (by a row of ``<prefix>_scope_aliases``,
one pair at most) and every other pair opens its own. Otherwise every pair
with a binding from before, or every pair when none had one, does not open
(``LegacyStoreNeedsMigration``) until the operator decides with
``migrate_legacy_store``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Never

from pyfect import schema as S
from pyfect._core import Effect
from pyfect._json_text import quote
from pyfect._text_keys import key_bytes
from pyfect.crypto.digest import Digest, DigestService, sha256
from pyfect.effect import fail, gen
from pyfect.eventlog._server_encrypted.models import make_compaction_config
from pyfect.eventlog._sql_server_encrypted import upgrade
from pyfect.eventlog._sql_server_encrypted.db import Db
from pyfect.eventlog._sql_server_encrypted.upgrade import Evidence
from pyfect.eventlog._store_unavailable import StoreUnavailable
from pyfect.persistence._columns import column_int, column_text
from pyfect.sql.client import SqlClient, SqlClientService
from pyfect.sql.error import SqlError

UPGRADE_NOTES = "https://pyfect.dev/docs/eventlog-upgrade"


class LegacyStoreNeedsMigration(S.TaggedError, StoreUnavailable, tag="LegacyStoreNeedsMigration"):
    """The store's tables from 0.6.5 or earlier hold batches, and the
    bindings from before the upgrade do not show that this store alone
    wrote them. ``authenticated``: its key had a binding before the upgrade;
    ``other_keys``: the other keys splitting the same legacy name that had
    one; ``automatic``: false when 0.6.6 or 0.6.7 opened the database first,
    so the server migrates nothing by itself."""

    public_key: str = S.field(S.String, key="publicKey")
    store_id: str = S.field(S.String, key="storeId")
    authenticated: bool = S.field(S.Boolean, default=False)
    other_keys: tuple[str, ...] = S.field(S.Array(S.String), default=(), key="otherKeys")
    automatic: bool = S.field(S.Boolean, default=True)

    @property
    def message(self) -> str:
        legacy = legacy_key(self.public_key, self.store_id)
        others = ", ".join(repr(key) for key in self.other_keys)
        if self.authenticated and others:
            why = (
                f"that this store or the store of {others} may have written: each key had "
                "authenticated before the upgrade. Find out which wrote them before migrating them"
            )
        elif self.authenticated:
            why = (
                "that only this store's key, among those sharing that name, had authenticated "
                "when pyfect 0.6.8 first started. pyfect 0.6.6 or 0.6.7 ran on this database "
                "before, so that binding may be newer than the upgrade, and the server moves "
                "nothing by itself. Migrate them once you know this store wrote them"
            )
        elif others:
            why = (
                f"that the store of {others} may have written, and this store's key had not "
                "authenticated before the upgrade. Do not migrate them to it unless you know it "
                "wrote them"
            )
        else:
            why = (
                "and no key sharing that name had authenticated before the upgrade, so nothing "
                "shows who wrote them. Do not migrate them to this store unless you know it did"
            )
        return (
            f"Store {self.store_id!r} of {self.public_key!r} does not open: the tables pyfect "
            f"0.6.5 named {legacy!r} hold batches {why} (see {UPGRADE_NOTES})"
        )

    @property
    def client_message(self) -> str:
        return (
            "This store holds data from before the server's upgrade from pyfect 0.6.5, "
            "which the server's operator must migrate"
        )


class LegacyStoreMigrationError(S.TaggedError, tag="LegacyStoreMigrationError"):
    """``migrate_legacy_store`` refused: nothing from before the upgrade
    shows the pair wrote the legacy tables and the call did not override
    that, other identities may have, the tables went to another pair, or
    the store already holds batches under its new key."""

    message: str = S.field(S.String)


def legacy_key(public_key: str, store_id: str) -> str:
    return f"{public_key}/{store_id}"


def scope_key(public_key: str, store_id: str) -> str:
    """The key naming the pair's tables: the legacy key when it splits back
    to this pair alone (one ``/``), else JSON with no ``/`` in it."""
    legacy = legacy_key(public_key, store_id)
    if legacy.count("/") == 1:
        return legacy
    pair = f"[{quote(public_key)},{quote(store_id)}]"
    return "\0" + pair.replace("/", "\\u002f")


def aliases_table(prefix: str) -> str:
    return f"{prefix}_scope_aliases"


def _scope(digest: DigestService, key: str) -> Effect[str]:
    return digest.digest_hex(sha256, key_bytes(key)).map(lambda hex: hex[:16])


def scope_of(digest: DigestService, key: str) -> Effect[str]:
    """The scope (table name hash) of a scope key or legacy key."""
    return _scope(digest, key)


def has_batches(db: Db, scope: str) -> Effect[bool, SqlError]:
    """Whether the store ``scope`` was opened and has stored a batch (its
    row's next sequence survives pruning). Every version creates the row
    on a store's first open."""

    def body():
        rows = yield from db.sql("SELECT next_sequence FROM {} WHERE scope = {}", db.stores, scope)
        if not rows:
            return False
        if column_int(rows[0]["next_sequence"]) > 1:
            return True
        return (yield from db.max_last_sequence(db.scope_tables(scope).table)) > 0

    return gen(body)


def holder(db: Db, legacy_scope: str) -> Effect[str | None, SqlError]:
    """The scope of the pair given the legacy tables, if one was."""
    return db.sql("SELECT scope FROM {} WHERE legacy_scope = {}", db.aliases, legacy_scope).map(
        lambda rows: column_text(rows[0]["scope"]) if rows else None
    )


def split_keys(legacy: str) -> list[str]:
    """The public key of every pair whose legacy key is ``legacy``."""
    return [legacy[:i] for i, c in enumerate(legacy) if c == "/"]


def store_of(legacy: str, public_key: str) -> str:
    """The store id that pairs with ``public_key``, a split of ``legacy``."""
    return legacy[len(public_key) + 1 :]


type Standing = Literal["pending", "unconfirmed", "ambiguous", "unbound"]
"""Where a pair stands on legacy tables no pair has, by the bindings from
before the upgrade: ``pending``, its key alone had one and the server gives
it the tables; ``unconfirmed``, likewise, but the record may postdate an
earlier upgrade (``Evidence.automatic``), so the operator does; ``ambiguous``,
other keys had one too; ``unbound``, its key had none."""


def others_before(public_key: str, store_id: str, evidence: Evidence) -> tuple[str, ...]:
    """The other keys splitting the pair's legacy key bound before the upgrade."""
    keys = split_keys(legacy_key(public_key, store_id))
    return tuple(sorted(k for k in keys if k != public_key and k in evidence.before))


def standing(public_key: str, store_id: str, evidence: Evidence) -> Standing:
    if public_key not in evidence.before:
        return "unbound"
    if others_before(public_key, store_id, evidence):
        return "ambiguous"
    return "pending" if evidence.automatic else "unconfirmed"


def _evidence(db: Db, legacy: str) -> Effect[Evidence, SqlError]:
    return upgrade.evidence(db, split_keys(legacy))


def holder_pair(digest: DigestService, legacy: str, given: str) -> Effect[tuple[str, str] | None]:
    """The pair sharing ``legacy`` whose scope is ``given``."""

    def body():
        for key in split_keys(legacy):
            store_id = store_of(legacy, key)
            if (yield from _scope(digest, scope_key(key, store_id))) == given:
                return (key, store_id)
        return None

    return gen(body)


def _give(db: Db, legacy_scope: str, scope: str, origin: str) -> Effect[bool, SqlError]:
    """Gives ``scope`` the legacy tables unless another pair has them;
    whether ``scope`` has them now."""

    def body():
        inserted = yield from db.insert_new(
            db.aliases, [{"legacy_scope": legacy_scope, "scope": scope}], ["legacy_scope"]
        )
        if inserted:
            yield from db.insert_new(
                db.alias_origins,
                [{"legacy_scope": legacy_scope, "origin": origin}],
                ["legacy_scope"],
            )
        return (yield from holder(db, legacy_scope)) == scope

    return db.sql.with_transaction(gen(body))


@dataclass(frozen=True, slots=True)
class Resolved:
    """The scope holding a pair's store. ``migrated``: it was just given its
    legacy tables. ``split``: its legacy tables hold batches too, which a
    0.6.5 node wrote after the store opened under its new key."""

    scope: str
    event: Literal["migrated", "split"] | None = None


def _unclaimed(
    db: Db, public_key: str, store_id: str, scope: str, legacy_scope: str
) -> Effect[Resolved, SqlError | LegacyStoreNeedsMigration]:
    """The scope of a pair whose legacy tables hold batches no pair has."""

    def body():
        evidence = yield from _evidence(db, legacy_key(public_key, store_id))
        stand = standing(public_key, store_id, evidence)
        others = others_before(public_key, store_id, evidence)
        if (yield from has_batches(db, scope)):
            return Resolved(scope, "split" if stand in ("pending", "unconfirmed") else None)
        if stand == "pending":
            given = yield from _give(db, legacy_scope, scope, "server")
            return Resolved(legacy_scope, "migrated") if given else Resolved(scope)
        if stand == "unbound" and others and evidence.automatic:
            # Only keys bound before the upgrade can have written them.
            return Resolved(scope)
        return (
            yield from fail(
                LegacyStoreNeedsMigration(
                    public_key=public_key,
                    store_id=store_id,
                    authenticated=stand != "unbound",
                    other_keys=others,
                    automatic=evidence.automatic,
                )
            )
        )

    return gen(body)


def resolve_scope(
    db: Db, digest: DigestService, public_key: str, store_id: str
) -> Effect[Resolved, SqlError | LegacyStoreNeedsMigration]:
    """The scope whose tables hold the pair's store, giving it its legacy
    tables when the bindings from before the upgrade show it alone wrote
    them."""

    def body():
        key = scope_key(public_key, store_id)
        scope = yield from _scope(digest, key)
        legacy = legacy_key(public_key, store_id)
        if key == legacy:
            return Resolved(scope)
        legacy_scope = yield from _scope(digest, legacy)
        given = yield from holder(db, legacy_scope)
        if given is not None:
            return Resolved(legacy_scope if given == scope else scope)
        if not (yield from has_batches(db, legacy_scope)):
            return Resolved(scope)
        return (yield from _unclaimed(db, public_key, store_id, scope, legacy_scope))

    return gen(body)


@dataclass(frozen=True, slots=True)
class Confirmation:
    """What the operator confirmed in ``migrate_legacy_store``."""

    not_written_by: tuple[str, ...]
    without_binding: bool
    taken_from: tuple[str, str] | None


def _bound_refusal(
    public_key: str, store_id: str, evidence: Evidence, confirmation: Confirmation
) -> str | None:
    """Why a pair whose key was bound before the upgrade may not have them."""
    legacy = legacy_key(public_key, store_id)
    if confirmation.without_binding:
        return f"{public_key!r} had authenticated before the upgrade: drop without_binding"
    others = list(others_before(public_key, store_id, evidence))
    if sorted(set(confirmation.not_written_by)) == others:
        return None
    if not others:
        return (
            "No other identity that had authenticated before the upgrade shares the name "
            f"{legacy!r}: call it without not_written_by"
        )
    return (
        f"Other identities that had authenticated before the upgrade share the name {legacy!r} "
        f"and may have written its tables: {others!r}. If you have confirmed that none of them "
        f"did, pass not_written_by={others!r}"
    )


def _unbound_refusal(
    public_key: str, store_id: str, evidence: Evidence, confirmation: Confirmation
) -> str | None:
    """Why a pair whose key was not bound before the upgrade may not have
    them: only the operator's override, naming every other pair, gives them."""
    legacy = legacy_key(public_key, store_id)
    every_other = sorted(k for k in split_keys(legacy) if k != public_key)
    if not confirmation.without_binding:
        since = " (it authenticated only since)" if public_key in evidence.now else ""
        return (
            f"{public_key!r} had no session auth binding before the upgrade{since}, so nothing "
            f"shows that its store {store_id!r} wrote the tables named {legacy!r}. If you know it "
            f"did, pass without_binding=True and not_written_by={every_other!r}"
        )
    if sorted(set(confirmation.not_written_by)) != every_other:
        return (
            f"With without_binding, name every other identity sharing {legacy!r}, having "
            f"confirmed that none of them wrote its tables: not_written_by={every_other!r}"
        )
    return None


def _taken_refusal(
    legacy: str, taken: tuple[str, str] | None, confirmation: Confirmation
) -> str | None:
    """Why the call may not take the tables from the pair that has them."""
    if taken == confirmation.taken_from:
        return None
    if taken is None:
        return f"The tables of {legacy!r} were not given to another store: drop taken_from"
    return (
        f"The tables of {legacy!r} were given to store {taken[1]!r} of {taken[0]!r}. If you have "
        f"confirmed that it did not write them, pass taken_from={taken!r}; that store then opens "
        "tables of its own, and the batches it wrote since go with these"
    )


def migrate_legacy_store(
    db: Db,
    digest: DigestService,
    public_key: str,
    store_id: str,
    confirmation: Confirmation,
) -> Effect[bool, SqlError | LegacyStoreMigrationError]:
    """Gives the pair its tables from 0.6.5 or earlier; whether it has them
    now (``False``: it has none, or never needed a new key)."""
    sql = db.sql

    def refuse(message: str) -> Effect[Never, LegacyStoreMigrationError]:
        return fail(LegacyStoreMigrationError(message=f"{message} (see {UPGRADE_NOTES})"))

    def body():
        key = scope_key(public_key, store_id)
        legacy = legacy_key(public_key, store_id)
        if key == legacy:
            return False
        scope = yield from _scope(digest, key)
        legacy_scope = yield from _scope(digest, legacy)
        given = yield from holder(db, legacy_scope)
        if given == scope:
            return True
        taken = None if given is None else (yield from holder_pair(digest, legacy, given))
        refusal = _taken_refusal(legacy, taken, confirmation)
        if refusal is None and not (yield from has_batches(db, legacy_scope)):
            return False
        if refusal is None:
            evidence = yield from _evidence(db, legacy)
            check = _bound_refusal if public_key in evidence.before else _unbound_refusal
            refusal = check(public_key, store_id, evidence, confirmation)
        if refusal is None and (yield from has_batches(db, scope)):
            refusal = (
                f"Store {store_id!r} of {public_key!r} already holds batches of its own, so a "
                f"pyfect 0.6.5 node wrote the tables named {legacy!r} after the store opened on a "
                "newer version; the two cannot be merged"
            )
        if refusal is not None:
            return (yield from refuse(refusal))
        for table in (db.aliases, db.alias_origins):
            yield from sql("DELETE FROM {} WHERE legacy_scope = {}", table, legacy_scope)
        yield from sql(
            "INSERT INTO {} (legacy_scope, scope) VALUES ({}, {})",
            db.aliases,
            legacy_scope,
            scope,
        )
        yield from sql(
            "INSERT INTO {} (legacy_scope, origin) VALUES ({}, {})",
            db.alias_origins,
            legacy_scope,
            "operator",
        )
        return True

    return sql.with_transaction(gen(body))


def with_db[A, E](
    entry_table_prefix: str, remote_id_table: str, f: Callable[[Db, DigestService], Effect[A, E]]
) -> Effect[A, E | SqlError, SqlClient | Digest]:
    """Runs ``f`` on the storage's tables, outside a server."""

    def body():
        digest = yield from Digest()
        sql: SqlClientService = (yield from SqlClient()).without_transforms()
        config = yield from make_compaction_config()
        db = Db(sql, entry_table_prefix, config)
        yield from upgrade.prepare(db, remote_id_table)
        return (yield from f(db, digest))

    return gen(body)


__all__ = [
    "UPGRADE_NOTES",
    "Confirmation",
    "LegacyStoreMigrationError",
    "LegacyStoreNeedsMigration",
    "Resolved",
    "Standing",
    "aliases_table",
    "has_batches",
    "holder",
    "holder_pair",
    "legacy_key",
    "migrate_legacy_store",
    "others_before",
    "resolve_scope",
    "scope_key",
    "scope_of",
    "split_keys",
    "standing",
    "store_of",
    "with_db",
]
