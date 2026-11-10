"""Ports of Effect's ``effect/test/eventlog/EventLogServerEncryptedTest.ts``
suite, run on the memory storage (``EventLogServerEncrypted.test.ts``), the
SQLite storage (``sql-sqlite-node``), the PostgreSQL storage (``sql-pg``,
skipped without a local server), and the MySQL and SQL Server storages
(``sql-mysql2``, ``sql-mssql``, skipped without Docker). Each test's
docstring is the Effect test title.

Effect's counting WebCrypto proxy is a counting ``AesGcm`` given to
``make_encryption_subtle``. Frames are JSON, so the man in the middle
rewrites an entry id's base64 text rather than its raw bytes.
"""

import base64
import itertools
import os
from collections.abc import Callable, Generator, Sequence
from typing import Any

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.context import Context
from pyfect.crypto import digest
from pyfect.eventlog import event_journal as J
from pyfect.eventlog import event_log as L
from pyfect.eventlog import event_log_message as M
from pyfect.eventlog import event_log_server_encrypted as Server
from pyfect.eventlog import sql_event_log_server_encrypted as SqlServer
from pyfect.eventlog.event_journal import Entry, RemoteEntry, StoreId
from pyfect.eventlog.event_log_encryption import (
    EventLogEncryption,
    layer_subtle,
    make_encryption_subtle,
)
from pyfect.eventlog.event_log_remote import EventLogRemoteClient, make_encrypted
from pyfect.reactivity import layer as reactivity_layer
from pyfect.rpc import test as rpc_test
from pyfect.sql import sqlite
from pyfect.sql.client import SqlClient

from ._counting_web_crypto import CountingWebCrypto
from ._postgres import PgServer

store_id = StoreId("store-a")
other_store_id = StoreId("store-b")


def make_entries(count: int) -> list[Entry]:
    return [
        Entry(
            id=J.make_entry_id_unsafe(),
            event="UserCreated",
            primary_key=f"user-{i}",
            payload=bytes([i % 256, 1, 2, 3]),
        )
        for i in range(count)
    ]


CountingAesGcm = CountingWebCrypto


class _Intercepted:
    """A man in the middle on one connection: it can rewrite change
    requests and the frames the server sends back."""

    def __init__(
        self,
        client: M.EventLogRemoteRpcs,
        store: StoreId | None,
        frame: Callable[[bytes], bytes] | None,
    ) -> None:
        self._client = client
        self._store = store
        self._frame = frame
        self.hello = client.hello
        self.authenticate = client.authenticate
        self.write_single = client.write_single
        self.write_chunked = client.write_chunked

    def changes(
        self, payload: M.ChangesPayload, *, as_queue: bool = True
    ) -> fx.Effect[Any, Any, Any]:
        def run():
            incoming = yield from self._client.changes(
                {**payload, "store_id": self._store or payload["store_id"]}, as_queue=True
            )
            outgoing = yield from fx.Queue[Any, Any].unbounded()

            def rewrite(part: Any) -> Any:
                if isinstance(part, M.SingleMessage) and self._frame is not None:
                    return M.SingleMessage(data=self._frame(part.data))
                return part

            yield from (
                incoming.take_all()
                .flat_map(lambda parts: outgoing.offer_all([rewrite(p) for p in parts]))
                .forever()
                .catch_cause(outgoing.fail_cause)
                .fork_scoped()
            )
            return outgoing

        return fx.gen(run)


def _replace_id(data: bytes, original: bytes, forged: bytes) -> bytes:
    def b64(value: bytes) -> bytes:
        return base64.b64encode(value)

    assert b64(original) in data, "the frame carries the entry id in plaintext"
    return data.replace(b64(original), b64(forged))


class Device:
    def __init__(self, remote: Any, identity: L.IdentityService, counts: CountingAesGcm) -> None:
        self._remote = remote
        self._identity = identity
        self.counts = counts

    def write(self, entries: Sequence[Entry], store: StoreId = store_id) -> fx.Effect[Any, Any]:
        return self._remote.write(identity=self._identity, store_id=store, entries=entries)

    def changes(
        self, start_sequence: int, store: StoreId = store_id
    ) -> fx.Effect[fx.Queue[RemoteEntry, Any], Any, Any]:
        return self._remote.changes(
            identity=self._identity, store_id=store, start_sequence=start_sequence
        )


