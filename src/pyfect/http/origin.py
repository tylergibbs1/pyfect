"""Which browser origins a server lets open a WebSocket or call an RPC
endpoint (cross-site WebSocket hijacking and RPC CSRF). A browser sends
``Origin`` on every WebSocket handshake and cross-origin ``POST`` with the
user's cookies, so a request whose ``Origin`` is neither the server's own
(its ``Host``) nor listed in ``AllowedOrigins`` is refused with 403. A
request without ``Origin`` did not come from a browser page and passes.

Same-origin only is the default; list more with ``AllowedOrigins``::

    layer.succeed(AllowedOrigins, origin.allow("https://app.example"))
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, NewType

from pyfect._core import Effect
from pyfect.context import Reference
from pyfect.effect import fail, succeed, void
from pyfect.http._authority import Authority, parse_authority
from pyfect.http._url_text import split_url
from pyfect.http.server_error import HttpServerError, OriginNotAllowed

if TYPE_CHECKING:
    from pyfect.http.server_request import ServerRequest

Origin = NewType("Origin", str)
"""A serialized origin, ``scheme://host[:port]``, lowercased and without
the scheme's default port; or ``null`` (an opaque origin)."""

_DEFAULT_PORTS = {"http": 80, "https": 443, "ws": 80, "wss": 443}


def _host_port(scheme: str, authority: str) -> str:
    """``authority`` lowercased, without ``scheme``'s default port."""
    authority = authority.lower()
    default = _DEFAULT_PORTS.get(scheme)
    return authority.removesuffix(f":{default}") if default is not None else authority


def parse_origin(text: str) -> Origin | None:
    """``text`` as an origin; ``None`` when it is not ``scheme://authority``
    alone (a path, query, fragment or userinfo)."""
    if text == "null":
        return Origin(text)
    parts = split_url(text)
    if parts is None:
        return None
    scheme = parts.scheme.lower()
    if not scheme or parts.path or parts.query or parts.fragment or text.endswith("#"):
        return None
    if parse_authority(parts.netloc) is None:
        return None
    return Origin(f"{scheme}://{_host_port(scheme, parts.netloc)}")


@dataclass(frozen=True, slots=True)
class OriginPolicy:
    """The origins allowed besides the server's own; ``any`` allows all."""

    origins: frozenset[Origin] = frozenset()
    any: bool = False

    def allows(self, sent: str | None, authority: Authority | None) -> bool:
        """Whether a request with ``Origin: sent`` to ``authority`` (its
        ``host[:port]``) may go on: no ``Origin``, the server's own, a
        listed one, or ``any``."""
        if sent is None or self.any:
            return True
        origin = parse_origin(sent.strip())
        if origin is None:
            return False
        if origin in self.origins:
            return True
        if authority is None or origin == "null":
            return False
        scheme, _, own = origin.partition("://")
        return own == _host_port(scheme, authority)


SAME_ORIGIN = OriginPolicy()
"""Only the server's own origin (the default)."""

ANY_ORIGIN = OriginPolicy(any=True)
"""Every origin: for a public API that authenticates without cookies."""


def allow(*origins: str) -> OriginPolicy:
    """The server's own origin and ``origins`` (``https://app.example``);
    a ``ValueError`` names one that is not an origin."""
    parsed: set[Origin] = set()
    for text in origins:
        origin = parse_origin(text)
        if origin is None:
            raise ValueError(f"not an origin (scheme://host[:port]): {text!r}")
        parsed.add(origin)
    return OriginPolicy(frozenset(parsed))


class AllowedOrigins(Reference[OriginPolicy]):
    """The origins a server accepts WebSocket upgrades and RPC calls from;
    ``SAME_ORIGIN`` by default."""

    @classmethod
    def default(cls) -> OriginPolicy:
        return SAME_ORIGIN


def _authority(request: ServerRequest) -> Authority | None:
    """The request's own ``host[:port]``: its URL's, which servers build
    from a checked ``Host``, else its ``Host``."""
    parts = split_url(request.original_url)
    netloc = "" if parts is None else parts.netloc
    return parse_authority(netloc or request.headers.get("host", ""))


def origin_allowed(request: ServerRequest) -> Effect[bool]:
    """Whether ``AllowedOrigins`` lets ``request`` go on."""
    sent = request.headers.get("origin")
    authority = _authority(request)
    return AllowedOrigins().flat_map(lambda policy: succeed(policy.allows(sent, authority)))


def require_allowed_origin(request: ServerRequest) -> Effect[None, HttpServerError]:
    """Fail with ``OriginNotAllowed`` (403) unless ``AllowedOrigins`` lets
    ``request`` go on: what every WebSocket upgrade and RPC call runs."""

    def check(allowed: bool) -> Effect[None, HttpServerError]:
        if allowed:
            return void
        sent = request.headers.get("origin")
        return fail(HttpServerError(OriginNotAllowed(request, f"Origin {sent!r} is not allowed")))

    return origin_allowed(request).flat_map(check)


__all__ = [
    "ANY_ORIGIN",
    "SAME_ORIGIN",
    "AllowedOrigins",
    "HttpServerError",
    "Origin",
    "OriginPolicy",
    "allow",
    "origin_allowed",
    "parse_origin",
    "require_allowed_origin",
]
