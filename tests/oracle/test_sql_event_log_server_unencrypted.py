"""Ports of Effect's ``effect/test/eventlog/SqlEventLogServerUnencryptedStorageTest.ts``
suite and of ``sql-sqlite-node/test/SqlEventLogServerUnencrypted.test.ts``,
``sql-pg/test/SqlEventLogServerUnencrypted.integration.test.ts`` and
``sql-mysql2/test/SqlEventLogServerUnencrypted.integration.test.ts``,
for ``pyfect.eventlog.sql_event_log_server_unencrypted``. The storage suite
runs on SQLite, on the session's PostgreSQL server and on its MySQL
container (each skipped without one); its
``RegressionTest`` suite runs in ``test_event_log_server_unencrypted.py``.

Each test's docstring is the Effect test title. Tables are unique per
test, since the PostgreSQL server is shared.
"""

import itertools
import re
import uuid
from collections.abc import Callable, Generator, Sequence
from typing import Any

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.eventlog import event_journal as J
from pyfect.eventlog import event_log as L
from pyfect.eventlog import event_log_message as M
from pyfect.eventlog import event_log_server_unencrypted as U
from pyfect.eventlog import sql_event_log_server_unencrypted as SqlU
from pyfect.eventlog._identity_derivation import make_get_identity_root_secret_material
from pyfect.eventlog.event_journal import Entry, RemoteEntry, StoreId
from pyfect.eventlog.event_log import RegisteredCompactor
from pyfect.eventlog.event_log_encryption import layer_subtle
from pyfect.eventlog.event_log_session_auth import SessionAuthPayload, sign_session_auth_payload
from pyfect.queue import Dequeue, Done
from pyfect.reactivity import layer as reactivity_layer
from pyfect.redacted import value as reveal
from pyfect.rpc import test as rpc_test
from pyfect.sql import sqlite
from pyfect.sql.client import SqlClient, SqlClientService
from pyfect.sql.statement import CurrentTransformer

from ._postgres import PgServer

_namespaces = itertools.count(1)


def _namespace(prefix: str) -> str:
    # Unique per session, whose tests share the PostgreSQL and MySQL servers
    # (each started for the session), and short enough for MySQL's 64
    # character names, as Effect's.
    return f"{prefix}_{next(_namespaces)}"


def make_options(prefix: str) -> dict[str, Any]:
    namespace = _namespace(prefix)
    return {
        "entry_table_prefix": f"effect_events_{namespace}",
        "remote_id_table": f"effect_remote_id_{namespace}",
        "insert_batch_size": 2,
    }


def make_store_id(prefix: str) -> StoreId:
    return StoreId(f"{_namespace(prefix)}_store")


def make_entry(name: str, primary_key: str = "user-1") -> Entry:
    return Entry(
        id=J.make_entry_id_unsafe(),
        event="UserNameSet",
        primary_key=primary_key,
        payload=name.encode(),
    )


type Connect = Callable[[], fx.Effect[SqlClientService, Any, Any]]


def _client() -> fx.Effect[SqlClientService, Any, Any]:
    return sqlite.make(sqlite.SqliteClientConfig(filename=":memory:"))


@pytest.fixture(params=["sqlite", "pg", "mysql2"])
def connect(request: pytest.FixtureRequest) -> Connect:
    """A new client of an in-memory SQLite database, or a new pool on the
    session's PostgreSQL server or MySQL container (skipped without one)."""
    if request.param == "sqlite":
        return _client
    if request.param == "pg":
        pytest.importorskip("psycopg")
        from pyfect.sql import pg

        server: PgServer = request.getfixturevalue("pg_server")
        return lambda: pg.make(pg.PgPoolConfig(url=server.url))
    pytest.importorskip("asyncmy")
    from pyfect.sql import mysql

    from ._mysql import MysqlServer

    mysql_server: MysqlServer = request.getfixturevalue("mysql_server")
    return lambda: mysql.make(mysql.MysqlClientConfig(url=mysql_server.url))


