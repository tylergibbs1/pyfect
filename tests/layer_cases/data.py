"""Reuse cases for the sql, persistence, eventlog and reactivity layers.

SQLite cases use an in-memory database per run; PostgreSQL, MySQL, SQL
Server and Redis cases use the throwaway servers of ``oracle._postgres`` /
``oracle._mysql`` / ``oracle._mssql`` / ``oracle._redis`` (they skip
without them). Uses that
touch an external store (a file, a server) pass whether or not an earlier
run's data is still there."""

# pyright: reportUnknownLambdaType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

import atexit
import itertools
import shutil
import tempfile
from collections.abc import Callable, Generator
from dataclasses import dataclass
from typing import Any, TypedDict

from oracle import _mssql, _mysql, _postgres, _redis

import pyfect as fx
from layer_cases._case import Case
from pyfect import config, config_provider, file_system, path
from pyfect import schema as S
from pyfect import socket as fx_socket
from pyfect.context import Tag
from pyfect.eventlog import event as Ev
from pyfect.eventlog import event_group as G
from pyfect.eventlog import event_journal as J
from pyfect.eventlog import event_log as EL
from pyfect.eventlog import event_log_message as M
from pyfect.eventlog import event_log_remote as Remote
from pyfect.eventlog import event_log_server as Server
from pyfect.eventlog import event_log_server_encrypted as Enc
from pyfect.eventlog import event_log_server_unencrypted as Unenc
from pyfect.eventlog import event_row as Row
from pyfect.eventlog import sql_event_journal as SqlJournal
from pyfect.eventlog import sql_event_log_server_encrypted as SqlEnc
from pyfect.eventlog import sql_event_log_server_unencrypted as SqlUnenc
from pyfect.eventlog.event_journal import Entry, RemoteEntry, StoreId
from pyfect.eventlog.event_log_encryption import EventLogEncryption, layer_subtle
from pyfect.eventlog.event_log_remote import EventLogRemoteError, EventLogRemoteService
from pyfect.persistence import PersistenceError, persistable, persistence, redis_py
from pyfect.persistence import circuit_breaker as cb
from pyfect.persistence import key_value_store as kvs
from pyfect.persistence import persisted_queue as pq
from pyfect.persistence import rate_limiter as rl
from pyfect.persistence import user_directories as ud
from pyfect.persistence.redis import Redis
from pyfect.queue import Queue
from pyfect.reactivity import Reactivity, atom, atom_registry
from pyfect.reactivity import layer as reactivity_layer
from pyfect.rpc import client as rpc_client
from pyfect.rpc import serialization as rs
from pyfect.rpc import server as rpc_server
from pyfect.rpc import test as rpc_test
from pyfect.socket import server as socket_server
from pyfect.socket.server import SocketServer
from pyfect.sql import mssql, mysql, pg, sqlite
from pyfect.sql.client import SqlClient
from pyfect.sql.mssql import migrator as mssql_migrator
from pyfect.sql.mysql import migrator as mysql_migrator
from pyfect.sql.pg import migrator as pg_migrator
from pyfect.sql.sqlite import migrator as sqlite_migrator

type AnyLayer = fx.Layer[Any, Any, Any]
type Body = Callable[[], Generator[Any, Any, Any]]


def _gen(body: Body) -> Callable[[], fx.Effect[Any, Any, Any]]:
    return lambda: fx.gen(body)


def _provider(**values: str) -> AnyLayer:
    return config_provider.layer(config_provider.from_unknown(values))


def _temporary_directory() -> str:
    directory = tempfile.mkdtemp(prefix="pyfect-layer-reuse-")
    atexit.register(shutil.rmtree, directory, True)
    return directory


# --- sql ------------------------------------------------------------------------------


def _sqlite() -> AnyLayer:
    return sqlite.layer(sqlite.SqliteClientConfig(filename=":memory:"))


def _pg_config() -> pg.PgPoolConfig:
    return pg.PgPoolConfig(url=_postgres.server().url, max_connections=2)


def _pg() -> AnyLayer:
    return pg.layer(_pg_config())


def _mysql_config() -> mysql.MysqlClientConfig:
    return mysql.MysqlClientConfig(url=_mysql.server().url, max_connections=2)


def _mysql_client() -> AnyLayer:
    return mysql.layer(_mysql_config())


def _mssql_config() -> mssql.MssqlClientConfig:
    return _mssql.server().config(max_connections=2)


def _mssql_client() -> AnyLayer:
    return mssql.layer(_mssql_config())


def _fresh_database():
    """A table made in this run is the only one: each build opens its own
    in-memory database."""
    sql = yield from SqlClient()
    yield from sql("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")
    yield from sql("INSERT INTO items (name) VALUES ('a')")
    assert (yield from sql("SELECT count(*) AS n FROM items")) == [{"n": 1}]


def _select_one():
    sql = yield from SqlClient()
    assert (yield from sql("SELECT 1 AS one")) == [{"one": 1}]


