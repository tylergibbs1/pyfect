"""Ports of Effect's ``http/HttpServer.test.ts``. Each test's docstring is
the Effect test title."""

from typing import Any
from urllib.parse import SplitResult, urlsplit

import pytest

import pyfect as fx
from pyfect import effect
from pyfect.exit import Failure
from pyfect.http import client as http_client
from pyfect.http import response as http_response
from pyfect.http import server
from pyfect.http.client import HttpClient
from pyfect.http.request import HttpClientRequest
from pyfect.http.server import HttpServer
from pyfect.net import NetAddressError
from pyfect.net.net_address import (
    SocketAddress,
    inet_address_from_string_unsafe,
    inet_address_unsafe,
    ipv4_loopback,
    unix_path_address,
)


def _server(address: SocketAddress) -> server.HttpServerService:
    return server.make(address=address, serve=lambda _app, _mw: effect.void)


def _formatted(address: SocketAddress) -> str:
    return fx.run_blocking(
        server.address_formatted_with(effect.succeed).pipe(
            effect.provide_service(HttpServer, _server(address))
        )
    )


def test_accepts_a_canonical_socket_address() -> None:
    """accepts a canonical socket address"""
    address = inet_address_unsafe(ipv4_loopback, 8080)
    assert _server(address).address is address


def test_passes_formatted_server_addresses_to_the_callback() -> None:
    """passes formatted server addresses to the callback"""
    for text, expected in [
        ("127.0.0.1:3000", "http://127.0.0.1:3000"),
        ("127.0.0.1:80", "http://127.0.0.1"),
        ("[::]:3000", "http://[::]:3000"),
        ("[::1]:3000", "http://[::1]:3000"),
        ("[fe80::1%0]:3000", "http://[fe80::1]:3000"),
    ]:
        formatted = _formatted(inet_address_from_string_unsafe(text))
        assert formatted == expected
        assert urlsplit(formatted).hostname is not None
    for path, expected in [
        ("server.sock", "unix://server.sock"),
        ("/tmp/server.sock", "unix:///tmp/server.sock"),
        ("./run/../socket?#", "unix://./run/../socket?#"),
    ]:
        assert _formatted(unix_path_address(path)) == expected


def _client(
    send: Any,
) -> http_client.HttpClientService[Any]:
    return http_client.make(send)


def _unexpected(*_: object) -> fx.Effect[Any]:
    return effect.die(AssertionError("unexpected request"))


def test_rejects_scoped_ipv6_test_server_addresses_before_dropping_their_scope() -> None:
    """rejects scoped IPv6 test server addresses before dropping their scope"""
    for text in ["[fe80::1%2]:3000", "[::%2]:3000"]:
        address = inet_address_from_string_unsafe(text)
        client = _client(_unexpected)
        exit = fx.run_blocking_exit(
            server.make_test_client.pipe(effect.provide_service(HttpServer, _server(address))).pipe(
                effect.provide_service(HttpClient, client)
            )
        )
        assert isinstance(exit, Failure)
        error = exit.cause.squash()
        assert isinstance(error, NetAddressError)
        assert error.input == address


@pytest.mark.parametrize(
    ("text", "origin"),
    [
        ("0.0.0.0:3000", "http://127.0.0.1:3000"),
        ("[::]:3000", "http://127.0.0.1:3000"),
        ("127.0.0.1:3000", "http://127.0.0.1:3000"),
        ("[::1]:3000", "http://[::1]:3000"),
        ("[2001:db8::1]:3000", "http://[2001:db8::1]:3000"),
    ],
)
def test_uses_ipv4_loopback_for_unspecified_listeners_and_preserves_explicit_hosts(
    text: str, origin: str
) -> None:
    """uses IPv4 loopback for unspecified listeners and preserves explicit hosts"""
    seen: list[str] = []

    def send(
        request: HttpClientRequest, url: SplitResult, *_: object
    ) -> fx.Effect[http_response.HttpClientResponse]:
        seen.append(f"{url.scheme}://{url.netloc}")
        return effect.succeed(http_response.make(request))

    address = inet_address_from_string_unsafe(text)

    @fx.fn
    def program():
        test_client = yield from server.make_test_client
        yield from test_client.get("/")

    fx.run_blocking(
        program()
        .pipe(effect.provide_service(HttpServer, _server(address)))
        .pipe(effect.provide_service(HttpClient, _client(send)))
        .or_die()
    )
    assert seen == [origin]
