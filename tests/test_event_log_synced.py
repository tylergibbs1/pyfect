"""``EventLogService.synced`` (a pyfect addition, dogfood quill #3: Effect has no way to
wait for a sync): it succeeds once the remote has acknowledged the log's entries and the
log has applied the remote's changes up to the latest sequence the server reports through
``EventLog.LatestSequence``. Each storage reports that sequence."""

from collections.abc import Callable, Generator, Sequence
from typing import Any, TypedDict

import pytest

import pyfect as fx
from pyfect import layer
from pyfect import schema as S
from pyfect.crypto import digest
from pyfect.eventlog import event as Ev
from pyfect.eventlog import event_group as G
from pyfect.eventlog import event_journal as J
from pyfect.eventlog import event_log as L
from pyfect.eventlog import event_log_remote as Remote
from pyfect.eventlog import event_log_server_encrypted as Server
from pyfect.eventlog import event_log_server_unencrypted as U
from pyfect.eventlog import sql_event_journal as SqlJ
from pyfect.eventlog import sql_event_log_server_encrypted as SqlServer
from pyfect.eventlog import sql_event_log_server_unencrypted as SqlU
from pyfect.eventlog.event_journal import Entry, RemoteEntry, StoreId
from pyfect.eventlog.event_log_encryption import EncryptedBatch, layer_subtle
from pyfect.eventlog.event_log_message import WriteAck
from pyfect.eventlog.event_log_remote import EventLogRemoteError, EventLogRemoteService
from pyfect.http import router, uvicorn_server
from pyfect.http import server as http_server
from pyfect.reactivity import layer as reactivity_layer
from pyfect.rpc import client as rpc_client
from pyfect.rpc import serialization
from pyfect.rpc import server as rpc_server
from pyfect.socket import ws
from pyfect.sql import sqlite
from pyfect.sql.client import SqlClient


class Note(TypedDict):
    id: str
    text: str


NoteAdded = Ev.make("NoteAdded", primary_key=lambda p: p["id"], payload=S.Struct(Note))
Notes = G.empty.add(NoteAdded)


def _device(identity: L.IdentityService, url: str) -> fx.Layer[Any, Any, Any]:
    handlers = L.group(Notes, lambda h: h.handle(NoteAdded, lambda _: fx.void))
    log = L.layer(L.schema(Notes), handlers).pipe(
        layer.provide(layer.merge(J.layer_memory, layer.succeed(L.Identity, identity)))
    )
    socket = rpc_client.layer_protocol_socket().pipe(
        layer.provide(layer.merge(ws.layer_web_socket(url), serialization.layer_ndjson))
    )
    return Remote.layer_encrypted.pipe(layer.provide(socket)).pipe(layer.provide_merge(log))


def _texts(entries: list[Entry]) -> list[str]:
    return sorted(entry.primary_key for entry in entries)


@fx.fn
def _two_devices():
    url = yield from http_server.address_formatted_with(
        lambda a: fx.succeed(a.replace("http://", "ws://") + "/sync")
    )
    identity = yield from L.make_identity
    phone = yield from _device(identity, url).build()
    laptop = yield from _device(identity, url).build()
    phone_log = phone.get(L.EventLog)
    laptop_log = laptop.get(L.EventLog)

    yield from laptop_log.write(NoteAdded, {"id": "n1", "text": "milk"})
    yield from laptop_log.write(NoteAdded, {"id": "n2", "text": "eggs"})
    yield from laptop_log.synced
    # Nothing waits for the phone's handler: synced alone says it has the entries.
    yield from phone_log.synced
    return _texts((yield from phone_log.entries))


def test_synced_waits_for_the_writes_of_another_device() -> None:
    protocol = rpc_server.layer_protocol_websocket("/sync").pipe(
        layer.provide(serialization.layer_ndjson)
    )
    routes = Server.layer.pipe(layer.provide(layer.merge(protocol, Server.layer_storage_memory)))
    served = router.serve(routes, disable_logger=True, disable_listen_log=True)
    program = (
        fx.scoped(_two_devices())
        .pipe(fx.provide(served))
        .pipe(fx.provide(uvicorn_server.layer_test()))
        .pipe(fx.provide(layer_subtle))
    )
    assert fx.run_blocking_exit(program.timeout("20 seconds")) == fx.Success(["n1", "n2"])


