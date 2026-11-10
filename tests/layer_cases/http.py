"""Reuse cases for the HTTP, HTTP API, socket, GraphQL, DevTools and net
layers. Servers bind loopback ports; peers a layer value must know before
any run (a socket's port, a WebSocket's URL) are stdlib or ``websockets``
servers on threads, started once per test process."""

# pyright: reportUnknownLambdaType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

import contextlib
import functools
import itertools
import json
import socket
import ssl
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, Never

from oracle._graphql import ViewerGroup, graphql_response, http_client_layer
from oracle._http_api import struct
from websockets.exceptions import ConnectionClosed
from websockets.sync.server import ServerConnection
from websockets.sync.server import serve as sync_serve

import pyfect as fx
from layer_cases._case import AnyEffect, AnyLayer, Case
from pyfect import devtools, file_system, graphql
from pyfect import layer as L
from pyfect import schema as S
from pyfect._tracer_ref import CurrentTracer
from pyfect.context import Tag
from pyfect.devtools import client as devtools_client
from pyfect.graphql import client as graphql_client
from pyfect.graphql.protocol import WebSocketOptions
from pyfect.http import client as http_client
from pyfect.http import (
    etag,
    httpx_client,
    hypercorn_server,
    live_server,
    platform,
    prometheus,
    router,
    server,
    server_response,
    static_server,
    uvicorn_server,
)
from pyfect.http import response as http_response
from pyfect.http.file_like import BytesFile
from pyfect.http.middleware import TracerDisabledWhen, layer_tracer_disabled_for_urls
from pyfect.http.platform import HttpPlatform
from pyfect.http.request import HttpClientRequest
from pyfect.http.web import WebRequest
from pyfect.http.web_handler import request_from_web
from pyfect.http_api import HttpApi, HttpApiGroup, builder, endpoint, get_group, scalar, swagger
from pyfect.http_api.client import make as api_client_make
from pyfect.http_api.middleware import (
    ClientMiddlewareOptions,
    HttpApiMiddleware,
    ProblemDetails,
    layer_client,
    layer_client_effect,
    layer_problem_details,
    layer_schema_error_transform,
)
from pyfect.net import address_resolver, dns
from pyfect.net.address_resolver import AddressResolver
from pyfect.net.dns import Dns
from pyfect.net.host import host_port_from_string_unsafe
from pyfect.net.net_address import InetAddressV4, InetAddressV6, format_ip, format_socket_address
from pyfect.redacted import Redacted
from pyfect.socket import (
    Socket,
    SocketService,
    TlsUpgradeOptions,
    make_net,
    make_tls,
    make_web_socket,
    ws,
)
from pyfect.socket import layer_net as socket_layer_net
from pyfect.socket import layer_tls as socket_layer_tls
from pyfect.socket import layer_web_socket as socket_layer_web_socket
from pyfect.socket import server as socket_server
from pyfect.socket.datagram import Bind, DatagramSocket, Options, OutgoingDatagram, layer_udp
from pyfect.socket.server import SocketServer, SocketServerService

# --- helpers ----------------------------------------------------------------


def _expect(made: AnyEffect, expected: object) -> AnyEffect:
    def check(got: object) -> AnyEffect:
        if got == expected:
            return fx.void
        return fx.die(AssertionError(f"expected {expected!r}, got {got!r}"))

    return made.flat_map(check)


def _fetch(path: str) -> AnyEffect:
    """``GET path`` through the ``HttpClient``: its status and text."""
    return http_client.get(path).flat_map(
        lambda response: response.text.map(lambda text: (response.status, text))
    )


def _get(path: str, expected: str) -> AnyEffect:
    return _expect(_fetch(path), (200, expected))


def _routes(path: str = "/", text: str = "ok") -> AnyLayer:
    return router.add("GET", path, server_response.text(text))


