"""Ports of platform-node's ``test/cluster/SqlMessageStorage.integration.test.ts``
for ``pyfect.cluster.sql_message_storage`` on SQLite and on the throwaway
PostgreSQL and MySQL servers (``_postgres.pg_server``, ``_mysql.mysql_server``;
those cases skip without one).

Each test's docstring is the Effect test title. Effect truncates shared
tables between cases; here SQLite gets a fresh file per test and
PostgreSQL and MySQL a fresh table prefix. SQL Server is not run (no
server). ``MessageStorageTest.ts``'s own memory cases ("saves a request",
"detects duplicates", "unprocessedMessages excludes complete requests",
"repliesFor", "registerReplyHandler") are the same titles already ported in
``test_message_storage.py``; its helpers are ``_cluster_messages.py``.

Omitted:
- "resetShards / resetAddresses does not deadlock with a concurrent
  message claim": they need ``SET LOCAL`` plan settings and a trigger
  sleeping inside one row's update to force a lock-order race; the claim
  and reset statements both lock in ``rowid`` order (``reset_unprocessed``).
- "rejects duplicate exit replies when another table has the same index
  name": SQL Server only.
- "keeps held messages readable while entity layers build": needs
  ``Sharding`` and ``Entity``, which are not ported.
"""

from __future__ import annotations

import itertools
import os
import re
import time
from collections.abc import Callable, Generator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Never

import pytest

import pyfect as fx
from pyfect import reactivity, testing
from pyfect.cluster import entity_address, envelope, shard_id, snowflake
from pyfect.cluster import sql_message_storage as SqlMessageStorage
from pyfect.cluster.cluster_error import PersistenceError
from pyfect.cluster.entity_id import EntityId
from pyfect.cluster.entity_type import EntityType
from pyfect.cluster.message import OutgoingRequest
from pyfect.cluster.message_storage import (
    EncodedStorage,
    MessageStorageService,
    SaveDuplicate,
    SaveSuccess,
    make_encoded,
)
from pyfect.cluster.reply import Chunk, WithExit
from pyfect.cluster.snowflake import Generator as SnowflakeGenerator
from pyfect.cluster.snowflake import Snowflake
from pyfect.latch import Latch
from pyfect.sql.client import SqlClient, SqlClientService

from ._cluster_messages import (
    LongKeyPayload,
    LongKeyRpc,
    PrimaryKeyPayload,
    PrimaryKeyTest,
    StreamRpc,
    make_ack_chunk,
    make_chunk_reply,
    make_reply,
    make_request,
)
from ._sqlite import make_client

_prefixes = itertools.count()

type ClientMaker = Callable[[], fx.Effect[SqlClientService, Any, fx.Scope]]


@dataclass(frozen=True)
class Backend:
    name: str
    client: ClientMaker
    prefix: str


@dataclass(frozen=True)
class Env:
    storage: MessageStorageService
    sql: SqlClientService
    prefix: str

    @property
    def messages(self) -> Any:
        return self.sql.identifier(f"{self.prefix}_messages")

    def encoded(self) -> fx.Effect[EncodedStorage]:
        return SqlMessageStorage.make_encoded_storage(prefix=self.prefix).pipe(
            fx.provide_service(SqlClient, self.sql)
        )


def _pg(pg_server: Any) -> fx.Effect[SqlClientService, Any, fx.Scope]:
    pytest.importorskip("psycopg")
    from pyfect.sql import pg

    return pg.make(pg.PgPoolConfig(url=pg_server.url)).pipe(fx.provide(reactivity.layer))


def _mysql(server: Any) -> fx.Effect[SqlClientService, Any, fx.Scope]:
    from pyfect.sql import mysql

    return mysql.make(mysql.MysqlClientConfig(url=server.url)).pipe(fx.provide(reactivity.layer))


@pytest.fixture(params=["sqlite", "pg", "mysql"])
def backend(request: pytest.FixtureRequest, tmp_path: Path) -> Backend:
    if request.param == "sqlite":
        return Backend("sqlite", lambda: make_client(tmp_path), "cluster")
    if request.param == "mysql":
        pytest.importorskip("asyncmy")
        server = request.getfixturevalue("mysql_server")
        return Backend("mysql", lambda: _mysql(server), f"msg_{os.getpid()}_{next(_prefixes)}")
    pytest.importorskip("psycopg")
    server = request.getfixturevalue("pg_server")
    return Backend("pg", lambda: _pg(server), f"msg_{os.getpid()}_{next(_prefixes)}")


