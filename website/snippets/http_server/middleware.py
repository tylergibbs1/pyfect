from urllib.parse import urlsplit

import pyfect as fx
from pyfect import layer
from pyfect.http import router, server_response, uvicorn_server
from pyfect.http.client import HttpClient
from pyfect.http.server_request import HttpServerRequest
from pyfect.http.server_response import HttpServerResponse


# Route middleware: a function of the handler it wraps.
@fx.fn
def check_key(handler: fx.Effect[HttpServerResponse, router.Unhandled]):
    request = yield from HttpServerRequest()
    if request.headers.get("x-api-key") != "secret":
        return server_response.text("unauthorized", status=401)
    return (yield from handler)


RequireKey = router.middleware(check_key)


@fx.fn
def public(routes: router.HttpRouterService):
    yield from routes.add("GET", "/health", server_response.text("ok"))


@fx.fn
def admin(routes: router.HttpRouterService):
    yield from routes.add("GET", "/admin/stats", server_response.text("42 users"))


def add_header(handler: fx.Effect[HttpServerResponse, router.Unhandled]):
    return handler.map(lambda res: res.set_header("x-served-by", "pyfect"))


# Global middleware wraps every request, matched or not.
served_by = router.middleware(add_header, global_=True)

App = (
    router.use(admin)
    .pipe(layer.provide(RequireKey.layer))  # only the admin routes
    .pipe(layer.provide_merge(router.use(public)))
    .pipe(layer.provide_merge(served_by))
    .pipe(layer.provide_merge(router.cors(allowed_origins=["https://example.com"])))
)


@fx.fn
def requests():
    http = yield from HttpClient()
    for sent in [
        http.get("/health"),
        http.get("/admin/stats"),
        http.get("/admin/stats", headers={"x-api-key": "secret"}),
    ]:
        res = yield from sent
        path = urlsplit(res.request.url).path
        print(path, res.status, (yield from res.text))
        print("  x-served-by:", res.headers["x-served-by"])
        print("  access-control-allow-origin:", res.headers["access-control-allow-origin"])


served = router.serve(App, disable_logger=True, disable_listen_log=True)
fx.run_main(requests().pipe(fx.provide(served)).pipe(fx.provide(uvicorn_server.layer_test())))