def _create_items():
    sql = yield from SqlClient()
    yield from sql("CREATE TABLE layer_reuse_items (id SERIAL PRIMARY KEY, name TEXT NOT NULL)")


def _create_items_mysql():
    sql = yield from SqlClient()
    yield from sql(
        "CREATE TABLE layer_reuse_items (id INT AUTO_INCREMENT PRIMARY KEY, name TEXT NOT NULL)"
    )


def _create_items_mssql():
    sql = yield from SqlClient()
    yield from sql(
        "CREATE TABLE layer_reuse_items (id INT IDENTITY PRIMARY KEY, name NVARCHAR(MAX) NOT NULL)"
    )


def _create_items_sqlite():
    sql = yield from SqlClient()
    yield from sql("CREATE TABLE layer_reuse_items (id INTEGER PRIMARY KEY, name TEXT NOT NULL)")


def _migrated_table():
    sql = yield from SqlClient()
    yield from sql("INSERT INTO layer_reuse_items (name) VALUES ('a')")
    [row] = yield from sql("SELECT count(*) AS n FROM layer_reuse_items")
    count = row["n"]
    assert isinstance(count, int)
    assert count >= 1


_SQL: dict[str, Case] = {
    "pyfect.sql.sqlite.client.layer": Case(layer=_sqlite, use=_gen(_fresh_database)),
    "pyfect.sql.sqlite.client.layer_config": Case(
        layer=lambda: sqlite.layer_config({"filename": config.string("DATABASE_PATH")}),
        needs=lambda: _provider(DATABASE_PATH=":memory:"),
        use=_gen(_fresh_database),
    ),
    "pyfect.sql.sqlite.migrator.layer": Case(
        layer=lambda: sqlite_migrator.layer(
            loader=sqlite_migrator.from_record({"1_create_items": fx.gen(_create_items_sqlite)})
        ),
        needs=_sqlite,
        use=_gen(_migrated_table),
    ),
    "pyfect.sql.pg.client.layer": Case(layer=_pg, use=_gen(_select_one)),
    "pyfect.sql.pg.client.layer_config": Case(
        layer=lambda: pg.layer_config({"url": config.redacted("DATABASE_URL")}),
        needs=lambda: _provider(DATABASE_URL=_postgres.server().uri),
        use=_gen(_select_one),
    ),
    "pyfect.sql.pg.client.layer_from": Case(
        layer=lambda: pg.layer_from(pg.make(_pg_config())), use=_gen(_select_one)
    ),
    "pyfect.sql.pg.migrator.layer": Case(
        layer=lambda: pg_migrator.layer(
            loader=pg_migrator.from_record({"1_create_items": fx.gen(_create_items)}),
            table="layer_reuse_migrations",
        ),
        needs=_pg,
        use=_gen(_migrated_table),
    ),
    "pyfect.sql.mysql.client.layer": Case(layer=_mysql_client, use=_gen(_select_one)),
    "pyfect.sql.mysql.client.layer_config": Case(
        layer=lambda: mysql.layer_config({"url": config.redacted("DATABASE_URL")}),
        needs=lambda: _provider(DATABASE_URL=_mysql.server().uri()),
        use=_gen(_select_one),
    ),
    "pyfect.sql.mysql.client.layer_from": Case(
        layer=lambda: mysql.layer_from(mysql.make(_mysql_config())), use=_gen(_select_one)
    ),
    "pyfect.sql.mysql.migrator.layer": Case(
        layer=lambda: mysql_migrator.layer(
            loader=mysql_migrator.from_record({"1_create_items": fx.gen(_create_items_mysql)}),
            table="layer_reuse_migrations",
        ),
        needs=_mysql_client,
        use=_gen(_migrated_table),
    ),
    "pyfect.sql.mssql.client.layer": Case(layer=_mssql_client, use=_gen(_select_one)),
    "pyfect.sql.mssql.client.layer_config": Case(
        layer=lambda: mssql.layer_config(
            {
                "server": config.string("MSSQL_SERVER"),
                "port": config.integer("MSSQL_PORT"),
                "username": config.string("MSSQL_USERNAME"),
                "password": config.redacted("MSSQL_PASSWORD"),
                "trust_server": config.boolean("MSSQL_TRUST_SERVER"),
            }
        ),
        needs=lambda: _provider(
            MSSQL_SERVER=_mssql.server().host,
            MSSQL_PORT=str(_mssql.server().port),
            MSSQL_USERNAME=_mssql.server().username,
            MSSQL_PASSWORD=_mssql.PASSWORD,
            MSSQL_TRUST_SERVER="true",
        ),
        use=_gen(_select_one),
    ),
    "pyfect.sql.mssql.client.layer_from": Case(
        layer=lambda: mssql.layer_from(mssql.make(_mssql_config())), use=_gen(_select_one)
    ),
    "pyfect.sql.mssql.migrator.layer": Case(
        layer=lambda: mssql_migrator.layer(
            loader=mssql_migrator.from_record({"1_create_items": fx.gen(_create_items_mssql)}),
            table="layer_reuse_migrations",
        ),
        needs=_mssql_client,
        use=_gen(_migrated_table),
    ),
}