def _serve(routes: AnyLayer) -> AnyLayer:
    """``routes`` served by a live test server, with an ``HttpClient``
    sending to it."""
    served: AnyLayer = router.serve(routes, disable_logger=True, disable_listen_log=True)
    return served.pipe(L.provide_merge(live_server.layer_test()))


def _serving(path: str = "/", expected: str = "ok") -> Any:
    """A whole run: the routes layer value served, then ``GET path``."""

    def run(value: AnyLayer) -> AnyEffect:
        return _get(path, expected).pipe(fx.provide(_serve(value)))

    return run


def _serving_any_text(path: str) -> Any:
    """``_serving`` for a body that depends on what else the process did."""

    def run(value: AnyLayer) -> AnyEffect:
        def ok(answer: tuple[int, str]) -> None:
            assert answer[0] == 200, answer

        return _fetch(path).map(ok).pipe(fx.provide(_serve(value)))

    return run


def _ok_app() -> AnyEffect:
    return fx.succeed(server_response.text("ok"))


# --- http: servers and routers -----------------------------------------------


def _router_service() -> AnyEffect:
    @fx.fn
    def body():
        service = yield from router.HttpRouter()
        yield from service.add("GET", "/", server_response.text("ok"))
        yield from server.serve_effect(service.as_http_effect())
        return (yield from _get("/", "ok"))

    return body()


_HTTP: dict[str, Case] = {
    "pyfect.http.router.add": Case(layer=_routes, run=_serving()),
    "pyfect.http.prometheus.layer_http": Case(
        layer=prometheus.layer_http, run=_serving_any_text("/metrics")
    ),
    "pyfect.http.router.layer_in_memory_client": Case(
        layer=lambda: router.layer_in_memory_client(_routes()),
        use=lambda: _get("http://localhost/", "ok"),
    ),
    "pyfect.http.router.add_all": Case(
        layer=lambda: router.add_all(
            [router.route("GET", "/users", server_response.text("users"))], prefix="/api"
        ),
        run=_serving("/api/users", "users"),
    ),
    "pyfect.http.router.use": Case(
        layer=lambda: router.use(lambda service: service.add("GET", "/", _ok_app())),
        run=_serving(),
    ),
    "pyfect.http.router.cors": Case(
        layer=lambda: _routes().pipe(L.provide_merge(router.cors())), run=_serving()
    ),
    "pyfect.http.router.disable_logger": Case(
        layer=lambda: router.disable_logger,
        run=lambda value: _serving()(_routes().pipe(L.provide(value))),
    ),
    "pyfect.http.router.layer": Case(
        layer=lambda: router.layer, needs=live_server.layer_test, use=_router_service
    ),
    "pyfect.http.router.serve": Case(
        layer=lambda: router.serve(_routes(), disable_logger=True, disable_listen_log=True),
        needs=live_server.layer_test,
        use=lambda: _get("/", "ok"),
    ),
    "pyfect.http.server.serve": Case(
        layer=lambda: server.serve(_ok_app()),
        needs=live_server.layer_test,
        use=lambda: _get("/", "ok"),
    ),
    "pyfect.http.server.with_log_address": Case(
        layer=lambda: server.with_log_address(server.serve(_ok_app())),
        needs=live_server.layer_test,
        use=lambda: _get("/", "ok"),
    ),
    "pyfect.http.live_server.layer_test": Case(
        layer=live_server.layer_test,
        run=lambda value: _get("/", "ok").pipe(
            fx.provide(server.serve(_ok_app()).pipe(L.provide_merge(value)))
        ),
    ),
    "pyfect.http.hypercorn_server.layer_test": Case(
        layer=hypercorn_server.layer_test,
        run=lambda value: _get("/", "ok").pipe(
            fx.provide(server.serve(_ok_app()).pipe(L.provide_merge(value)))
        ),
    ),
    "pyfect.http.uvicorn_server.layer_test": Case(
        layer=uvicorn_server.layer_test,
        run=lambda value: _get("/", "ok").pipe(
            fx.provide(server.serve(_ok_app()).pipe(L.provide_merge(value)))
        ),
    ),
}