def test_synced_with_no_remote_succeeds_at_once() -> None:
    @fx.fn
    def body():
        log = yield from L.EventLog()
        yield from log.write(NoteAdded, {"id": "n1", "text": "milk"})
        yield from log.synced

    handlers = L.group(Notes, lambda h: h.handle(NoteAdded, lambda _: fx.void))
    log = L.layer(L.schema(Notes), handlers).pipe(
        layer.provide(layer.merge(J.layer_memory, layer.effect(L.Identity, L.make_identity)))
    )
    program = body().pipe(fx.provide(log)).pipe(fx.provide(layer_subtle))
    assert fx.run_blocking_exit(program) == fx.Success(None)


# --- the cursor and this log's own acknowledged writes ------------------------------


def _journals() -> dict[str, fx.Layer[J.EventJournal, Any]]:
    sql = sqlite.layer(sqlite.SqliteClientConfig(filename=":memory:"))
    return {"memory": J.layer_memory, "sql": SqlJ.layer().pipe(layer.provide(sql))}


class _OwnWritesNotEchoed:
    """A remote holding another device's entry at sequence 0. It leaves this log's writes
    out of its change stream, as Effect's server leaves out a connection's own writes, and
    it sends the other entry once, when first asked for its latest sequence. ``synced`` asks after
    its upload's acks are committed (the uploader's too: ``with_remote_uncommitted`` has
    nothing left for ``synced`` only once they are), so they come before the replay."""

    def __init__(self, other: Entry, changes: fx.Queue[RemoteEntry, EventLogRemoteError]):
        self.stored = [other]
        self._changes = changes
        self._sent = False
        self.service = EventLogRemoteService(
            id=J.make_remote_id_unsafe(),
            changes=self._open_changes,
            write=self._write,
            latest_sequence=self._latest_sequence,
        )

    def _open_changes(self, **_: object) -> fx.Effect[fx.Queue[RemoteEntry, EventLogRemoteError]]:
        return fx.succeed(self._changes)

    def _write(self, *, entries: Sequence[Entry], **_: object) -> fx.Effect[list[WriteAck]]:
        def store() -> list[WriteAck]:
            ids = [entry.id for entry in self.stored]
            for entry in entries:
                if entry.id not in ids:
                    self.stored.append(entry)
                    ids.append(entry.id)
            return [WriteAck(entry_id=e.id, sequence=ids.index(e.id)) for e in entries]

        return fx.sync(store)

    def _latest_sequence(self, **_: object) -> fx.Effect[int]:
        latest = len(self.stored) - 1
        if self._sent:
            return fx.succeed(latest)
        self._sent = True
        return self._changes.offer(RemoteEntry(remote_sequence=0, entry=self.stored[0])).as_(latest)


def _synced_against_a_remote_that_skips_own_writes(
    journal: str, then: fx.Effect[Any, Any, L.EventLog] = fx.void
) -> fx.Exit[Any, Any]:
    """Writes n2, waits for ``synced`` (the remote's n1 replays only after n2's acks
    commit), runs ``then`` and gives the log's entries and what ``then`` gave."""

    @fx.fn
    def body():
        log = yield from L.EventLog()
        registry = yield from L.Registry()
        payload = yield from S.encode_effect(NoteAdded.payload_codec)({"id": "n1", "text": "milk"})
        other = Entry(
            id=J.make_entry_id_unsafe(), event="NoteAdded", primary_key="n1", payload=payload
        )
        changes = yield from fx.Queue[RemoteEntry, EventLogRemoteError].unbounded()
        yield from registry.register_remote(_OwnWritesNotEchoed(other, changes).service)
        yield from log.write(NoteAdded, {"id": "n2", "text": "eggs"})
        yield from log.synced
        after = yield from then
        return _texts((yield from log.entries)), after

    handlers = L.group(Notes, lambda h: h.handle(NoteAdded, lambda _: fx.void))
    log = L.layer(L.schema(Notes), handlers).pipe(
        layer.provide(layer.merge(_journals()[journal], layer.effect(L.Identity, L.make_identity)))
    )
    program = fx.scoped(body()).pipe(fx.provide(log)).pipe(fx.provide(layer_subtle))
    return fx.run_blocking_exit(program.timeout("10 seconds"))


