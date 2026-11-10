"""Ports of the ``SqlEventLogServer`` titles of Effect's
``sql-sqlite-node/test/SqlEventLogServerEncrypted.test.ts`` for
``pyfect.eventlog.sql_event_log_server_encrypted`` on SQLite (its
``EventLogServerEncryptedTest`` suite runs on SQLite in
``test_event_log_server_encrypted.py``).

Each test's docstring is the Effect test title. ``RpcTest.makeClient`` is
``rpc.test.make_client``; a client's ``changes`` stream fails with the
server's error.
"""

from collections.abc import Callable, Generator, Sequence
from typing import Any

import pyfect as fx
from pyfect import stream as St
from pyfect import testing
from pyfect.context import Context
from pyfect.crypto import digest
from pyfect.eventlog import event_journal as J
from pyfect.eventlog import event_log as L
from pyfect.eventlog import event_log_message as M
from pyfect.eventlog import event_log_server_encrypted as Server
from pyfect.eventlog import sql_event_log_server_encrypted as SqlServer
from pyfect.eventlog._identity_derivation import make_get_identity_root_secret_material
from pyfect.eventlog.event_journal import Entry, StoreId
from pyfect.eventlog.event_log_encryption import (
    EncryptedBatch,
    EncryptedRemoteBatch,
    EventLogEncryption,
    EventLogEncryptionService,
    layer_subtle,
)
from pyfect.eventlog.event_log_session_auth import SessionAuthPayload, sign_session_auth_payload
from pyfect.reactivity import layer as reactivity_layer
from pyfect.redacted import value as reveal
from pyfect.rpc import test as rpc_test
from pyfect.sql import sqlite
from pyfect.sql.client import SqlClient

store_a = StoreId("store-a")
store_b = StoreId("store-b")
get_material = make_get_identity_root_secret_material()


def make_entry(value: int) -> Entry:
    return Entry(
        id=J.make_entry_id_unsafe(),
        event="UserCreated",
        primary_key=f"user-{value}",
        payload=bytes([value]),
    )


def make_batch(index: int, entry_id: J.EntryId | None = None) -> EncryptedBatch:
    return EncryptedBatch(
        entry_ids=(entry_id or J.make_entry_id_unsafe(),),
        iv=bytes(12),
        encrypted_batch=bytes([index]),
    )


def _storage() -> Generator[Any, Any, Server.StorageService]:
    client = yield from sqlite.make(sqlite.SqliteClientConfig(filename=":memory:"))
    return (yield from SqlServer.make_storage().pipe(fx.provide_service(SqlClient, client)))


def _run(body: Callable[[], Generator[Any, Any, Any]]) -> fx.Effect[Any, Any, Any]:
    return fx.gen(body).pipe(
        fx.provide(fx.layer.merge(reactivity_layer, layer_subtle, digest.layer_web_crypto))
    )


def _encode_write(
    encryption: EventLogEncryptionService, identity: L.IdentityService, entry: Entry
) -> Generator[Any, Any, bytes]:
    batches = yield from encryption.encrypt(identity, store_a, [entry])
    return (
        yield from M.WriteEntries(
            public_key=identity.public_key, store_id=store_a, batches=tuple(batches)
        ).encoded
    )


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


def _handlers(storage: Server.StorageService) -> fx.Layer[Any, Any, Any]:
    return Server.layer_rpc_handlers.pipe(
        fx.layer.provide(fx.layer.succeed(Server.Storage, storage))
    )


def _client(
    handlers: fx.Layer[Any, Any, Any] | Context[Any],
) -> fx.Effect[M.EventLogRemoteRpcs, Any, Any]:
    return rpc_test.make_client(M.EventLogRemoteRpcs).pipe(fx.provide(handlers))


def _authenticated_client(
    storage: Server.StorageService, identities: Sequence[L.IdentityService]
) -> Generator[Any, Any, M.EventLogRemoteRpcs]:
    client = yield from _client(_handlers(storage))
    for identity in identities:
        hello = yield from client.hello()
        yield from client.authenticate((yield from _authenticate_request(identity, hello)))
    return client


