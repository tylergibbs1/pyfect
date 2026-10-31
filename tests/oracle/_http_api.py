"""Helpers for the HTTP API oracle tests."""

from collections.abc import Callable, Iterable, Mapping
from typing import Any, NotRequired, TypedDict, cast

import pyfect as fx
from pyfect import effect, layer
from pyfect import schema as S
from pyfect._core import Effect
from pyfect.exit import Exit
from pyfect.http import live_server, router, server
from pyfect.http.server_request import HttpServerRequest
from pyfect.http.web import WebRequest
from pyfect.http.web_handler import request_from_web
from pyfect.http_api import builder, get_group
from pyfect.http_api import test as api_test
from pyfect.http_api.api import HttpApi
from pyfect.layer import Layer
from pyfect.scope import scoped

_typed_dict = cast("Any", TypedDict)


def struct(
    fields: Mapping[str, S.Codec[Any, Any, Any, Any]], *, optional: Iterable[str] = ()
) -> S.StructSchema[Any, Any, Any]:
    """A struct of ``fields`` (Effect's ``Schema.Struct({...})``), the keys
    in ``optional`` may be missing."""
    missing = set(optional)
    keys = {name: NotRequired[object] if name in missing else object for name in fields}
    return S.Struct(_typed_dict("Fields", keys), **fields)


type _AnyLayer = Layer[Any, Any, Any]
type _AnyEffect = Effect[Any, Any, Any]


def serve_layer(app: _AnyLayer) -> _AnyLayer:
    """``app`` (a router layer) served by a live test server, with an
    ``HttpClient`` sending to it (Effect's ``NodeHttpServer.layerTest``)."""
    served: _AnyLayer = router.serve(app, disable_logger=True, disable_listen_log=True)
    return served.pipe(layer.provide_merge(live_server.layer_test()))


def run_served(app: _AnyLayer, program: _AnyEffect, *around: _AnyLayer) -> object:
    """Run ``program`` against ``app`` served by ``serve_layer``, the
    server and the program both given the layers ``around``."""
    served: _AnyEffect = scoped(program).pipe(fx.provide(serve_layer(app)))
    for provided in around:
        served = served.pipe(fx.provide(provided))
    return fx.run_sync(served.or_die())


def api_layer(api: HttpApi[Any], *layers: _AnyLayer) -> _AnyLayer:
    """``HttpApiBuilder.layer(api)`` with ``layers`` provided in order."""
    out: _AnyLayer = builder.layer(api)
    for provided in layers:
        out = out.pipe(layer.provide(provided))
    return out


def call_group(
    api: HttpApi[Any],
    group: Any,
    build: Callable[[Any], Any],
    use: Callable[[Any], _AnyEffect],
    *around: _AnyLayer,
) -> Any:
    """Run ``use`` on ``group``'s client from ``HttpApiTest.groups``, the
    group's handlers made by ``build`` and the layers ``around`` provided."""
    live = builder.group(api, group, build)

    def program() -> Any:
        api_client = yield from api_test.groups(api, [group])
        return (yield from use(get_group(api_client, group)))

    out: _AnyEffect = scoped(effect.gen(program)).pipe(fx.provide(live))
    for provided in around:
        out = out.pipe(fx.provide(provided))
    return fx.run_sync(out.pipe(fx.provide(server.layer_services)))


def respond(api: HttpApi[Any], live: _AnyLayer, request: WebRequest) -> Exit[Any, Any]:
    """The exit of ``api``'s HTTP effect (``HttpRouter.toHttpEffect``) for
    ``request``, its groups' handlers ``live``."""

    def program() -> Any:
        handler = yield from router.to_http_effect(
            api_layer(api, live).pipe(layer.provide(server.layer_services))
        )
        return (
            yield from handler.pipe(
                fx.provide_service(HttpServerRequest, request_from_web(request))
            ).exit()
        )

    return fx.run_sync(scoped(effect.gen(program)))
