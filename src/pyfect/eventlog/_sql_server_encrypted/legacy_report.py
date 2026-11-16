"""The stores whose tables from 0.6.5 or earlier hold batches under a name
several (public key, store id) pairs share, for operators
(``sql_event_log_server_encrypted.legacy_stores``).

Store ids and public keys are not stored with the tables (they are named
by a hash), so the names checked are every known key, followed by ``/``
and each of the app's store ids. The known keys are those bound before the
upgrade, those bound since, and any the caller names (a store written
straight through the storage has no binding). Every pair splitting a name
that holds batches is listed, the name's other pairs included.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from pyfect._core import Effect
from pyfect.crypto.digest import DigestService
from pyfect.effect import gen
from pyfect.eventlog._sql_server_encrypted import upgrade
from pyfect.eventlog._sql_server_encrypted.db import Db
from pyfect.eventlog._sql_server_encrypted.legacy import (
    has_batches,
    holder,
    legacy_key,
    others_before,
    scope_key,
    scope_of,
    split_keys,
    standing,
    store_of,
)
from pyfect.persistence._columns import column_text
from pyfect.sql.error import SqlError

type LegacyStoreState = Literal[
    "pending", "unconfirmed", "ambiguous", "unbound", "split", "migrated", "taken"
]
type LegacyBinding = Literal["before_upgrade", "after_upgrade", "none"]
type LegacyMigratedBy = Literal["server", "operator", "earlier_version"]


@dataclass(frozen=True, slots=True)
class LegacyStore:
    """A pair whose legacy name (``legacy_name``, which other pairs share)
    names 0.6.5 tables holding batches.

    ``state``, while no pair has the tables:

    - ``"pending"``: its key alone, among the name's pairs, had a session
      auth binding before the upgrade; the server gives it the tables on
      the next request (or ``migrate_legacy_store`` does now).
    - ``"unconfirmed"``: likewise, but pyfect 0.6.6 or 0.6.7 opened the
      database before this version, so the binding may be newer than the
      upgrade; the store waits for ``migrate_legacy_store``.
    - ``"ambiguous"``: ``other_keys`` had bindings before the upgrade too;
      the store waits for the operator to decide.
    - ``"unbound"``: its key had no binding before the upgrade. When no
      pair of the name had one, the name's stores wait for the operator.
    - ``"split"``: its key alone had a binding, and the store holds batches
      under its new tables too: a 0.6.5 node wrote to it after the upgrade.

    Once a pair has the tables: ``"migrated"`` (this pair) or ``"taken"``
    (another pair of the name), and ``migrated_by`` says who gave them:
    the server, the operator, or 0.6.6 / 0.6.7, whose rules may have given
    them to a pair that did not write them.

    ``other_keys`` are the name's other keys bound before the upgrade;
    ``binding`` is when this pair's key was bound.
    """

    public_key: str
    store_id: str
    state: LegacyStoreState
    other_keys: tuple[str, ...] = ()
    binding: LegacyBinding = "before_upgrade"
    migrated_by: LegacyMigratedBy | None = None

    @property
    def legacy_name(self) -> str:
        return legacy_key(self.public_key, self.store_id)


def _origins(db: Db) -> Effect[dict[str, LegacyMigratedBy], SqlError]:
    def origin(text: str) -> LegacyMigratedBy:
        return "operator" if text == "operator" else "server"

    return db.sql("SELECT legacy_scope, origin FROM {}", db.alias_origins).map(
        lambda rows: {
            column_text(row["legacy_scope"]): origin(column_text(row["origin"])) for row in rows
        }
    )


def legacy_stores(
    db: Db, digest: DigestService, store_ids: Iterable[str], public_keys: Iterable[str] = ()
) -> Effect[list[LegacyStore], SqlError]:
    sql = db.sql

    def body():
        evidence = yield from upgrade.all_evidence(db)
        opened = {
            column_text(row["scope"]) for row in (yield from sql("SELECT scope FROM {}", db.stores))
        }
        origins = yield from _origins(db)
        ids = sorted(set(store_ids))
        keys = evidence.before | evidence.now | frozenset(public_keys)
        names = sorted(
            {
                legacy
                for key in keys
                for store_id in ids
                if (legacy := legacy_key(key, store_id)) != scope_key(key, store_id)
            }
        )
        found: list[LegacyStore] = []
        for legacy in names:
            legacy_scope = yield from scope_of(digest, legacy)
            if legacy_scope not in opened or not (yield from has_batches(db, legacy_scope)):
                continue
            given = yield from holder(db, legacy_scope)
            for key in split_keys(legacy):
                store_id = store_of(legacy, key)
                scope = yield from scope_of(digest, scope_key(key, store_id))
                binding: LegacyBinding = (
                    "before_upgrade"
                    if key in evidence.before
                    else "after_upgrade"
                    if key in evidence.now
                    else "none"
                )
                others = others_before(key, store_id, evidence)
                if given is not None:
                    state: LegacyStoreState = "migrated" if given == scope else "taken"
                    by = origins.get(legacy_scope, "earlier_version")
                    found.append(LegacyStore(key, store_id, state, others, binding, by))
                    continue
                state = standing(key, store_id, evidence)
                if state in ("pending", "unconfirmed") and (yield from has_batches(db, scope)):
                    state = "split"
                found.append(LegacyStore(key, store_id, state, others, binding))
        return found

    return gen(body)


__all__ = [
    "LegacyBinding",
    "LegacyMigratedBy",
    "LegacyStore",
    "LegacyStoreState",
    "legacy_stores",
]
