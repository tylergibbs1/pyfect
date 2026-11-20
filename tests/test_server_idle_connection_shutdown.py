"""Every HTTP server adapter stops as Effect's ``NodeHttpServer`` does while a client holds an
idle keep-alive connection: an idle HTTP/1.1 connection is closed at once and an HTTP/2
session within ``graceful_shutdown_timeout``. Over TLS asyncio waits up to 30 seconds for
the client's ``close_notify`` before a closed connection counts as closed, which held
hypercorn's shutdown that long (dogfood turnstile #2)."""

from __future__ import annotations

import asyncio
import datetime as dt
import socket
import ssl
import threading
import time
from dataclasses import dataclass
from typing import Any, Literal

import httpx
import pytest
from _timing import PAST_ANY_TEST, wait_until
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

import pyfect as fx
from pyfect import layer
from pyfect.http import (
    hypercorn_server,
    live_server,
    router,
    server,
    server_response,
    uvicorn_server,
)
from pyfect.net.net_address import InetAddressV4
from pyfect.scope import scoped
from pyfect.socket import server as socket_server

GRACEFUL_SECONDS = 2.0

_PAST = PAST_ANY_TEST.to_seconds()
"""A timeout in seconds, for the engines' configs, that the test never lives to see."""


@pytest.fixture(autouse=True)
def _slow_paths_past_the_test(monkeypatch: pytest.MonkeyPatch) -> None:
    """asyncio's TLS waits (60 s for a handshake, 30 s for the client's ``close_notify``) past
    the test's time limit: a shutdown or close that waits for them fails as hung."""
    monkeypatch.setattr(asyncio.constants, "SSL_HANDSHAKE_TIMEOUT", _PAST)
    monkeypatch.setattr(asyncio.constants, "SSL_SHUTDOWN_TIMEOUT", _PAST)


@dataclass(frozen=True)
class Pem:
    cert: bytes
    key: bytes
    cert_path: str
    key_path: str