# --- persistence ----------------------------------------------------------------------


def _redis_client() -> AnyLayer:
    return redis_py.layer(_redis.server().url)


_shared_keys = itertools.count()


def _kv_use(*, fresh: bool) -> Callable[[], fx.Effect[Any, Any, Any]]:
    """Set then get; a ``fresh`` store (one Effect makes per build) starts
    empty in every run. A shared one (files) gets a key of each run's own:
    runs at once writing the same file can read it half written."""

    def body():
        kv = yield from kvs.KeyValueStore()
        if fresh:
            assert (yield from kv.size) == 0
            key = "key"
        else:
            key = f"key-{next(_shared_keys)}"
        yield from kv.set(key, "value")
        assert (yield from kv.get(key)) == "value"
        if fresh:
            assert (yield from kv.size) == 1

    return _gen(body)


def _backing_use(*, fresh: bool) -> Callable[[], fx.Effect[Any, Any, Any]]:
    def body():
        store = yield from (yield from persistence.BackingPersistence()).make("layer_reuse")
        if fresh:
            assert (yield from store.get("key")) is None
        yield from store.set("key", {"name": "Alice"}, None)
        assert (yield from store.get("key")) == {"name": "Alice"}

    return _gen(body)


class _Item(S.Class):
    name: str


@dataclass(frozen=True)
class _GetItem(persistable.Class(success=_Item, error=PersistenceError)):
    id: int

    def primary_key(self) -> str:
        return f"item:{self.id}"


def _persistence_use(*, fresh: bool) -> Callable[[], fx.Effect[Any, Any, Any]]:
    def body():
        store = yield from (yield from persistence.Persistence()).make(store_id="layer_reuse")
        if fresh:
            assert (yield from store.get(_GetItem(1))) is None
        yield from store.set(_GetItem(1), fx.exit.succeed(_Item(name="a")))
        assert (yield from store.get(_GetItem(1))) == fx.exit.succeed(_Item(name="a"))

    return _gen(body)


class _Text(TypedDict):
    s: str


_TEXT = S.Struct(_Text)


def _offer_take():
    queue = yield from pq.make(name="layer-reuse", schema=_TEXT)
    yield from queue.offer({"s": "hello"})
    taken = yield from queue.take(lambda value, _meta: fx.succeed(value))
    assert taken == {"s": "hello"}


def _queue_store_use() -> fx.Effect[Any, Any, Any]:
    """Offer then take through a factory over the store under test."""
    return fx.gen(_offer_take).pipe(fx.provide(pq.layer))


def _consume(*, fresh: bool) -> Callable[[], fx.Effect[Any, Any, Any]]:
    """One token of a bucket; a ``fresh`` store has the whole bucket."""

    def body():
        limiter = yield from rl.RateLimiter()
        result = yield from limiter.consume(key="layer-reuse", limit=1000, window=60)
        assert result.remaining == 999 if fresh else result.remaining >= 0

    return _gen(body)


def _rate_store_use(*, fresh: bool) -> Callable[[], fx.Effect[Any, Any, Any]]:
    consume = _consume(fresh=fresh)
    return lambda: consume().pipe(fx.provide(rl.layer))


def _breaker() -> AnyLayer:
    return cb.layer(trip_policy=cb.consecutive(5), open_duration=60)


def _execute():
    breaker = yield from cb.CircuitBreaker()
    assert (yield from fx.succeed(1).pipe(breaker.execute(key="layer-reuse"))) == 1


def _breaker_store_use() -> fx.Effect[Any, Any, Any]:
    return fx.gen(_execute).pipe(fx.provide(_breaker()))


def _redis_set_get():
    redis = yield from Redis()
    yield from redis.send("SET", "layer-reuse", "value")
    assert (yield from redis.send("GET", "layer-reuse")) == "value"


def _home():
    directories = yield from ud.UserDirectories()
    assert (yield from directories.home)


def _config_directory():
    directories = yield from ud.UserDirectories()
    assert (yield from directories.config("layer-reuse")).endswith("layer-reuse")


def _redis_and_prefix(prefix: str) -> Callable[[], AnyLayer]:
    return lambda: fx.layer.merge(_redis_client(), _provider(PREFIX=prefix))


_PREFIX = {"prefix": config.string("PREFIX")}
_PLATFORM = fx.layer.merge(file_system.layer, path.layer)

