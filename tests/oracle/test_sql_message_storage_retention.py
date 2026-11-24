"""Ports of platform-node's ``test/cluster/SqlMessageStorage.integration.test.ts``
cases for ``delete_processed`` (Effect 4.1.4, #10267) and the lookup-index
migrations, on the backends of ``_sql_storage_backends``. Each test's
docstring is the Effect test title.

The deadlock cases pause one transaction inside a test trigger and run
``delete_processed`` while it waits, as Effect's do; table and trigger names
carry the test's prefix instead of ``cluster``."""

from __future__ import annotations

from collections.abc import Generator, Sequence
from pathlib import Path
from typing import Any

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.cluster import snowflake
from pyfect.cluster import sql_message_storage as SqlMessageStorage
from pyfect.cluster.cluster_error import PersistenceError
from pyfect.cluster.message import OutgoingEnvelope, OutgoingRequest
from pyfect.cluster.message_storage import SaveDuplicate, SaveSuccess, make_encoded
from pyfect.cluster.snowflake import Generator as SnowflakeGenerator
from pyfect.duration import millis
from pyfect.exit import Failure, Success
from pyfect.sql.client import SqlClient, SqlClientService
from pyfect.sql.connection import Row

from ._cluster_messages import (
    PrimaryKeyPayload,
    PrimaryKeyTest,
    StreamRpc,
    make_ack_chunk,
    make_chunk_reply,
    make_reply,
    make_request,
)
from ._sql_storage_backends import (
    BACKENDS,
    Backend,
    Env,
    fresh_prefix,
    make_backend,
    mssql,
    mysql,
    pg,
    run,
)

CUTOFF = 1_767_225_600_000
"""``Date.UTC(2026, 0, 1)``, the cutoff of Effect's ``deleteProcessed`` tests."""

_MAX_VALUE = 1.7976931348623157e308
"""JavaScript's ``Number.MAX_VALUE``."""

type Body = Generator[fx.Effect[Any, Any, Any], Any]


@pytest.fixture(params=BACKENDS)
def backend(request: pytest.FixtureRequest, tmp_path: Path) -> Backend:
    return make_backend(request, tmp_path, sqlite_fsync=False)


@pytest.mark.parametrize("backend", ["sqlite"], indirect=True)
@testing.live
def test_the_sqlite_backend_commits_without_fsync(backend: Backend):
    """These tests check retention, not durability: a runner's slow disk flush must not time
    them out. test_sql_message_storage keeps a file with the default sync."""

    def body() -> Body:
        sql = yield from backend.client()
        assert (yield from sql("PRAGMA synchronous")) == [{"synchronous": 0}]

    yield from fx.scoped(fx.gen(body))


# The servers come in through fixtures, so a container's startup runs in the test's setup,
# outside its timeout.
@pytest.fixture
def pg_backend(request: pytest.FixtureRequest) -> Backend:
    pytest.importorskip("psycopg")
    server = request.getfixturevalue("pg_server")
    return Backend("pg", lambda: pg(server), fresh_prefix("ret"))


@pytest.fixture
def mysql_backend(request: pytest.FixtureRequest) -> Backend:
    pytest.importorskip("asyncmy")
    server = request.getfixturevalue("mysql_server")
    return Backend("mysql", lambda: mysql(server), fresh_prefix("ret"))


@pytest.fixture
def mssql_backend(request: pytest.FixtureRequest) -> Backend:
    pytest.importorskip("pytds")
    server = request.getfixturevalue("mssql_server")
    return Backend("mssql", lambda: mssql(server), fresh_prefix("ret"))


def _delete(env: Env, completed_before: float, limit: int = 100) -> fx.Effect[int, Any]:
    return env.storage.delete_processed(
        entity_type="test", completed_before=completed_before, limit=limit
    )


def _interrupt(request: OutgoingRequest) -> fx.Effect[OutgoingEnvelope, Any, SnowflakeGenerator]:
    return SnowflakeGenerator().map(
        lambda snowflakes: OutgoingEnvelope.interrupt(
            id=snowflakes.next_unsafe(),
            request_id=request.envelope.request_id,
            address=request.envelope.address,
        )
    )