# --- http: clients, platforms, services --------------------------------------


def _absolute_get() -> AnyEffect:
    """``GET /`` at the served address, through an ``HttpClient`` that
    knows no base URL."""
    return server.address_formatted_with(lambda origin: _get(origin + "/", "ok"))


def _ok_server(make: AnyLayer) -> AnyLayer:
    """``make`` (a server layer) serving the ok app."""
    return server.serve(_ok_app()).pipe(L.provide_merge(make))


def _live_ok_server() -> AnyLayer:
    return _ok_server(live_server.layer(host="127.0.0.1"))


def _with_httpx(value: AnyLayer) -> AnyEffect:
    """A whole run over a server layer value: it serves the ok app and
    httpx sends to it."""
    return _absolute_get().pipe(
        fx.provide(_ok_server(value).pipe(L.provide_merge(httpx_client.layer)))
    )


def _echo_client(request: HttpClientRequest) -> AnyEffect:
    return fx.succeed(http_response.make(request, "ok", status=200))


def _etag_of_file(expected: str) -> AnyEffect:
    file = BytesFile(b"hello", "hello.txt", "text/plain")
    return _expect(
        etag.Generator()
        .flat_map(lambda gen: gen.from_file_web(file))
        .map(type)
        .map(lambda t: t.__name__),
        expected,
    )


def _web_file_response() -> AnyEffect:
    """A response for an in-memory file (it needs no file system)."""
    file = BytesFile(b"hello", "hello.txt", "text/plain")
    made = HttpPlatform().flat_map(lambda service: service.file_web_response(file))
    return _expect(made.map(lambda response: response.status), 200)


def _file_response() -> AnyEffect:
    """A response streaming this file from the live file system."""
    made = HttpPlatform().flat_map(lambda service: service.file_response(__file__))
    return _expect(made.map(lambda response: response.status), 200)


def _tracer_disabled() -> AnyEffect:
    request = request_from_web(WebRequest("http://localhost/health"))
    return _expect(TracerDisabledWhen().map(lambda disabled: disabled(request)), True)


_STATIC_ROOT = Path(__file__).parent


_CLIENTS: dict[str, Case] = {
    "pyfect.http.client.layer_test": Case(
        layer=lambda: http_client.layer_test(_echo_client), use=lambda: _get("http://test/", "ok")
    ),
    "pyfect.http.httpx_client.layer": Case(
        layer=lambda: httpx_client.layer, needs=_live_ok_server, use=_absolute_get
    ),
    "pyfect.http.httpx_client.layer_with": Case(
        layer=lambda: httpx_client.layer_with(timeout=5),
        needs=_live_ok_server,
        use=_absolute_get,
    ),
    "pyfect.http.server.layer_test_client": Case(
        layer=lambda: server.layer_test_client,
        needs=lambda: _live_ok_server().pipe(L.provide_merge(httpx_client.layer)),
        use=lambda: _get("/", "ok"),
    ),
    "pyfect.http.live_server.layer": Case(
        layer=lambda: live_server.layer(host="127.0.0.1"), run=_with_httpx
    ),
    "pyfect.http.live_server.layer_server": Case(
        layer=lambda: live_server.layer_server(host="127.0.0.1"), run=_with_httpx
    ),
    "pyfect.http.hypercorn_server.layer": Case(
        layer=lambda: hypercorn_server.layer(host="127.0.0.1"), run=_with_httpx
    ),
    "pyfect.http.hypercorn_server.layer_server": Case(
        layer=lambda: hypercorn_server.layer_server(host="127.0.0.1"), run=_with_httpx
    ),
    "pyfect.http.uvicorn_server.layer": Case(
        layer=lambda: uvicorn_server.layer(host="127.0.0.1"), run=_with_httpx
    ),
    "pyfect.http.uvicorn_server.layer_server": Case(
        layer=lambda: uvicorn_server.layer_server(host="127.0.0.1"), run=_with_httpx
    ),
    "pyfect.http.live_server.layer_services": Case(
        layer=lambda: live_server.layer_services, use=_file_response
    ),
    "pyfect.http.server.layer_services": Case(
        layer=lambda: server.layer_services, use=_web_file_response
    ),
    "pyfect.http.etag.layer": Case(layer=lambda: etag.layer, use=lambda: _etag_of_file("Strong")),
    "pyfect.http.etag.layer_weak": Case(
        layer=lambda: etag.layer_weak, use=lambda: _etag_of_file("Weak")
    ),
    "pyfect.http.platform.layer": Case(
        layer=lambda: platform.layer, needs=lambda: file_system.layer, use=_file_response
    ),
    "pyfect.http.platform.layer_strong": Case(
        layer=lambda: platform.layer_strong, needs=lambda: file_system.layer, use=_file_response
    ),
    "pyfect.http.platform.layer_live": Case(layer=lambda: platform.layer_live, use=_file_response),
    "pyfect.http.middleware.layer_tracer_disabled_for_urls": Case(
        layer=lambda: layer_tracer_disabled_for_urls(["/health"]), use=_tracer_disabled
    ),
    "pyfect.http.static_server.layer": Case(
        layer=lambda: static_server.layer(root=str(_STATIC_ROOT)),
        run=lambda value: _expect(_fetch("/_case.py").map(lambda got: got[0]), 200).pipe(
            fx.provide(_serve(value))
        ),
    ),
}