def make_storage(sql: SqlClientService, **options: Any) -> fx.Effect[U.StorageService, Any, Any]:
    return SqlU.make_storage(**options).pipe(fx.provide_service(SqlClient, sql)).or_die()


def open_changes(
    storage: U.StorageService, store_id: StoreId
) -> fx.Effect[Dequeue[RemoteEntry, Done[None]], Any, Any]:
    return storage.changes(store_id, 0, {}).to_queue(capacity="unbounded")


def assert_entries(
    rows: Sequence[RemoteEntry], expected: Sequence[Entry], start_sequence: int
) -> None:
    assert [r.remote_sequence for r in rows] == [start_sequence + i for i in range(len(expected))]
    assert [r.entry.id_string for r in rows] == [e.id_string for e in expected]


def assert_drained(changes: Dequeue[RemoteEntry, Done[None]]) -> Generator[Any, Any]:
    yield from fx.yield_now()
    assert (yield from changes.poll()) is None


def _first(changes: Dequeue[RemoteEntry, Done[None]], backlog: Entry) -> Generator[Any, Any]:
    assert_entries([(yield from changes.take())], [backlog], 1)


def _run(body: Callable[[], Generator[Any, Any, Any]]) -> fx.Effect[Any, Any, Any]:
    return fx.gen(body).pipe(fx.provide(reactivity_layer))


def write_with_held_publication(
    sql: SqlClientService,
    storage: U.StorageService,
    store_id: StoreId,
    entries: Sequence[Entry],
) -> Generator[Any, Any, fx.Effect[Any, Any, Any]]:
    """Writes ``entries`` in a caller-owned transaction whose earlier
    after-commit callback holds it between COMMIT and the storage's
    publication until the returned effect runs."""
    committed = yield from fx.Deferred[None].make()
    released = yield from fx.Deferred[None].make()

    def transaction():
        yield from sql.after_commit(committed.succeed(None).and_then(released.wait()))
        yield from storage.write(store_id, entries)

    writer = yield from sql.with_transaction(fx.gen(transaction)).fork()
    yield from committed.wait()
    return released.succeed(None).and_then(writer.join())


@testing.live(timeout="30 seconds")
def test_persists_remote_id_across_storage_instances(connect: Connect):
    """SqlEventLogServerUnencrypted / persists remote id across storage instances"""

    def body():
        sql = yield from connect()
        options = make_options("remote_id")
        storage_a = yield from make_storage(sql, **options)
        storage_b = yield from make_storage(sql, **options)
        assert (yield from storage_a.get_id) == (yield from storage_b.get_id)

    yield from _run(body)


@testing.live(timeout="30 seconds")
def test_starts_over_existing_entries_with_long_primary_keys(connect: Connect):
    """SqlEventLogServerUnencrypted / starts over existing entries with long primary keys"""

    def body():
        sql = yield from connect()
        options = make_options("long_keys")
        table = sql.identifier(options["entry_table_prefix"])
        # The entries table as created before any secondary index existed.
        if sql.dialect == "pg":
            yield from sql(
                "CREATE TABLE {} (store_id TEXT NOT NULL, sequence BIGINT NOT NULL, "
                "entry_id BYTEA NOT NULL, event TEXT NOT NULL, primary_key TEXT NOT NULL, "
                "payload BYTEA NOT NULL, PRIMARY KEY (store_id, sequence), "
                "UNIQUE (store_id, entry_id))",
                table,
            )
        elif sql.dialect == "mysql":
            yield from sql(
                "CREATE TABLE {} (store_id VARCHAR(191) NOT NULL, sequence BIGINT NOT NULL, "
                "entry_id BINARY(16) NOT NULL, event TEXT NOT NULL, primary_key TEXT NOT NULL, "
                "payload BLOB NOT NULL, PRIMARY KEY (store_id, sequence), "
                "UNIQUE (store_id, entry_id))",
                table,
            )
        else:
            yield from sql(
                "CREATE TABLE {} (store_id TEXT NOT NULL, sequence INTEGER NOT NULL, "
                "entry_id BLOB NOT NULL, event TEXT NOT NULL, primary_key TEXT NOT NULL, "
                "payload BLOB NOT NULL, PRIMARY KEY (store_id, sequence), "
                "UNIQUE (store_id, entry_id))",
                table,
            )

        def long_key() -> str:
            return "".join(str(uuid.uuid4()) for _ in range(125))

        existing = make_entry("Ada", long_key())
        yield from sql(
            "INSERT INTO {} {}",
            table,
            sql.insert(
                {
                    "store_id": make_store_id("long_keys_existing"),
                    "sequence": 1,
                    "entry_id": existing.id,
                    "event": existing.event,
                    "primary_key": existing.primary_key,
                    "payload": existing.payload,
                }
            ),
        )
        storage = yield from make_storage(sql, **options)
        written = yield from storage.write(
            make_store_id("long_keys"), [make_entry("Grace", long_key())]
        )
        assert [r.remote_sequence for r in written] == [1]

    yield from _run(body)