def _run(
    backend: Backend, body: Callable[[Env], Generator[fx.Effect[Any, Any, Any], Any]]
) -> fx.Effect[None, Any, Any]:
    def run() -> Generator[fx.Effect[Any, Any, Any], Any]:
        sql = yield from backend.client()
        storage = yield from SqlMessageStorage.make(prefix=backend.prefix).pipe(
            fx.provide_service(SqlClient, sql)
        )
        yield from fx.gen(lambda: body(Env(storage, sql, backend.prefix)))

    return fx.gen(run).pipe(fx.provide(snowflake.layer_generator))


def _address(entity_id: str, shard: int = 1) -> entity_address.EntityAddress:
    return entity_address.make(
        shard_id=shard_id.make("default", shard),
        entity_type=EntityType("test"),
        entity_id=EntityId(entity_id),
    )


def _payload_ids(messages: list[Any]) -> list[int]:
    return [m.envelope.payload["id"] for m in messages]


def _stream_request() -> fx.Effect[OutgoingRequest, Never, SnowflakeGenerator]:
    return make_request(rpc=StreamRpc, payload=PrimaryKeyPayload(id=123))


_SHARD = shard_id.make("default", 1)


def _now() -> int:
    return time.time_ns() // 1_000_000


class _FixedIds:
    """A generator counting by two from just above 2**53."""

    def __init__(self) -> None:
        self.next = 9007199254740993

    def next_unsafe(self) -> Snowflake:
        value = Snowflake(self.next)
        self.next += 2
        return value

    def set_machine_id(self, _machine_id: Any) -> fx.Effect[None]:
        return fx.void


@testing.live
def test_preserves_ids_above_2_53(tmp_path: Path):
    """preserves ids above 2^53 with a number-returning SQLite driver"""

    def body() -> Generator[fx.Effect[Any, Any, Any], Any]:
        sql = yield from make_client(tmp_path)
        yield from SqlMessageStorage.run_migrations().pipe(fx.provide_service(SqlClient, sql))
        storage = yield from SqlMessageStorage.make_encoded_storage().pipe(
            fx.provide_service(SqlClient, sql)
        )
        storage = yield from make_encoded(storage)
        request = yield from make_request(rpc=PrimaryKeyTest, payload=PrimaryKeyPayload(id=123))
        request_id = request.envelope.request_id
        assert request_id > 2**53
        yield from storage.save_request(request)
        shards = [request.envelope.address.shard_id]
        messages = yield from storage.unprocessed_messages(shards)
        assert len(messages) == 1
        assert messages[0].envelope.request_id == request_id
        assert (yield from storage.unprocessed_messages(shards)) == []

        reply = yield from make_reply(request)
        yield from storage.save_reply(reply)
        assert (yield from storage.replies_for([request])) == [reply.reply]
        yield from storage.reset_shards(shards)
        assert (yield from storage.unprocessed_messages(shards)) == []

        duplicate = yield from storage.save_request(
            (yield from make_request(rpc=PrimaryKeyTest, payload=request.envelope.payload))
        )
        assert isinstance(duplicate, SaveDuplicate)
        assert duplicate.original_id == request_id
        assert duplicate.last_received_reply == reply.reply
        assert (
            yield from storage.request_id_for_primary_key(
                address=request.envelope.address, tag=request.envelope.tag, id="123"
            )
        ) == request_id

    yield from fx.gen(body).pipe(fx.provide_service(SnowflakeGenerator, _FixedIds()))  # pyright: ignore[reportArgumentType]


@testing.live
def test_creates_an_index_for_insertion_ordered_message_reads(pg_server: Any):
    """creates an index for insertion-ordered message reads"""
    prefix = f"idx_{os.getpid()}_{next(_prefixes)}"

    def body(env: Env) -> Generator[fx.Effect[Any, Any, Any], Any]:
        indexes = yield from env.sql(
            "SELECT indexname FROM pg_indexes WHERE tablename = {} AND indexname = {}",
            f"{prefix}_messages",
            f"{prefix}_messages_rowid_idx",
        )
        assert len(indexes) == 1

    yield from _run(Backend("pg", lambda: _pg(pg_server), prefix), body)


@testing.live
def test_reset_requests_with_no_ids(backend: Backend):
    """resetRequests with no IDs leaves existing claims untouched"""

    def body(env: Env) -> Generator[fx.Effect[Any, Any, Any], Any]:
        request = yield from make_request()
        yield from env.storage.save_request(request)
        assert len((yield from env.storage.unprocessed_messages([_SHARD]))) == 1
        yield from env.storage.reset_requests([])
        assert len((yield from env.storage.unprocessed_messages([_SHARD]))) == 0

    yield from _run(backend, body)


