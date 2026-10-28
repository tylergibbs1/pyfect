"""What a request's ASGI scope says: its target relative to the mount
point (``root_path``), absolute URL, headers and peer."""

from __future__ import annotations

from urllib.parse import quote

from pyfect.http.asgi._types import Scope

# What ``quote`` keeps of a path: RFC 3986 ``pchar``s and ``/``.
_PATH_SAFE = "/:@!$&'()*+,;=-._~%"


def _strip_prefix(path: str, prefix: str) -> str:
    if prefix and path.startswith(prefix) and path[len(prefix) : len(prefix) + 1] in ("", "/"):
        return path[len(prefix) :] or "/"
    return path


def target(scope: Scope) -> str:
    """The path and query, without the ``root_path`` the app is mounted at
    (servers and Starlette's ``Mount`` keep it in ``path``)."""
    root = quote(scope.get("root_path", ""), safe=_PATH_SAFE)
    raw: bytes | None = scope.get("raw_path")
    path = raw.decode("latin-1") if raw else quote(scope["path"], safe=_PATH_SAFE)
    path = _strip_prefix(path.split("?", 1)[0], root) or "/"
    query: bytes = scope.get("query_string", b"")
    return f"{path}?{query.decode('latin-1')}" if query else path


def header_lines(scope: Scope) -> list[tuple[str, str]]:
    pairs: list[tuple[bytes, bytes]] = scope.get("headers", [])
    return [(name.decode("latin-1").lower(), value.decode("latin-1")) for name, value in pairs]


def _host(scope: Scope, lines: list[tuple[str, str]]) -> str:
    for name, value in lines:
        if name == "host":
            return value
    server: tuple[str, int | None] | None = scope.get("server")
    if server is None:
        return "localhost"
    host, port = server
    host = f"[{host}]" if ":" in host else host
    return host if port is None else f"{host}:{port}"


def url(scope: Scope, lines: list[tuple[str, str]]) -> str:
    """The absolute URL: ``http`` or ``https`` (``ws`` and ``wss`` too)."""
    scheme = "https" if scope.get("scheme") in ("https", "wss") else "http"
    return f"{scheme}://{_host(scope, lines)}{target(scope)}"


def remote_address(scope: Scope) -> str | None:
    client: tuple[str, int] | None = scope.get("client")
    return None if client is None else client[0]


def has_body(scope: Scope, lines: list[tuple[str, str]]) -> bool:
    """Whether the request has a body: framed by its headers over HTTP/1,
    possible on any request with content over HTTP/2 and 3."""
    for name, value in lines:
        if name == "transfer-encoding":
            return True
        if name == "content-length":
            return value.strip() != "0"
    return scope.get("http_version", "1.1") not in ("1.0", "1.1") and scope.get("method") not in (
        "GET",
        "HEAD",
    )
