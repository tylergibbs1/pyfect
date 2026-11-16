"""Which tables hold a store, and the stores 0.6.5 and earlier named ambiguously.

Up to 0.6.5 a (public key, store id) pair named its tables by
``publicKey/storeId`` (as Effect does), which two pairs can share when the
text has more than one ``/``: ``("a/b", "c")`` and ``("a", "b/c")``. Text
with exactly one ``/`` splits back to one pair, so such a pair keeps that
key and its tables. Every other pair has a key that holds no ``/``.

The tables a legacy key named may hold either pair's batches, and the
server cannot read them. A pair gets them by a row of
``<prefix>_scope_aliases`` (one pair at most), which the operator makes
(``migrate.py``). The server makes one by itself only when the storage
says every 0.6.5 write went through a server (``LegacyMigration``): then a
key that wrote had authenticated, and when exactly one key splitting the
legacy text had a session auth binding before the upgrade (``upgrade.py``),
its pair gets them. A store written straight through the storage has no
binding, so without that promise every pair of the name waits for the
operator (``LegacyStoreNeedsMigration``).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, Never
from warnings import deprecated

from pyfect import schema as S
from pyfect._core import Effect
from pyfect._json_text import quote
from pyfect._text_keys import key_bytes
from pyfect.crypto.digest import Digest, DigestService, sha256
from pyfect.effect import fail, gen, succeed
from pyfect.eventlog._server_encrypted.models import make_compaction_config
from pyfect.eventlog._sql_server_encrypted import upgrade
from pyfect.eventlog._sql_server_encrypted.db import Db
from pyfect.eventlog._sql_server_encrypted.tables import create_alias_tables
from pyfect.eventlog._sql_server_encrypted.upgrade import Evidence
from pyfect.eventlog._store_unavailable import StoreUnavailable
from pyfect.persistence._columns import column_int, column_text
from pyfect.sql.client import SqlClient, SqlClientService
from pyfect.sql.error import SqlError

UPGRADE_NOTES = "https://pyfect.dev/docs/eventlog-upgrade"

type LegacyMigration = Literal["never", "when_server_written"]
"""Whether the server gives a store its 0.6.5 tables by itself:
``"never"`` (every such store waits for ``migrate_legacy_store``), or
``"when_server_written"``, which promises that every write to the database
under 0.6.5 or earlier went through a server, none straight through the
storage."""

type Standing = Literal["pending", "unconfirmed", "ambiguous", "unbound"]
"""Where a pair stands on legacy tables no pair has, by the bindings from
before the upgrade: ``pending``, its key alone had one; ``unconfirmed``,
likewise, but the record may postdate an earlier upgrade
(``Evidence.automatic``); ``ambiguous``, other keys had one too;
``unbound``, its key had none."""


class LegacyStoreNeedsMigration(S.TaggedError, StoreUnavailable, tag="LegacyStoreNeedsMigration"):
    """The store's tables from 0.6.5 or earlier hold batches that no pair
    has, and the server does not give them away by itself. ``state`` is
    where the pair stands (``Standing``); ``other_keys``: the other keys
    splitting the same legacy name that had a binding before the upgrade."""

    public_key: str = S.field(S.String, key="publicKey")
    store_id: str = S.field(S.String, key="storeId")
    state: Standing = S.field(S.Literals("pending", "unconfirmed", "ambiguous", "unbound"))
    other_keys: tuple[str, ...] = S.field(S.Array(S.String), default=(), key="otherKeys")

    @property
    def authenticated(self) -> bool:
        """Whether its key had a binding before the upgrade."""
        return self.state != "unbound"

    @property
    @deprecated("LegacyStoreNeedsMigration.automatic is deprecated; read .state instead")
    def automatic(self) -> bool:
        """Deprecated since 0.6.9: whether the upgrade record predates every earlier
        upgrade, as in 0.6.8 (``state != "unconfirmed"``). The server no longer migrates
        by itself unless ``layer_storage(migrate_legacy_stores="when_server_written")``."""
        return self.state != "unconfirmed"

    @property
    def message(self) -> str:
        legacy = legacy_key(self.public_key, self.store_id)
        others = ", ".join(repr(key) for key in self.other_keys)
        match self.state:
            case "ambiguous":
                why = (
                    f"that this store or the store of {others} may have written: each key had "
                    "authenticated before the upgrade. Find out which wrote them before migrating "
                    "them"
                )
            case "pending":
                why = (
                    "and only this store's key, among those sharing that name, had authenticated "
                    "before the upgrade. A store written straight through the storage leaves no "
                    "binding, so the server moves nothing by itself unless layer_storage has "
                    "migrate_legacy_stores='when_server_written'. Migrate them once you know this "
                    "store wrote them"
                )
            case "unconfirmed":
                why = (
                    "that only this store's key, among those sharing that name, had authenticated "
                    "when pyfect 0.6.8 or later first started. pyfect 0.6.6 or 0.6.7 ran on this "
                    "database before, so that binding may be newer than the upgrade, and the "
                    "server moves nothing by itself. Migrate them once you know this store wrote "
                    "them"
                )
            case "unbound" if others:
                why = (
                    f"that the store of {others} may have written, as its key had authenticated "
                    "before the upgrade; this store's key had not, so it wrote them only if it "
                    "wrote straight through the storage. Find out which wrote them before "
                    "migrating them"
                )
            case "unbound":
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
    """``migrate_legacy_store`` refused: no server of 0.6.8 or later has
    started on the database yet, nothing from before the upgrade shows the
    pair wrote the legacy tables and the call did not override that, other
    identities may have, the tables went to another pair, or the store
    already holds batches under its new key."""

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


def scope_of(digest: DigestService, key: str) -> Effect[str]:
    """The scope (table name hash) of a scope key or legacy key."""
    return digest.digest_hex(sha256, key_bytes(key)).map(lambda hex: hex[:16])


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


def head(db: Db, scope: str) -> Effect[int, SqlError]:
    """The last sequence the opened store ``scope`` has given out."""

    def body():
        row = yield from db.select_store(scope)
        last = yield from db.max_last_sequence(db.scope_tables(scope).table)
        return max(row.next_sequence - 1, last)

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


def evidence_of(db: Db, legacy: str) -> Effect[Evidence, SqlError]:
    return upgrade.evidence(db, split_keys(legacy))


def holder_pair(digest: DigestService, legacy: str, given: str) -> Effect[tuple[str, str] | None]:
    """The pair sharing ``legacy`` whose scope is ``given``."""

    def body():
        for key in split_keys(legacy):
            store_id = store_of(legacy, key)
            if (yield from scope_of(digest, scope_key(key, store_id))) == given:
                return (key, store_id)
        return None

    return gen(body)


def record_alias(db: Db, legacy_scope: str, scope: str, origin: str) -> Effect[bool, SqlError]:
    """Gives ``scope`` the legacy tables unless another pair has them,
    recording who did and the legacy store's head, after which every batch
    is the holder's; whether ``scope`` has them now. Runs in the caller's
    transaction."""

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
            through = yield from head(db, legacy_scope)
            yield from db.insert_new(
                db.alias_bounds,
                [{"legacy_scope": legacy_scope, "through_sequence": through}],
                ["legacy_scope"],
            )
        return (yield from holder(db, legacy_scope)) == scope

    return gen(body)


@dataclass(frozen=True, slots=True)
class Resolved:
    """The scope holding a pair's store. ``migrated``: it was just given its
    legacy tables. ``split``: its legacy tables hold batches too, which a
    0.6.5 node wrote after the store opened under its new key. ``beside``:
    it opens tables of its own while its legacy tables hold batches another
    pair has or may get."""

    scope: str
    event: Literal["migrated", "split", "beside"] | None = None


def written_since(db: Db, legacy_scope: str, scope: str) -> Effect[bool, SqlError]:
    """Whether the legacy tables stored a batch in or after the hour the
    store's own tables first did (by the compaction buckets, whose newest
    hour per store survives the sweep)."""

    def hour(aggregate: Literal["MIN", "MAX"], of: str) -> Effect[int | None, SqlError]:
        return db.sql(
            "SELECT {}(bucket_hour) AS h FROM {} WHERE scope = {}",
            db.sql.literal(aggregate),
            db.buckets,
            of,
        ).map(lambda rows: None if not rows or rows[0]["h"] is None else column_int(rows[0]["h"]))

    def body():
        newest_legacy = yield from hour("MAX", legacy_scope)
        oldest_own = yield from hour("MIN", scope)
        return newest_legacy is not None and oldest_own is not None and newest_legacy >= oldest_own

    return gen(body)


def _unclaimed(
    db: Db,
    public_key: str,
    store_id: str,
    scope: str,
    legacy_scope: str,
    *,
    migration: LegacyMigration,
) -> Effect[Resolved, SqlError | LegacyStoreNeedsMigration]:
    """The scope of a pair whose legacy tables hold batches no pair has."""

    def body():
        evidence = yield from evidence_of(db, legacy_key(public_key, store_id))
        stand = standing(public_key, store_id, evidence)
        others = others_before(public_key, store_id, evidence)
        if (yield from has_batches(db, scope)):
            # Its own tables were written first: a 0.6.5 node wrote the legacy
            # ones after, when nothing else could have (its key alone was
            # bound) or the buckets show it.
            alone = stand in ("pending", "unconfirmed")
            if alone or (
                stand == "unbound"
                and not others
                and (yield from written_since(db, legacy_scope, scope))
            ):
                return Resolved(scope, "split")
            return Resolved(scope, "beside")
        automatic = migration == "when_server_written"
        if automatic and stand == "pending":
            given = yield from db.sql.with_transaction(
                record_alias(db, legacy_scope, scope, "server")
            )
            return Resolved(legacy_scope, "migrated") if given else Resolved(scope, "beside")
        if automatic and stand == "unbound" and others and evidence.automatic:
            # Only keys bound before the upgrade can have written them.
            return Resolved(scope, "beside")
        return (
            yield from fail(
                LegacyStoreNeedsMigration(
                    public_key=public_key, store_id=store_id, state=stand, other_keys=others
                )
            )
        )

    return gen(body)


def resolve_scope(
    db: Db, digest: DigestService, public_key: str, store_id: str, migration: LegacyMigration
) -> Effect[Resolved, SqlError | LegacyStoreNeedsMigration]:
    """The scope whose tables hold the pair's store, giving it its legacy
    tables when ``migration`` allows and the bindings from before the
    upgrade show it alone wrote them."""

    def body():
        key = scope_key(public_key, store_id)
        scope = yield from scope_of(digest, key)
        legacy = legacy_key(public_key, store_id)
        if key == legacy:
            return Resolved(scope)
        legacy_scope = yield from scope_of(digest, legacy)
        given = yield from holder(db, legacy_scope)
        if given is not None:
            return Resolved(legacy_scope) if given == scope else Resolved(scope, "beside")
        if not (yield from has_batches(db, legacy_scope)):
            return Resolved(scope)
        return (
            yield from _unclaimed(
                db, public_key, store_id, scope, legacy_scope, migration=migration
            )
        )

    return gen(body)


def still_resolves(
    db: Db, digest: DigestService, public_key: str, store_id: str, scope: str
) -> Effect[bool, SqlError]:
    """Whether the pair's store is still in ``scope``: the operator may have
    given its legacy tables to it, or taken them from it, since it opened."""
    key = scope_key(public_key, store_id)
    legacy = legacy_key(public_key, store_id)
    if key == legacy:
        return succeed(True)

    def body():
        own = yield from scope_of(digest, key)
        legacy_scope = yield from scope_of(digest, legacy)
        given = yield from holder(db, legacy_scope)
        return given == own if scope == legacy_scope else given != own

    return gen(body)


def _db(entry_table_prefix: str) -> Effect[tuple[Db, DigestService], Never, SqlClient | Digest]:
    def body():
        digest = yield from Digest()
        sql: SqlClientService = (yield from SqlClient()).without_transforms()
        config = yield from make_compaction_config()
        return Db(sql, entry_table_prefix, config), digest

    return gen(body)


def with_listing_db[A, E](
    entry_table_prefix: str, f: Callable[[Db, DigestService], Effect[A, E]]
) -> Effect[A, E, SqlClient | Digest]:
    """Runs ``f`` on the storage's tables, outside a server, creating and
    recording nothing."""
    return _db(entry_table_prefix).flat_map(lambda found: f(*found))


def with_operator_db[A, E](
    entry_table_prefix: str, f: Callable[[Db, DigestService], Effect[A, E]]
) -> Effect[A, E | SqlError | LegacyStoreMigrationError, SqlClient | Digest]:
    """Runs ``f`` on the storage's tables, outside a server, once a server
    of 0.6.8 or later has recorded the upgrade: only the server's first
    start may, so a call made while 0.6.5 serves does not count as one."""

    def body():
        db, digest = yield from _db(entry_table_prefix)
        if not (yield from upgrade.recorded(db)):
            return (
                yield from fail(
                    LegacyStoreMigrationError(
                        message=(
                            "No server of pyfect 0.6.8 or later has started on this database yet, "
                            "so nothing records which keys had authenticated before the upgrade. "
                            "Stop every node of an earlier version, start the upgraded server "
                            f"once, then migrate (see {UPGRADE_NOTES})"
                        )
                    )
                )
            )
        yield from create_alias_tables(db.sql, db.prefix)
        return (yield from f(db, digest))

    return gen(body)


__all__ = [
    "UPGRADE_NOTES",
    "LegacyMigration",
    "LegacyStoreMigrationError",
    "LegacyStoreNeedsMigration",
    "Resolved",
    "Standing",
    "aliases_table",
    "evidence_of",
    "has_batches",
    "head",
    "holder",
    "holder_pair",
    "legacy_key",
    "others_before",
    "record_alias",
    "resolve_scope",
    "scope_key",
    "scope_of",
    "split_keys",
    "standing",
    "still_resolves",
    "store_of",
    "with_listing_db",
    "with_operator_db",
    "written_since",
]
