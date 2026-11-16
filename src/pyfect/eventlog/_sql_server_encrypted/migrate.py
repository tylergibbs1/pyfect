"""The operator's migration of a store's 0.6.5 tables
(``sql_event_log_server_encrypted.migrate_legacy_store``).

The call names what the operator confirmed (``Confirmation``), and is
refused unless it matches what the bindings from before the upgrade show.
``taken_from`` takes the tables back from the pair an alias gave them to.
Every batch after the alias was made is that pair's, encrypted under its
key, so it goes to that pair's own tables, at the same sequences, and the
store that gets the tables back holds only what was there before, and goes
on from there. 0.6.9
records the legacy store's head with each alias it makes; for an alias an
earlier version made, the operator gives it (``through_sequence``).

It locks the legacy store's row, and the rows of the pairs it moves
tables between, before reading anything: a server's write locks its
store's row and then checks it still resolves there
(``legacy.still_resolves``), so the two never interleave.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Never, NewType

from pyfect._core import Effect
from pyfect.crypto.digest import DigestService
from pyfect.effect import fail, gen, succeed
from pyfect.eventlog._sql_server_encrypted.db import Db
from pyfect.eventlog._sql_server_encrypted.legacy import (
    UPGRADE_NOTES,
    LegacyStoreMigrationError,
    evidence_of,
    has_batches,
    head,
    holder,
    holder_pair,
    legacy_key,
    others_before,
    record_alias,
    scope_key,
    scope_of,
    split_keys,
)
from pyfect.eventlog._sql_server_encrypted.rows import StoreRow
from pyfect.eventlog._sql_server_encrypted.tables import create_scope_tables
from pyfect.eventlog._sql_server_encrypted.upgrade import Evidence
from pyfect.logger import log_info
from pyfect.persistence._columns import column_int
from pyfect.sql.error import SqlError

type Pair = tuple[str, str]

LastSequence = NewType("LastSequence", int)
"""The last sequence of a batch, so 1 or more (``confirmation`` parses it)."""


@dataclass(frozen=True, slots=True)
class Confirmation:
    """What the operator confirmed in ``migrate_legacy_store``."""

    not_written_by: tuple[str, ...]
    without_binding: bool
    taken_from: Pair | None
    through_sequence: LastSequence | None


def confirmation(
    not_written_by: Sequence[str],
    without_binding: bool,
    taken_from: Pair | None,
    through_sequence: int | None,
) -> Effect[Confirmation, LegacyStoreMigrationError]:
    """The ``Confirmation`` of ``migrate_legacy_store``'s arguments, or why
    they are refused."""
    if through_sequence is None:
        through = None
    elif through_sequence >= 1:
        through = LastSequence(through_sequence)
    else:
        return _refuse(
            "through_sequence must be 1 or more: the last sequence the store you take the "
            "tables back for wrote before they were given away, which ends one of its batches"
        )
    return succeed(Confirmation(tuple(not_written_by), without_binding, taken_from, through))


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


def _taken_refusal(legacy: str, taken: Pair | None, confirmation: Confirmation) -> str | None:
    """Why the call may not take the tables from the pair that has them."""
    if confirmation.taken_from is None and confirmation.through_sequence is not None:
        return "through_sequence goes with taken_from: drop it"
    if taken == confirmation.taken_from:
        return None
    if taken is None:
        return f"The tables of {legacy!r} were not given to another store: drop taken_from"
    return (
        f"The tables of {legacy!r} were given to store {taken[1]!r} of {taken[0]!r}. If you have "
        f"confirmed that it did not write them, pass taken_from={taken!r}; the batches it wrote "
        "since then go to tables of its own"
    )


def _recorded_bound(db: Db, legacy_scope: str) -> Effect[int | None, SqlError]:
    return db.sql(
        "SELECT through_sequence FROM {} WHERE legacy_scope = {}", db.alias_bounds, legacy_scope
    ).map(lambda rows: column_int(rows[0]["through_sequence"]) if rows else None)


def _taker_bound(
    db: Db,
    legacy: str,
    legacy_scope: str,
    row: StoreRow,
    taken: Pair,
    *,
    asked: LastSequence | None,
) -> Effect[int | str, SqlError]:
    """The last sequence of the legacy tables from before they were given to
    ``taken``, or why it is not known."""
    tables = db.scope_tables(legacy_scope)

    def body():
        last = yield from head(db, legacy_scope)
        recorded = yield from _recorded_bound(db, legacy_scope)
        if recorded is not None and asked is not None and asked != recorded:
            return (
                f"The tables of {legacy!r} held batches through sequence {recorded} when they "
                f"were given to {taken!r}: drop through_sequence"
            )
        through = recorded if recorded is not None else asked
        if through is None:
            return (
                f"The tables of {legacy!r} were given to {taken!r} by pyfect 0.6.6, 0.6.7 or "
                f"0.6.8, which did not record how far they ran then, and they hold batches "
                f"through sequence {last}. Batches written after they were given away are "
                f"{taken!r}'s, which the store you give them to cannot decrypt. Pass "
                "through_sequence, the last sequence written before then: an up-to-date client "
                "of the store that wrote them has it, as next_remote_sequence(remote_id) - 1 of "
                f"its journal. The batches after it go to {taken!r}'s own tables. If "
                f"{taken!r} wrote nothing, pass through_sequence={last}"
            )
        if through > last:
            return (
                f"through_sequence must be between 1 and {last}, the last sequence of the tables "
                f"of {legacy!r}"
            )
        inside = yield from db.sql(
            "SELECT sequence FROM {} WHERE sequence <= {} AND last_sequence > {}",
            tables.table,
            through,
            through,
        )
        if inside:
            return f"Sequence {through} of the tables of {legacy!r} falls inside a batch"
        if through < last and (row.open_stage is not None or row.base > through):
            return (
                f"The tables of {legacy!r} were compacted past sequence {through} after they were "
                f"given to {taken!r}, so their batches cannot be told apart any more"
            )
        return through

    return gen(body)


def _move_after(db: Db, legacy_scope: str, taker_scope: str, through: int) -> Effect[int, SqlError]:
    """Moves the batches of the legacy tables after ``through``, their ids
    and their buckets, to the taker's own tables at the same sequences; how
    many batches moved. The taker's tables exist."""
    sql = db.sql
    source = db.scope_tables(legacy_scope)
    target = db.scope_tables(taker_scope)

    def body():
        taker_row = yield from db.lock_store_if_any(taker_scope)
        rows = yield from sql(
            "SELECT COUNT(*) AS n FROM {} WHERE sequence > {}", source.table, through
        )
        moved = column_int(rows[0]["n"])
        if moved == 0:
            return 0
        yield from sql(
            "INSERT INTO {} (sequence, last_sequence, iv, entry_ids, encrypted_batch) "
            "SELECT sequence, last_sequence, iv, entry_ids, encrypted_batch FROM {} "
            "WHERE sequence > {}",
            target.table,
            source.table,
            through,
        )
        yield from sql(
            "INSERT INTO {} (entry_id, sequence) SELECT entry_id, sequence FROM {} "
            "WHERE sequence > {}",
            target.ids_table,
            source.ids_table,
            through,
        )
        yield from sql("DELETE FROM {} WHERE sequence > {}", source.ids_table, through)
        yield from sql("DELETE FROM {} WHERE sequence > {}", source.table, through)
        # No client of the store getting the tables back saw those sequences
        # (it was served other tables), and one waiting to be synced waits
        # for the head to be reached.
        yield from sql(
            "UPDATE {} SET next_sequence = {} WHERE scope = {}",
            db.stores,
            through + 1,
            legacy_scope,
        )
        yield from sql("DELETE FROM {} WHERE scope = {}", db.buckets, taker_scope)
        yield from sql(
            "UPDATE {} SET scope = {} WHERE scope = {} AND last_sequence > {}",
            db.buckets,
            taker_scope,
            legacy_scope,
            through,
        )
        if taker_row is None:
            yield from db.ensure_store(taker_scope, target.table)
        else:
            last = yield from db.max_last_sequence(target.table)
            yield from sql(
                "UPDATE {} SET next_sequence = {} WHERE scope = {}",
                db.stores,
                max(taker_row.next_sequence, last + 1),
                taker_scope,
            )
        return moved

    return gen(body)