@testing.live
def test_reset_requests_releases_only_the_selected_request(backend: Backend):
    """resetRequests releases only the selected request at a shared address"""

    def body(env: Env) -> Generator[fx.Effect[Any, Any, Any], Any]:
        selected = yield from make_request()
        unrelated = yield from make_request()
        yield from env.storage.save_request(selected)
        yield from env.storage.save_request(unrelated)
        assert len((yield from env.storage.unprocessed_messages([_SHARD]))) == 2
        yield from env.storage.reset_requests([selected.envelope.request_id])
        messages = yield from env.storage.unprocessed_messages([_SHARD])
        assert [m.envelope.request_id for m in messages] == [selected.envelope.request_id]
        assert len((yield from env.storage.unprocessed_messages([_SHARD]))) == 0

    yield from _run(backend, body)


@testing.live
def test_reset_requests_preserves_replies_and_completed_state(backend: Backend):
    """resetRequests preserves chunk replies, exit replies, and completed state"""

    def body(env: Env) -> Generator[fx.Effect[Any, Any, Any], Any]:
        storage = env.storage
        streaming = yield from _stream_request()
        completed = yield from make_request()
        yield from storage.save_request(streaming)
        yield from storage.save_request(completed)
        assert len((yield from storage.unprocessed_messages([_SHARD]))) == 2
        yield from storage.save_reply((yield from make_chunk_reply(streaming)))
        yield from storage.save_reply((yield from make_reply(completed)))
        replies = yield from storage.replies_for([streaming, completed])
        assert len(replies) == 2
        assert len((yield from storage.unprocessed_messages([_SHARD]))) == 0
        select = env.sql("SELECT processed FROM {} ORDER BY rowid", env.messages)
        processed = yield from select
        yield from storage.reset_requests(
            [streaming.envelope.request_id, completed.envelope.request_id]
        )
        assert len((yield from storage.unprocessed_messages([_SHARD]))) == 0
        assert (yield from storage.replies_for([streaming, completed])) == replies
        assert (yield from select) == processed

    yield from _run(backend, body)


@testing.live
def test_clear_replies_requeues_when_expected_reply_is_current(backend: Backend):
    """clearReplies requeues when the expected reply is current"""

    def body(env: Env) -> Generator[fx.Effect[Any, Any, Any], Any]:
        request = yield from make_request()
        reply = yield from make_reply(request)
        yield from env.storage.save_request(request)
        yield from env.storage.save_reply(reply)
        yield from env.storage.clear_replies(
            request.envelope.request_id, expected_reply_id=reply.reply.id
        )
        assert (yield from env.storage.replies_for([request])) == []
        assert len((yield from env.storage.unprocessed_messages([_SHARD]))) == 1

    yield from _run(backend, body)


@testing.live
def test_clear_replies_with_stale_expected_reply(backend: Backend):
    """clearReplies with a stale expected reply preserves a newer completion and processed state"""

    def body(env: Env) -> Generator[fx.Effect[Any, Any, Any], Any]:
        storage = env.storage
        request = yield from _stream_request()
        old_reply = yield from make_chunk_reply(request)
        completed = yield from make_reply(request)
        yield from storage.save_request(request)
        yield from storage.save_reply(old_reply)
        yield from storage.save_reply(completed)
        select = env.sql(
            "SELECT processed, last_reply_id FROM {} WHERE id = {}",
            env.messages,
            str(request.envelope.request_id),
        )
        before = yield from select
        yield from storage.clear_replies(
            request.envelope.request_id, expected_reply_id=old_reply.reply.id
        )
        assert [r.id for r in (yield from storage.replies_for([request]))] == [
            old_reply.reply.id,
            completed.reply.id,
        ]
        assert (yield from select) == before
        assert len((yield from storage.unprocessed_messages([_SHARD]))) == 0

    yield from _run(backend, body)


