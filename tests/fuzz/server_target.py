"""The live server end to end: a connection's bytes sent over loopback to an
app that reads everything a handler can (origin check, Web request, cookies,
URL, JSON, form and multipart bodies, compressed bodies). Typed failures are
answered 400, so a 500 means a defect; every answer must be a well-formed
HTTP/1.1 response, and the server must close the connection once the client
stops sending."""

from __future__ import annotations

import errno
import functools
import queue
import re
import socket
import struct
import threading
import time
from typing import Any

import pyfect as fx
from pyfect import effect
from pyfect.http import live_server, multipart, origin, router, server_response
from pyfect.http.middleware import decompression
from pyfect.http.server import HttpServer
from pyfect.http.server_request import HttpServerRequest, ServerRequest, to_url_result
from pyfect.http.web_handler import request_to_web
from pyfect.net.net_address import InetAddressV4
from pyfect.scope import scoped

from ._harness import Crash, target

_TIMEOUT = 4.0


def _consume(part: Any) -> fx.Effect[Any, Any]:
    return part.content.run_drain() if isinstance(part, multipart.File) else effect.void


def _handle(request: ServerRequest) -> fx.Effect[Any, Any]:
    def body() -> Any:
        yield from origin.origin_allowed(request)
        request_to_web(request)
        to_url_result(request)
        dict(request.cookies)
        kind = request.headers.get("content-type", "")
        if "multipart" in kind:
            yield from request.multipart_stream.map_effect(_consume).run_drain()
        elif "json" in kind:
            yield from request.json
        elif "urlencoded" in kind:
            yield from request.url_params_body
        else:
            yield from request.bytes_
        return server_response.text("ok")

    return effect.gen(body).catch_all(
        lambda _error: effect.succeed(server_response.text("bad", status=400))
    )


@functools.cache
def _port() -> int:
    """A live server, started once and left running in a daemon thread."""
    ports: queue.Queue[int] = queue.Queue()

    def serve() -> Any:
        server = yield from HttpServer()
        address = server.address
        assert isinstance(address, InetAddressV4)
        ports.put(address.port)
        yield from effect.never

    app = router.add("*", "*", HttpServerRequest().flat_map(_handle))
    served = effect.gen(serve).pipe(
        fx.provide(
            router.serve(
                app,
                middleware=decompression(max_decompressed_size=65536),
                disable_logger=True,
                disable_listen_log=True,
            )
        )
    )
    program = scoped(served).pipe(
        fx.provide(live_server.layer(host="127.0.0.1", keep_alive_timeout="1 second"))
    )
    threading.Thread(target=lambda: fx.run_blocking(program.or_die()), daemon=True).start()
    return ports.get(timeout=30)


def _connect() -> socket.socket:
    """A loopback connection that closes with a reset, so thousands a second
    leave no client port in ``TIME_WAIT``; out of ports, it waits for one."""
    for _ in range(100):
        try:
            conn = socket.create_connection(("127.0.0.1", _port()), timeout=_TIMEOUT)
        except OSError as error:
            if error.errno != errno.EADDRNOTAVAIL:
                raise
            time.sleep(0.05)
            continue
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))
        return conn
    raise Crash("no loopback port came free")


def _exchange(data: bytes) -> bytes:
    received = bytearray()
    with _connect() as conn:
        try:
            conn.sendall(data)
            conn.shutdown(socket.SHUT_WR)
        except OSError:
            pass
        deadline = time.monotonic() + _TIMEOUT
        while True:
            if time.monotonic() > deadline:
                raise Crash(
                    "the server kept the connection open after the client stopped"
                ) from None
            try:
                chunk = conn.recv(65536)
            except ConnectionResetError:
                break
            except TimeoutError:
                raise Crash(
                    "the server kept the connection open after the client stopped"
                ) from None
            if not chunk:
                break
            received += chunk
    return bytes(received)


_STATUS_LINE = re.compile(rb"HTTP/1\.1 ([1-5]\d\d) [^\r\n]*\r\n")


def _statuses(data: bytes) -> list[int]:
    """The status of each response in ``data``: the app's bodies are ``ok``
    and ``bad``, so status lines are found by their shape (a ``HEAD``
    response has a ``Content-Length`` but no body)."""
    if data and not _STATUS_LINE.match(data):
        raise Crash(f"the answer does not start with a status line: {data[:80]!r}")
    return [int(status) for status in _STATUS_LINE.findall(data)]


@target("http_server")
def http_server(data: bytes) -> None:
    statuses = _statuses(_exchange(data))
    if 500 in statuses:
        raise Crash("the server answered 500: a handler or the server died")