def _wait_for(check: fx.Effect[Sequence[Row], Any]) -> fx.Effect[None, Any]:
    """Polls ``check`` until it gives a row: another connection is paused
    in a test trigger's sleep."""

    def loop() -> Body:
        while not (yield from check):
            yield from fx.sleep(millis(10))

    return fx.gen(loop).timeout("5 seconds")


def _wait_for_pg_sleep(sql: SqlClientService) -> fx.Effect[None, Any]:
    return _wait_for(
        sql(
            "SELECT 1 FROM pg_stat_activity "
            "WHERE pid <> pg_backend_pid() AND wait_event = 'PgSleep'"
        )
    )


def _wait_for_mysql_sleep(sql: SqlClientService) -> fx.Effect[None, Any]:
    return _wait_for(
        sql(
            "SELECT 1 FROM information_schema.PROCESSLIST "
            "WHERE ID <> CONNECTION_ID() AND STATE = 'User sleep'"
        )
    )


def _wait_for_mssql_waitfor(sql: SqlClientService) -> fx.Effect[None, Any]:
    return _wait_for(
        sql(
            "SELECT 1 FROM sys.dm_exec_requests "
            "WHERE session_id <> @@SPID AND wait_type = 'WAITFOR'"
        )
    )


def _ids(env: Env, table: str, request: OutgoingRequest) -> fx.Effect[Sequence[Row], Any]:
    return env.sql(
        "SELECT id FROM {} WHERE request_id = {}",
        env.sql.identifier(f"{env.prefix}_{table}"),
        str(request.envelope.request_id),
    )


# --- every backend ----------------------------------------------------------------------


@testing.live
def test_delete_processed_forgets_request_families_completed_before_the_cutoff(
    backend: Backend,
):
    """deleteProcessed forgets request families completed before the cutoff"""

    def request(id: int, entity_type: str = "test") -> fx.Effect[OutgoingRequest, Any, Any]:
        return make_request(
            rpc=StreamRpc, payload=PrimaryKeyPayload(id=id), entity_type=entity_type
        )

    def body(env: Env) -> Body:
        storage = env.storage
        expired = yield from request(1)
        recent = yield from request(2)
        reset = yield from request(3)
        other_type = yield from request(4, "other")
        for r in (expired, recent, reset, other_type):
            yield from storage.save_request(r)
        chunk = yield from make_chunk_reply(expired)
        yield from storage.save_reply(chunk)
        yield from storage.save_envelope((yield from make_ack_chunk(expired, chunk)))
        yield from storage.save_envelope((yield from _interrupt(expired)))
        yield from storage.save_reply((yield from make_reply(expired, CUTOFF - 1)))
        yield from storage.save_reply((yield from make_reply(recent, CUTOFF + 1)))
        yield from storage.save_reply((yield from make_reply(reset, CUTOFF - 2)))
        yield from storage.clear_replies(reset.envelope.request_id)
        yield from storage.save_reply((yield from make_reply(other_type, CUTOFF - 3)))

        assert (yield from _delete(env, CUTOFF)) == 1

        assert list((yield from _ids(env, "messages", expired))) == []
        assert list((yield from _ids(env, "replies", expired))) == []
        assert isinstance((yield from storage.save_request((yield from request(1)))), SaveSuccess)
        for id, kept in ((2, recent), (3, reset), (4, other_type)):
            again = yield from request(id, kept.envelope.address.entity_type)
            assert isinstance((yield from storage.save_request(again)), SaveDuplicate)
        kept_replies = yield from storage.replies_for_unfiltered(
            [recent.envelope.request_id, other_type.envelope.request_id]
        )
        assert len(kept_replies) == 2

    yield from run(backend, body)