@testing.live
def test_save_request(backend: Backend):
    """saveRequest"""

    def body(env: Env) -> Generator[fx.Effect[Any, Any, Any], Any]:
        storage = env.storage
        request = yield from make_request(payload={"id": 1})
        assert isinstance((yield from storage.save_request(request)), SaveSuccess)
        for i in range(2, 6):
            yield from storage.save_request((yield from make_request(payload={"id": i})))
        yield from storage.save_reply((yield from make_reply(request)))

        messages = yield from storage.unprocessed_messages([_SHARD])
        assert _payload_ids(messages) == [2, 3, 4, 5]
        for i in range(6, 11):
            yield from storage.save_request((yield from make_request(payload={"id": i})))
        messages = yield from storage.unprocessed_messages([_SHARD])
        assert _payload_ids(messages) == [6, 7, 8, 9, 10]

    yield from _run(backend, body)


@testing.live
def test_save_reply_and_save_request_duplicate(backend: Backend):
    """saveReply + saveRequest duplicate"""

    def body(env: Env) -> Generator[fx.Effect[Any, Any, Any], Any]:
        storage = env.storage
        request = yield from _stream_request()
        assert isinstance((yield from storage.save_request(request)), SaveSuccess)

        chunk = yield from make_chunk_reply(request, 0)
        yield from storage.save_reply(chunk)
        yield from storage.save_envelope((yield from make_ack_chunk(request, chunk)))
        chunk = yield from make_chunk_reply(request, 1)
        yield from storage.save_reply(chunk)

        result = yield from storage.save_request((yield from _stream_request()))
        assert isinstance(result, SaveDuplicate)
        assert isinstance(result.last_received_reply, Chunk)

        # the un-acked chunk
        assert len((yield from storage.replies_for([request]))) == 1

        yield from storage.save_reply((yield from make_reply(request)))
        result = yield from storage.save_request((yield from _stream_request()))
        assert isinstance(result, SaveDuplicate)
        assert isinstance(result.last_received_reply, WithExit)

        # a duplicate WithExit
        error = yield from storage.save_reply((yield from make_reply(request))).flip()
        assert isinstance(error, PersistenceError)

    yield from _run(backend, body)


@testing.live
def test_detects_duplicates(backend: Backend):
    """detects duplicates"""

    def body(env: Env) -> Generator[fx.Effect[Any, Any, Any], Any]:
        make = make_request(rpc=PrimaryKeyTest, payload=PrimaryKeyPayload(id=123))
        yield from env.storage.save_request((yield from make))
        result = yield from env.storage.save_request((yield from make))
        assert isinstance(result, SaveDuplicate)

    yield from _run(backend, body)


@testing.live
def test_hashes_primary_keys_longer_than_the_column(backend: Backend):
    """hashes primary keys longer than the message_id column"""

    def body(env: Env) -> Generator[fx.Effect[Any, Any, Any], Any]:
        long_id = "long-key-" * 50
        make = make_request(rpc=LongKeyRpc, payload=LongKeyPayload(id=long_id))
        request = yield from make
        assert isinstance((yield from env.storage.save_request(request)), SaveSuccess)
        assert isinstance((yield from env.storage.save_request((yield from make))), SaveDuplicate)
        request_id = yield from env.storage.request_id_for_primary_key(
            address=request.envelope.address, tag=request.envelope.tag, id=long_id
        )
        assert request_id == request.envelope.request_id
        rows = yield from env.sql("SELECT message_id FROM {}", env.messages)
        assert len(rows) == 1
        assert re.fullmatch(r"[0-9a-f]{64}", str(rows[0]["message_id"]))

    yield from _run(backend, body)


@testing.live
def test_keeps_short_primary_keys_as_plaintext(backend: Backend):
    """keeps primary keys within the column width as plaintext"""

    def body(env: Env) -> Generator[fx.Effect[Any, Any, Any], Any]:
        make = make_request(rpc=PrimaryKeyTest, payload=PrimaryKeyPayload(id=456))
        request = yield from make
        yield from env.storage.save_request(request)
        # rows of earlier versions hold the plaintext composed key
        plaintext = envelope.primary_key(request.envelope)
        rows = yield from env.sql("SELECT message_id FROM {}", env.messages)
        assert len(rows) == 1
        assert rows[0]["message_id"] == plaintext

        result = yield from env.storage.save_request((yield from make))
        assert isinstance(result, SaveDuplicate)
        assert result.original_id == request.envelope.request_id
        request_id = yield from env.storage.request_id_for_primary_key(
            address=request.envelope.address, tag=request.envelope.tag, id="456"
        )
        assert request_id == request.envelope.request_id

    yield from _run(backend, body)