def _assert_forbidden(effect: fx.Effect[Any, Any, Any]) -> Generator[Any, Any]:
    error = yield from effect.flip()
    assert isinstance(error, M.EventLogProtocolError)
    assert error.code == "Forbidden"


def _take(stream: St.Stream[Any, Any, Any], n: int) -> fx.Effect[list[Any], Any, Any]:
    return stream.take(n).run_collect()


def _split(data: bytes) -> tuple[M.ChunkedMessage, M.ChunkedMessage]:
    midpoint = (len(data) + 1) // 2
    return (
        M.ChunkedMessage(id=1, part=(0, 2), data=data[:midpoint]),
        M.ChunkedMessage(id=1, part=(1, 2), data=data[midpoint:]),
    )


def _sequences(batches: Sequence[EncryptedRemoteBatch]) -> list[int]:
    return [batch.sequence for batch in batches]


@testing.effect
def test_forbids_reading_another_identitys_changes():
    """SqlEventLogServer / forbids reading another identity's changes"""

    def body():
        storage = yield from _storage()
        encryption = yield from EventLogEncryption()
        identity_a = yield from encryption.generate_identity
        identity_b = yield from encryption.generate_identity
        client = yield from _authenticated_client(storage, [identity_a])
        yield from storage.write(identity_b.public_key, store_a, [make_batch(1)])
        yield from _assert_forbidden(
            _take(
                client.changes(
                    {"public_key": identity_b.public_key, "store_id": store_a, "start_sequence": 0}
                ),
                1,
            )
        )

    yield from _run(body)


@testing.effect
def test_forbids_writing_entries_for_another_identity():
    """SqlEventLogServer / forbids writing entries for another identity"""

    def body():
        storage = yield from _storage()
        encryption = yield from EventLogEncryption()
        identity_a = yield from encryption.generate_identity
        identity_b = yield from encryption.generate_identity
        client = yield from _authenticated_client(storage, [identity_a])
        data = yield from _encode_write(encryption, identity_b, make_entry(1))
        yield from _assert_forbidden(client.write_single({"data": data}))
        written = yield from storage.write(identity_b.public_key, store_a, [make_batch(2)])
        assert _sequences(written) == [1]

    yield from _run(body)


@testing.effect
def test_forbids_writing_chunked_entries_for_another_identity():
    """SqlEventLogServer / forbids writing chunked entries for another identity"""

    def body():
        storage = yield from _storage()
        encryption = yield from EventLogEncryption()
        identity_a = yield from encryption.generate_identity
        identity_b = yield from encryption.generate_identity
        client = yield from _authenticated_client(storage, [identity_a])
        first, second = _split((yield from _encode_write(encryption, identity_b, make_entry(1))))
        yield from client.write_chunked(first)
        yield from _assert_forbidden(client.write_chunked(second))
        written = yield from storage.write(identity_b.public_key, store_a, [make_batch(2)])
        assert _sequences(written) == [1]

    yield from _run(body)


@testing.effect
def test_isolates_authenticated_identities_between_connections():
    """SqlEventLogServer / isolates authenticated identities between connections"""

    def body():
        storage = yield from _storage()
        encryption = yield from EventLogEncryption()
        identity_a = yield from encryption.generate_identity
        identity_b = yield from encryption.generate_identity
        handlers = yield from _handlers(storage).build()
        client_a = yield from _client(handlers)
        client_b = yield from _client(handlers)
        hello_a = yield from client_a.hello()
        yield from client_a.authenticate((yield from _authenticate_request(identity_a, hello_a)))
        hello_b = yield from client_b.hello()
        yield from client_b.authenticate((yield from _authenticate_request(identity_b, hello_b)))
        data = yield from _encode_write(encryption, identity_b, make_entry(1))
        first, second = _split(data)
        yield from storage.write(identity_b.public_key, store_a, [make_batch(1)])
        yield from _assert_forbidden(
            _take(
                client_a.changes(
                    {"public_key": identity_b.public_key, "store_id": store_a, "start_sequence": 0}
                ),
                1,
            )
        )
        yield from _assert_forbidden(client_a.write_single({"data": data}))
        yield from client_a.write_chunked(first)
        yield from _assert_forbidden(client_a.write_chunked(second))

    yield from _run(body)


