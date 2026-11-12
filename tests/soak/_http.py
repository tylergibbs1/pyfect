"""HTTPS and WSS traffic against pyfect's live server, through keep-alive connections:
plain requests, streamed uploads and downloads, WebSocket conversations, and the
error paths around them (client timeouts mid-request, bodies failing mid-stream,
responses dropped half read, conversations cut off)."""

from __future__ import annotations

import random
from typing import Any

import pyfect as fx
from pyfect import layer, stream
from pyfect.http import body as http_body
from pyfect.http import live_server, router, server_response
from pyfect.http.client import HttpClientService
from pyfect.http.error import HttpClientError
from pyfect.http.server import HttpServer
from pyfect.http.server_request import HttpServerRequest, ServerRequest
from pyfect.scope import scoped
from pyfect.socket import CloseEvent, SocketError, make_web_socket
from pyfect.socket import ws as ws_platform

from ._tls import Pem
from ._workload import Workload, check, expect_failure, failed_with

CHUNK = 1024
DOWNLOAD_CHUNKS = 64


class Broken(Exception):
    """A body that fails on purpose."""


def _upload(request: ServerRequest) -> fx.Effect[Any, Any]:
    counted = request.stream.run_fold(lambda: 0, lambda total, chunk: total + len(chunk))
    return counted.map(lambda total: server_response.text(str(total)))


def _chunks(count: int) -> fx.Stream[bytes]:
    return stream.range(1, count).map(lambda _: b"d" * CHUNK)


def _download(_: ServerRequest) -> fx.Effect[Any]:
    return fx.succeed(server_response.stream(_chunks(DOWNLOAD_CHUNKS)))


def _download_failing(_: ServerRequest) -> fx.Effect[Any]:
    failing = _chunks(8).concat(stream.fail(Broken("server body")))
    return fx.succeed(server_response.stream(failing))


@fx.fn
def _echo():
    request = yield from HttpServerRequest()
    sock = yield from request.upgrade

    @fx.fn
    def run():
        reader = yield from sock.reader
        writer = yield from sock.writer
        while True:
            chunks = yield from reader.pull
            yield from writer.write_all(chunks)

    yield from scoped(run()).ignore()
    return server_response.empty()


routes = layer.merge(
    router.add("GET", "/hello", server_response.text("ok")),
    router.add("GET", "/slow", fx.sleep("2 seconds").as_(server_response.text("slow"))),
    router.add("POST", "/upload", _upload),
    router.add("GET", "/download", _download),
    router.add("GET", "/download-failing", _download_failing),
    router.add("GET", "/ws", scoped(_echo())),
)
app = router.serve(routes, disable_logger=True, disable_listen_log=True)


def server_layer(pem: Pem) -> fx.Layer[Any, Any]:
    made = live_server.make_tls(
        host="127.0.0.1", cert=pem.cert, key=pem.key, graceful_shutdown_timeout="5 seconds"
    )
    return layer.merge(layer.effect(HttpServer, made), live_server.layer_services)


def workloads(client: HttpClientService[HttpClientError], base: str) -> list[Workload]:
    ok = client.filter_status_ok()

    @fx.fn
    def get(rng: random.Random):
        if rng.random() < 0.1:
            # Give up on a slow response: the request is aborted mid-flight.
            slow = ok.get(f"{base}/slow").timeout("50 millis").exit()
            ex = yield from slow
            yield from check(
                failed_with(ex, fx.TimeoutException),
                f"expected a timeout, got {ex!r}",
            )
            return
        response = yield from ok.get(f"{base}/hello")
        text = yield from response.text
        yield from check(text == "ok", f"GET /hello answered {text!r}")

    @fx.fn
    def upload(rng: random.Random):
        count = rng.randint(1, 64)
        body = stream.range(1, count).map(lambda _: b"u" * CHUNK)
        if rng.random() < 0.1:
            broken = body.take(count // 2).concat(stream.fail(Broken("client body")))
            yield from expect_failure(
                ok.post(f"{base}/upload", body=http_body.stream(broken)), HttpClientError
            )
            return
        response = yield from ok.post(f"{base}/upload", body=http_body.stream(body))
        text = yield from response.text
        yield from check(text == str(count * CHUNK), f"uploaded {count * CHUNK}, server saw {text}")

    @fx.fn
    def download(rng: random.Random):
        roll = rng.random()
        if roll < 0.1:
            failing = ok.get(f"{base}/download-failing").flat_map(lambda r: r.stream.run_drain())
            yield from expect_failure(failing, HttpClientError)
            return
        response = yield from ok.get(f"{base}/download")
        if roll < 0.3:
            # Read two chunks and drop the rest of the body.
            yield from response.stream.take(2).run_drain()
            return
        total = yield from response.stream.run_fold(lambda: 0, lambda n, c: n + len(c))
        expected = DOWNLOAD_CHUNKS * CHUNK
        yield from check(total == expected, f"downloaded {total} of {expected} bytes")

    return [
        Workload("http_get", get, loops=4, pace=0.08),
        Workload("http_upload", upload, loops=2, pace=0.2),
        Workload("http_download", download, loops=2, pace=0.2),
    ]


def websocket_workload(base: str) -> Workload:
    url = base.replace("https://", "wss://") + "/ws"

    @fx.fn
    def converse(rng: random.Random):
        messages = [f"m{i}-{rng.random()}" for i in range(rng.randint(1, 8))]
        sock = yield from make_web_socket(url, open_timeout="10 seconds")

        @fx.fn
        def talk():
            writer = yield from sock.writer
            reader = yield from sock.reader
            got: list[str | bytes] = []
            for message in messages:
                yield from writer.write(message)
                while len(got) < messages.index(message) + 1:
                    got.extend((yield from reader.pull))
            yield from writer.write(CloseEvent(1000, "bye"))
            return got

        if rng.random() < 0.1:
            # Cut the conversation off part way: the socket's scope closes under it.
            cut = scoped(talk()).timeout(f"{rng.randint(0, 5)} millis").exit()
            ex = yield from cut
            if isinstance(ex, fx.Failure):
                yield from check(
                    failed_with(ex, fx.TimeoutException | SocketError),
                    f"a cut conversation failed with {ex!r}",
                )
            return
        got = yield from scoped(talk())
        yield from check(list(got) == messages, f"echoed {got!r}, sent {messages!r}")

    return Workload(
        "websocket",
        lambda rng: converse(rng).pipe(fx.provide(ws_platform.layer_web_socket_constructor)),
        loops=2,
        pace=0.4,
    )
