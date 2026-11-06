"""``pyfect.http.hypercorn_server``: HTTP/2, which Effect's ``NodeHttpServer``
serves when given ``node:http2``'s ``createServer``."""

from typing import Any

import httpx

import pyfect as fx
from pyfect import effect
from pyfect.http import hypercorn_server, router, server, server_response
from pyfect.net.net_address import InetAddressV4
from pyfect.scope import scoped


def _speak_http2(port: int) -> tuple[str, str]:
    with httpx.Client(http1=False, http2=True) as client:
        response = client.get(f"http://127.0.0.1:{port}/hello")
        return response.http_version, response.text


def test_serves_http_2_in_cleartext() -> None:
    @fx.fn
    def program():
        running = yield from server.HttpServer()
        assert isinstance(running.address, InetAddressV4)
        at = running.address.port
        return (yield from effect.blocking(lambda: _speak_http2(at)))

    routes: fx.Layer[Any, Any, Any] = router.add("GET", "/hello", server_response.text("hi"))
    served = program().pipe(fx.provide(router.serve(routes, disable_logger=True)))
    provided = scoped(served).pipe(fx.provide(hypercorn_server.layer_test()))
    assert fx.run_blocking(provided.or_die()) == ("HTTP/2", "hi")


def test_the_server_stops_when_its_scope_closes() -> None:
    @fx.fn
    def program():
        running = yield from server.HttpServer()
        assert isinstance(running.address, InetAddressV4)
        return running.address.port

    at = fx.run_blocking(scoped(program()).pipe(fx.provide(hypercorn_server.layer_test())).or_die())
    with httpx.Client() as client:
        try:
            client.get(f"http://127.0.0.1:{at}/", timeout=1)
        except httpx.TransportError:
            return
    raise AssertionError("the server still accepts connections")