# --- peers on threads ---------------------------------------------------------
#
# A client layer value names its peer (a port, a URL) before any run, so the
# peers outlive every run: daemon threads, started on first use.

_TLS = Path(__file__).parent.parent / "oracle" / "fixtures" / "tls"
_CERT = (_TLS / "cert.pem").read_text()
_KEY = (_TLS / "key.pem").read_text()


def _accepting(listener: socket.socket, serve: Callable[[socket.socket], None]) -> int:
    def accept() -> None:
        while True:
            conn, _ = listener.accept()
            threading.Thread(target=serve, args=(conn,), daemon=True).start()

    threading.Thread(target=accept, daemon=True).start()
    return listener.getsockname()[1]


def _echo(conn: socket.socket) -> None:
    with contextlib.suppress(OSError), conn:
        while data := conn.recv(65536):
            conn.sendall(data)


@functools.cache
def _tcp_echo_port() -> int:
    return _accepting(socket.create_server(("127.0.0.1", 0)), _echo)


@functools.cache
def _tls_echo_port() -> int:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(_TLS / "cert.pem", _TLS / "key.pem")

    def serve(conn: socket.socket) -> None:
        with contextlib.suppress(OSError):
            _echo(context.wrap_socket(conn, server_side=True))

    return _accepting(socket.create_server(("127.0.0.1", 0)), serve)