@testing.live(timeout="30 seconds")
def test_replays_backlog_then_streams_live_changes(connect: Connect):
    """SqlEventLogServerUnencrypted / replays backlog and then streams live changes without
    startup duplication"""

    def body():
        sql = yield from connect()
        storage = yield from make_storage(sql, **make_options("changes_backlog_then_live"))
        store_id = make_store_id("changes")
        entry_a, entry_b, entry_c = make_entry("Ada"), make_entry("Grace"), make_entry("Margaret")
        yield from storage.write(store_id, [entry_a, entry_b])
        changes = yield from open_changes(storage, store_id)
        replayed = yield from changes.take_all()
        assert_entries(replayed, [entry_a, entry_b], 1)
        yield from storage.write(store_id, [entry_c])
        assert_entries([(yield from changes.take())], [entry_c], 3)
        yield from assert_drained(changes)

    yield from _run(body)


@testing.live(timeout="30 seconds")
def test_handles_the_changes_startup_race(connect: Connect):
    """SqlEventLogServerUnencrypted / handles the changes startup race without losing or
    duplicating rows"""

    def body():
        sql = yield from connect()
        storage = yield from make_storage(sql, **make_options("changes_startup_race"))
        for iteration in range(5):
            store_id = make_store_id(f"startup_race_{iteration}")
            backlog_entry = make_entry(f"Ada_{iteration}")
            raced_entry = make_entry(f"Grace_{iteration}")
            yield from storage.write(store_id, [backlog_entry])
            changes_fiber = yield from open_changes(storage, store_id).fork()
            yield from storage.write(store_id, [raced_entry])
            changes = yield from changes_fiber.join()
            first = yield from changes.take()
            second = yield from changes.take()
            assert_entries([first, second], [backlog_entry, raced_entry], 1)
            yield from assert_drained(changes)

    yield from _run(body)


@testing.live(timeout="30 seconds")
def test_isolates_reads_and_streams_between_stores(connect: Connect):
    """SqlEventLogServerUnencrypted / isolates reads and streams between stores"""

    def body():
        sql = yield from connect()
        storage = yield from make_storage(sql, **make_options("store_isolation"))
        store_a, store_b = make_store_id("isolation_a"), make_store_id("isolation_b")
        entry_a1, entry_b1 = make_entry("Ada"), make_entry("Grace")
        entry_a2, entry_b2 = make_entry("Margaret"), make_entry("Linus")
        yield from storage.write(store_a, [entry_a1])
        yield from storage.write(store_b, [entry_b1])
        changes_a = yield from open_changes(storage, store_a)
        backlog_a = yield from changes_a.take_all()
        assert [r.entry.id_string for r in backlog_a] == [entry_a1.id_string]
        yield from storage.write(store_b, [entry_b2])
        yield from assert_drained(changes_a)
        yield from storage.write(store_a, [entry_a2])
        assert_entries([(yield from changes_a.take())], [entry_a2], 2)

    yield from _run(body)