@testing.live
def test_does_not_store_an_ack_chunk_or_interrupt_for_a_request_delete_processed_removed(
    backend: Backend,
):
    """does not store an AckChunk or Interrupt for a request deleteProcessed removed"""

    def body(env: Env) -> Body:
        storage = env.storage
        request = yield from make_request(rpc=StreamRpc, payload=PrimaryKeyPayload(id=1))
        chunk = yield from make_chunk_reply(request)
        yield from storage.save_request(request)
        yield from storage.save_reply(chunk)
        yield from storage.save_reply((yield from make_reply(request, CUTOFF - 1)))
        assert (yield from _delete(env, CUTOFF)) == 1

        # a late acknowledgement and cancellation, such as ones that waited behind the delete
        yield from storage.save_envelope((yield from make_ack_chunk(request, chunk)))
        yield from storage.save_envelope((yield from _interrupt(request)))
        shards = [request.envelope.address.shard_id]
        assert (yield from storage.unprocessed_messages(shards)) == []
        assert list((yield from _ids(env, "messages", request))) == []

    yield from run(backend, body)


@testing.live
def test_delete_processed_takes_an_unbounded_extreme_or_fractional_cutoff(backend: Backend):
    """deleteProcessed takes an unbounded, extreme or fractional cutoff"""

    def body(env: Env) -> Body:
        storage = env.storage
        completed_at = CUTOFF
        for id in range(1, 7):
            request = yield from make_request(payload={"id": id})
            yield from storage.save_request(request)
            yield from storage.save_reply((yield from make_reply(request, completed_at + id - 1)))
        # completed before the snowflake epoch, so its reply id is negative
        pre_epoch = yield from make_request(payload={"id": 0})
        yield from storage.save_request(pre_epoch)
        yield from storage.save_reply(
            (yield from make_reply(pre_epoch, snowflake.EPOCH_MILLIS - 1))
        )
        make_running = make_request(rpc=PrimaryKeyTest, payload=PrimaryKeyPayload(id=7))
        # still running, so never eligible
        yield from storage.save_request((yield from make_running))
        # MessageRetention's cutoffs for an infinite, huge, sub-millisecond,
        # negative huge and negative infinite retention
        assert (yield from _delete(env, float("-inf"), 2)) == 0
        assert (yield from _delete(env, -_MAX_VALUE, 2)) == 0
        assert (yield from _delete(env, snowflake.EPOCH_MILLIS, 2)) == 1
        assert (yield from _delete(env, completed_at + 0.5, 2)) == 1
        assert (yield from _delete(env, _MAX_VALUE, 2)) == 2
        assert (yield from _delete(env, float("inf"), 2)) == 2
        assert (yield from _delete(env, float("inf"), 2)) == 1
        running = yield from storage.save_request((yield from make_running))
        assert isinstance(running, SaveDuplicate)

    yield from run(backend, body)


@testing.live
def test_delete_processed_takes_nan_as_no_cutoff(backend: Backend):
    """pyfect: a NaN cutoff deletes nothing, as Effect's ``!(completedBefore > ...)``
    check reads it."""

    def body(env: Env) -> Body:
        request = yield from make_request()
        yield from env.storage.save_request(request)
        yield from env.storage.save_reply((yield from make_reply(request, CUTOFF - 1)))
        assert (yield from _delete(env, float("nan"))) == 0
        assert (yield from _delete(env, CUTOFF)) == 1

    yield from run(backend, body)


# --- PostgreSQL ---------------------------------------------------------------------------