_PERSISTENCE: dict[str, Case] = {
    "pyfect.persistence.key_value_store.layer_memory": Case(
        layer=lambda: kvs.layer_memory, use=_kv_use(fresh=True)
    ),
    "pyfect.persistence.key_value_store.layer_storage": Case(
        layer=lambda: kvs.layer_storage(dict), use=_kv_use(fresh=True)
    ),
    "pyfect.persistence.key_value_store.layer_file_system": Case(
        layer=lambda: kvs.layer_file_system(_temporary_directory()),
        needs=lambda: _PLATFORM,
        use=_kv_use(fresh=False),
    ),
    "pyfect.persistence.key_value_store.layer_sql": Case(
        layer=kvs.layer_sql, needs=_sqlite, use=_kv_use(fresh=True)
    ),
    "pyfect.persistence.persistence.layer_backing_memory": Case(
        layer=lambda: persistence.layer_backing_memory, use=_backing_use(fresh=True)
    ),
    "pyfect.persistence.persistence.layer_backing_kvs": Case(
        layer=lambda: persistence.layer_backing_kvs,
        needs=lambda: kvs.layer_memory,
        use=_backing_use(fresh=True),
    ),
    "pyfect.persistence.persistence.layer_backing_redis": Case(
        layer=lambda: persistence.layer_backing_redis,
        needs=_redis_client,
        use=_backing_use(fresh=False),
    ),
    "pyfect.persistence.persistence.layer_backing_sql": Case(
        layer=lambda: persistence.layer_backing_sql, needs=_sqlite, use=_backing_use(fresh=True)
    ),
    "pyfect.persistence.persistence.layer_backing_sql_multi_table": Case(
        layer=lambda: persistence.layer_backing_sql_multi_table,
        needs=_sqlite,
        use=_backing_use(fresh=True),
    ),
    "pyfect.persistence.persistence.layer": Case(
        layer=lambda: persistence.layer,
        needs=lambda: persistence.layer_backing_memory,
        use=_persistence_use(fresh=True),
    ),
    "pyfect.persistence.persistence.layer_memory": Case(
        layer=lambda: persistence.layer_memory, use=_persistence_use(fresh=True)
    ),
    "pyfect.persistence.persistence.layer_kvs": Case(
        layer=lambda: persistence.layer_kvs,
        needs=lambda: kvs.layer_memory,
        use=_persistence_use(fresh=True),
    ),
    "pyfect.persistence.persistence.layer_redis": Case(
        layer=lambda: persistence.layer_redis,
        needs=_redis_client,
        use=_persistence_use(fresh=False),
    ),
    "pyfect.persistence.persistence.layer_sql": Case(
        layer=lambda: persistence.layer_sql, needs=_sqlite, use=_persistence_use(fresh=True)
    ),
    "pyfect.persistence.persistence.layer_sql_multi_table": Case(
        layer=lambda: persistence.layer_sql_multi_table,
        needs=_sqlite,
        use=_persistence_use(fresh=True),
    ),
    "pyfect.persistence.persisted_queue.layer": Case(
        layer=lambda: pq.layer, needs=lambda: pq.layer_store_memory, use=_gen(_offer_take)
    ),
    "pyfect.persistence.persisted_queue.layer_cleanup": Case(
        layer=lambda: pq.layer_cleanup(interval=60),
        needs=lambda: pq.layer.pipe(fx.layer.provide_merge(pq.layer_store_memory)),
        use=_gen(_offer_take),
    ),
    "pyfect.persistence.persisted_queue.layer_store_memory": Case(
        layer=lambda: pq.layer_store_memory, use=_queue_store_use
    ),
    "pyfect.persistence.persisted_queue.layer_store_redis": Case(
        layer=lambda: pq.layer_store_redis(
            prefix="layer-reuse-q:", poll_interval=0.05, lock_refresh_interval=0.1
        ),
        needs=_redis_client,
        use=_queue_store_use,
    ),
    "pyfect.persistence.persisted_queue.layer_store_sql": Case(
        layer=lambda: pq.layer_store_sql(poll_interval=0.05),
        needs=_sqlite,
        use=_queue_store_use,
    ),
    "pyfect.persistence.rate_limiter.layer": Case(
        layer=lambda: rl.layer, needs=lambda: rl.layer_store_memory, use=_consume(fresh=True)
    ),
    "pyfect.persistence.rate_limiter.layer_store_memory": Case(
        layer=lambda: rl.layer_store_memory, use=_rate_store_use(fresh=True)
    ),
    "pyfect.persistence.rate_limiter.layer_store_redis": Case(
        layer=lambda: rl.layer_store_redis(prefix="layer-reuse-rl:"),
        needs=_redis_client,
        use=_rate_store_use(fresh=False),
    ),
    "pyfect.persistence.rate_limiter.layer_store_redis_config": Case(
        layer=lambda: rl.layer_store_redis_config(_PREFIX),
        needs=_redis_and_prefix("layer-reuse-rl-config:"),
        use=_rate_store_use(fresh=False),
    ),
    "pyfect.persistence.circuit_breaker.layer": Case(
        layer=_breaker, needs=cb.layer_store_memory, use=_gen(_execute)
    ),
    "pyfect.persistence.circuit_breaker.layer_store_memory": Case(
        layer=cb.layer_store_memory, use=_breaker_store_use
    ),
    "pyfect.persistence.circuit_breaker.layer_store_redis": Case(
        layer=lambda: cb.layer_store_redis(prefix="layer-reuse-cb:"),
        needs=_redis_client,
        use=_breaker_store_use,
    ),
    "pyfect.persistence.circuit_breaker.layer_store_redis_config": Case(
        layer=lambda: cb.layer_store_redis_config(_PREFIX),
        needs=_redis_and_prefix("layer-reuse-cb-config:"),
        use=_breaker_store_use,
    ),
    "pyfect.persistence.redis_py.layer": Case(layer=_redis_client, use=_gen(_redis_set_get)),
    "pyfect.persistence.redis_py.layer_config": Case(
        layer=lambda: redis_py.layer_config({"url": config.string("REDIS_URL")}),
        needs=lambda: _provider(REDIS_URL=_redis.server().url),
        use=_gen(_redis_set_get),
    ),
    "pyfect.persistence.user_directories.layer": Case(layer=lambda: ud.layer, use=_gen(_home)),
    "pyfect.persistence.user_directories.layer_platform": Case(
        layer=lambda: ud.layer_platform("linux"), use=_gen(_config_directory)
    ),
}