def make_server() -> Generator[Any, Any, Callable[..., fx.Effect[Device, Any, Any]]]:
    handlers: Context[Any] = yield from Server.layer_rpc_handlers.build()
    identity = yield from L.make_identity

    # Each device is a separate connection for the same identity.
    def make_device(
        store: StoreId | None = None, frame: Callable[[bytes], bytes] | None = None
    ) -> fx.Effect[Device, Any, Any]:
        def run():
            counts = CountingAesGcm()
            client: Any = yield from rpc_test.make_client(M.EventLogRemoteRpcs).pipe(
                fx.provide(handlers)
            )
            if store is not None or frame is not None:
                client = _Intercepted(client, store, frame)
            encryption = yield from make_encryption_subtle(counts)
            remote = (
                yield from make_encrypted.pipe(fx.provide_service(EventLogRemoteClient, client))
                .pipe(fx.provide_service(EventLogEncryption, encryption))
                .pipe(fx.provide(L.layer_registry))
            )
            return Device(remote, identity, counts)

        return fx.gen(run)

    return make_device


def summarize(received: Sequence[RemoteEntry]) -> dict[str, list[Any]]:
    return {
        "ids": [r.entry.id_string for r in received],
        "primary_keys": [r.entry.primary_key for r in received],
        "payloads": [r.entry.payload.hex() for r in received],
        "sequences": [r.remote_sequence for r in received],
    }


def expected(entries: Sequence[Entry], first_sequence: int) -> dict[str, list[Any]]:
    return {
        "ids": [e.id_string for e in entries],
        "primary_keys": [e.primary_key for e in entries],
        "payloads": [e.payload.hex() for e in entries],
        "sequences": [first_sequence + i for i in range(len(entries))],
    }


_namespaces = itertools.count()


def _sql_storage(client: fx.Layer[SqlClient, Any]) -> fx.Layer[Server.Storage, Any]:
    # Own tables: the PostgreSQL server is shared by the session.
    namespace = f"encrypted_{os.getpid()}_{next(_namespaces)}"
    return (
        SqlServer.layer_storage(
            entry_table_prefix=f"effect_events_{namespace}",
            remote_id_table=f"effect_remote_id_{namespace}",
        )
        .pipe(fx.layer.provide(client))
        .pipe(fx.layer.provide(reactivity_layer))
        .pipe(fx.layer.provide(digest.layer_web_crypto))
    )


@pytest.fixture
def storage(request: pytest.FixtureRequest) -> fx.Layer[Server.Storage, Any]:
    """The memory storage, or the SQL storage on an in-memory SQLite database,
    the session's PostgreSQL server or its MySQL or SQL Server container
    (skipped without one)."""
    match request.param:
        case "memory":
            return Server.layer_storage_memory
        case "SQLite":
            return _sql_storage(sqlite.layer(sqlite.SqliteClientConfig(filename=":memory:")))
        case "pg":
            pytest.importorskip("psycopg")
            from pyfect.sql import pg

            server: PgServer = request.getfixturevalue("pg_server")
            return _sql_storage(pg.layer(pg.PgPoolConfig(url=server.url)))
        case "mssql":
            pytest.importorskip("pytds")
            from pyfect.sql import mssql

            from ._mssql import MssqlServer

            mssql_server: MssqlServer = request.getfixturevalue("mssql_server")
            return _sql_storage(mssql.layer(mssql_server.config()))
        case _:
            pytest.importorskip("asyncmy")
            from pyfect.sql import mysql

            from ._mysql import MysqlServer

            mysql_server: MysqlServer = request.getfixturevalue("mysql_server")
            return _sql_storage(mysql.layer(mysql.MysqlClientConfig(url=mysql_server.url)))


STORAGES = pytest.mark.parametrize(
    "storage", ["memory", "SQLite", "pg", "mysql2", "mssql"], indirect=True
)


