import itertools

import pyfect as fx
from pyfect.crypto.digest import layer_web_crypto
from pyfect.eventlog import sql_event_log_server_encrypted as SqlServer
from pyfect.sql import sqlite

# The store ids your app opens: the server keeps only a hash of each.
STORE_IDS = ["main", "notes"]
# Keys that wrote straight through the storage, which have no binding.
DIRECT_KEYS: list[str] = []

# Your server's database; this one is empty, so nothing waits.
database = sqlite.layer(sqlite.SqliteClientConfig(filename=":memory:"))

stores = fx.run_blocking(
    SqlServer.legacy_stores(
        STORE_IDS,
        public_keys=DIRECT_KEYS,
        # Keyword arguments: the same values as your layer_storage(...) call.
        entry_table_prefix="effect_events",
        remote_id_table="effect_remote_id",
    )
    .pipe(fx.provide(layer_web_crypto))
    .pipe(fx.provide(database))
    .or_die()
)
if stores and not stores[0].upgrade_recorded:
    print("no upgraded server has started yet: bindings made before it still count")
# Rows come sorted by legacy name: one group per name, one row per pair sharing it.
for name, group in itertools.groupby(stores, key=lambda store: store.legacy_name):
    rows = list(group)
    states = {store.state for store in rows}
    direct = [store for store in rows if store.public_key in DIRECT_KEYS]
    if states & {"migrated", "taken"}:
        holder = next(store for store in rows if store.state == "migrated")
        if holder.migrated_by != "operator":
            print(f"check {name!r}: {holder.migrated_by} gave it to {holder.public_key!r}")
    elif "split" in states:
        print(f"{name!r}: a 0.6.5 node wrote to it after the upgrade")
    elif (states & {"pending", "unconfirmed"}) and not direct:
        owner = next(store for store in rows if store.state in {"pending", "unconfirmed"})
        print(f"{name!r}: migrate to {owner.public_key!r}, {owner.store_id!r} if it wrote it")
    else:
        # Several bound keys, or a key that wrote straight through the storage: any of
        # them may have written it. With no bound key, any pair of the name may have.
        bound = [store for store in rows if store.state != "unbound"]
        candidates = [(store.public_key, store.store_id) for store in (bound + direct or rows)]
        print(f"decide who wrote {name!r}: one of {candidates}")
assert stores == []