# --- reactivity -----------------------------------------------------------------------


def _query_reruns_on_invalidate():
    reactivity = yield from Reactivity()
    runs = [0]

    def count() -> int:
        runs[0] += 1
        return runs[0]

    results = yield from reactivity.query(["layer-reuse"], fx.sync(count))
    assert (yield from results.take()) == 1
    yield from reactivity.invalidate(["layer-reuse"])
    assert (yield from results.take()) == 2


def _atom_set_get():
    registry = yield from atom_registry.AtomRegistry()
    counter = atom.make(0)
    registry.set(counter, 1)
    assert registry.get(counter) == 1


_REACTIVITY: dict[str, Case] = {
    "pyfect.reactivity.layer": Case(
        layer=lambda: reactivity_layer, use=_gen(_query_reruns_on_invalidate)
    ),
    "pyfect.reactivity.atom_registry.layer": Case(
        layer=lambda: atom_registry.layer, use=_gen(_atom_set_get)
    ),
    "pyfect.reactivity.atom_registry.layer_options": Case(
        layer=lambda: atom_registry.layer_options(default_idle_ttl=1), use=_gen(_atom_set_get)
    ),
}


# --- eventlog -------------------------------------------------------------------------


class _KeyPayload(TypedDict):
    key: str


_Set = Ev.make("Set", primary_key=lambda p: p["key"], payload=S.Struct(_KeyPayload))
_group = G.empty.add(_Set)
_schema = EL.schema(_group)
_STORE = StoreId("default")


class _RowFields(TypedDict):
    id: str
    name: str


_Row = Row.make("row", key="id", schema=S.Struct(_RowFields))
_row_group = G.empty.add(_Row)


class _Seen(Tag[Queue[str]], key="tests/layer_cases/data/Seen"):
    """What this run's handlers saw (the primary keys they handled)."""


def _seen() -> AnyLayer:
    return fx.layer.effect(_Seen, Queue[str].unbounded())


def _record(input_: EL.HandlerInput[Any]) -> fx.Effect[None, Any, Any]:
    return _Seen().flat_map(lambda seen: seen.offer(input_.entry.primary_key)).as_void()


def _handlers() -> AnyLayer:
    return EL.group(_group, lambda h: h.handle(_Set, _record))


def _row_handlers() -> AnyLayer:
    return EL.group(_row_group, lambda h: h.handle(_Row, _record))


def _ignoring_handlers() -> AnyLayer:
    return EL.group(_group, lambda h: h.handle(_Set, lambda _: fx.void))


def _identity() -> AnyLayer:
    return fx.layer.effect(EL.Identity, EL.make_identity).pipe(fx.layer.provide(layer_subtle))


def _journal_and_identity() -> AnyLayer:
    return fx.layer.merge(J.layer_memory, _identity())


def _log() -> AnyLayer:
    """An event log (and its ``Registry``) over a memory journal."""
    return EL.layer_event_log.pipe(fx.layer.provide(_journal_and_identity()))


def _log_with_handlers(handlers: AnyLayer) -> AnyLayer:
    return handlers.pipe(fx.layer.provide_merge(fx.layer.merge(_log(), _seen())))


def _write_and_handle():
    log = yield from EL.EventLog()
    yield from log.write(_Set, {"key": "a"})
    assert (yield from (yield from _Seen()).take()) == "a"
    assert [entry.primary_key for entry in (yield from log.entries)] == ["a"]


def _replayed(event: Ev.AnyEvent, payload: Any, expected: str) -> Body:
    """A remote sends one entry of ``event``; its handler sees ``expected``."""

    def body():
        registry = yield from EL.Registry()
        changes = yield from Queue[RemoteEntry, EventLogRemoteError].unbounded()
        data = yield from S.encode_effect(event.payload_codec)(payload).or_die()
        entry = Entry(
            id=J.make_entry_id_unsafe(),
            event=event.tag,
            primary_key=event.primary_key(payload),
            payload=data,
        )
        yield from changes.offer(RemoteEntry(remote_sequence=0, entry=entry))
        yield from registry.register_remote(
            EventLogRemoteService(
                id=J.make_remote_id_unsafe(),
                changes=lambda **_: fx.succeed(changes),
                write=lambda **_: fx.succeed(None),
            )
        )
        assert (yield from (yield from _Seen()).take()) == expected

    return body