@testing.live(timeout="30 seconds")
def test_commits_outer_writes_but_discards_a_caught_nested_rollback(connect: Connect):
    """SqlEventLogServerUnencrypted / commits outer writes but discards a caught nested
    rollback and its notifications"""

    def body():
        sql = yield from connect()
        storage = yield from make_storage(sql, **make_options("nested_rollback"))
        store_id = make_store_id("nested_rollback")
        backlog, before, rolled_back = (
            make_entry("Ada"),
            make_entry("Grace"),
            make_entry("Margaret"),
        )
        after, sentinel = make_entry("Linus"), make_entry("Barbara")
        yield from storage.write(store_id, [backlog])
        changes = yield from open_changes(storage, store_id)
        yield from _first(changes, backlog)

        def nested():
            yield from storage.write(store_id, [rolled_back])
            return (yield from fx.fail("nested rollback"))

        def outer():
            yield from storage.write(store_id, [before])
            error = yield from storage.with_transaction(fx.gen(nested)).flip()
            assert error == "nested rollback"
            yield from storage.write(store_id, [after])

        yield from storage.with_transaction(fx.gen(outer))
        # The sentinel exposes leaked notifications without sleeps.
        yield from storage.write(store_id, [sentinel])
        assert_entries((yield from changes.take_n(3)), [before, after, sentinel], 2)
        yield from assert_drained(changes)
        persisted = yield from (yield from open_changes(storage, store_id)).take_all()
        assert_entries(persisted, [backlog, before, after, sentinel], 1)

    yield from _run(body)


@testing.live(timeout="30 seconds")
def test_persists_and_streams_multiple_successful_transaction_levels(connect: Connect):
    """SqlEventLogServerUnencrypted / persists and streams multiple successful transaction
    levels in write order exactly once"""

    def body():
        sql = yield from connect()
        storage = yield from make_storage(sql, **make_options("multiple_nesting"))
        store_id = make_store_id("multiple_nesting")
        backlog, outer_entry, nested_entry = (
            make_entry("Ada"),
            make_entry("Grace"),
            make_entry("Margaret"),
        )
        deepest, after, sentinel = make_entry("Linus"), make_entry("Barbara"), make_entry("Donald")
        yield from storage.write(store_id, [backlog])
        changes = yield from open_changes(storage, store_id)
        yield from _first(changes, backlog)

        def nested():
            yield from storage.write(store_id, [nested_entry])
            yield from storage.with_transaction(storage.write(store_id, [deepest]))

        def outer():
            yield from storage.write(store_id, [outer_entry])
            yield from storage.with_transaction(fx.gen(nested))
            yield from storage.write(store_id, [after])

        yield from storage.with_transaction(fx.gen(outer))
        yield from storage.write(store_id, [sentinel])
        assert_entries(
            (yield from changes.take_n(5)), [outer_entry, nested_entry, deepest, after, sentinel], 2
        )
        yield from assert_drained(changes)
        persisted = yield from (yield from open_changes(storage, store_id)).take_all()
        assert_entries(persisted, [backlog, outer_entry, nested_entry, deepest, after, sentinel], 1)

    yield from _run(body)


def pausing_client(
    sql: SqlClientService, completed: fx.Deferred[None], release: fx.Deferred[None]
) -> tuple[SqlClientService, list[bool], list[bool]]:
    """``sql`` whose next ``with_transaction`` after ``pause[0] = True``
    completes ``completed`` and waits for ``release`` once its transaction
    completes; each ``with_transaction`` appends to ``entered``."""
    pause = [False]
    entered: list[bool] = []
    base = type(sql)

    class Pausing(base):
        __slots__ = ()

        def with_transaction(self, effect: fx.Effect[Any, Any, Any]) -> fx.Effect[Any, Any, Any]:
            def run() -> fx.Effect[Any, Any, Any]:
                entered.append(True)
                paused = pause[0]
                pause[0] = False
                hold = completed.succeed(None).and_then(release.wait()) if paused else fx.void
                return base.with_transaction(self, effect).tap(lambda _: hold)

            return fx.suspend(run)

    pausing = object.__new__(Pausing)
    for cls in base.__mro__:
        for slot in getattr(cls, "__slots__", ()):
            if hasattr(sql, slot):
                object.__setattr__(pausing, slot, getattr(sql, slot))
    return pausing, pause, entered


