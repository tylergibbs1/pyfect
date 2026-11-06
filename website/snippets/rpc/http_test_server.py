import pyfect as fx
from pyfect import layer
from pyfect import schema as S
from pyfect.http import httpx_client, router, server, uvicorn_server
from pyfect.rpc import RpcGroup, RpcRequest, make, serialization
from pyfect.rpc import client as rpc_client
from pyfect.rpc import server as rpc_server


class Greeter(RpcGroup):
    greet = make("Greet", payload=S.String, success=S.String)


def greet(request: RpcRequest[str]) -> fx.Effect[str]:
    return fx.succeed(f"hi {request.payload}")


Served = (
    rpc_server.layer_http(Greeter, path="/rpc", protocol="http")
    .pipe(layer.provide(Greeter.to_layer(Greeter.handlers().handle(Greeter.greet)(greet))))
    .pipe(layer.provide(serialization.layer_json))
)


@fx.fn
def call():
    greeter = yield from rpc_client.make(Greeter)
    return (yield from greeter.greet("ada"))


@fx.fn
def program():
    # The address the test server got, and a real client: not the test server's own.
    url = yield from server.address_formatted_with(lambda origin: fx.succeed(f"{origin}/rpc"))
    protocol = rpc_client.layer_protocol_http(url).pipe(
        layer.provide(layer.merge(serialization.layer_json, httpx_client.layer))
    )
    print((yield from fx.scoped(call()).pipe(fx.provide(protocol))))


served = router.serve(Served, disable_logger=True, disable_listen_log=True)
fx.run_main(
    fx.scoped(program()).pipe(fx.provide(served)).pipe(fx.provide(uvicorn_server.layer_test()))
)
