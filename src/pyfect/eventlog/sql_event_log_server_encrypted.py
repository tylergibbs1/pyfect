"""Storage of an encrypted event log server in a SQL database (Effect's
``eventlog/SqlEventLogServerEncrypted``), on SQLite, PostgreSQL, MySQL or
SQL Server, with remote compaction.

Each identity and store has a table of batches, named by a hash of the
pair under ``entry_table_prefix``, a table of the entry ids it holds with
the sequence each was first stored at, and a table of snapshot batches.
A batch is stored when one of its ids is new; sequences start at 1.
``remote_id_table`` keeps the server's remote id,
``<entry_table_prefix>_session_auth_bindings`` the signing key bound to
each public key, and ``<entry_table_prefix>_compaction_*`` the compaction
state of every store.

Up to 0.6.5 tables were named by ``publicKey/storeId``, which two pairs
share when it holds more than one ``/``. A pair whose key has one ``/``
keeps its tables. Of the pairs sharing any other name whose 0.6.5 tables
hold batches, the one whose public key alone had authenticated (had a
session auth binding) before the upgrade gets them on the first request,
and the others open tables of their own. A binding made after the upgrade
counts for nothing. When no key or several had one, or pyfect 0.6.6 or
0.6.7 opened the database first, the stores die with
``LegacyStoreNeedsMigration`` until the operator runs
``migrate_legacy_store``. ``legacy_stores`` lists them. See
https://pyfect.dev/docs/eventlog-upgrade.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

from pyfect._core import Effect
from pyfect._public import publish
from pyfect.crypto.digest import Digest
from pyfect.crypto.digest import layer_web_crypto as digest_layer_web_crypto
from pyfect.eventlog._server_encrypted.models import CompactionOptions
from pyfect.eventlog._server_encrypted.storage import Storage
from pyfect.eventlog._sql_server_encrypted import legacy, legacy_report
from pyfect.eventlog._sql_server_encrypted.legacy import (
    LegacyStoreMigrationError,
    LegacyStoreNeedsMigration,
)
from pyfect.eventlog._sql_server_encrypted.legacy_report import (
    LegacyBinding,
    LegacyMigratedBy,
    LegacyStore,
    LegacyStoreState,
)
from pyfect.eventlog._sql_server_encrypted.storage import make_storage
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.layer import provide as layer_provide
from pyfect.sql.client import SqlClient
from pyfect.sql.error import SqlError

__all__ = [
    "LegacyBinding",
    "LegacyMigratedBy",
    "LegacyStore",
    "LegacyStoreMigrationError",
    "LegacyStoreNeedsMigration",
    "LegacyStoreState",
    "SqlError",
    "layer_storage",
    "layer_storage_subtle",
    "legacy_stores",
    "make_storage",
    "migrate_legacy_store",
]


def migrate_legacy_store(
    public_key: str,
    store_id: str,
    *,
    not_written_by: Sequence[str] = (),
    without_binding: bool = False,
    taken_from: tuple[str, str] | None = None,
    entry_table_prefix: str = "effect_events",
    remote_id_table: str = "effect_remote_id",
) -> Effect[bool, SqlError | LegacyStoreMigrationError, SqlClient | Digest]:
    """Gives the store of ``public_key`` and ``store_id`` the tables 0.6.5
    named ``publicKey/storeId``, once you have confirmed it wrote them.
    Succeeds with whether the store has them now.

    When ``public_key`` had a session auth binding before the upgrade,
    ``not_written_by`` names exactly the other keys sharing the name that
    had one. When it had none (its store was written straight through the
    storage, or it authenticated only since), pass ``without_binding=True``
    and name every other key sharing the name. ``taken_from`` names the
    pair the tables were given to, to take them back from it.
    ``entry_table_prefix`` and ``remote_id_table`` must be those of the
    ``layer_storage`` call."""
    confirmation = legacy.Confirmation(tuple(not_written_by), without_binding, taken_from)
    return legacy.with_db(
        entry_table_prefix,
        remote_id_table,
        lambda db, digest: legacy.migrate_legacy_store(
            db, digest, public_key, store_id, confirmation
        ),
    )


def legacy_stores(
    store_ids: Iterable[str],
    *,
    public_keys: Iterable[str] = (),
    entry_table_prefix: str = "effect_events",
    remote_id_table: str = "effect_remote_id",
) -> Effect[list[LegacyStore], SqlError, SqlClient | Digest]:
    """Every pair sharing a 0.6.5 table name that holds batches, with where
    it stands (``LegacyStore``). The names checked are each key bound
    before or since the upgrade, and each of ``public_keys``, followed by
    ``/`` and each of the app's ``store_ids``: neither is stored with the
    tables. Name in ``public_keys`` the keys that wrote straight through
    the storage."""
    return legacy.with_db(
        entry_table_prefix,
        remote_id_table,
        lambda db, digest: legacy_report.legacy_stores(db, digest, store_ids, public_keys),
    )


def layer_storage(
    *,
    entry_table_prefix: str = "effect_events",
    remote_id_table: str = "effect_remote_id",
    compaction: CompactionOptions | None = None,
) -> Layer[Storage, SqlError, SqlClient | Digest]:
    """The ``Storage`` of ``make_storage``."""
    return layer_effect(
        Storage,
        make_storage(
            entry_table_prefix=entry_table_prefix,
            remote_id_table=remote_id_table,
            compaction=compaction,
        ),
    )


def layer_storage_subtle(
    *,
    entry_table_prefix: str = "effect_events",
    remote_id_table: str = "effect_remote_id",
    compaction: CompactionOptions | None = None,
) -> Layer[Storage, SqlError, SqlClient]:
    """``layer_storage`` with the Web Crypto ``Digest``."""
    return layer_storage(
        entry_table_prefix=entry_table_prefix,
        remote_id_table=remote_id_table,
        compaction=compaction,
    ).pipe(layer_provide(digest_layer_web_crypto))


publish(globals())
