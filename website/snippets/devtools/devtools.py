from typing import Any

import pyfect as fx
from pyfect import devtools, logger
from pyfect.devtools import server as devtools_server
from pyfect.net.net_address import InetAddressV4
from pyfect.queue import Queue
from pyfect.socket import server as socket_server


@fx.fn("checkout")
def checkout(order: int):
    yield from fx.annotate_current_span("order", order)
    yield from fx.log_info("charging")
    yield from fx.void.with_span("charge")


def describe(request: devtools_server.RequestWithoutPing) -> str:
    match request["_tag"]:
        case "Span":
            return f"Span {request['name']}: {request['status']['_tag']}"
        case "SpanEvent":
            return f"SpanEvent {request['name']}"
        case "MetricsSnapshot":
            return "MetricsSnapshot"


@fx.fn
def program():
    # The DevTools side: a WebSocket SocketServer, the protocol the default client speaks.
    srv = yield from socket_server.SocketServer()
    assert isinstance(srv.address, InetAddressV4)
    seen = yield from Queue[str, Any].unbounded()

    def handle(client: devtools_server.Client) -> fx.Effect[Any]:
        return client.queue.take().flat_map(lambda r: seen.offer(describe(r))).forever()

    yield from devtools_server.run(handle).fork_scoped()

    # The app side: with devtools.layer(url), every span is reported to the DevTools.
    @fx.fn
    def app():
        yield from checkout(7)
        while (line := (yield from seen.take().timeout("5 seconds"))) != "Span checkout: Ended":
            if line != "MetricsSnapshot":
                print(line)
        print(line)

    url = f"ws://127.0.0.1:{srv.address.port}"
    yield from app().pipe(fx.provide(devtools.layer(url)))


server = socket_server.layer_web_socket(port=0, host="127.0.0.1")
# Logs go only to their span's events here, so the DevTools gets them and the console does not.
quiet = logger.layer([logger.tracer_logger])
fx.run_main(fx.scoped(program()).pipe(fx.provide(server)).pipe(fx.provide(quiet)))