@testing.live(timeout="30 seconds")
def test_save_request_keeps_a_duplicate_whose_original_is_deleted_mid_save(pg_backend: Backend):
    """saveRequest keeps a duplicate whose original is deleted mid-save"""
    backend = pg_backend

    def body(env: Env) -> Body:
        sql, storage = env.sql, env.storage
        function = sql.identifier(f"{env.prefix}_slow_insert")
        make = make_request(rpc=PrimaryKeyTest, payload=PrimaryKeyPayload(id=1))
        expired = yield from make
        yield from storage.save_request(expired)
        yield from storage.save_reply((yield from make_reply(expired, CUTOFF - 1)))
        # Pause after the duplicate's insert hits the conflict, before it reads the existing row.
        yield from sql(
            "CREATE FUNCTION {}() RETURNS trigger AS $$ BEGIN PERFORM pg_sleep(2); "
            "RETURN NULL; END $$ LANGUAGE plpgsql",
            function,
        )
        yield from sql(
            "CREATE TRIGGER {} AFTER INSERT ON {} FOR EACH STATEMENT EXECUTE FUNCTION {}()",
            function,
            env.messages,
            function,
        )
        resend = yield from make
        save = yield from storage.save_request(resend).fork()
        yield from _wait_for_pg_sleep(sql)
        assert (yield from _delete(env, CUTOFF)) == 1
        result = yield from save.join()
        if isinstance(result, SaveDuplicate):
            assert result.last_received_reply is not None
        else:
            # a reported success must have stored the request
            shards = [resend.envelope.address.shard_id]
            messages = yield from storage.unprocessed_messages(shards)
            assert [m.envelope.request_id for m in messages] == [resend.envelope.request_id]

    yield from run(backend, body)


@testing.live(timeout="30 seconds")
def test_clear_replies_does_not_deadlock_with_a_concurrent_delete_processed(pg_backend: Backend):
    """clearReplies does not deadlock with a concurrent deleteProcessed"""
    backend = pg_backend

    def body(env: Env) -> Body:
        sql, storage = env.sql, env.storage
        function = sql.identifier(f"{env.prefix}_slow_clear")
        message = yield from make_request()
        yield from storage.save_request(message)
        yield from storage.save_reply((yield from make_reply(message, CUTOFF - 1)))
        # Pause clearReplies after it deletes the final reply, only in the transaction that opts in.
        yield from sql(
            "CREATE FUNCTION {}() RETURNS trigger AS $$ BEGIN "
            "IF current_setting('cluster_test.slow_clear', true) = 'on' THEN "
            "PERFORM pg_sleep(2); END IF; RETURN OLD; END $$ LANGUAGE plpgsql",
            function,
        )
        yield from sql(
            "CREATE TRIGGER {} AFTER DELETE ON {} FOR EACH ROW EXECUTE FUNCTION {}()",
            function,
            sql.identifier(f"{env.prefix}_replies"),
            function,
        )
        clear = (
            sql("SET LOCAL cluster_test.slow_clear = 'on'")
            .and_then(storage.clear_replies(message.envelope.request_id))
            .pipe(sql.with_transaction)
        )
        clear_fiber = yield from clear.exit().fork()
        yield from _wait_for_pg_sleep(sql)
        cleanup = yield from _delete(env, CUTOFF).exit()
        cleared = yield from clear_fiber.join()
        assert isinstance(cleared, Success), cleared
        assert isinstance(cleanup, Success), cleanup
        # the reset started first, so the request is kept and delivered again
        assert cleanup.value == 0
        shards = [message.envelope.address.shard_id]
        messages = yield from storage.unprocessed_messages(shards)
        assert [m.envelope.request_id for m in messages] == [message.envelope.request_id]

    yield from run(backend, body)


@pytest.mark.parametrize("save_first", [False, True])
@testing.live
def test_guarded_clear_replies_preserves_a_concurrently_saved_reply_in_either_lock_order(
    pg_backend: Backend, save_first: bool
):
    """guarded clearReplies preserves a concurrently saved reply in either lock order

    Effect holds the first operation's lock with ``pg_sleep(2)``; a fifth of a second is
    enough to have the second connection start while it is held."""
    backend = pg_backend

    def body(env: Env) -> Body:
        sql, storage = env.sql, env.storage
        message = yield from make_request()
        old_reply = yield from make_reply(message)
        new_reply = yield from make_reply(message)
        yield from storage.save_request(message)
        yield from storage.save_reply(old_reply)
        reset = storage.clear_replies(
            message.envelope.request_id, expected_reply_id=old_reply.reply.id
        )
        save = storage.save_reply(new_reply)
        # A competing runner resets the old completion before saving its new reply.
        first, second = (reset.and_then(save), reset) if save_first else (reset, save)
        # Hold the first operation's lock while the second connection starts.
        held: fx.Effect[Any, Any, Any] = first.and_then(sql("SELECT pg_sleep(0.2)")).pipe(
            sql.with_transaction
        )
        fiber = yield from held.fork()
        yield from _wait_for_pg_sleep(sql)
        yield from second
        yield from fiber.join()
        replies = yield from storage.replies_for([message])
        assert replies[-1].id == new_reply.reply.id
        shards = [message.envelope.address.shard_id]
        assert (yield from storage.unprocessed_messages(shards)) == []

    yield from run(backend, body)


