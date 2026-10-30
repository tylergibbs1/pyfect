import pyfect as fx
from pyfect import byte_size, effect
from pyfect.http import body, router, server_response, uvicorn_server
from pyfect.http.client import HttpClient
from pyfect.http.incoming_message import MaxBodySize
from pyfect.http.server_request import HttpServerRequest


@fx.fn
def upload():
    request = yield from HttpServerRequest()
    text = yield from request.text  # a 413 once the body passes MaxBodySize
    return server_response.text(f"{len(text)} bytes")


@fx.fn
def add_routes(routes: router.HttpRouterService):
    # Every whole-body read is capped at 10 MiB; this route lowers it to 1 KiB.
    small = effect.provide_service(MaxBodySize, byte_size.kibibytes(1))
    yield from routes.add("POST", "/upload", upload().pipe(small))


@fx.fn
def requests():
    http = yield from HttpClient()
    for size in [100, 5000]:
        res = yield from http.post("/upload", body=body.text("x" * size))
        print(size, res.status)


served = router.serve(router.use(add_routes), disable_logger=True, disable_listen_log=True)
fx.run_main(requests().pipe(fx.provide(served)).pipe(fx.provide(uvicorn_server.layer_test())))
