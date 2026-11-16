"""What the database showed when 0.6.8 or later first opened it: the only
evidence the server lets move a store's 0.6.5 tables by itself.

A session auth binding is made the first time a key authenticates, by
whoever presents it. One made after the upgrade shows only that someone
authenticated since, so it can neither claim a legacy store nor make one
ambiguous. The first start copies the bound keys into
``<prefix>_legacy_bindings`` and writes the one row of
``<prefix>_legacy_upgrade`` in the same transaction.

0.6.6 and 0.6.7 changed the tables' names too, and kept no such record,
so on a database either of them opened (its ``<prefix>_scope_aliases``
exists) the copied bindings may postdate that upgrade: ``automatic`` is
then false, and every legacy store waits for the operator. This version
creates the aliases table only after its record is written, so the check
cannot see a table it made itself.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from pyfect._core import Effect
from pyfect.effect import gen
from pyfect.eventlog._sql_server_encrypted.db import CHUNK, Db
from pyfect.eventlog._sql_server_encrypted.tables import (
    create_065_tables,
    create_alias_tables,
    create_upgrade_tables,
)
from pyfect.persistence._columns import column_int, column_text
from pyfect.persistence._sql_keys import key_equals
from pyfect.sql.client import SqlClientService
from pyfect.sql.error import SqlError
from pyfect.sql.statement import Identifier


@dataclass(frozen=True, slots=True)
class Evidence:
    """The bindings of some keys: ``before`` the upgrade (in the record) and
    ``now``; ``automatic``: the record predates every other upgrade, so the
    server may act on it by itself."""

    before: frozenset[str]
    now: frozenset[str]
    automatic: bool


def _table_exists(sql: SqlClientService, name: str) -> Effect[bool, SqlError]:
    def pg():
        # to_regclass folds unquoted names to lowercase, so pass the quoted name.
        quoted = sql("{}", sql.identifier(name)).compile(True)[0]
        return sql("SELECT 1 AS found FROM pg_class WHERE oid = to_regclass({})", quoted)

    query = sql.on_dialect_or_else(
        pg=pg,
        mysql=lambda: sql(
            "SELECT 1 AS found FROM information_schema.tables "
            "WHERE table_schema = DATABASE() AND LOWER(table_name) = LOWER({})",
            name,
        ),
        mssql=lambda: sql("SELECT 1 AS found WHERE OBJECT_ID({}, N'U') IS NOT NULL", name),
        or_else=lambda: sql(
            "SELECT 1 AS found FROM sqlite_master WHERE type = 'table' AND name = {}", name
        ),
    )
    return query.map(lambda rows: len(rows) > 0)


def _upgrade(db: Db) -> Identifier:
    return db.sql.identifier(f"{db.prefix}_legacy_upgrade")


def _snapshot(db: Db) -> Identifier:
    return db.sql.identifier(f"{db.prefix}_legacy_bindings")


def _record(db: Db) -> Effect[None, SqlError]:
    """Writes the record unless a start wrote it. The marker row is
    inserted first: a concurrent start waits on it, finds it taken, and
    copies nothing."""
    sql = db.sql

    def take():
        ran_066 = yield from _table_exists(sql, f"{db.prefix}_scope_aliases")
        inserted = yield from db.insert_new(
            _upgrade(db), [{"id": 1, "automatic": 0 if ran_066 else 1}], ["id"]
        )
        if inserted == 0:
            return
        yield from sql(
            "INSERT INTO {} (public_key) SELECT public_key FROM {}", _snapshot(db), db.bindings
        )

    def body():
        if (yield from sql("SELECT id FROM {}", _upgrade(db))):
            return
        yield from sql.with_transaction(gen(take))

    return gen(body)


def prepare(db: Db, remote_id_table: str) -> Effect[None, SqlError]:
    """Creates the global tables, writing the record of the upgrade before
    the aliases table exists."""
    sql = db.sql

    def body():
        yield from create_065_tables(sql, db.prefix, remote_id_table)
        yield from create_upgrade_tables(sql, db.prefix)
        yield from _record(db)
        yield from create_alias_tables(sql, db.prefix)

    return gen(body)


def automatic(db: Db) -> Effect[bool, SqlError]:
    return db.sql("SELECT automatic FROM {}", _upgrade(db)).map(
        lambda rows: bool(rows) and column_int(rows[0]["automatic"]) == 1
    )


def _bound(db: Db, table: Identifier, keys: list[str]) -> Effect[frozenset[str], SqlError]:
    """Which of ``keys`` ``table`` holds, compared exactly."""
    sql = db.sql

    def body():
        found: set[str] = set()
        for start in range(0, len(keys), CHUNK):
            chunk = keys[start : start + CHUNK]
            rows = yield from sql(
                "SELECT public_key FROM {} WHERE {}",
                table,
                sql.join(" OR ", False)([key_equals(sql, "public_key", k) for k in chunk]),
            )
            found.update(column_text(row["public_key"]) for row in rows)
        # Keep exact matches only, whatever the column's collation.
        return frozenset(found.intersection(keys))

    return gen(body)


def evidence(db: Db, keys: Iterable[str]) -> Effect[Evidence, SqlError]:
    """The bindings of ``keys`` before the upgrade and now."""
    keys = sorted(set(keys))

    def body():
        before = yield from _bound(db, _snapshot(db), keys)
        now = yield from _bound(db, db.bindings, keys)
        return Evidence(before, now, (yield from automatic(db)))

    return gen(body)


def all_evidence(db: Db) -> Effect[Evidence, SqlError]:
    """The bindings of every key, for listing many stores."""
    sql = db.sql

    def keys(table: Identifier) -> Effect[frozenset[str], SqlError]:
        return sql("SELECT public_key FROM {}", table).map(
            lambda rows: frozenset(column_text(row["public_key"]) for row in rows)
        )

    def body():
        before = yield from keys(_snapshot(db))
        now = yield from keys(db.bindings)
        return Evidence(before, now, (yield from automatic(db)))

    return gen(body)


__all__ = ["Evidence", "all_evidence", "automatic", "evidence", "prepare"]