@testing.live
def test_detects_duplicates_for_legacy_long_key_rows(tmp_path: Path):
    """detects duplicates for legacy long-key plaintext rows"""

    def body(env: Env) -> Generator[fx.Effect[Any, Any, Any], Any]:
        long_id = "legacy-long-key-" * 30
        make = make_request(rpc=LongKeyRpc, payload=LongKeyPayload(id=long_id))
        request = yield from make
        yield from env.storage.save_request(request)
        # a row written before message ids were hashed
        plaintext = envelope.primary_key(request.envelope)
        assert plaintext is not None and len(plaintext) > 255
        yield from env.sql(
            "UPDATE {} SET message_id = {} WHERE id = {}",
            env.messages,
            plaintext,
            str(request.envelope.request_id),
        )
        result = yield from env.storage.save_request((yield from make))
        assert isinstance(result, SaveDuplicate)
        assert result.original_id == request.envelope.request_id
        request_id = yield from env.storage.request_id_for_primary_key(
            address=request.envelope.address, tag=request.envelope.tag, id=long_id
        )
        assert request_id == request.envelope.request_id

    yield from _run(Backend("sqlite", lambda: make_client(tmp_path), "cluster"), body)


@testing.live
def test_unprocessed_messages(backend: Backend):
    """unprocessedMessages"""

    def body(env: Env) -> Generator[fx.Effect[Any, Any, Any], Any]:
        yield from env.storage.save_request((yield from make_request()))
        assert len((yield from env.storage.unprocessed_messages([_SHARD]))) == 1
        assert len((yield from env.storage.unprocessed_messages([_SHARD]))) == 0
        yield from env.storage.save_request((yield from make_request()))
        assert len((yield from env.storage.unprocessed_messages([_SHARD]))) == 1

    yield from _run(backend, body)


@testing.live
def test_unprocessed_messages_honors_the_limit(backend: Backend):
    """unprocessedMessages honors the limit and claims only returned rows"""

    def body(env: Env) -> Generator[fx.Effect[Any, Any, Any], Any]:
        for i in range(1, 6):
            request = yield from make_request(payload={"id": i}, entity_id=str(i))
            yield from env.storage.save_request(request)
        limited = yield from env.storage.unprocessed_messages([_SHARD], limit=3)
        assert _payload_ids(limited) == [1, 2, 3]
        assert _payload_ids((yield from env.storage.unprocessed_messages([_SHARD]))) == [4, 5]

    yield from _run(backend, body)


@testing.live
def test_unprocessed_messages_filters_by_address(backend: Backend):
    """unprocessedMessages filters by address"""

    def body(env: Env) -> Generator[fx.Effect[Any, Any, Any], Any]:
        for i in range(1, 5):
            request = yield from make_request(payload={"id": i}, entity_id=str(i))
            yield from env.storage.save_request(request)
        filtered = yield from env.storage.unprocessed_messages(
            [_SHARD], addresses=[_address("2"), _address("4")]
        )
        assert _payload_ids(filtered) == [2, 4]
        assert _payload_ids((yield from env.storage.unprocessed_messages([_SHARD]))) == [1, 3]

    yield from _run(backend, body)


@testing.live
def test_unprocessed_messages_filters_addresses_by_shard(backend: Backend):
    """unprocessedMessages filters addresses by shard"""

    def body(env: Env) -> Generator[fx.Effect[Any, Any, Any], Any]:
        one, two = shard_id.make("default", 1), shard_id.make("default", 2)
        yield from env.storage.save_request((yield from make_request(payload={"id": 1}, shard=one)))
        yield from env.storage.save_request((yield from make_request(payload={"id": 2}, shard=two)))
        messages = yield from env.storage.unprocessed_messages(
            [one, two], addresses=[_address("1", 1)]
        )
        assert _payload_ids(messages) == [1]
        assert _payload_ids((yield from env.storage.unprocessed_messages([one, two]))) == [2]

    yield from _run(backend, body)


@testing.live
def test_encoded_unprocessed_messages_fails_closed_for_empty_addresses(backend: Backend):
    """encoded unprocessedMessages fails closed for empty addresses"""

    def body(env: Env) -> Generator[fx.Effect[Any, Any, Any], Any]:
        request = yield from make_request()
        yield from env.storage.save_request(request)
        encoded = yield from env.encoded()
        shard = str(request.envelope.address.shard_id)
        assert (yield from encoded.unprocessed_messages([shard], _now(), addresses=[])) == []
        assert len((yield from encoded.unprocessed_messages([shard], _now()))) == 1

    yield from _run(backend, body)