@testing.effect
def test_supports_multiple_authenticated_identities_on_one_connection():
    """SqlEventLogServer / supports multiple authenticated identities on one connection"""

    def body():
        storage = yield from _storage()
        encryption = yield from EventLogEncryption()
        identity_a = yield from encryption.generate_identity
        identity_b = yield from encryption.generate_identity
        client = yield from _authenticated_client(storage, [identity_a, identity_b])
        data_a = yield from _encode_write(encryption, identity_a, make_entry(1))
        data_b = yield from _encode_write(encryption, identity_b, make_entry(2))
        yield from client.write_single({"data": data_a})
        yield from client.write_single({"data": data_b})
        changes_a = yield from _take(
            client.changes(
                {"public_key": identity_a.public_key, "store_id": store_a, "start_sequence": 0}
            ),
            1,
        )
        changes_b = yield from _take(
            client.changes(
                {"public_key": identity_b.public_key, "store_id": store_a, "start_sequence": 0}
            ),
            1,
        )
        assert len(changes_a) == 1
        assert len(changes_b) == 1

    yield from _run(body)


@testing.effect
def test_persists_remote_id_across_storage_instances():
    """SqlEventLogServer / persists remote id across storage instances"""

    def body():
        client = yield from sqlite.make(sqlite.SqliteClientConfig(filename=":memory:"))
        storage_a = yield from SqlServer.make_storage().pipe(fx.provide_service(SqlClient, client))
        storage_b = yield from SqlServer.make_storage().pipe(fx.provide_service(SqlClient, client))
        assert (yield from storage_a.get_id) == (yield from storage_b.get_id)

    yield from _run(body)


@testing.effect
def test_rejects_session_auth_rebinding_for_an_existing_public_key():
    """SqlEventLogServer / rejects session-auth rebinding for an existing publicKey"""

    def body():
        storage = yield from _storage()
        client = yield from _client(_handlers(storage))
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

    yield from _run(body)


@testing.effect
def test_writes_entries_and_streams_changes():
    """SqlEventLogServer / writes entries and streams changes"""

    def body():
        storage = yield from _storage()
        encryption = yield from EventLogEncryption()
        identity = yield from encryption.generate_identity
        persisted = yield from encryption.encrypt(identity, store_a, [make_entry(1), make_entry(2)])
        written = yield from storage.write(identity.public_key, store_a, persisted)
        assert _sequences(written) == [1]
        decrypted = yield from encryption.decrypt(identity, store_a, written)
        assert [e.remote_sequence for e in decrypted] == [1, 2]
        changes = yield from storage.changes(identity.public_key, store_a, 0).to_queue(
            capacity="unbounded"
        )
        taken = yield from changes.take_all()
        decrypted = yield from encryption.decrypt(identity, store_a, taken)
        assert [e.remote_sequence for e in decrypted] == [1, 2]
        next_persisted = yield from encryption.encrypt(identity, store_a, [make_entry(3)])
        updated = yield from storage.write(identity.public_key, store_a, next_persisted)
        assert _sequences(updated) == [3]
        assert (yield from changes.take()).sequence == 3

    yield from _run(body)


