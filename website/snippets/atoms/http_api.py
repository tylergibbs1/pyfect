from typing import TypedDict

import pyfect as fx
from pyfect import layer
from pyfect import schema as S
from pyfect.http import router, uvicorn_server
from pyfect.http.client import HttpClient
from pyfect.http_api import HttpApi, HttpApiGroup, builder, client, endpoint
from pyfect.reactivity import atom, atom_http_api, atom_registry


class Name(TypedDict):
    name: str


class Greetings(HttpApiGroup, identifier="greetings"):
    hello = endpoint.get("hello", "/hello/:name", params=S.Struct(Name), success=S.String)


api = HttpApi.make("example").add(Greetings)
ApiLive = builder.layer(api).pipe(
    layer.provide(
        builder.group(
            api,
            Greetings,
            lambda handlers: handlers.handle(Greetings.hello)(
                lambda request: fx.succeed(f"hello, {request.params['name']}")
            ),
        )
    )
)


class ExampleClient(fx.Tag[client.Client[Greetings]]): ...


@fx.gen
def program():
    http = yield from HttpClient()
    # The atoms' client sends its requests with this HttpClient.
    api_atoms = atom_http_api.make(
        ExampleClient, api=api, http_client=layer.succeed(HttpClient, http)
    )
    hello = api_atoms.query(Greetings, Greetings.hello, params={"name": "Ada"})
    print((yield from atom.get_result(hello)))


served = router.serve(ApiLive, disable_logger=True, disable_listen_log=True)
fx.run_main(
    program.pipe(fx.provide(atom_registry.layer))
    .pipe(fx.provide(served))
    .pipe(fx.provide(uvicorn_server.layer_test()))
)
