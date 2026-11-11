import pyfect as fx
from pyfect import logger
from pyfect.http import asgi, hypercorn_server, router, server_response
from pyfect.http.asgi import Receive, Scope, Send
from pyfect.http.client import HttpClient
from pyfect.logger import CurrentLogAnnotations


async def legacy(scope: Scope, receive: Receive, send: Send) -> None:
    """The routes not migrated yet: any ASGI app, such as the FastAPI one."""
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": f"legacy {scope['path']}".encode()})


async def admin(scope: Scope, receive: Receive, send: Send) -> None:
    """An app mounted under a prefix, such as a FastAPI admin app."""
    body = f"admin root_path={scope['root_path']} path={scope['path']}"
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": body.encode()})


@fx.fn
def get_user():
    params = yield from router.params
    return (yield from server_response.json({"id": params["id"]}))


@fx.fn
def add_routes(routes: router.HttpRouterService):
    yield from routes.add("GET", "/users/:id", get_user())
    # Under a prefix the mounted app gets it as its root_path, so its own routes still match.
    mounted = router.route("*", "*", asgi.from_asgi(admin)).pipe(router.prefix_route("/admin"))
    yield from routes.add_all([mounted])
    # Every other path goes to the legacy app.
    yield from routes.add("*", "/*", asgi.from_asgi(legacy))


def request_log(entry: logger.Options) -> None:
    notes = entry.fiber.get_ref(CurrentLogAnnotations)
    print(*entry.message, notes["http.method"], notes["http.url"], notes["http.status"])


@fx.fn
def requests():
    http = yield from HttpClient()
    for path in ("/users/7", "/admin/health", "/healthz"):
        response = yield from http.get(path)
        print(response.status, (yield from response.text))


# serve logs each request with the loggers of the server's layer (with to_asgi, those of
# the layer it builds); disable_listen_log leaves out the "Listening on" line.
App = router.serve(router.use(add_routes), disable_listen_log=True)
program = requests().pipe(fx.provide(App)).pipe(fx.provide(hypercorn_server.layer_test()))
fx.run_main(program.pipe(fx.provide(logger.layer([logger.Logger.make(request_log)]))))