@testing.live(timeout="30 seconds")
def test_streams_concurrent_sibling_transactions_in_sequence_order(connect: Connect):
    """SqlEventLogServerUnencrypted / streams concurrent sibling transactions in sequence
    order exactly once"""

    def body():
        sql = yield from connect()
        completed = yield from fx.Deferred[None].make()
        release = yield from fx.Deferred[None].make()
        # Pause after savepoint completion releases the SQL permit.
        delayed, pause, _ = pausing_client(sql, completed, release)
        storage = yield from make_storage(delayed, **make_options("sibling_ordering"))
        store_id = make_store_id("sibling_ordering")
        backlog, first, second, sentinel = (
            make_entry("Ada"),
            make_entry("Grace"),
            make_entry("Margaret"),
            make_entry("Linus"),
        )
        yield from storage.write(store_id, [backlog])
        changes = yield from open_changes(storage, store_id)
        yield from _first(changes, backlog)

        def outer():
            pause[0] = True
            writer = yield from storage.write(store_id, [first]).fork()
            yield from completed.wait()
            yield from storage.write(store_id, [second]).ensuring(release.succeed(None))
            yield from writer.join()

        yield from storage.with_transaction(fx.gen(outer))
        yield from storage.write(store_id, [sentinel])
        rows = yield from changes.take_n(3)
        yield from assert_drained(changes)
        persisted = yield from (yield from open_changes(storage, store_id)).take_all()
        assert_entries(persisted, [backlog, first, second, sentinel], 1)
        assert_entries(rows, [first, second, sentinel], 2)

    yield from _run(body)


@testing.live(timeout="30 seconds")
def test_rolls_back_an_interrupted_pre_commit_body(connect: Connect):
    """SqlEventLogServerUnencrypted / rolls back an interrupted pre-commit body without
    publishing its writes"""

    def body():
        sql = yield from connect()
        storage = yield from make_storage(sql, **make_options("interrupted_transaction"))
        store_id = make_store_id("interrupted_transaction")
        backlog, rolled_back, sentinel = (
            make_entry("Ada"),
            make_entry("Grace"),
            make_entry("Margaret"),
        )
        yield from storage.write(store_id, [backlog])
        changes = yield from open_changes(storage, store_id)
        yield from _first(changes, backlog)
        written = yield from fx.Deferred[None].make()

        def transaction():
            yield from storage.write(store_id, [rolled_back])
            yield from written.succeed(None)
            return (yield from fx.never)

        writer = yield from storage.with_transaction(fx.gen(transaction)).fork()
        yield from written.wait()
        yield from writer.interrupt()
        exit_ = yield from writer.await_exit()
        assert isinstance(exit_, fx.Failure)
        assert exit_.cause.has_interrupts
        yield from storage.write(store_id, [sentinel])
        assert_entries([(yield from changes.take())], [sentinel], 2)
        yield from assert_drained(changes)
        persisted = yield from (yield from open_changes(storage, store_id)).take_all()
        assert_entries(persisted, [backlog, sentinel], 1)

    yield from _run(body)