# --- MySQL --------------------------------------------------------------------------------


@testing.live(timeout="30 seconds")
def test_a_late_ack_chunk_does_not_deadlock_with_a_concurrent_delete_processed(
    mysql_backend: Backend,
):
    """a late AckChunk does not deadlock with a concurrent deleteProcessed"""
    backend = mysql_backend

    def body(env: Env) -> Body:
        sql, storage = env.sql, env.storage
        trigger = sql.identifier(f"{env.prefix}_slow_ack")
        message = yield from make_request(rpc=StreamRpc, payload=PrimaryKeyPayload(id=1))
        chunk = yield from make_chunk_reply(message)
        yield from storage.save_request(message)
        yield from storage.save_reply(chunk)
        yield from storage.save_reply((yield from make_reply(message, CUTOFF - 1)))
        # Pause the acknowledgement after it updates the chunk reply, only on the
        # connection that opts in.
        yield from sql(
            "CREATE TRIGGER {} AFTER UPDATE ON {} FOR EACH ROW BEGIN "
            "IF @cluster_test_slow_ack = 1 THEN DO SLEEP(2); END IF; END",
            trigger,
            sql.identifier(f"{env.prefix}_replies"),
        ).unprepared
        ack = yield from make_ack_chunk(message, chunk)
        acknowledge = (
            sql("SET @cluster_test_slow_ack = 1")
            .and_then(
                storage.save_envelope(ack).ensuring(
                    sql("SET @cluster_test_slow_ack = NULL").or_die()
                )
            )
            .pipe(sql.with_transaction)
        )
        ack_fiber = yield from acknowledge.exit().fork()
        yield from _wait_for_mysql_sleep(sql)
        cleanup = yield from _delete(env, CUTOFF).exit()
        acked = yield from ack_fiber.join()
        assert isinstance(acked, Success), acked
        assert isinstance(cleanup, Success), cleanup
        # cleanup either deletes the whole family, including the new AckChunk, or leaves
        # it for a later tick
        remaining = yield from env.sql(
            "SELECT kind FROM {} WHERE request_id = {}",
            env.messages,
            str(message.envelope.request_id),
        )
        kinds = sorted(int(str(row["kind"])) for row in remaining)
        assert kinds == ([] if cleanup.value == 1 else [0, 1])
        yield from sql("DROP TRIGGER {}", trigger).unprepared

    yield from run(backend, body)


@testing.live(timeout="30 seconds")
def test_a_stream_reply_does_not_deadlock_with_delete_processed_of_another_request(
    mysql_backend: Backend,
):
    """a stream reply does not deadlock with deleteProcessed of another request"""
    backend = mysql_backend

    def body(env: Env) -> Body:
        sql, storage = env.sql, env.storage
        trigger = sql.identifier(f"{env.prefix}_slow_reply")
        for id in range(1, 21):
            expired = yield from make_request(payload={"id": id})
            yield from storage.save_request(expired)
            yield from storage.save_reply((yield from make_reply(expired, CUTOFF - id)))
        # an incomplete stream, which deleteProcessed must not select
        streaming = yield from make_request(
            rpc=StreamRpc, payload=PrimaryKeyPayload(id=21), entity_id="2"
        )
        yield from storage.save_request(streaming)
        yield from storage.save_reply((yield from make_chunk_reply(streaming, 0)))
        # Pause saveReply after it updates the request row, before it inserts the reply,
        # only on the connection that opts in.
        yield from sql(
            "CREATE TRIGGER {} AFTER UPDATE ON {} FOR EACH ROW BEGIN "
            "IF @cluster_test_slow_reply = 1 THEN DO SLEEP(2); END IF; END",
            trigger,
            env.messages,
        ).unprepared
        chunk = yield from make_chunk_reply(streaming, 1)
        reply = (
            sql("SET @cluster_test_slow_reply = 1")
            .and_then(
                storage.save_reply(chunk).ensuring(
                    sql("SET @cluster_test_slow_reply = NULL").or_die()
                )
            )
            .pipe(sql.with_transaction)
        )
        reply_fiber = yield from reply.exit().fork()
        yield from _wait_for_mysql_sleep(sql)
        cleanup = yield from _delete(env, CUTOFF).exit()
        replied = yield from reply_fiber.join()
        assert isinstance(replied, Success), replied
        assert isinstance(cleanup, Success), cleanup
        assert cleanup.value == 20
        yield from sql("DROP TRIGGER {}", trigger).unprepared

    yield from run(backend, body)