def _refuse(message: str) -> Effect[Never, LegacyStoreMigrationError]:
    return fail(LegacyStoreMigrationError(message=f"{message} (see {UPGRADE_NOTES})"))


def _migrate(
    db: Db, digest: DigestService, public_key: str, store_id: str, confirmation: Confirmation
) -> Effect[tuple[bool, int], SqlError | LegacyStoreMigrationError]:
    """``migrate_legacy_store`` in one transaction: whether the pair has the
    tables now, and how many batches went to the pair they were taken from."""
    sql = db.sql
    legacy = legacy_key(public_key, store_id)

    def body():
        scope = yield from scope_of(digest, scope_key(public_key, store_id))
        legacy_scope = yield from scope_of(digest, legacy)
        legacy_row = yield from db.lock_store_if_any(legacy_scope)
        yield from db.lock_store_if_any(scope)
        given = yield from holder(db, legacy_scope)
        if given == scope:
            return (True, 0)
        taken = None if given is None else (yield from holder_pair(digest, legacy, given))
        refusal = _taken_refusal(legacy, taken, confirmation)
        if refusal is None and (
            legacy_row is None or not (yield from has_batches(db, legacy_scope))
        ):
            return (False, 0)
        if refusal is None:
            evidence = yield from evidence_of(db, legacy)
            check = _bound_refusal if public_key in evidence.before else _unbound_refusal
            refusal = check(public_key, store_id, evidence, confirmation)
        if refusal is None and (yield from has_batches(db, scope)):
            refusal = (
                f"Store {store_id!r} of {public_key!r} already holds batches of its own, so a "
                f"pyfect 0.6.5 node wrote the tables named {legacy!r} after the store opened on a "
                "newer version; the two cannot be merged"
            )
        through: int | None = None
        if refusal is None and taken is not None and legacy_row is not None:
            bound = yield from _taker_bound(
                db, legacy, legacy_scope, legacy_row, taken, asked=confirmation.through_sequence
            )
            if isinstance(bound, str):
                refusal = bound
            else:
                through = bound
        if refusal is not None:
            return (yield from _refuse(refusal))
        moved = 0
        if given is not None and through is not None:
            moved = yield from _move_after(db, legacy_scope, given, through)
        for table in (db.aliases, db.alias_origins, db.alias_bounds):
            yield from sql("DELETE FROM {} WHERE legacy_scope = {}", table, legacy_scope)
        yield from record_alias(db, legacy_scope, scope, "operator")
        return (True, moved)

    return sql.with_transaction(gen(body))


