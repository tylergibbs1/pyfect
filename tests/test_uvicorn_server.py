"""``pyfect.http.uvicorn_server``, and ``asgi.to_asgi`` apps run by uvicorn
itself. Clients connect to localhost only."""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Never

import httpx
import pytest
import uvicorn

import pyfect as fx
from pyfect import effect, layer, stream, testing
from pyfect.clock import sleep
from pyfect.context import Tag
from pyfect.fiber_set import FiberSet
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
    return fx.run_blocking(provided.or_die())


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
        exit = fx.run_blocking(made)
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


def test_leaves_the_programs_signal_handlers_alone_on_the_main_thread() -> None:
    """uvicorn on the main thread's loop would take SIGINT / SIGTERM and shut
    itself down, cancelling streamed responses at its timeout before the
    program (``run_main``) is interrupted and closes the server's scope
    (dogfood beacon #12)."""
    handlers: list[object] = []

    def record() -> None:
        handlers.extend(signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM))

    routes = router.add("GET", "/", effect.sync(record).as_(server_response.text("ok")))
    provided = scoped(_serving(routes, _get("/"))).pipe(fx.provide(uvicorn_server.layer_test()))

    async def main() -> tuple[tuple[int, str], list[object]]:
        before: list[object] = [signal.getsignal(s) for s in (signal.SIGINT, signal.SIGTERM)]
        return await fx.run_async(provided.or_die()), before

    result, before = asyncio.run(main())
    assert result == (200, "ok")
    assert handlers == before


_SSE_UNTIL_CTRL_C = """
import socket, threading
import pyfect as fx
from pyfect import layer, stream
from pyfect.http import router, server, server_response, uvicorn_server

received = bytearray()

def read(at):
    with socket.create_connection(("127.0.0.1", at), timeout=10) as conn:
        conn.sendall(b"GET /events HTTP/1.1\\r\\nhost: x\\r\\n\\r\\n")
        received.extend(conn.recv(65536))
        print("ready", flush=True)
        while chunk := conn.recv(65536):
            received.extend(chunk)
    print(received.endswith(b"0\\r\\n\\r\\n"), flush=True)

def start(srv):
    # Not a daemon: the process exits once it has read the end.
    threading.Thread(target=read, args=(srv.address.port,)).start()

body = stream.make(b"data: 1\\n\\n").concat(stream.never)
routes = router.add("GET", "/events", server_response.stream(body))
serving = router.serve(routes, disable_logger=True).pipe(
    layer.provide_merge(
        uvicorn_server.layer(host="127.0.0.1", graceful_shutdown_timeout="300 millis")
    )
)
main = server.HttpServer().map(start).and_then(fx.never)
fx.run_main(main.pipe(fx.provide(serving)))
"""