@testing.live
def test_encoded_reset_addresses_fails_closed_for_empty_list(backend: Backend):
    """encoded resetAddresses fails closed for an empty address list"""

    def body(env: Env) -> Generator[fx.Effect[Any, Any, Any], Any]:
        request = yield from make_request()
        yield from env.storage.save_request(request)
        encoded = yield from env.encoded()
        shard = str(request.envelope.address.shard_id)
        assert len((yield from encoded.unprocessed_messages([shard], _now()))) == 1
        yield from encoded.reset_addresses([])
        assert (yield from encoded.unprocessed_messages([shard], _now())) == []

    yield from _run(backend, body)


@testing.live
def test_reset_addresses_releases_claims_in_one_batch(backend: Backend):
    """resetAddresses releases claims in one batch"""

    def body(env: Env) -> Generator[fx.Effect[Any, Any, Any], Any]:
        for i in range(1, 5):
            request = yield from make_request(payload={"id": i}, entity_id=str(i))
            yield from env.storage.save_request(request)
        yield from env.storage.unprocessed_messages([_SHARD], limit=3)
        yield from env.storage.reset_addresses([_address("1"), _address("3")])
        messages = yield from env.storage.unprocessed_messages([_SHARD])
        assert _payload_ids(messages) == [1, 3, 4]

    yield from _run(backend, body)


@testing.live
def test_unprocessed_messages_excludes_complete_requests(backend: Backend):
    """unprocessedMessages excludes complete requests"""

    def body(env: Env) -> Generator[fx.Effect[Any, Any, Any], Any]:
        request = yield from make_request()
        yield from env.storage.save_request(request)
        yield from env.storage.save_reply((yield from make_reply(request)))
        assert (yield from env.storage.unprocessed_messages([_SHARD])) == []

    yield from _run(backend, body)


@testing.live
def test_replies_for(backend: Backend):
    """repliesFor"""

    def body(env: Env) -> Generator[fx.Effect[Any, Any, Any], Any]:
        request = yield from make_request()
        yield from env.storage.save_request(request)
        assert (yield from env.storage.replies_for([request])) == []
        yield from env.storage.save_reply((yield from make_reply(request)))
        replies = yield from env.storage.replies_for([request])
        assert len(replies) == 1
        assert replies[0].request_id == request.envelope.request_id

    yield from _run(backend, body)


@testing.live
def test_register_reply_handler(backend: Backend):
    """registerReplyHandler"""

    def body(env: Env) -> Generator[fx.Effect[Any, Any, Any], Any]:
        latch = yield from Latch.make()
        request = yield from make_request()
        request.respond = lambda _reply: latch.open().as_void()
        yield from env.storage.save_request(request)
        fiber = yield from env.storage.register_reply_handler(request).fork()
        yield from fx.sleep("1 millis")
        yield from env.storage.save_reply((yield from make_reply(request)))
        yield from latch.wait()
        yield from fiber.await_exit()

    yield from _run(backend, body)


@testing.live
def test_unprocessed_messages_by_id(backend: Backend):
    """unprocessedMessagesById"""

    def body(env: Env) -> Generator[fx.Effect[Any, Any, Any], Any]:
        storage = env.storage
        request = yield from _stream_request()
        yield from storage.save_request(request)
        ids = [request.envelope.request_id]
        assert len((yield from storage.unprocessed_messages_by_id(ids))) == 1

        chunk = yield from make_chunk_reply(request)
        yield from storage.save_reply(chunk)
        ack = yield from make_ack_chunk(request, chunk)
        yield from storage.save_envelope(ack)

        encoded = yield from env.encoded()
        acknowledgements = yield from encoded.unprocessed_messages_by_id([ack.envelope.id], 0)
        assert len(acknowledgements) == 1
        assert acknowledgements[0].envelope["_tag"] == "AckChunk"
        assert acknowledgements[0].envelope["replyId"] == str(chunk.reply.id)

        yield from storage.save_reply((yield from make_reply(request)))
        assert (yield from storage.unprocessed_messages_by_id(ids)) == []

    yield from _run(backend, body)


def test_message_id_width_counts_utf16_code_units():
    """(pyfect) message ids measure keys in UTF-16 code units, as Effect's
    ``primaryKey.length`` does, so rows match Effect's (digest printed by
    Node)."""
    emoji = "\U0001f600"
    assert SqlMessageStorage.message_id_for_primary_key(emoji * 128) == (
        "fe398dab7db39ba250a21ff3e7f8099108b655511e183e3edde4fc55f0975d62"
    )
    assert SqlMessageStorage.message_id_for_primary_key(emoji * 127 + "a") == emoji * 127 + "a"
