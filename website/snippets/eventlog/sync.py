from typing import TypedDict

import pyfect as fx
from pyfect import layer
from pyfect import schema as S
from pyfect.eventlog import event as Ev
from pyfect.eventlog import event_group as G
from pyfect.eventlog import event_journal as J
from pyfect.eventlog import event_log as L
from pyfect.eventlog import event_log_remote as Remote
from pyfect.eventlog import event_log_server_encrypted as Server
from pyfect.eventlog.event_log_encryption import layer_subtle
from pyfect.http import router, uvicorn_server
from pyfect.http import server as http_server
from pyfect.rpc import client as rpc_client
from pyfect.rpc import serialization
from pyfect.rpc import server as rpc_server
from pyfect.socket import ws


class Note(TypedDict):
    id: str
    text: str


NoteAdded = Ev.make("NoteAdded", primary_key=lambda p: p["id"], payload=S.Struct(Note))
Notes = G.empty.add(NoteAdded)

# The server stores encrypted batches it cannot read, served as RPC over a WebSocket.
protocol = rpc_server.layer_protocol_websocket("/sync").pipe(
    layer.provide(serialization.layer_ndjson)
)
sync_server = Server.layer.pipe(layer.provide(layer.merge(protocol, Server.layer_storage_memory)))
served = router.serve(sync_server, disable_logger=True, disable_listen_log=True)


def device(name: str, identity: L.IdentityService, url: str, seen: fx.Queue[str]):
    """One client: its own journal and read model, syncing as ``identity``."""

    def added(note: L.HandlerInput[Note]) -> fx.Effect[None]:
        return seen.offer(f"{name} has {note.payload['text']!r}").as_void()

    handlers = L.group(Notes, lambda h: h.handle(NoteAdded, added))
    log = L.layer(L.schema(Notes), handlers).pipe(
        layer.provide(layer.merge(J.layer_memory, layer.succeed(L.Identity, identity)))
    )
    socket = rpc_client.layer_protocol_socket().pipe(
        layer.provide(layer.merge(ws.layer_web_socket(url), serialization.layer_ndjson))
    )
    remote = Remote.layer_encrypted.pipe(layer.provide(socket))
    return remote.pipe(layer.provide_merge(log))


@fx.fn
def program():
    url = yield from http_server.address_formatted_with(
        lambda a: fx.succeed(a.replace("http://", "ws://") + "/sync")
    )
    # Both devices are the same user: the identity travels as text (a QR code, say).
    identity = yield from L.make_identity
    shared = L.decode_identity_string(L.encode_identity_string(identity))
    seen = yield from fx.Queue[str].unbounded()

    # The phone stays connected for the rest of the program.
    yield from device("phone", shared, url, seen).build()

    @fx.fn
    def on_laptop():
        log = yield from L.EventLog()
        yield from log.write(NoteAdded, {"id": "n1", "text": "buy milk"})
        # The laptop handles its own write; the phone gets it through the server.
        for _ in range(2):
            print((yield from seen.take()))

    yield from fx.scoped(on_laptop()).pipe(fx.provide(device("laptop", identity, url, seen)))


fx.run_main(
    fx.scoped(program())
    .pipe(fx.provide(served))
    .pipe(fx.provide(uvicorn_server.layer_test()))
    .pipe(fx.provide(layer_subtle))
)
