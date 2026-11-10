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
"""

from __future__ import annotations

from pyfect.crypto.digest import Digest
from pyfect.crypto.digest import layer_web_crypto as digest_layer_web_crypto
from pyfect.eventlog._server_encrypted.models import CompactionOptions
from pyfect.eventlog._server_encrypted.storage import Storage
from pyfect.eventlog._sql_server_encrypted.storage import make_storage
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.layer import provide as layer_provide
from pyfect.sql.client import SqlClient
from pyfect.sql.error import SqlError

__all__ = ["SqlError", "layer_storage", "layer_storage_subtle", "make_storage"]


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