@pytest.fixture(scope="module")
def pem(tmp_path_factory: pytest.TempPathFactory) -> Pem:
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = dt.datetime.now(dt.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - dt.timedelta(minutes=5))
        .not_valid_after(now + dt.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    folder = tmp_path_factory.mktemp("tls")
    (folder / "cert.pem").write_bytes(cert_pem)
    (folder / "key.pem").write_bytes(key_pem)
    return Pem(cert_pem, key_pem, str(folder / "cert.pem"), str(folder / "key.pem"))


type Adapter = Literal["hypercorn", "uvicorn", "live"]
type Http = Literal["h1", "h2"]


def _server(
    adapter: Adapter, pem: Pem | None, graceful: float = GRACEFUL_SECONDS
) -> fx.Layer[Any, Any, Any]:
    """The adapter's server, with every timeout that would close an idle or stalled connection
    by itself (keep-alive, TLS handshake) past the test's time limit."""
    timeout = f"{graceful} seconds"
    host = "127.0.0.1"
    match adapter:
        case "hypercorn":
            config: dict[str, Any] = {"keep_alive_timeout": _PAST, "ssl_handshake_timeout": _PAST}
            if pem is not None:
                config |= {"certfile": pem.cert_path, "keyfile": pem.key_path}
            return hypercorn_server.layer(
                host=host, graceful_shutdown_timeout=timeout, config=config
            )
        case "uvicorn":
            config = {"timeout_keep_alive": _PAST}
            if pem is not None:
                config |= {"ssl_certfile": pem.cert_path, "ssl_keyfile": pem.key_path}
            return uvicorn_server.layer(host=host, graceful_shutdown_timeout=timeout, config=config)
        case "live":
            if pem is None:
                return live_server.layer(
                    host=host, graceful_shutdown_timeout=timeout, keep_alive_timeout=PAST_ANY_TEST
                )
            made = live_server.make_tls(
                host=host,
                graceful_shutdown_timeout=timeout,
                keep_alive_timeout=PAST_ANY_TEST,
                cert=pem.cert,
                key=pem.key,
                handshake_timeout=PAST_ANY_TEST,
            )
            return layer.merge(layer.effect(server.HttpServer, made), live_server.layer_services)


def _shut_down(adapter: Adapter, http: Http, pem: Pem | None, graceful: float) -> None:
    """Serve one request on a connection the client then keeps open, and stop the server."""
    ports: list[int] = []
    stop, stopped, ready = threading.Event(), threading.Event(), threading.Event()

    @fx.fn
    def serving():
        running = yield from server.HttpServer()
        assert isinstance(running.address, InetAddressV4)
        ports.append(running.address.port)
        ready.set()
        yield from fx.blocking(stop.wait)

    routes = router.add("GET", "/", server_response.text("ok"))
    app = router.serve(routes, disable_logger=True, disable_listen_log=True)
    program = scoped(serving().pipe(fx.provide(app))).pipe(
        fx.provide(_server(adapter, pem, graceful))
    )

    def run() -> None:
        fx.run_blocking(program.or_die())
        stopped.set()

    threading.Thread(target=run, daemon=True).start()
    assert ready.wait(10)
    verify: ssl.SSLContext | bool = (
        False if pem is None else ssl.create_default_context(cadata=pem.cert.decode())
    )
    scheme = "http" if pem is None else "https"
    with httpx.Client(http1=http == "h1", http2=http == "h2", verify=verify) as client:
        response = client.get(f"{scheme}://localhost:{ports[0]}/")
        assert (response.http_version, response.text) == (
            "HTTP/1.1" if http == "h1" else "HTTP/2",
            "ok",
        )
        stop.set()
        wait_until(stopped.is_set, what="the server to stop")


def _cases() -> list[Any]:
    cases: list[Any] = []
    for adapter, https in [("hypercorn", ("h1", "h2")), ("uvicorn", ("h1",)), ("live", ("h1",))]:
        for tls in (False, True):
            for http in https:
                kind = f"{adapter}-{http}-{'tls' if tls else 'cleartext'}"
                cases.append(pytest.param(adapter, http, tls, id=kind))
    return cases


GRACEFUL: dict[Http, float] = {"h1": PAST_ANY_TEST.to_seconds(), "h2": GRACEFUL_SECONDS}
"""What ``NodeHttpServer`` (``node:http2``'s secure server allowing HTTP/1.1) does: it closes
idle HTTP/1.1 connections at once, so waiting for the timeout fails as hung, and waits for
HTTP/2 sessions up to the timeout, so that one ends within the test."""


@pytest.mark.parametrize(("adapter", "http", "tls"), _cases())
def test_an_idle_keep_alive_connection_does_not_hold_the_shutdown(
    adapter: Adapter, http: Http, tls: bool, pem: Pem
) -> None:
    _shut_down(adapter, http, pem if tls else None, GRACEFUL[http])


type Stall = Literal["silent", "partial-hello"]

STALLS: dict[Stall, bytes] = {"silent": b"", "partial-hello": b"\x16\x03\x01\x02\x00\x01"}
"""What a client that never finishes its TLS handshake sends: nothing, or the start of a
ClientHello."""


def _stalled_shut_down(adapter: Adapter, stall: Stall, pem: Pem, graceful: float) -> None:
    """Stop the server while a client sits in its TLS handshake."""
    ports: list[int] = []
    stop, stopped, ready = threading.Event(), threading.Event(), threading.Event()

    @fx.fn
    def serving():
        running = yield from server.HttpServer()
        assert isinstance(running.address, InetAddressV4)
        ports.append(running.address.port)
        ready.set()
        yield from fx.blocking(stop.wait)

    routes = router.add("GET", "/", server_response.text("ok"))
    app = router.serve(routes, disable_logger=True, disable_listen_log=True)
    served = _server(adapter, pem, graceful)
    program = scoped(serving().pipe(fx.provide(app))).pipe(fx.provide(served))

    def run() -> None:
        fx.run_blocking(program.or_die())
        stopped.set()

    threading.Thread(target=run, daemon=True).start()
    assert ready.wait(10)
    with socket.create_connection(("127.0.0.1", ports[0])) as client:
        client.sendall(STALLS[stall])
        time.sleep(0.1)  # let the server accept it
        stop.set()
        wait_until(stopped.is_set, what="the server to stop")


@pytest.mark.parametrize("stall", list(STALLS))
@pytest.mark.parametrize("adapter", sorted({case.values[0] for case in _cases()}))
def test_a_stalled_tls_handshake_does_not_hold_the_shutdown(
    adapter: Adapter, stall: Stall, pem: Pem
) -> None:
    """``NodeHttpServer`` over https stops within ``gracefulShutdownTimeout`` while a client
    never finishes its handshake: the stall held it for the handshake timeout (10 or 60 s),
    past the test's time limit."""
    _stalled_shut_down(adapter, stall, pem, graceful=1.0)


type SocketServerKind = Literal["web-socket-tls", "web-socket", "tls"]


def _socket_server(kind: SocketServerKind, pem: Pem) -> fx.Effect[Any, Any, Any]:
    match kind:
        case "web-socket-tls":
            context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            context.load_cert_chain(pem.cert_path, pem.key_path)
            return socket_server.make_web_socket(0, "127.0.0.1", ssl=context, open_timeout=_PAST)
        case "web-socket":
            # websockets' open timeout is 10 s by default, its TLS handshake's too.
            return socket_server.make_web_socket(0, "127.0.0.1", open_timeout=_PAST)
        case "tls":
            # make_tls waits 120 s for a handshake: past the test's time limit already.
            return socket_server.make_tls(cert=pem.cert, key=pem.key, host="127.0.0.1")


@pytest.mark.parametrize("stall", list(STALLS))
@pytest.mark.parametrize("kind", ["web-socket-tls", "web-socket", "tls"])
def test_a_connection_still_opening_does_not_hold_a_socket_servers_close(
    kind: SocketServerKind, stall: Stall, pem: Pem
) -> None:
    """Effect's ``NodeSocketServer`` closes at once while a client has connected but not
    finished opening (Node's ``server.close`` drops connections that sent no request)."""
    ports: list[int] = []
    stop, stopped, ready = threading.Event(), threading.Event(), threading.Event()

    @fx.fn
    def serving():
        running = yield from _socket_server(kind, pem)
        assert isinstance(running.address, InetAddressV4)
        ports.append(running.address.port)
        ready.set()
        yield from fx.blocking(stop.wait)

    def run() -> None:
        fx.run_blocking(scoped(serving()).or_die())
        stopped.set()

    threading.Thread(target=run, daemon=True).start()
    assert ready.wait(10)
    with socket.create_connection(("127.0.0.1", ports[0])) as client:
        client.sendall(STALLS[stall])
        time.sleep(0.1)  # let the server accept it
        stop.set()
        # The stall held the close for the handshake timeout, past the test's time limit.
        wait_until(stopped.is_set, what="the socket server to close")


def test_every_server_adapter_is_covered() -> None:
    """A new server module must join the cases above."""
    import pkgutil

    import pyfect.http as http_package

    modules = {module.name for module in pkgutil.iter_modules(http_package.__path__)}
    servers = {name for name in modules if name.endswith("_server")} - {"static_server"}
    adapters = {name.removesuffix("_server") for name in servers}
    covered = {str(case.values[0]) for case in _cases()}
    assert adapters == covered