class _WsPeer:
    """A ``websockets`` server: ``/echo`` echoes, ``/devtools`` answers
    pings and records the spans it is sent, ``/graphql`` answers every
    graphql-transport-ws operation with ``VIEWER``."""

    def __init__(self) -> None:
        self.spans: set[str] = set()
        self.seen = threading.Condition()
        self.server = sync_serve(self._handle, "127.0.0.1", 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def url(self, path: str) -> str:
        return f"ws://127.0.0.1:{self.server.socket.getsockname()[1]}{path}"

    def _handle(self, connection: ServerConnection) -> None:
        path = connection.request.path if connection.request is not None else ""
        with contextlib.suppress(ConnectionClosed):
            for message in connection:
                if path == "/echo":
                    connection.send(message)
                elif path == "/devtools":
                    self._devtools(connection, message)
                else:
                    self._graphql(connection, json.loads(message))

    def _devtools(self, connection: ServerConnection, message: str | bytes) -> None:
        text = message if isinstance(message, str) else message.decode()
        for line in filter(None, text.split("\n")):
            request = json.loads(line)
            if request["_tag"] == "Ping":
                connection.send('{"_tag":"Pong"}\n')
            elif request["_tag"] == "Span":
                with self.seen:
                    self.spans.add(request["name"])
                    self.seen.notify_all()

    def _graphql(self, connection: ServerConnection, message: dict[str, Any]) -> None:
        if message["type"] == "connection_init":
            connection.send(json.dumps({"type": "connection_ack"}))
        elif message["type"] == "subscribe":
            answer = {"id": message["id"], "type": "next", "payload": _VIEWER}
            connection.send(json.dumps(answer))
            connection.send(json.dumps({"id": message["id"], "type": "complete"}))

    def wait_for_span(self, name: str) -> AnyEffect:
        def wait() -> bool:
            with self.seen:
                return self.seen.wait_for(lambda: name in self.spans, timeout=5)

        return _expect(fx.blocking(wait), True)


@functools.cache
def _ws_peer() -> _WsPeer:
    return _WsPeer()


# --- sockets -------------------------------------------------------------------


def _hello(sock: SocketService) -> AnyEffect:
    """Send ``hello`` on ``sock`` and read until it comes back."""

    @fx.fn
    def body():
        writer = yield from sock.writer
        reader = yield from sock.reader
        yield from writer.write("hello")
        text = ""
        while len(text) < len("hello"):
            for chunk in (yield from reader.pull):
                text += chunk if isinstance(chunk, str) else chunk.decode()
        return text

    return _expect(fx.scoped(body()), "hello")


def _socket_round_trip() -> AnyEffect:
    return Socket().flat_map(_hello)


def _echo_handler(sock: SocketService) -> AnyEffect:
    @fx.fn
    def body():
        writer = yield from sock.writer
        reader = yield from sock.reader
        while True:
            yield from writer.write_all((yield from reader.pull))

    return fx.scoped(body()).catch_all(lambda _: fx.void)


def _port_of(srv: SocketServerService) -> int:
    address = srv.address
    assert isinstance(address, InetAddressV4 | InetAddressV6)
    return address.port


def _serving_echo(client: Callable[[int], AnyEffect]) -> Callable[[], AnyEffect]:
    """Run an echo handler on the ``SocketServer`` and round-trip through
    the client ``client`` makes for its port."""

    @fx.fn
    def body():
        srv = yield from SocketServer()
        yield from srv.run(_echo_handler).fork_scoped()
        sock = yield from client(_port_of(srv))
        return (yield from _hello(sock))

    return body


def _udp_round_trip() -> AnyEffect:
    @fx.fn
    def body():
        sock = yield from DatagramSocket()
        reader = yield from sock.reader
        writer = yield from sock.writer
        yield from writer.write_all([OutgoingDatagram("ping", reader.address)])
        received = yield from reader.pull
        return [datagram.payload for datagram in received]

    return _expect(fx.scoped(body()).timeout("5 seconds"), [b"ping"])


_SOCKETS: dict[str, Case] = {
    "pyfect.socket.layer_net": Case(
        layer=lambda: socket_layer_net(_tcp_echo_port(), "127.0.0.1"), use=_socket_round_trip
    ),
    "pyfect.socket.layer_tls": Case(
        layer=lambda: socket_layer_tls(
            _tls_echo_port(), "127.0.0.1", tls=TlsUpgradeOptions(ca=[_CERT])
        ),
        use=_socket_round_trip,
    ),
    "pyfect.socket.layer_web_socket": Case(
        layer=lambda: socket_layer_web_socket(_ws_peer().url("/echo")),
        needs=lambda: ws.layer_web_socket_constructor,
        use=_socket_round_trip,
    ),
    "pyfect.socket.ws.layer_web_socket": Case(
        layer=lambda: ws.layer_web_socket(_ws_peer().url("/echo")), use=_socket_round_trip
    ),
    "pyfect.socket.ws.layer_web_socket_constructor": Case(
        layer=lambda: ws.layer_web_socket_constructor,
        use=lambda: make_web_socket(_ws_peer().url("/echo")).flat_map(_hello),
    ),
    "pyfect.socket.ws.layer_web_socket_constructor_with": Case(
        layer=lambda: ws.layer_web_socket_constructor_with(max_message_size=1024),
        use=lambda: make_web_socket(_ws_peer().url("/echo")).flat_map(_hello),
    ),
    "pyfect.socket.server.layer": Case(
        layer=lambda: socket_server.layer(0, "127.0.0.1"),
        use=_serving_echo(lambda port: fx.succeed(make_net(port, "127.0.0.1"))),
    ),
    "pyfect.socket.server.layer_tls": Case(
        layer=lambda: socket_server.layer_tls(cert=_CERT, key=Redacted(_KEY), host="127.0.0.1"),
        use=_serving_echo(
            lambda port: fx.succeed(make_tls(port, "127.0.0.1", tls=TlsUpgradeOptions(ca=[_CERT])))
        ),
    ),
    "pyfect.socket.ws.layer_server": Case(
        layer=lambda: ws.layer_server(0, "127.0.0.1"),
        needs=lambda: ws.layer_web_socket_constructor,
        use=_serving_echo(lambda port: make_web_socket(f"ws://127.0.0.1:{port}")),
    ),
    "pyfect.socket.datagram.layer_udp": Case(
        layer=lambda: layer_udp(Options(bind=Bind("127.0.0.1"))), use=_udp_round_trip
    ),
}


# --- devtools ------------------------------------------------------------------

_span_names = itertools.count()


def _reports_a_span() -> AnyEffect:
    """A span of the run reaches the DevTools peer."""
    name = f"layer-reuse-{next(_span_names)}"
    return fx.void.with_span(name).and_then(_ws_peer().wait_for_span(name))


def _devtools_socket() -> AnyLayer:
    return ws.layer_web_socket(_ws_peer().url("/devtools"))


_DEVTOOLS: dict[str, Case] = {
    "pyfect.devtools.layer": Case(
        layer=lambda: devtools.layer(_ws_peer().url("/devtools")), use=_reports_a_span
    ),
    "pyfect.devtools.layer_web_socket": Case(
        layer=lambda: devtools.layer_web_socket(_ws_peer().url("/devtools")),
        needs=lambda: ws.layer_web_socket_constructor,
        use=_reports_a_span,
    ),
    "pyfect.devtools.layer_tracer": Case(
        layer=lambda: devtools.layer_tracer, needs=_devtools_socket, use=_reports_a_span
    ),
    "pyfect.devtools.client.layer": Case(
        layer=lambda: devtools_client.layer,
        run=lambda value: _reports_a_span().pipe(
            fx.provide(
                L.effect(CurrentTracer, devtools_client.make_tracer)
                .pipe(L.provide(value))
                .pipe(L.provide(_devtools_socket()))
            )
        ),
    ),
}


# --- graphql -------------------------------------------------------------------

_VIEWER = {"data": {"viewer": {"login": "tim"}}}


class _Viewers(Tag[ViewerGroup], key="test/layer_cases/http/Viewers"):
    pass


def _graphql_http(request: HttpClientRequest, _body: str | None, _url: object) -> Any:
    return graphql_response(request, _VIEWER)


def _viewer() -> AnyEffect:
    made = graphql_client.make(ViewerGroup).flat_map(lambda api: api.viewer())
    return _expect(made, {"viewer": {"login": "tim"}})


_GRAPHQL: dict[str, Case] = {
    "pyfect.graphql.layer_http": Case(
        layer=lambda: graphql.layer_http(url="http://localhost/graphql"),
        needs=lambda: http_client_layer(_graphql_http),
        use=_viewer,
    ),
    "pyfect.graphql.layer_web_socket": Case(
        layer=lambda: graphql.layer_web_socket(WebSocketOptions(url=_ws_peer().url("/graphql"))),
        needs=lambda: ws.layer_web_socket_constructor,
        use=_viewer,
    ),
    "pyfect.graphql.client.layer_test": Case(
        layer=lambda: graphql_client.layer_test(
            _Viewers, ViewerGroup, viewer=lambda _v, _o: fx.succeed(_VIEWER["data"])
        ),
        use=lambda: _expect(_Viewers().flat_map(lambda api: api.viewer()), _VIEWER["data"]),
    ),
}


# --- net -----------------------------------------------------------------------


def _dns_lookup(host: str, expected: str) -> AnyEffect:
    looked_up = Dns().flat_map(lambda service: service.lookup(host, family="IPv4"))
    return _expect(looked_up.map(lambda found: expected in map(format_ip, found)), True)


def _resolve(host: str, expected: str) -> AnyEffect:
    resolved = AddressResolver().flat_map(
        lambda service: service.resolve(host_port_from_string_unsafe(f"{host}:80"), family="IPv4")
    )
    return _expect(resolved.map(lambda found: expected in map(format_socket_address, found)), True)


def _db_zone() -> AnyLayer:
    return dns.layer_static(hosts={"db.internal": ["10.0.0.5"]})


_NET: dict[str, Case] = {
    "pyfect.net.dns.layer_static": Case(
        layer=_db_zone, use=lambda: _dns_lookup("db.internal", "10.0.0.5")
    ),
    "pyfect.net.dns.layer_system": Case(
        layer=dns.layer_system, use=lambda: _dns_lookup("localhost", "127.0.0.1")
    ),
    "pyfect.net.address_resolver.layer": Case(
        layer=address_resolver.layer,
        needs=_db_zone,
        use=lambda: _resolve("db.internal", "10.0.0.5:80"),
    ),
    "pyfect.net.address_resolver.layer_system": Case(
        layer=address_resolver.layer_system,
        needs=dns.layer_system,
        use=lambda: _resolve("localhost", "127.0.0.1:80"),
    ),
}


# --- http_api ------------------------------------------------------------------


class _Health(HttpApiGroup, identifier="health"):
    check = endpoint.get("check", "/health", success=S.String)


class _Clients(HttpApiMiddleware, key="test/layer_cases/http/Clients", required_for_client=True):
    pass


class _Clients2(HttpApiMiddleware, key="test/layer_cases/http/Clients2", required_for_client=True):
    pass


class _Schemas(HttpApiMiddleware[Never, Never], key="test/layer_cases/http/Schemas"):
    pass


_COUNT = (
    HttpApiGroup.make("count")
    .add(endpoint.get("count", "/count/:n", params=struct({"n": S.FiniteFromString})))
    .middleware(_Schemas)
)


def _health_api() -> HttpApi[Any]:
    return HttpApi.make("health").add(_Health)


def _health_live() -> AnyLayer:
    return builder.group(
        _health_api(), _Health, lambda h: h.handle(_Health.check)(lambda _: fx.succeed("ok"))
    )


def _served_api(app: AnyLayer, path: str, status: int) -> AnyEffect:
    return _expect(_fetch(path).map(lambda got: got[0]), status).pipe(fx.provide(_serve(app)))


def _pass_through(effect: AnyEffect, _options: object) -> AnyEffect:
    return effect


def _sets_header(options: ClientMiddlewareOptions) -> AnyEffect:
    return options.next(options.request.set_header("x-client", "1"))


def _client_call(
    api: HttpApi[Any], middleware: type[HttpApiMiddleware]
) -> Callable[..., AnyEffect]:
    """A whole run: ``api`` served (its ``middleware`` passing through), and
    called with its client over the client middleware layer value."""

    def run(value: AnyLayer) -> AnyEffect:
        @fx.fn
        def call():
            api_client = yield from api_client_make(api).pipe(fx.provide(value))
            return (yield from get_group(api_client, _Guarded).check())

        app = (
            builder.layer(api)
            .pipe(L.provide(_guarded_live(api)))
            .pipe(L.provide(L.succeed(middleware, _pass_through)))
        )
        return _expect(call(), "1").pipe(fx.provide(_serve(app)))

    return run


class _Guarded(HttpApiGroup, identifier="guarded"):
    check = endpoint.get("check", "/guarded", success=S.String)


def _guarded_api(middleware: type[HttpApiMiddleware]) -> HttpApi[Any]:
    return HttpApi.make("guarded").add(_Guarded.middleware(middleware))


def _guarded_live(api: HttpApi[Any]) -> AnyLayer:
    def handle(ctx: Any) -> AnyEffect:
        return fx.succeed(ctx.request.headers.get("x-client") or "missing")

    return builder.group(api, _Guarded, lambda h: h.handle(_Guarded.check)(handle))


def _count_api() -> HttpApi[Any]:
    return HttpApi.make("count").add(_COUNT)


_PROBLEMS = (
    HttpApiGroup.make("problems")
    .add(endpoint.get("count", "/count/:n", params=struct({"n": S.FiniteFromString})))
    .middleware(ProblemDetails)
)


def _problems_app(value: AnyLayer) -> AnyLayer:
    api = HttpApi.make("problems").add(_PROBLEMS)
    live = builder.group(
        api, _PROBLEMS, lambda h: h.handle(_PROBLEMS.endpoints["count"])(lambda _: fx.void)
    )
    return builder.layer(api).pipe(L.provide(live)).pipe(L.provide(value))


def _unprocessable(_error: object, _options: object) -> AnyEffect:
    return fx.succeed(server_response.empty(status=422))


def _count_app(value: AnyLayer) -> AnyLayer:
    api = _count_api()
    live = builder.group(
        api, _COUNT, lambda h: h.handle(_COUNT.endpoints["count"])(lambda _: fx.void)
    )
    return builder.layer(api).pipe(L.provide(live)).pipe(L.provide(value))


_HTTP_API: dict[str, Case] = {
    "pyfect.http_api.builder.layer": Case(
        layer=lambda: builder.layer(_health_api()),
        run=lambda value: _served_api(value.pipe(L.provide(_health_live())), "/health", 200),
    ),
    "pyfect.http_api.builder.group": Case(
        layer=_health_live,
        run=lambda value: _served_api(
            builder.layer(_health_api()).pipe(L.provide(value)), "/health", 200
        ),
    ),
    "pyfect.http_api.scalar.layer": Case(
        layer=lambda: scalar.layer(_health_api()),
        run=lambda value: _served_api(value, "/docs", 200),
    ),
    "pyfect.http_api.scalar.layer_cdn": Case(
        layer=lambda: scalar.layer_cdn(_health_api()),
        run=lambda value: _served_api(value, "/docs", 200),
    ),
    "pyfect.http_api.swagger.layer": Case(
        layer=lambda: swagger.layer(_health_api()),
        run=lambda value: _served_api(value, "/docs", 200),
    ),
    "pyfect.http_api.middleware.layer_client": Case(
        layer=lambda: layer_client(_Clients, _sets_header),
        run=_client_call(_guarded_api(_Clients), _Clients),
    ),
    "pyfect.http_api.middleware.layer_client_effect": Case(
        layer=lambda: layer_client_effect(_Clients2, fx.sync(lambda: _sets_header)),
        run=_client_call(_guarded_api(_Clients2), _Clients2),
    ),
    "pyfect.http_api.middleware.layer_schema_error_transform": Case(
        layer=lambda: layer_schema_error_transform(_Schemas, _unprocessable),
        run=lambda value: _served_api(_count_app(value), "/count/abc", 422),
    ),
    "pyfect.http_api.middleware.layer_problem_details": Case(
        layer=lambda: layer_problem_details(include_details=True),
        run=lambda value: _served_api(_problems_app(value), "/count/abc", 400),
    ),
}

CASES: dict[str, Case] = {
    **_HTTP,
    **_CLIENTS,
    **_SOCKETS,
    **_DEVTOOLS,
    **_GRAPHQL,
    **_NET,
    **_HTTP_API,
}
SKIPPED: dict[str, str] = {}
