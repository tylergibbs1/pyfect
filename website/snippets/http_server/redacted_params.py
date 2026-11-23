import pyfect as fx
from pyfect import logger
from pyfect.http import router, server_response, uvicorn_server
from pyfect.http.client import HttpClient
from pyfect.http.server_request import ServerRequest
from pyfect.logger import CurrentLogAnnotations, Logger


def echo(request: ServerRequest) -> fx.Effect[server_response.HttpServerResponse]:
    return fx.succeed(server_response.text(request.url))


# The token is a secret: the request log and the server span record it as REDACTED.
Hook = router.add("POST", "/hooks/:id/:token", echo, redacted_params=["token"])

print_path = Logger.make(
    lambda options: print("logged:", options.fiber.get_ref(CurrentLogAnnotations)["http.url"])
)


@fx.fn
def requests():
    http = yield from HttpClient()
    res = yield from http.post("/hooks/7/s3cret")
    print("handler saw:", (yield from res.text))


served = router.serve(Hook, disable_listen_log=True)
fx.run_main(
    requests()
    .pipe(fx.provide(served))
    .pipe(fx.provide(uvicorn_server.layer_test()))
    .pipe(fx.provide(logger.layer([print_path])))
)