def test_ctrl_c_under_run_main_ends_an_open_stream_quietly(tmp_path: Path) -> None:
    """Ctrl-C with an SSE response open: the program's shutdown, not
    uvicorn's, ends it after ``graceful_shutdown_timeout``; the client gets
    the last chunk and nothing is printed (dogfood beacon #12)."""
    script = tmp_path / "main.py"
    script.write_text(_SSE_UNTIL_CTRL_C)
    proc = subprocess.Popen(
        [sys.executable, str(script)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True
    )
    try:
        assert proc.stdout is not None
        while (line := proc.stdout.readline()) and line != "ready\n":
            assert "Listening on" in line
        started = time.monotonic()
        os.kill(proc.pid, signal.SIGINT)
        stdout, stderr = proc.communicate(timeout=20)
    finally:
        proc.kill()
    elapsed = time.monotonic() - started
    assert (stdout, stderr) == ("True\n", "")
    assert elapsed < 3
    assert proc.returncode == 130


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
        yield from sleep("100 millis")

    slow = effect.never.on_interrupt(effect.sync(lambda: interrupted.append(True)))
    routes = router.add("GET", "/slow", slow.as_(server_response.empty()))
    started = time.monotonic()
    _run(_serving(routes, program()), graceful_shutdown_timeout="200 millis")
    assert time.monotonic() - started < 5
    assert interrupted == [True]


def test_disable_preemptive_shutdown_interrupts_requests_at_once() -> None:
    """Effect's ``disablePreemptiveShutdown``: closing the serving scope gives
    requests in flight no time, whatever the timeout says."""
    interrupted: list[bool] = []

    @fx.fn
    def program():
        at = yield from port

        def request() -> None:
            with socket.create_connection(("127.0.0.1", at), timeout=5) as conn:
                conn.sendall(b"GET /slow HTTP/1.1\r\nhost: x\r\n\r\n")
                # Longer than the server takes to stop, so no client abort ends it.
                time.sleep(4)

        yield from effect.blocking(request).fork_daemon()
        yield from sleep("100 millis")

    slow = effect.never.on_interrupt(effect.sync(lambda: interrupted.append(True)))
    routes = router.add("GET", "/slow", slow.as_(server_response.empty()))
    started = time.monotonic()
    _run(
        _serving(routes, program()),
        graceful_shutdown_timeout="30 seconds",
        disable_preemptive_shutdown=True,
    )
    assert time.monotonic() - started < 3
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


def test_shutdown_ends_a_streamed_response_still_open_after_the_timeout(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An endless body (an SSE stream) open when the server closes ends once
    ``graceful_shutdown_timeout`` has passed, before uvicorn's own timeout
    cancels the request: the client reads the last chunk and nothing is
    logged as an error (dogfood beacon #12)."""
    received = bytearray()

    @fx.fn
    def program():
        at = yield from port

        def request() -> None:
            with socket.create_connection(("127.0.0.1", at), timeout=5) as conn:
                conn.sendall(b"GET /events HTTP/1.1\r\nhost: x\r\n\r\n")
                while chunk := conn.recv(65536):
                    received.extend(chunk)

        yield from effect.blocking(request).fork_daemon()
        yield from sleep("200 millis")

    body = stream.make(b"data: 1\n\n").concat(stream.never)
    routes = router.add(
        "GET", "/events", server_response.stream(body, content_type="text/event-stream")
    )
    started = time.monotonic()
    with caplog.at_level(logging.WARNING):
        _run(_serving(routes, program()), graceful_shutdown_timeout="300 millis")
        deadline = time.monotonic() + 2
        while not received.endswith(b"0\r\n\r\n") and time.monotonic() < deadline:
            time.sleep(0.01)
    assert time.monotonic() - started < 2
    assert received.endswith(b"data: 1\n\n\r\n0\r\n\r\n")
    assert [r.getMessage() for r in caplog.records if r.name.startswith("uvicorn")] == []


def test_shutdown_does_not_wait_for_a_response_the_client_left_unread() -> None:
    big = server_response.text("x" * 2_000_000)
    routes = router.add("GET", "/", big)

    @fx.fn
    def program():
        client = yield from HttpClient()
        response = yield from client.get("/")
        return response.status

    started = time.monotonic()
    assert _run(_serving(routes, program()), graceful_shutdown_timeout="10 seconds") == 200
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


def test_under_run_blocking_inside_a_running_loop_the_server_runs_on_a_loop_of_its_own() -> None:
    # run_blocking blocks the coroutine's loop, so uvicorn must not be put on it.
    routes = router.add("GET", "/", server_response.text("ok"))

    async def main() -> tuple[int, str]:
        return _run(_serving(routes, _get("/")))

    assert asyncio.run(main()) == (200, "ok")


@testing.live(timeout="10 seconds")
def test_a_fiber_a_request_forks_into_a_longer_lived_set_can_still_be_interrupted():
    """A handler can fork a fiber that outlives its request (beacon's watcher
    keeps one per monitor in a FiberMap). It runs on the server's loop; the set
    holding it is closed after the server, so interrupting it then must still
    finish (DOGFOOD pulse #5: the loop thread had stopped, the set's close
    waited for ever, and the test stalled)."""
    background = yield from FiberSet[Never, Never].make()
    started = yield from fx.Deferred[None, Never].make()

    def handler() -> fx.Effect[Any, Any, Any]:
        forked = background.run(started.succeed(None).and_then(fx.never))
        return forked.as_(server_response.text("forked"))

    routes = router.add("GET", "/", handler())
    answer = yield from scoped(_serving(routes, _get("/"))).pipe(
        fx.provide(uvicorn_server.layer_test())
    )
    yield from started.wait()
    assert answer == (200, "forked")
    yield from background.clear()
    assert (yield from background.size()) == 0
