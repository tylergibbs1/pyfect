import pyfect as fx
from pyfect import layer, stream
from pyfect import schema as S
from pyfect.http import router, uvicorn_server
from pyfect.http.client import HttpClient
from pyfect.http_api import HttpApi, HttpApiGroup, builder, client, endpoint
from pyfect.http_api import schema as api_schema
from pyfect.reactivity import atom, atom_http_api, atom_registry


class Status(HttpApiGroup, identifier="status"):
    # Server-Sent Events: the success is a stream of the events' data.
    changes = endpoint.get("changes", "/changes", success=api_schema.StreamSse(data=S.String))
    connected = endpoint.get("connected", "/connected", success=S.Int)


api = HttpApi.make("status").add(Status)
connections = [0]


def changes() -> fx.Effect[fx.Stream[str]]:
    """Each connection sends two events, then the stream ends."""
    connections[0] += 1
    n = connections[0]
    return fx.succeed(stream.make(f"connection {n}: up", f"connection {n}: down"))


ApiLive = builder.layer(api).pipe(
    layer.provide(
        builder.group(
            api,
            Status,
            lambda handlers: handlers.handle(Status.changes)(lambda _: changes()).handle(
                Status.connected
            )(lambda _: fx.sync(lambda: connections[0])),
        )
    )
)


class StatusClient(fx.Tag[client.Client[Status]]): ...


@fx.gen
def program():
    http = yield from HttpClient()
    api_atoms = atom_http_api.make(
        StatusClient, api=api, http_client=layer.succeed(HttpClient, http)
    )
    # The query holds the open stream, not an event.
    events = api_atoms.query(Status, Status.changes)
    # A stream atom over it holds the latest event, waiting while the stream is open.
    # suspend_on_waiting: once the query is refreshed, read the new stream, not the old one.
    latest = atom.make(lambda get: stream.unwrap(get.result(events, suspend_on_waiting=True)))
    # Another query, fetched again whenever an event arrives.
    connected = api_atoms.query(Status, Status.connected).refresh_on_signal(latest)
    yield from atom.mount(latest)
    yield from atom.mount(connected)
    print((yield from atom.get_result(latest, suspend_on_waiting=True)))

    # Not waiting means the stream has ended: refresh the query to connect again.
    yield from atom.refresh(events)
    print((yield from atom.get_result(latest, suspend_on_waiting=True)))
    print("connections:", (yield from atom.get_result(connected, suspend_on_waiting=True)))


served = router.serve(ApiLive, disable_logger=True, disable_listen_log=True)
fx.run_main(
    fx.scoped(program)
    .pipe(fx.provide(atom_registry.layer))
    .pipe(fx.provide(served))
    .pipe(fx.provide(uvicorn_server.layer_test()))
)
