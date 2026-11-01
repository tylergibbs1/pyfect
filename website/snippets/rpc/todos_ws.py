import pyfect as fx
from pyfect import layer
from pyfect import schema as S
from pyfect.http import router, server, uvicorn_server
from pyfect.rpc import RpcGroup, RpcRequest, make, serialization
from pyfect.rpc import client as rpc_client
from pyfect.rpc import server as rpc_server
from pyfect.socket import ws  # needs the websockets extra: pip install "pyfect-dev[websockets]"


class Greeter(RpcGroup):
    greet = make("Greet", payload=S.String, success=S.String)


def greet(request: RpcRequest[str]):
    return fx.succeed(f"Hello, {request.payload}!")


# rpc_server.layer_http serves over WebSockets unless protocol="http" is given.
GreeterLive = (
    rpc_server.layer_http(Greeter, path="/rpc")
    .pipe(layer.provide(Greeter.to_layer(Greeter.handlers().handle(Greeter.greet)(greet))))
    .pipe(layer.provide(serialization.layer_json))
)


def socket_protocol(url: str):
    """The protocol over one WebSocket, opened when the layer is built and closed with it."""
    return (
        rpc_client.layer_protocol_socket()
        .pipe(layer.provide(ws.layer_web_socket(url)))
        .pipe(layer.provide(serialization.layer_json))
    )


@fx.fn
def calls():
    """Every call here goes over the same WebSocket."""
    greeter = yield from rpc_client.make(Greeter)
    print((yield from greeter.greet("Ada")))
    print((yield from greeter.greet("Grace")))


@fx.fn
def program():
    url = yield from server.address_formatted_with(
        lambda origin: fx.succeed(origin.replace("http://", "ws://") + "/rpc")
    )
    # Provided around the code that uses the client: the socket stays open until it ends.
    yield from fx.scoped(calls()).pipe(fx.provide(socket_protocol(url)))


served = router.serve(GreeterLive, disable_logger=True, disable_listen_log=True)
fx.run_main(
    fx.scoped(program())
    .pipe(fx.provide(served))
    .pipe(fx.provide(uvicorn_server.layer(host="127.0.0.1")))
)