@testing.live
def test_fails_the_migrations_when_the_retention_index_cannot_be_created(mysql_backend: Backend):
    """fails the migrations when the retention index cannot be created"""
    backend = mysql_backend
    prefix = fresh_prefix("brokenidx")

    def body(env: Env) -> Body:
        sql = env.sql
        # A messages table that predates the migrations and lacks the last_reply_id
        # column. 0001 keeps it and 0004 (pyfect's exact keys) only changes the key
        # columns, so the retention index fails on the missing column, not on a
        # duplicate index name.
        yield from sql(
            "CREATE TABLE {} (id BIGINT NOT NULL, message_id VARCHAR(255) NULL, "
            "shard_id VARCHAR(50) NOT NULL, entity_type VARCHAR(150) NOT NULL, "
            "entity_id VARCHAR(255) NOT NULL, processed BOOLEAN NOT NULL DEFAULT FALSE)",
            sql.identifier(f"{prefix}_messages"),
        )
        exit = (
            yield from SqlMessageStorage.make(prefix=prefix)
            .pipe(fx.provide_service(SqlClient, sql))
            .exit()
        )
        assert isinstance(exit, Failure)
        assert "last_reply_id" in str(exit.cause.squash())

    yield from run(backend, body)


# --- SQL Server ---------------------------------------------------------------------------


@testing.live(timeout="30 seconds")
def test_a_stream_acknowledgement_does_not_deadlock_with_delete_processed_of_another_request(
    mssql_backend: Backend,
):
    """a stream acknowledgement does not deadlock with deleteProcessed of another request"""
    backend = mssql_backend

    def body(env: Env) -> Body:
        sql, storage = env.sql, env.storage
        trigger = sql.identifier(f"{env.prefix}_slow_ack")
        expired = yield from make_request(payload={"id": 1})
        yield from storage.save_request(expired)
        yield from storage.save_reply((yield from make_reply(expired, CUTOFF - 1)))
        # an incomplete stream, which deleteProcessed must not select
        streaming = yield from make_request(
            rpc=StreamRpc, payload=PrimaryKeyPayload(id=2), entity_id="2"
        )
        chunk = yield from make_chunk_reply(streaming)
        yield from storage.save_request(streaming)
        yield from storage.save_reply(chunk)
        # Pause the acknowledgement after it updates the chunk reply, only on the session
        # that opts in.
        yield from sql(
            "CREATE TRIGGER {} ON {} AFTER UPDATE AS "
            "IF SESSION_CONTEXT(N'cluster_test_slow_ack') = 1 WAITFOR DELAY '00:00:02'",
            trigger,
            sql.identifier(f"{env.prefix}_replies"),
        ).unprepared
        ack = yield from make_ack_chunk(streaming, chunk)
        acknowledge = (
            sql("EXEC sp_set_session_context @key = N'cluster_test_slow_ack', @value = 1")
            .and_then(
                storage.save_envelope(ack).ensuring(
                    sql(
                        "EXEC sp_set_session_context @key = N'cluster_test_slow_ack', @value = NULL"
                    ).or_die()
                )
            )
            .pipe(sql.with_transaction)
        )
        ack_fiber = yield from acknowledge.exit().fork()
        yield from _wait_for_mssql_waitfor(sql)
        cleanup = yield from _delete(env, CUTOFF).exit()
        acked = yield from ack_fiber.join()
        assert isinstance(acked, Success), acked
        assert isinstance(cleanup, Success), cleanup
        assert cleanup.value == 1
        yield from sql("DROP TRIGGER {}", trigger).unprepared

    yield from run(backend, body)


