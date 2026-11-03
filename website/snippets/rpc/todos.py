import pyfect as fx
from pyfect import layer, stream
from pyfect import schema as S
from pyfect.http import httpx_client, router, server, uvicorn_server
from pyfect.rpc import RpcGroup, RpcRequest, make, rpc_schema, serialization
from pyfect.rpc import client as rpc_client
from pyfect.rpc import server as rpc_server


class Todo(S.Class, identifier="Todo"):
    id: int
    title: str


class TodoNotFound(S.TaggedError):
    id: int


# The group: each RPC's payload, success and error are schemas.
class Todos(RpcGroup):
    get_todo = make("GetTodo", payload=S.Int, success=Todo, error=TodoNotFound)
    # A stream RPC: the client gets the values as the handler produces them.
    countdown = make("Countdown", payload=S.Int, success=rpc_schema.Stream(S.Int, S.Never))


todos = {1: Todo(id=1, title="Write docs")}


@fx.fn
def get_todo(request: RpcRequest[int]):
    todo = todos.get(request.payload)
    if todo is None:
        return (yield from TodoNotFound(id=request.payload))
    return todo


def countdown(request: RpcRequest[int]):
    return stream.iterate(request.payload, lambda n: n - 1).take(request.payload + 1)


TodosLive = Todos.to_layer(
    Todos.handlers().handle(Todos.get_todo)(get_todo).handle(Todos.countdown)(countdown)
)

# Serve the group on POST /rpc of the router. It needs the handlers and a serialization.
RpcLive = rpc_server.layer_http(Todos, path="/rpc", protocol="http")


def client_protocol(url: str):
    return rpc_client.layer_protocol_http(url).pipe(layer.provide(serialization.layer_ndjson))


# The client: an instance of the group whose attributes call the server. `layer=` builds
# the protocol into this scope, so it lives as long as the client.
@fx.fn
def program():
    url = yield from server.address_formatted_with(lambda origin: fx.succeed(f"{origin}/rpc"))
    todos_client = yield from rpc_client.make(Todos, layer=client_protocol(url))
    print((yield from todos_client.get_todo(1)))
    print(repr((yield from todos_client.get_todo(2).flip())))
    print((yield from todos_client.countdown(3).run_collect()))


# serve passes what the routes need through: provide the handlers and newline-delimited
# JSON to the served layer.
served = (
    router.serve(RpcLive, disable_logger=True, disable_listen_log=True)
    .pipe(layer.provide(TodosLive))
    .pipe(layer.provide(serialization.layer_ndjson))
)
fx.run_main(
    fx.scoped(program())
    .pipe(fx.provide(served))
    .pipe(fx.provide(uvicorn_server.layer(host="127.0.0.1")))  # any free port
    .pipe(fx.provide(httpx_client.layer))
)