def services(storage: fx.Layer[Server.Storage, Any]) -> fx.Layer[Any, Any]:
    return fx.layer.merge(storage, layer_subtle)


@STORAGES
@testing.effect
def test_encrypts_in_batches_of_100(storage: fx.Layer[Server.Storage, Any]):
    """encrypts writes in batches of at most 100 entries and replays every entry"""

    def body():
        make_device = yield from make_server()
        writer = yield from make_device()
        reader = yield from make_device()
        entries = make_entries(250)
        yield from writer.write(entries)
        changes = yield from reader.changes(0)
        received = yield from changes.take_n(250)
        assert summarize(received) == expected(entries, received[0].remote_sequence)
        assert {
            "encrypts": writer.counts.encrypts,
            "ivs": len(writer.counts.ivs),
            "decrypts": reader.counts.decrypts,
        } == {"encrypts": 3, "ivs": 3, "decrypts": 3}

    yield from fx.gen(body).pipe(fx.provide(services(storage)))


@STORAGES
@testing.effect
def test_resumes_inside_a_batch(storage: fx.Layer[Server.Storage, Any]):
    """resumes from a sequence inside a batch without repeating earlier entries"""

    def body():
        make_device = yield from make_server()
        writer = yield from make_device()
        reader = yield from make_device()
        entries = make_entries(150)
        yield from writer.write(entries)
        first = yield from fx.scoped(reader.changes(0).flat_map(lambda q: q.take()))
        first_sequence = first.remote_sequence
        reader.counts.decrypts = 0
        changes = yield from reader.changes(first_sequence + 120)
        resumed = yield from changes.take_n(30)
        [next_entry] = make_entries(1)
        yield from writer.write([next_entry])
        live = yield from changes.take()
        assert summarize(resumed) == expected(entries[120:], first_sequence + 120)
        assert summarize([live]) == expected([next_entry], first_sequence + 150)
        # One call for the batch holding entries 100 to 149, one for the live write.
        assert reader.counts.decrypts == 2

    yield from fx.gen(body).pipe(fx.provide(services(storage)))


@STORAGES
@testing.effect
def test_stores_a_retried_write_once(storage: fx.Layer[Server.Storage, Any]):
    """stores a retried write once"""

    def body():
        make_device = yield from make_server()
        writer = yield from make_device()
        reader = yield from make_device()
        entries = make_entries(3)
        # A retry after a lost response re-encrypts the same entries.
        yield from writer.write(entries[:2])
        yield from writer.write(entries[:2])
        yield from writer.write(entries[2:])
        changes = yield from reader.changes(0)
        received = yield from changes.take_n(3)
        assert summarize(received) == expected(entries, received[0].remote_sequence)

    yield from fx.gen(body).pipe(fx.provide(services(storage)))


@STORAGES
@testing.effect
def test_rejects_altered_entry_ids(storage: fx.Layer[Server.Storage, Any]):
    """rejects a batch whose plaintext entry ids were altered"""

    def body():
        make_device = yield from make_server()
        writer = yield from make_device()
        entry, forged = make_entries(2)

        def frame(data: bytes) -> bytes:
            return _replace_id(data, entry.id, forged.id)

        reader = yield from make_device(frame=frame)
        yield from writer.write([entry])
        exit = yield from reader.changes(0).flat_map(lambda q: q.take()).exit()
        assert isinstance(exit, fx.Failure)

    yield from fx.gen(body).pipe(fx.provide(services(storage)))


@STORAGES
@testing.effect
def test_rejects_batch_from_another_store(storage: fx.Layer[Server.Storage, Any]):
    """rejects a batch served from another store of the same identity"""

    def body():
        make_device = yield from make_server()
        writer = yield from make_device()
        reader = yield from make_device(store=store_id)
        yield from writer.write(make_entries(1))
        exit = yield from reader.changes(0, other_store_id).flat_map(lambda q: q.take()).exit()
        assert isinstance(exit, fx.Failure)

    yield from fx.gen(body).pipe(fx.provide(services(storage)))