@testing.live
def test_rejects_duplicate_exit_replies_when_another_table_has_the_same_index_name(
    mssql_backend: Backend,
):
    """rejects duplicate exit replies when another table has the same index name"""
    backend = mssql_backend
    prefix = fresh_prefix("collision")

    def body(env: Env) -> Body:
        sql = env.sql
        other = sql.identifier(f"{prefix}_other")
        yield from sql("CREATE TABLE {} (id INT)", other)
        yield from sql(
            "CREATE INDEX {} ON {} (id)", sql.identifier(f"{prefix}_replies_one_exit"), other
        )
        storage = yield from SqlMessageStorage.make_encoded_storage(prefix=prefix).pipe(
            fx.provide_service(SqlClient, sql)
        )
        yield from SqlMessageStorage.run_migrations(prefix=prefix).pipe(
            fx.provide_service(SqlClient, sql)
        )
        exit: Any = {"_tag": "Success", "value": None}
        yield from storage.save_reply(
            {"_tag": "WithExit", "id": "1", "requestId": "1", "exit": exit}
        )
        error = yield from storage.save_reply(
            {"_tag": "WithExit", "id": "2", "requestId": "1", "exit": exit}
        ).flip()
        assert isinstance(error, PersistenceError)

    yield from run(backend, body)


@testing.live
def test_acknowledges_and_cleans_up_when_another_table_has_the_lookup_index_names(
    mssql_backend: Backend,
):
    """acknowledges and cleans up when another table has the lookup index names"""
    backend = mssql_backend
    prefix = fresh_prefix("collision_idx")

    def body(env: Env) -> Body:
        sql = env.sql
        other = sql.identifier(f"{prefix}_other")
        yield from sql("CREATE TABLE {} (id INT)", other)
        for index in ("messages_request_id_idx", "replies_request_lookup_idx"):
            yield from sql("CREATE INDEX {} ON {} (id)", sql.identifier(f"{prefix}_{index}"), other)
        migrate = SqlMessageStorage.run_migrations(prefix=prefix).pipe(
            fx.provide_service(SqlClient, sql)
        )
        yield from migrate
        # Recreate a schema migrated before this change: the lookup indexes are
        # missing from the storage tables and only the migrations before them ran
        # (Effect's 1-3, and pyfect's 0004).
        for index, table in (
            (f"{prefix}_messages_request_id_idx", f"{prefix}_messages"),
            (f"{prefix}_replies_request_lookup_idx", f"{prefix}_replies"),
        ):
            yield from sql(
                "IF EXISTS (SELECT 1 FROM sys.indexes WHERE name = {} "
                "AND object_id = OBJECT_ID({})) DROP INDEX {} ON {}",
                index,
                table,
                sql.identifier(index),
                sql.identifier(table),
            )
        yield from sql(
            "DELETE FROM {} WHERE migration_id > 4", sql.identifier(f"{prefix}_migrations")
        )
        yield from migrate
        encoded = yield from SqlMessageStorage.make_encoded_storage(prefix=prefix).pipe(
            fx.provide_service(SqlClient, sql)
        )
        storage = yield from make_encoded(encoded)

        message = yield from make_request(rpc=StreamRpc, payload=PrimaryKeyPayload(id=1))
        chunk = yield from make_chunk_reply(message)
        yield from storage.save_request(message)
        yield from storage.save_reply(chunk)
        yield from storage.save_envelope((yield from make_ack_chunk(message, chunk)))
        yield from storage.save_reply((yield from make_reply(message, CUTOFF - 1)))
        deleted = yield from storage.delete_processed(
            entity_type="test", completed_before=CUTOFF, limit=100
        )
        assert deleted == 1

    yield from run(backend, body)
