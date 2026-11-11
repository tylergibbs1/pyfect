"""Every HTTP server adapter stops as Effect's ``NodeHttpServer`` does while a client holds an
idle keep-alive connection: an idle HTTP/1.1 connection is closed at once and an HTTP/2
session within ``graceful_shutdown_timeout``. Over TLS asyncio waits up to 30 seconds for
the client's ``close_notify`` before a closed connection counts as closed, which held
hypercorn's shutdown that long (dogfood turnstile #2)."""

from __future__ import annotations

import datetime
import ssl
import threading
import time
from dataclasses import dataclass
from typing import Any, Literal

import httpx
import pytest
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

GRACEFUL_SECONDS = 2.0
SLACK_SECONDS = 0.5
"""Beyond what Effect takes: scheduling, and uvicorn polls its connections every 0.1 s."""


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
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=1))
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


def _server(adapter: Adapter, pem: Pem | None) -> fx.Layer[Any, Any, Any]:
    timeout = f"{GRACEFUL_SECONDS} seconds"
    host = "127.0.0.1"
    match adapter:
        case "hypercorn":
            config = {} if pem is None else {"certfile": pem.cert_path, "keyfile": pem.key_path}
            return hypercorn_server.layer(
                host=host, graceful_shutdown_timeout=timeout, config=config
            )
        case "uvicorn":
            config = (
                {} if pem is None else {"ssl_certfile": pem.cert_path, "ssl_keyfile": pem.key_path}
            )
            return uvicorn_server.layer(host=host, graceful_shutdown_timeout=timeout, config=config)
        case "live":
            if pem is None:
                return live_server.layer(host=host, graceful_shutdown_timeout=timeout)
            made = live_server.make_tls(
                host=host, graceful_shutdown_timeout=timeout, cert=pem.cert, key=pem.key
            )
            return layer.merge(layer.effect(server.HttpServer, made), live_server.layer_services)


def _shutdown_seconds(adapter: Adapter, http: Http, pem: Pem | None) -> float:
    """Serve one request on a connection the client then keeps open, and time how long the
    server takes to stop."""
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
    program = scoped(serving().pipe(fx.provide(app))).pipe(fx.provide(_server(adapter, pem)))

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
        started = time.monotonic()
        stop.set()
        assert stopped.wait(60), "the server did not stop"
        return time.monotonic() - started


def _cases() -> list[Any]:
    cases: list[Any] = []
    for adapter, https in [("hypercorn", ("h1", "h2")), ("uvicorn", ("h1",)), ("live", ("h1",))]:
        for tls in (False, True):
            for http in https:
                kind = f"{adapter}-{http}-{'tls' if tls else 'cleartext'}"
                cases.append(pytest.param(adapter, http, tls, id=kind))
    return cases


EFFECT_SECONDS: dict[Http, float] = {"h1": 0.0, "h2": GRACEFUL_SECONDS}
"""What ``NodeHttpServer`` (``node:http2``'s secure server allowing HTTP/1.1) takes: it
closes idle HTTP/1.1 connections at once and waits for HTTP/2 sessions up to the timeout."""


@pytest.mark.parametrize(("adapter", "http", "tls"), _cases())
def test_an_idle_keep_alive_connection_does_not_hold_the_shutdown(
    adapter: Adapter, http: Http, tls: bool, pem: Pem
) -> None:
    took = _shutdown_seconds(adapter, http, pem if tls else None)
    assert took <= EFFECT_SECONDS[http] + SLACK_SECONDS, f"shutdown took {took:.2f}s"


def test_every_server_adapter_is_covered() -> None:
    """A new server module must join the cases above."""
    import pkgutil

    import pyfect.http as http_package

    modules = {module.name for module in pkgutil.iter_modules(http_package.__path__)}
    servers = {name for name in modules if name.endswith("_server")} - {"static_server"}
    adapters = {name.removesuffix("_server") for name in servers}
    covered = {str(case.values[0]) for case in _cases()}
    assert adapters == covered
