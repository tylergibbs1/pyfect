"""``pyfect.http.uvicorn_server``, and ``asgi.to_asgi`` apps run by uvicorn
itself. Clients connect to localhost only."""

from __future__ import annotations

import asyncio
import socket
import threading
import time
from typing import Any

import httpx
import uvicorn

import pyfect as fx
from pyfect import effect, layer
from pyfect.clock import sleep
from pyfect.context import Tag
from pyfect.http import asgi, router, server, server_response, uvicorn_server
from pyfect.http.asgi import Receive, Scope, Send
from pyfect.http.client import HttpClient
from pyfect.http.server_request import HttpServerRequest
from pyfect.net.net_address import InetAddressV4
from pyfect.scope import acquire_release, scoped

port: fx.Effect[int, Any, server.HttpServer] = server.HttpServer().map(
    lambda srv: srv.address.port if isinstance(srv.address, InetAddressV4) else 0
)


def _run(program: fx.Effect[Any, Any, Any], **options: Any) -> Any:
    provided = scoped(program).pipe(fx.provide(uvicorn_server.layer_test(**options)))
    return fx.run_sync(provided.or_die())


def _serving(
    routes: fx.Layer[Any, Any, Any], program: fx.Effect[Any, Any, Any]
) -> fx.Effect[Any, Any, Any]:
    return program.pipe(fx.provide(router.serve(routes, disable_logger=True)))


def _get(path: str) -> fx.Effect[tuple[int, str], Any, HttpClient]:
    @fx.fn
    def body():
        client = yield from HttpClient()
        response = yield from client.get(path)
        return response.status, (yield from response.text)

    return body()


def test_requests_before_an_app_is_served_get_a_503() -> None:
    assert _run(_get("/"))[0] == 503


def test_the_address_is_the_bound_socket() -> None:
    @fx.fn
    def program():
        srv = yield from server.HttpServer()
        return server.format_address(srv.address), (yield from port)

    address, at = _run(program())
    assert address == f"http://127.0.0.1:{at}"


def test_the_server_stops_listening_when_its_scope_closes() -> None:
    at = _run(_serving(router.add("GET", "/", server_response.text("ok")), port))
    try:
        socket.create_connection(("127.0.0.1", at), timeout=1).close()
    except OSError:
        return
    raise AssertionError("the server still accepts connections")


def test_a_port_in_use_fails_with_a_socket_server_error() -> None:
    with socket.create_server(("127.0.0.1", 0)) as taken:
        at = taken.getsockname()[1]
        made = scoped(uvicorn_server.make(host="127.0.0.1", port=at)).exit()
        exit = fx.run_sync(made)
    assert isinstance(exit, fx.Failure)
    assert "SocketServerError" in type(exit.cause.squash()).__name__


def test_serves_on_the_programs_loop_under_run_async() -> None:
    loops: list[object] = []

    def handler() -> fx.Effect[Any, Any, Any]:
        return effect.sync(lambda: loops.append(asyncio.get_running_loop())).as_(
            server_response.text("ok")
        )

    routes = router.add("GET", "/", handler())
    provided = scoped(_serving(routes, _get("/"))).pipe(fx.provide(uvicorn_server.layer_test()))

    async def main() -> tuple[tuple[int, str], object]:
        result = await fx.run_async(provided.or_die())
        return result, asyncio.get_running_loop()

    result, loop = asyncio.run(main())
    assert result == (200, "ok")
    assert loops == [loop]


def test_graceful_shutdown_cancels_requests_still_running_after_the_timeout() -> None:
    interrupted: list[bool] = []

    @fx.fn
    def program():
        at = yield from port

        def request() -> None:
            # The request never ends; it holds the connection open.
            with socket.create_connection(("127.0.0.1", at), timeout=5) as conn:
                conn.sendall(b"GET /slow HTTP/1.1\r\nhost: x\r\n\r\n")
                time.sleep(0.3)

        yield from effect.blocking(request).fork_daemon()
        yield from sleep(0.1)

    slow = effect.never.on_interrupt(effect.sync(lambda: interrupted.append(True)))
    routes = router.add("GET", "/slow", slow.as_(server_response.empty()))
    started = time.monotonic()
    _run(_serving(routes, program()), graceful_shutdown_timeout=0.2)
    assert time.monotonic() - started < 5
    assert interrupted == [True]


# --- to_asgi under uvicorn ---------------------------------------------------------------


class Counter(Tag[list[str]], key="test/uvicorn/Counter"):
    pass


def _uvicorn(app: Any) -> tuple[uvicorn.Server, threading.Thread, int]:
    sock = socket.create_server(("127.0.0.1", 0))
    at = sock.getsockname()[1]
    server_ = uvicorn.Server(uvicorn.Config(app, log_config=None, lifespan="on"))
    thread = threading.Thread(target=lambda: server_.run(sockets=[sock]), daemon=True)
    thread.start()
    deadline = time.monotonic() + 5
    while not server_.started and time.monotonic() < deadline:
        time.sleep(0.01)
    return server_, thread, at


def test_shutdown_does_not_wait_for_a_response_the_client_left_unread() -> None:
    big = server_response.text("x" * 2_000_000)
    routes = router.add("GET", "/", big)

    @fx.fn
    def program():
        client = yield from HttpClient()
        response = yield from client.get("/")
        return response.status

    started = time.monotonic()
    assert _run(_serving(routes, program()), graceful_shutdown_timeout=10) == 200
    assert time.monotonic() - started < 5


def test_uvicorn_runs_a_to_asgi_app_and_its_lifespan() -> None:
    events: list[str] = []
    services = layer.effect(
        Counter,
        acquire_release(
            effect.sync(lambda: events.append("acquired")).as_(events),
            lambda _events, _exit: effect.sync(lambda: events.append("released")),
        ),
    )

    def handle(_request: Any) -> fx.Effect[Any, Any, Counter]:
        return Counter().map(lambda seen: server_response.text(",".join(seen)))

    app = asgi.to_asgi(HttpServerRequest().flat_map(handle), services)
    server_, thread, at = _uvicorn(app)
    try:
        response = httpx.get(f"http://127.0.0.1:{at}/", timeout=5)
    finally:
        server_.should_exit = True
        thread.join(5)
    assert response.text == "acquired"
    assert events == ["acquired", "released"]


async def _hello(scope: Scope, receive: Receive, send: Send) -> None:
    await receive()
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": scope["root_path"].encode()})


def test_a_pyfect_app_mounts_an_asgi_application_served_by_uvicorn_server() -> None:
    routes = router.add_all(
        [router.route("*", "*", asgi.from_asgi(_hello)).pipe(router.prefix_route("/legacy"))]
    )
    assert _run(_serving(routes, _get("/legacy/anything"))) == (200, "/legacy")


def test_closing_the_serving_scope_stops_the_server() -> None:
    def accepts(at: int) -> bool:
        try:
            socket.create_connection(("127.0.0.1", at), timeout=1).close()
        except OSError:
            return False
        return True

    @fx.fn
    def program():
        at = yield from port
        routes = router.add("GET", "/", server_response.text("ok"))
        served = yield from scoped(_serving(routes, _get("/")))
        # The server layer is still in scope; serving is over (Effect's
        # preemptive shutdown).
        return served, (yield from effect.blocking(lambda: accepts(at)))

    assert _run(program()) == ((200, "ok"), False)