def migrate_legacy_store(
    db: Db, digest: DigestService, public_key: str, store_id: str, confirmation: Confirmation
) -> Effect[bool, SqlError | LegacyStoreMigrationError]:
    """Gives the pair its tables from 0.6.5 or earlier; whether it has them
    now (``False``: it has none, or never needed a new key)."""
    legacy = legacy_key(public_key, store_id)

    def prepare_taker(taken: Pair) -> Effect[None, SqlError]:
        """Creates the tables of the pair named by ``taken_from`` when it has
        the legacy tables, before the transaction (MySQL commits on DDL)."""

        def body():
            taker_scope = yield from scope_of(digest, scope_key(*taken))
            legacy_scope = yield from scope_of(digest, legacy)
            if (yield from holder(db, legacy_scope)) == taker_scope:
                yield from create_scope_tables(db.sql, f"{db.prefix}_{taker_scope}")

        return gen(body)

    def body():
        if scope_key(public_key, store_id) == legacy:
            return False
        if confirmation.taken_from is not None:
            yield from prepare_taker(confirmation.taken_from)
        has, moved = yield from _migrate(db, digest, public_key, store_id, confirmation)
        if moved:
            taken = confirmation.taken_from
            yield from log_info(
                f"Gave the tables pyfect 0.6.5 named {legacy!r} back to store {store_id!r} of "
                f"{public_key!r}; the {moved} batches {taken!r} wrote after they were given to it "
                "moved to its own tables"
            ).annotate_logs({"service": "SqlEventLogServerEncrypted"})
        return has

    return gen(body)


__all__ = ["Confirmation", "LastSequence", "confirmation", "migrate_legacy_store"]