@testing.live(timeout="30 seconds")
def test_discards_outer_rollback_rows_and_notifications(connect: Connect):
    """SqlEventLogServerUnencrypted / discards outer rollback rows and notifications,
    including successful nested writes"""

    def body():
        sql = yield from connect()
        storage = yield from make_storage(sql, **make_options("outer_rollback"))
        store_id = make_store_id("outer_rollback")
        backlog, rolled_back, nested, sentinel = (
            make_entry("Ada"),
            make_entry("Grace"),
            make_entry("Margaret"),
            make_entry("Linus"),
        )
        yield from storage.write(store_id, [backlog])
        changes = yield from open_changes(storage, store_id)
        yield from _first(changes, backlog)

        def transaction():
            yield from storage.write(store_id, [rolled_back])
            yield from storage.with_transaction(storage.write(store_id, [nested]))
            return (yield from fx.fail("rollback"))

        error = yield from storage.with_transaction(fx.gen(transaction)).flip()
        assert error == "rollback"
        yield from storage.write(store_id, [sentinel])
        assert_entries([(yield from changes.take())], [sentinel], 2)
        yield from assert_drained(changes)
        persisted = yield from (yield from open_changes(storage, store_id)).take_all()
        assert_entries(persisted, [backlog, sentinel], 1)

    yield from _run(body)


@testing.live(timeout="30 seconds")
def test_publishes_writes_in_an_enclosing_sql_transaction_only_after_commit(connect: Connect):
    """SqlEventLogServerUnencrypted / publishes writes made in an enclosing SQL transaction
    only after it commits"""

    def body():
        sql = yield from connect()
        storage = yield from make_storage(sql, **make_options("sql_outer_commit"))
        store_id = make_store_id("sql_outer_commit")
        backlog, rolled_back, committed = (
            make_entry("Ada"),
            make_entry("Grace"),
            make_entry("Margaret"),
        )
        yield from storage.write(store_id, [backlog])
        changes = yield from open_changes(storage, store_id)
        yield from _first(changes, backlog)
        yield from sql.with_transaction(
            storage.write(store_id, [rolled_back]).and_then(fx.fail("rollback"))
        ).exit()

        def transaction():
            yield from storage.write(store_id, [committed])
            yield from assert_drained(changes)

        yield from sql.with_transaction(fx.gen(transaction))
        assert_entries([(yield from changes.take())], [committed], 2)

    yield from _run(body)


@testing.live(timeout="30 seconds")
def test_does_not_redeliver_entries_removed_by_backlog_compaction(connect: Connect):
    """SqlEventLogServerUnencrypted / does not redeliver entries removed by backlog
    compaction when startup publication resumes"""

    def body():
        sql = yield from connect()
        storage = yield from make_storage(sql, **make_options("compacted_startup"))
        store_id = make_store_id("compacted_startup")
        folded, sentinel = make_entry("Ada"), make_entry("Grace")
        compacted = yield from fx.Deferred[None].make()
        release = yield from write_with_held_publication(sql, storage, store_id, [folded])

        def compact(entries: Sequence[Entry], _write: L.CompactWrite) -> fx.Effect[None]:
            assert [e.id_string for e in entries] == [folded.id_string]
            return compacted.succeed(None).as_void()

        compactors = {
            "UserNameSet": RegisteredCompactor(events=frozenset({"UserNameSet"}), effect=compact)
        }
        changes = yield from storage.changes(store_id, 0, compactors).to_queue(capacity="unbounded")
        yield from compacted.wait()
        yield from release
        yield from storage.write(store_id, [sentinel])
        assert_entries([(yield from changes.take())], [sentinel], 2)

    yield from _run(body)


@testing.live(timeout="30 seconds")
def test_publishes_storage_owned_transactions_in_commit_order(connect: Connect):
    """pyfect: a storage-owned transaction holds its permit through publication, so a
    write that commits after it is published after it (Effect's delayed-return test
    pauses after publication, so it cannot see a missing permit)"""

    def body():
        sql = yield from connect()
        storage = yield from make_storage(sql, **make_options("commit_order"))
        store_id = make_store_id("commit_order")
        backlog, first, second = make_entry("Ada"), make_entry("Grace"), make_entry("Margaret")
        yield from storage.write(store_id, [backlog])
        changes = yield from open_changes(storage, store_id)
        yield from _first(changes, backlog)
        committed = yield from fx.Deferred[None].make()
        released = yield from fx.Deferred[None].make()

        def transaction():
            # Registered first, so it runs between COMMIT and the publication.
            yield from sql.after_commit(committed.succeed(None).and_then(released.wait()))
            yield from storage.write(store_id, [first])

        writer_one = yield from storage.with_transaction(fx.gen(transaction)).fork()
        yield from committed.wait()
        writer_two = yield from storage.write(store_id, [second]).fork()
        # Without the permit writer two commits and publishes in this window.
        yield from fx.sleep("200 millis")
        yield from released.succeed(None)
        yield from writer_one.join()
        yield from writer_two.join()
        assert_entries((yield from changes.take_n(2)), [first, second], 2)

    yield from _run(body)


