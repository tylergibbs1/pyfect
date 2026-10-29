import pyfect as fx
from pyfect import testing
from pyfect.http import router, server_response, uvicorn_server
from pyfect.http.client import HttpClient


@fx.fn
def add_routes(routes: router.HttpRouterService):
    yield from routes.add("GET", "/hello/:name", greet())


@fx.fn
def greet():
    params = yield from router.params
    return server_response.text(f"hello, {params['name']}")


served = router.serve(router.use(add_routes), disable_logger=True, disable_listen_log=True)


def on_server[A, E](requests: fx.Effect[A, E, HttpClient]):
    """Run `requests` against a real server on a free local port."""
    return requests.pipe(fx.provide(served)).pipe(fx.provide(uvicorn_server.layer_test()))


@fx.fn
def get(path: str):
    res = yield from (yield from HttpClient()).get(path)
    return res.status, (yield from res.text)


@testing.effect
def test_greets_by_name():
    assert (yield from on_server(get("/hello/ada"))) == (200, "hello, ada")


@testing.effect
def test_an_unknown_path_is_a_404():
    status, _ = yield from on_server(get("/goodbye"))
    assert status == 404