def _compact(c: EL.Compaction) -> fx.Effect[None]:
    return fx.for_each(c.events, lambda e: c.write(e.tag, {"key": "compacted"})).as_void()


def _compact_batch(c: EL.BatchCompaction) -> fx.Effect[None]:
    return fx.for_each(c.entries, lambda _: c.write(_Set, {"key": "compacted"})).as_void()


def _registry_knows_handlers():
    registry = yield from EL.Registry()
    yield from _handlers().pipe(fx.layer.provide(_seen())).build()
    assert set(registry.handlers) == {"Set"}


def _journal_write_read():
    journal = yield from J.EventJournal()
    payload = yield from S.encode_effect(_Set.payload_codec)({"key": "a"}).or_die()
    yield from journal.write(event="Set", primary_key="a", payload=payload, effect=fx.succeed)
    assert [entry.primary_key for entry in (yield from journal.entries)] == ["a"]


def _entry() -> Generator[Any, Any, Entry]:
    payload = yield from S.encode_effect(_Set.payload_codec)({"key": "a"}).or_die()
    return Entry(id=J.make_entry_id_unsafe(), event="Set", primary_key="a", payload=payload)


def _encrypt_decrypt():
    encryption = yield from EventLogEncryption()
    identity = yield from encryption.generate_identity
    entry = yield from _entry()
    batches = yield from encryption.encrypt(identity, _STORE, [entry])
    remote = [Enc.remote_batch(0, batch) for batch in batches]
    [decrypted] = yield from encryption.decrypt(identity, _STORE, remote)
    assert decrypted.entry.id == entry.id


def _encrypted_storage_round_trip():
    storage = yield from Enc.Storage()
    encryption = yield from EventLogEncryption()
    identity = yield from encryption.generate_identity
    entry = yield from _entry()
    batches = yield from encryption.encrypt(identity, _STORE, [entry])
    yield from storage.write(identity.public_key, _STORE, batches)
    acks = yield from storage.entry_sequences(identity.public_key, _STORE, [entry.id])
    assert len(acks) == 1


def _with_subtle(body: Body) -> Callable[[], fx.Effect[Any, Any, Any]]:
    return lambda: fx.gen(body).pipe(fx.provide(layer_subtle))


def _unencrypted_storage_round_trip():
    storage = yield from Unenc.Storage()
    store = StoreId(f"layer-reuse-{J.make_remote_id_unsafe().hex()}")
    entry = yield from _entry()
    written = yield from storage.write(store, [entry])
    assert [remote.entry.id for remote in written] == [entry.id]
    assert (yield from storage.get_id)


class _AllowAll(Unenc.EventLogServerAuthorizationService):
    def authorize_write(self, **_: Any) -> fx.Effect[None, Unenc.EventLogServerAuthError]:
        return fx.void

    def authorize_read(self, **_: Any) -> fx.Effect[None, Unenc.EventLogServerAuthError]:
        return fx.void

    def authorize_identity(self, **_: Any) -> fx.Effect[None, Unenc.EventLogServerAuthError]:
        return fx.void


def _unencrypted_server_services() -> AnyLayer:
    return fx.layer.merge(
        Unenc.layer_storage_memory,
        Unenc.layer_store_mapping_static(store_id=_STORE),
        fx.layer.succeed(Unenc.EventLogServerAuthorization, _AllowAll()),
    )


def _server_transport() -> AnyLayer:
    """An RPC server protocol on a socket server of a free local port."""
    return rpc_server.layer_protocol_socket_server.pipe(
        fx.layer.provide_merge(socket_server.layer(0, "127.0.0.1"))
    ).pipe(fx.layer.provide(rs.layer_ndjson))


def _client_protocol() -> AnyLayer:
    """An RPC client protocol connected to the ``SocketServer``."""
    port = SocketServer().map(lambda s: fx_socket.layer_net(s.address.port, "127.0.0.1"))  # pyright: ignore[reportAttributeAccessIssue]
    return (
        rpc_client.layer_protocol_socket()
        .pipe(fx.layer.provide(fx.layer.unwrap(port)))
        .pipe(fx.layer.provide(rs.layer_ndjson))
    )


def _encrypted_server() -> AnyLayer:
    return Enc.layer.pipe(fx.layer.provide_merge(_server_transport())).pipe(
        fx.layer.provide(Enc.layer_storage_memory)
    )


def _unencrypted_server() -> AnyLayer:
    return (
        Unenc.layer(_schema, _ignoring_handlers())
        .pipe(fx.layer.provide_merge(_server_transport()))
        .pipe(fx.layer.provide(_unencrypted_server_services()))
    )


def _connected(server: AnyLayer) -> AnyLayer:
    """A client protocol to ``server`` and a ``Registry`` for a remote."""
    return fx.layer.merge(_client_protocol().pipe(fx.layer.provide(server)), EL.layer_registry)