@testing.effect
def test_publishes_each_entry_only_once_when_the_same_batch_is_written_twice():
    """SqlEventLogServer / publishes each entry only once when the same batch is written twice"""

    def body():
        storage = yield from _storage()
        entries = [make_batch(1), make_batch(2)]
        written = yield from storage.write("client-1", store_a, entries)
        assert _sequences(written) == [1, 2]
        changes = yield from storage.changes("client-1", store_a, 0).to_queue(capacity="unbounded")
        assert [(yield from changes.take()), (yield from changes.take())] == written
        yield from storage.write("client-1", store_a, entries)
        acks = yield from storage.entry_sequences(
            "client-1", store_a, [entries[1].entry_ids[0], entries[0].entry_ids[0]]
        )
        assert sorted(acks, key=lambda ack: ack.sequence) == [
            M.WriteAck(entry_id=entries[0].entry_ids[0], sequence=1),
            M.WriteAck(entry_id=entries[1].entry_ids[0], sequence=2),
        ]
        next_ = yield from storage.write("client-1", store_a, [make_batch(3)])
        # A fresh entry marks the end of the replay without a sleep or timeout.
        published = yield from (
            St.from_queue(changes)
            .take_until(lambda batch: batch.sequence == next_[0].sequence)
            .run_collect()
        )
        backlog = yield from _take(storage.changes("client-1", store_a, 0), 3)
        assert backlog == [*written, *next_]
        assert published == next_

    yield from _run(body)


@testing.effect
def test_isolates_same_public_key_across_store_ids():
    """SqlEventLogServer / isolates same publicKey across storeIds"""

    def body():
        storage = yield from _storage()
        yield from storage.write("client-1", store_a, [make_batch(1)])
        yield from storage.write("client-1", store_b, [make_batch(2)])
        assert _sequences((yield from _take(storage.changes("client-1", store_a, 0), 1))) == [1]
        assert _sequences((yield from _take(storage.changes("client-1", store_b, 0), 1))) == [1]

    yield from _run(body)


@testing.effect
def test_isolates_same_store_id_across_public_keys():
    """SqlEventLogServer / isolates same storeId across publicKeys"""

    def body():
        storage = yield from _storage()
        yield from storage.write("client-1", store_a, [make_batch(1)])
        yield from storage.write("client-2", store_a, [make_batch(2)])
        assert _sequences((yield from _take(storage.changes("client-1", store_a, 0), 1))) == [1]
        assert _sequences((yield from _take(storage.changes("client-2", store_a, 0), 1))) == [1]

    yield from _run(body)


@testing.effect
def test_keeps_deduplication_isolated_per_encrypted_scope():
    """SqlEventLogServer / keeps deduplication isolated per encrypted scope"""

    def body():
        storage = yield from _storage()
        shared = J.make_entry_id_unsafe()
        yield from storage.write("client-1", store_a, [make_batch(1, shared)])
        yield from storage.write("client-1", store_a, [make_batch(2, shared)])
        yield from storage.write("client-1", store_b, [make_batch(3, shared)])
        yield from storage.write("client-2", store_a, [make_batch(4, shared)])
        assert _sequences((yield from _take(storage.changes("client-1", store_a, 0), 1))) == [1]
        assert _sequences((yield from _take(storage.changes("client-1", store_b, 0), 1))) == [1]
        assert _sequences((yield from _take(storage.changes("client-2", store_a, 0), 1))) == [1]

    yield from _run(body)


@testing.effect
def test_acknowledges_each_id_of_a_batch_at_its_own_sequence():
    """pyfect: each id of a multi-id batch is acknowledged at the sequence of its
    entry (Effect's titles only acknowledge single-id batches)"""

    def body():
        storage = yield from _storage()
        first, second, third = (J.make_entry_id_unsafe() for _ in range(3))
        batch = EncryptedBatch(entry_ids=(first, second), iv=bytes(12), encrypted_batch=b"\1")
        yield from storage.write("client-1", store_a, [batch])
        yield from storage.write("client-1", store_a, [make_batch(3, third)])
        acks = yield from storage.entry_sequences("client-1", store_a, [first, second, third])
        assert sorted((ack.sequence, ack.entry_id) for ack in acks) == [
            (1, first),
            (2, second),
            (3, third),
        ]

    yield from _run(body)
