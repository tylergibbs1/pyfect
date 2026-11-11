import pyfect as fx
import pyfect.socket as so
from pyfect import stream
from pyfect.http import live_server, router, server_response
from pyfect.http.server import HttpServer, format_address
from pyfect.http.server_request import HttpServerRequest
from pyfect.socket import ws


@fx.fn
def shout(socket: so.SocketService):
    # Taking the reader opens the socket: until then every write waits.
    reader = yield from socket.reader
    writer = yield from socket.writer
    while True:
        # A pull fails with a SocketError once the socket closes.
        for message in (yield from reader.pull):
            text = message if isinstance(message, str) else message.decode()
            yield from writer.write(text.upper())
            if text == "bye":
                yield from writer.write(so.CloseEvent(1000, "done"))


@fx.fn
def handler():
    request = yield from HttpServerRequest()
    socket = yield from request.upgrade
    yield from fx.scoped(shout(socket)).pipe(fx.catch_tag(so.SocketError, lambda _: fx.void))
    return server_response.empty()


@fx.fn
def chat():
    server = yield from HttpServer()
    url = format_address(server.address).replace("http", "ws", 1) + "/shout"
    socket = yield from so.make_web_socket(url)
    writer = yield from socket.writer
    # The client's writes wait for its reader too: the stream below takes it.
    yield from writer.write_all(["hello", "bye"]).fork()
    replies = (
        so.to_stream(socket)
        .map(bytes.decode)
        # A normal close fails the stream with code 1000, as in Effect: end it instead.
        .catch_if(so.is_clean_close, lambda _: stream.empty)
    )
    print((yield from replies.run_collect()))


served = router.serve(
    router.add("GET", "/shout", handler()), disable_logger=True, disable_listen_log=True
)
program = (
    fx.scoped(chat())
    .pipe(fx.provide(ws.layer_web_socket_constructor))
    .pipe(fx.provide(served))
    .pipe(fx.provide(live_server.layer_test()))
)
fx.run_main(program)