def _remote_write():
    remote = yield from Remote.EventLogRemote()
    identity = yield from EL.make_identity.pipe(fx.provide(layer_subtle))
    entry = yield from _entry()
    acks = yield from remote.write(identity=identity, store_id=_STORE, entries=[entry])
    assert acks is not None
    assert len(acks) == 1


def _over_socket(remote: AnyLayer) -> Callable[[], fx.Effect[Any, Any, Any]]:
    """The remote ``remote`` over a client protocol to the server in the
    context (its ``SocketServer``) writes an entry."""
    layer = remote.pipe(fx.layer.provide(fx.layer.merge(_client_protocol(), EL.layer_registry)))
    return lambda: fx.gen(_remote_write).pipe(fx.provide(layer))


def _over_handlers(make: fx.Effect[EventLogRemoteService, Any, Any]) -> Body:
    """A remote calling the handlers in the context directly writes an
    entry."""

    def body():
        client = yield from rpc_test.make_client(M.EventLogRemoteRpcs)
        remote = yield from make.pipe(fx.provide_service(Remote.EventLogRemoteClient, client)).pipe(
            fx.provide(fx.layer.merge(layer_subtle, EL.layer_registry))
        )
        yield from fx.gen(_remote_write).pipe(fx.provide_service(Remote.EventLogRemote, remote))

    return body


def _hello():
    client = yield from Remote.EventLogRemoteClient()
    hello = yield from client.hello()
    assert hello.remote_id


_REMOTE_ID = J.make_remote_id_unsafe()


def _no_writes(*_: Any) -> fx.Effect[Any, Any]:
    return fx.succeed(())


def _no_changes(*_: Any) -> Any:
    return fx.stream.empty


def _no_latest_sequence(*_: Any) -> fx.Effect[int | None, Any]:
    return fx.succeed(None)


def _hello_handlers():
    client = yield from rpc_test.make_client(M.EventLogRemoteRpcs)
    hello = yield from client.hello()
    assert hello.remote_id == _REMOTE_ID
    assert hello.challenge


def _store_mapping_resolves():
    mapping = yield from Unenc.StoreMapping()
    assert (yield from mapping.resolve(public_key="pk", store_id=_STORE)) == _STORE


def _server_write():
    yield from _ignoring_handlers().build()
    write = yield from Unenc.make_write(_schema)
    yield from write(store_id=_STORE, event=_Set, payload={"key": "a"})
    storage = yield from Unenc.Storage()
    written = yield from storage.changes(_STORE, 0, {}).take(1).run_collect()
    assert [remote.entry.primary_key for remote in written] == ["a"]


def _authentication_service():
    assert callable((yield from Server.EventLogAuthentication()))


