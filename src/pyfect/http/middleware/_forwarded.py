"""Trusting ``X-Forwarded-*`` headers from known proxies (Effect's
``HttpMiddleware.xForwardedHeaders``)."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any

from pyfect._core import Effect, _WithFiber
from pyfect._fiber import Fiber
from pyfect._primitives import _Locally
from pyfect.http._authority import parse_authority
from pyfect.http.middleware._types import AppMiddleware
from pyfect.http.server_request import HttpServerRequest, ServerRequest
from pyfect.http.server_response import HttpServerResponse
from pyfect.net import ip_network
from pyfect.net.ip_network import IpNetwork
from pyfect.net.net_address import (
    IpAddress,
    format_ip,
    inet_address_from_string,
    ip_from_string,
    to_canonical,
)
from pyfect.result import Ok

type TrustedProxies = Sequence[IpNetwork] | Callable[[IpAddress], bool]
"""The proxies whose forwarded headers are believed: networks, or a test."""


def _split(value: str | None) -> list[str] | None:
    return None if value is None else [part.strip() for part in value.split(",")]


def _aligned(header: str | None, length: int, index: int) -> str | None:
    """A host or proto list belongs to the hops only with one value per
    ``X-Forwarded-For`` entry."""
    values = _split(header)
    return values[index] if values is not None and len(values) == length else None


def _address(text: str | None) -> IpAddress | None:
    if text is None:
        return None
    bare = text[1:-1] if text.startswith("[") and text.endswith("]") else text
    match ip_from_string(bare):
        case Ok(ip):
            return to_canonical(ip)
        case _:
            pass
    match inet_address_from_string(text):
        case Ok(inet):
            return to_canonical(inet.address)
        case _:
            return None


def _apply(request: ServerRequest, trusted: Callable[[IpAddress], bool]) -> ServerRequest:
    peer = _address(request.peer_address)
    if peer is None or not trusted(peer):
        return request
    addresses = _split(request.headers.get("x-forwarded-for"))
    if addresses is None:
        return request
    for index in range(len(addresses) - 1, -1, -1):
        address = _address(addresses[index])
        if address is None:
            return request
        if index > 0 and trusted(address):
            continue
        host = _aligned(request.headers.get("x-forwarded-host"), len(addresses), index)
        protocol = _aligned(request.headers.get("x-forwarded-proto"), len(addresses), index)
        protocol = None if protocol is None else protocol.lower()
        return request.modify(
            remote_address=format_ip(address),
            peer_address=request.peer_address,
            headers=request.headers.set("host", host)
            if host is not None and parse_authority(host) is not None
            else None,
            protocol="https" if protocol == "https" else "http" if protocol == "http" else None,
        )
    return request


def x_forwarded_headers(
    trusted_proxies: TrustedProxies,
) -> AppMiddleware[HttpServerRequest]:
    """Middleware taking the client address (and its aligned
    ``X-Forwarded-Host`` / ``-Proto``) from ``X-Forwarded-For`` when the
    transport peer is a trusted proxy: the rightmost hop that is not one,
    stopping at an entry that is not an address."""
    trusted: Callable[[IpAddress], bool]
    if callable(trusted_proxies):
        trusted = trusted_proxies
    else:
        networks = tuple(trusted_proxies)

        def in_networks(address: IpAddress) -> bool:
            return any(ip_network.contains(network, address) for network in networks)

        trusted = in_networks

    def middleware[E, R](
        app: Effect[HttpServerResponse, E, R],
    ) -> Effect[HttpServerResponse, E, R | HttpServerRequest]:
        def body(fiber: Fiber[Any, Any]) -> Effect[HttpServerResponse, E, R]:
            request = _apply(fiber._context.unsafe_get(HttpServerRequest), trusted)
            return _Locally(app, lambda ctx: ctx.add(HttpServerRequest, request))

        return _WithFiber(body)

    return middleware