@pytest.mark.parametrize("journal", _journals())
def test_synced_succeeds_when_its_acks_commit_before_the_replay(journal: str) -> None:
    # Quill's hang: the ack of sequence 1 came while the cursor was still 0, so it could not
    # move it; the replay of 0 moved it to 1, and 1 never comes back on this connection.
    exit = _synced_against_a_remote_that_skips_own_writes(journal)
    assert exit == fx.Success((["n1", "n2"], None))


def test_synced_after_destroy_does_not_count_the_acks_of_destroyed_entries() -> None:
    # destroy empties the journal and resets its cursor; the remote still holds n1 and n2,
    # which the log no longer has, so synced must not succeed (Effect does not restart the
    # change stream on destroy, so nothing re-applies them: it waits).
    @fx.fn
    def destroy_then_sync():
        log = yield from L.EventLog()
        yield from log.destroy
        return (yield from log.synced.timeout("1 second").exit())

    exit = _synced_against_a_remote_that_skips_own_writes("memory", destroy_then_sync())
    assert isinstance(exit, fx.Success), exit
    entries, synced = exit.value
    assert entries == []
    assert not isinstance(synced, fx.Success), synced


# --- each storage reports its latest sequence ---------------------------------------

store = StoreId("store")


def _entry(n: int) -> Entry:
    return Entry(id=J.make_entry_id_unsafe(), event="E", primary_key=f"k{n}", payload=bytes([n]))


def _batch(size: int) -> EncryptedBatch:
    return EncryptedBatch(
        entry_ids=tuple(J.make_entry_id_unsafe() for _ in range(size)),
        iv=bytes(12),
        encrypted_batch=b"x",
    )


def _sqlite() -> fx.Effect[Any, Any, Any]:
    return sqlite.make(sqlite.SqliteClientConfig(filename=":memory:"))


def _encrypted(make: fx.Effect[Server.StorageService, Any, Any]) -> Generator[Any, Any, list[Any]]:
    storage = yield from make
    seen = [(yield from storage.latest_sequence("pk", store))]
    yield from storage.write("pk", store, [_batch(2), _batch(3)])
    seen.append((yield from storage.latest_sequence("pk", store)))
    seen.append((yield from storage.latest_sequence("other", store)))
    return seen


def _unencrypted(make: fx.Effect[U.StorageService, Any, Any]) -> Generator[Any, Any, list[Any]]:
    storage = yield from make
    seen = [(yield from storage.latest_sequence(store))]
    yield from storage.write(store, [_entry(n) for n in range(5)])
    seen.append((yield from storage.latest_sequence(store)))
    seen.append((yield from storage.latest_sequence(StoreId("other"))))
    return seen


def _sql_encrypted() -> fx.Effect[Server.StorageService, Any, Any]:
    return _sqlite().flat_map(
        lambda client: SqlServer.make_storage().pipe(fx.provide_service(SqlClient, client))
    )


def _sql_unencrypted() -> fx.Effect[U.StorageService, Any, Any]:
    return _sqlite().flat_map(
        lambda client: SqlU.make_storage().pipe(fx.provide_service(SqlClient, client))
    )


STORAGES: dict[str, Callable[[], Generator[Any, Any, list[Any]]]] = {
    "encrypted-memory": lambda: _encrypted(Server.make_storage_memory),
    "encrypted-sql": lambda: _encrypted(_sql_encrypted()),
    "unencrypted-memory": lambda: _unencrypted(U.make_storage_memory),
    "unencrypted-sql": lambda: _unencrypted(_sql_unencrypted()),
}


@pytest.mark.parametrize("name", STORAGES)
def test_a_storage_reports_the_sequence_of_its_last_entry(name: str) -> None:
    # Five entries each; the memory encrypted storage numbers from 0.
    first = 0 if name == "encrypted-memory" else 1
    program = fx.scoped(fx.gen(STORAGES[name])).pipe(
        fx.provide(layer.merge(layer_subtle, reactivity_layer, digest.layer_web_crypto))
    )
    assert fx.run_blocking_exit(program) == fx.Success([None, first + 4, None])