# --- sql-sqlite-node SqlEventLogServerUnencrypted.test.ts -------------------------------


class _AllowAll(U.EventLogServerAuthorizationService):
    def authorize_write(self, **_: Any) -> fx.Effect[None, U.EventLogServerAuthError]:
        return fx.void

    def authorize_read(self, **_: Any) -> fx.Effect[None, U.EventLogServerAuthError]:
        return fx.void

    def authorize_identity(self, **_: Any) -> fx.Effect[None, U.EventLogServerAuthError]:
        return fx.void


class _Identity(U.StoreMappingService):
    def resolve(self, **options: Any) -> fx.Effect[StoreId, U.EventLogServerStoreError]:
        return fx.succeed(options["store_id"])

    def has_store(self, **_: Any) -> fx.Effect[bool]:
        return fx.succeed(True)


def _rpc_client(storage: U.StorageService) -> fx.Effect[M.EventLogRemoteRpcs, Any, Any]:
    handlers = (
        U.layer_rpc_handlers.pipe(fx.layer.provide_merge(L.layer_registry))
        .pipe(fx.layer.provide(fx.layer.succeed(U.Storage, storage)))
        .pipe(fx.layer.provide(fx.layer.succeed(U.StoreMapping, _Identity())))
        .pipe(fx.layer.provide(fx.layer.succeed(U.EventLogServerAuthorization, _AllowAll())))
    )
    return rpc_test.make_client(M.EventLogRemoteRpcs).pipe(fx.provide(handlers))


get_material = make_get_identity_root_secret_material()


def _authenticate_request(
    identity: L.IdentityService, hello: M.HelloResponse
) -> Generator[Any, Any, M.Authenticate]:
    material = yield from get_material(identity)
    signature = yield from sign_session_auth_payload(
        SessionAuthPayload(
            remote_id=hello.remote_id,
            challenge=hello.challenge,
            public_key=identity.public_key,
            signing_public_key=material.signing_public_key,
        ),
        reveal(material.signing_private_key),
    )
    return M.Authenticate(
        public_key=identity.public_key,
        signing_public_key=material.signing_public_key,
        signature=signature,
        algorithm="Ed25519",
    )


def _created(value: int) -> Entry:
    return Entry(
        id=J.make_entry_id_unsafe(),
        event="UserCreated",
        primary_key=f"user-{value}",
        payload=bytes([value]),
    )


def _run_auth(body: Callable[[], Generator[Any, Any, Any]]) -> fx.Effect[Any, Any, Any]:
    return fx.gen(body).pipe(fx.provide(fx.layer.merge(reactivity_layer, layer_subtle)))


@testing.effect
def test_forbids_writing_entries_for_another_identity():
    """SqlEventLogServerUnencrypted (sql-sqlite-node) / forbids writing entries for another
    identity"""

    def body():
        sql = yield from _client()
        storage = yield from make_storage(sql)
        client = yield from _rpc_client(storage)
        identity_a = yield from L.make_identity
        identity_b = yield from L.make_identity
        hello = yield from client.hello()
        yield from client.authenticate((yield from _authenticate_request(identity_a, hello)))
        store_id = StoreId("store-a")
        data = yield from M.WriteEntriesUnencrypted(
            public_key=identity_b.public_key, store_id=store_id, entries=(_created(1),)
        ).encoded
        error = yield from client.write_single({"data": data}).flip()
        assert isinstance(error, M.EventLogProtocolError)
        assert error.code == "Forbidden"
        written = yield from storage.write(store_id, [_created(2)])
        assert [r.remote_sequence for r in written] == [1]

    yield from _run_auth(body)


