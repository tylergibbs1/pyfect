import pyfect as fx
from pyfect.crypto.digest import layer_web_crypto
from pyfect.eventlog import sql_event_log_server_encrypted as SqlServer
from pyfect.sql import sqlite

# A store whose key alone authenticated before the upgrade ("pending" or "unconfirmed"
# in legacy_stores), once you know this pair wrote it. The keyword arguments take the
# same values as your layer_storage(...) call.
pending = SqlServer.migrate_legacy_store(
    "Kq9/xT2+bQ==",
    "main",
    entry_table_prefix="effect_events",
    remote_id_table="effect_remote_id",
)

# A store written straight through the storage, so its key has no binding, once you
# know this pair wrote it: name every other key that splits "Kq9/xT2+bQ==/main".
unbound = SqlServer.migrate_legacy_store(
    "Kq9/xT2+bQ==", "main", without_binding=True, not_written_by=["Kq9"]
)

# A store an earlier version gave to ("Kq9", "xT2+bQ==/main"), which didn't write it.
# through_sequence: the last sequence written before then (needed when 0.6.6, 0.6.7 or
# 0.6.8 gave it away); the batches after it go to that pair's own tables.
taken_back = SqlServer.migrate_legacy_store(
    "Kq9/xT2+bQ==",
    "main",
    without_binding=True,
    not_written_by=["Kq9"],
    taken_from=("Kq9", "xT2+bQ==/main"),
    through_sequence=2,
)

# Your server's database. On this one no upgraded server has started yet, so nothing
# records who had authenticated before the upgrade, and the call is refused.
database = sqlite.layer(sqlite.SqliteClientConfig(filename=":memory:"))
refused = fx.run_blocking(
    pending.pipe(fx.provide(layer_web_crypto)).pipe(fx.provide(database)).exit()
)
assert isinstance(refused, fx.Failure)
