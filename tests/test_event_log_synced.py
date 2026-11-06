"""``EventLogService.synced`` (a pyfect addition, dogfood quill #3: Effect has no way to
wait for a sync): it succeeds once the remote has acknowledged the log's entries and the
log has applied the remote's changes up to the latest sequence the server reports through
``EventLog.LatestSequence``. Each storage reports that sequence."""

from collections.abc import Callable, Generator
from typing import Any, TypedDict

import pytest

import pyfect as fx
from pyfect import layer
from pyfect import schema as S
from pyfect.eventlog import event as Ev
from pyfect.eventlog import event_group as G
from pyfect.eventlog import event_journal as J
from pyfect.eventlog import event_log as L
from pyfect.eventlog import event_log_remote as Remote
from pyfect.eventlog import event_log_server_encrypted as Server
from pyfect.eventlog import event_log_server_unencrypted as U
from pyfect.eventlog import sql_event_log_server_encrypted as SqlServer
from pyfect.eventlog import sql_event_log_server_unencrypted as SqlU
from pyfect.eventlog.event_journal import Entry, StoreId
from pyfect.eventlog.event_log_encryption import EncryptedBatch, layer_subtle
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
    assert fx.run_blocking_exit(program.timeout(20)) == fx.Success(["n1", "n2"])


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
        fx.provide(layer.merge(layer_subtle, reactivity_layer))
    )
    assert fx.run_blocking_exit(program) == fx.Success([None, first + 4, None])