@testing.effect
def test_rejects_session_auth_rebinding_for_an_existing_public_key():
    """SqlEventLogServerUnencrypted (sql-sqlite-node) / rejects session-auth rebinding for an
    existing publicKey"""

    def body():
        sql = yield from _client()
        storage = yield from make_storage(sql)
        client = yield from _rpc_client(storage)
        first_identity = yield from L.make_identity
        second_seed = yield from L.make_identity
        second_identity = L.IdentityService(first_identity.public_key, second_seed.private_key)
        first_material = yield from get_material(first_identity)
        second_material = yield from get_material(second_identity)
        assert first_material.signing_public_key != second_material.signing_public_key
        first_hello = yield from client.hello()
        yield from client.authenticate(
            (yield from _authenticate_request(first_identity, first_hello))
        )
        second_hello = yield from client.hello()
        error = yield from client.authenticate(
            (yield from _authenticate_request(second_identity, second_hello))
        ).flip()
        assert isinstance(error, M.EventLogProtocolError)
        assert error.code == "Forbidden"
        assert error.message == "Session auth signature verification failed"

    yield from _run_auth(body)


_PLAN_ROW = re.compile(
    r"^SEARCH effect_events USING (COVERING )?INDEX \S+ \(.*\b(entry_id|primary_key)=\?"
)


@testing.effect
def test_reads_batch_history_through_id_and_primary_key_lookups():
    """SqlEventLogServerUnencrypted (sql-sqlite-node) / reads batch history through id and
    primary key lookups"""
    statements: list[tuple[str, Sequence[Any]]] = []

    def record(statement: Any, *_: Any) -> fx.Effect[Any]:
        def run() -> Any:
            statements.append(statement.compile())
            return statement

        return fx.sync(run)

    def body():
        sql = yield from _client()
        storage = yield from make_storage(sql)

        def entry(msecs: int, key: str) -> Entry:
            return Entry(
                id=J.make_entry_id_unsafe(msecs=msecs),
                event="Set",
                primary_key=key,
                payload=b"{}",
            )

        store_id = StoreId("plan")
        yield from storage.write(store_id, [entry(2_000, "a"), entry(3_000, "b")])
        statements.clear()
        batch = [entry(1_000, "a")]
        yield from storage.entries_after(store_id, batch[0], batch).pipe(
            fx.provide_service(CurrentTransformer, record)
        )
        reads = [
            (text, params)
            for text, params in statements
            if re.match(r"^\s*SELECT\b", text, re.IGNORECASE) and '"effect_events"' in text
        ]
        assert reads
        for text, params in reads:
            plan = yield from sql.unsafe(f"EXPLAIN QUERY PLAN {text}", params)
            details = [str(row["detail"]) for row in plan]
            for detail in (d for d in details if "effect_events" in d):
                # A range on entry_id alone reads every entry after the batch.
                assert _PLAN_ROW.match(detail), detail

    yield from _run_auth(body)


@pytest.mark.parametrize("size", [0, -1])
@testing.live(timeout="30 seconds")
def test_a_batch_size_below_one_writes_a_row_at_a_time(size: int):
    """Effect flushes once it holds ``insertBatchSize`` rows, so every row here."""

    def body():
        sql = yield from _client()
        storage = yield from make_storage(
            sql, **{**make_options("size"), "insert_batch_size": size}
        )
        store_id = make_store_id("size")
        entries = [make_entry("a"), make_entry("b"), make_entry("c")]
        yield from storage.write(store_id, entries)
        changes = yield from open_changes(storage, store_id)
        rows = yield from changes.take_n(3)
        assert_entries(rows, entries, 1)

    yield from _run(body)
