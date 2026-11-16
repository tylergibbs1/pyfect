import pyfect as fx
from pyfect.crypto.digest import layer_web_crypto
from pyfect.eventlog import sql_event_log_server_encrypted as SqlServer
from pyfect.sql import sqlite

# A store legacy_stores lists as "pending" or "unconfirmed". The keyword arguments take
# the same values as your layer_storage(...) call.
pending = SqlServer.migrate_legacy_store(
    "Kq9/xT2+bQ==",
    "main",
    entry_table_prefix="effect_events",
    remote_id_table="effect_remote_id",
)

# A store no key had a binding for before the upgrade, once you know this pair wrote it:
# name every other key that splits "Kq9/xT2+bQ==/main".
unbound = SqlServer.migrate_legacy_store(
    "Kq9/xT2+bQ==", "main", without_binding=True, not_written_by=["Kq9"]
)

# A store 0.6.6 or 0.6.7 gave to ("Kq9", "xT2+bQ==/main"), which didn't write it.
taken_back = SqlServer.migrate_legacy_store(
    "Kq9/xT2+bQ==",
    "main",
    without_binding=True,
    not_written_by=["Kq9"],
    taken_from=("Kq9", "xT2+bQ==/main"),
)

# Your server's database; this one is empty, so there is nothing to migrate.
database = sqlite.layer(sqlite.SqliteClientConfig(filename=":memory:"))
migrated = fx.run_blocking(
    pending.pipe(fx.provide(layer_web_crypto)).pipe(fx.provide(database)).or_die()
)
assert migrated is False