_EVENTLOG: dict[str, Case] = {
    "pyfect.eventlog.event_journal.layer_memory": Case(
        layer=lambda: J.layer_memory, use=_gen(_journal_write_read)
    ),
    "pyfect.eventlog.sql_event_journal.layer": Case(
        layer=SqlJournal.layer, needs=_sqlite, use=_gen(_journal_write_read)
    ),
    "pyfect.eventlog.event_log_encryption.layer_subtle": Case(
        layer=lambda: layer_subtle, use=_gen(_encrypt_decrypt)
    ),
    "pyfect.eventlog.event_log.layer_registry": Case(
        layer=lambda: EL.layer_registry, use=_gen(_registry_knows_handlers)
    ),
    "pyfect.eventlog.event_log.layer_event_log": Case(
        layer=lambda: EL.layer_event_log,
        needs=_journal_and_identity,
        use=lambda: fx.gen(_write_and_handle).pipe(
            fx.provide(_handlers().pipe(fx.layer.provide_merge(_seen())))
        ),
    ),
    "pyfect.eventlog.event_log.layer": Case(
        layer=lambda: EL.layer(_schema, _handlers()),
        needs=lambda: fx.layer.merge(_journal_and_identity(), _seen()),
        use=_gen(_write_and_handle),
    ),
    "pyfect.eventlog.event_log.group": Case(
        layer=_handlers,
        needs=lambda: fx.layer.merge(_log(), _seen()),
        use=_gen(_write_and_handle),
    ),
    "pyfect.eventlog.event_log.group_reactivity": Case(
        layer=lambda: EL.group_reactivity(_group, ["layer-reuse"]),
        needs=lambda: _log_with_handlers(_handlers()),
        use=_gen(_write_and_handle),
    ),
    "pyfect.eventlog.event_log.group_compaction": Case(
        layer=lambda: EL.group_compaction(_group, _compact),
        needs=lambda: _log_with_handlers(_handlers()),
        use=_gen(_replayed(_Set, {"key": "a"}, "compacted")),
    ),
    "pyfect.eventlog.event_log.group_batch_compaction": Case(
        layer=lambda: EL.group_batch_compaction(_group, _compact_batch),
        needs=lambda: _log_with_handlers(_handlers()),
        use=_gen(_replayed(_Set, {"key": "a"}, "compacted")),
    ),
    "pyfect.eventlog.event_row.compaction": Case(
        layer=lambda: Row.compaction(_row_group, _Row),
        needs=lambda: _log_with_handlers(_row_handlers()),
        use=_gen(_replayed(_Row, _Row.set({"id": "r1", "name": "x"}).payload, "r1")),
    ),
    "pyfect.eventlog.event_log_server_encrypted.layer_storage_memory": Case(
        layer=lambda: Enc.layer_storage_memory,
        use=_with_subtle(_encrypted_storage_round_trip),
    ),
    "pyfect.eventlog.sql_event_log_server_encrypted.layer_storage": Case(
        layer=SqlEnc.layer_storage,
        needs=lambda: fx.layer.merge(_sqlite(), layer_subtle),
        use=_with_subtle(_encrypted_storage_round_trip),
    ),
    "pyfect.eventlog.sql_event_log_server_encrypted.layer_storage_subtle": Case(
        layer=SqlEnc.layer_storage_subtle,
        needs=_sqlite,
        use=_with_subtle(_encrypted_storage_round_trip),
    ),
    "pyfect.eventlog.event_log_server_unencrypted.layer_storage_memory": Case(
        layer=lambda: Unenc.layer_storage_memory, use=_gen(_unencrypted_storage_round_trip)
    ),
    "pyfect.eventlog.sql_event_log_server_unencrypted.layer_storage": Case(
        layer=SqlUnenc.layer_storage, needs=_sqlite, use=_gen(_unencrypted_storage_round_trip)
    ),
    "pyfect.eventlog.event_log_server_unencrypted.layer_store_mapping_static": Case(
        layer=lambda: Unenc.layer_store_mapping_static(store_id=_STORE),
        use=_gen(_store_mapping_resolves),
    ),
    "pyfect.eventlog.event_log_server_unencrypted.layer_server": Case(
        layer=lambda: Unenc.layer_server,
        needs=lambda: Unenc.layer_storage_memory,
        use=_gen(_server_write),
    ),
    "pyfect.eventlog.event_log_server.layer_auth_middleware": Case(
        layer=lambda: Server.layer_auth_middleware, use=_gen(_authentication_service)
    ),
    "pyfect.eventlog.event_log_server.layer_rpc_handlers": Case(
        layer=lambda: Server.layer_rpc_handlers(
            remote_id=_REMOTE_ID,
            get_or_create_session_auth_binding=lambda _key, signing: fx.succeed(signing),
            on_write=_no_writes,
            changes=_no_changes,
            latest_sequence=_no_latest_sequence,
        ),
        use=_gen(_hello_handlers),
    ),
    "pyfect.eventlog.event_log_server_encrypted.layer_rpc_handlers": Case(
        layer=lambda: Enc.layer_rpc_handlers,
        needs=lambda: Enc.layer_storage_memory,
        use=_gen(_over_handlers(Remote.make_encrypted)),
    ),
    "pyfect.eventlog.event_log_server_unencrypted.layer_rpc_handlers": Case(
        layer=lambda: Unenc.layer_rpc_handlers,
        needs=lambda: fx.layer.merge(_unencrypted_server_services(), EL.layer_registry),
        use=_gen(_over_handlers(Remote.make_unencrypted)),
    ),
    "pyfect.eventlog.event_log_server_unencrypted.layer_no_rpc_server": Case(
        layer=lambda: Unenc.layer_no_rpc_server(_schema, _ignoring_handlers()),
        needs=_unencrypted_server_services,
        use=_gen(_over_handlers(Remote.make_unencrypted)),
    ),
    "pyfect.eventlog.event_log_server_encrypted.layer": Case(
        layer=lambda: Enc.layer,
        needs=lambda: fx.layer.merge(_server_transport(), Enc.layer_storage_memory),
        use=_over_socket(Remote.layer_encrypted),
    ),
    "pyfect.eventlog.event_log_server_unencrypted.layer": Case(
        layer=lambda: Unenc.layer(_schema, _ignoring_handlers()),
        needs=lambda: fx.layer.merge(_server_transport(), _unencrypted_server_services()),
        use=_over_socket(Remote.layer_unencrypted),
    ),
    "pyfect.eventlog.event_log_remote.layer_client": Case(
        layer=lambda: Remote.layer_client,
        needs=lambda: _client_protocol().pipe(fx.layer.provide(_encrypted_server())),
        use=_gen(_hello),
    ),
    "pyfect.eventlog.event_log_remote.layer_encrypted": Case(
        layer=lambda: Remote.layer_encrypted,
        needs=lambda: _connected(_encrypted_server()),
        use=_gen(_remote_write),
    ),
    "pyfect.eventlog.event_log_remote.layer_unencrypted": Case(
        layer=lambda: Remote.layer_unencrypted,
        needs=lambda: _connected(_unencrypted_server()),
        use=_gen(_remote_write),
    ),
}

CASES: dict[str, Case] = {**_SQL, **_PERSISTENCE, **_REACTIVITY, **_EVENTLOG}
SKIPPED: dict[str, str] = {}
