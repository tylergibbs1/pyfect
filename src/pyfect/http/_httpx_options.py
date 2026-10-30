"""The ``httpx.AsyncClient`` options that would add to every request
(``headers``, ``params``, ``cookies``, ``auth``), taken out of httpx's hands.

httpx merges them into each request it sends, after pyfect's request
transformations (``follow_redirects`` stripping credentials on a hop to
another origin among them) have run. Parsed here once into a
``RequestDefaults`` that the pyfect client applies as a request
preprocessing step instead, so the request pyfect sees is the request sent.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from pyfect._extras import missing_extra
from pyfect.http.request import HttpClientRequest

REQUEST_DEFAULT_OPTIONS: Final = frozenset(("headers", "params", "cookies", "auth"))
"""The ``httpx.AsyncClient`` parameters httpx merges into every request."""


@dataclass(frozen=True, slots=True)
class RequestDefaults:
    """What each request gets unless it sets the same name itself."""

    headers: tuple[tuple[str, str], ...] = ()
    params: tuple[tuple[str, str], ...] = ()
    basic_auth: tuple[str, str] | None = None

    def is_empty(self) -> bool:
        return not self.headers and not self.params and self.basic_auth is None

    def apply(self, request: HttpClientRequest) -> HttpClientRequest:
        if self.basic_auth is not None and "authorization" not in request.headers:
            request = request.basic_auth(*self.basic_auth)
        missing = [(name, value) for name, value in self.headers if name not in request.headers]
        if missing:
            request = request.update_headers(lambda headers: headers.set_all(missing))
        params = request.url_params
        added = [(name, value) for name, value in self.params if not params.get_all(name)]
        if added:
            request = request.set_url_params(params.append_all(added))
        return request


def _text(value: str | bytes) -> str:
    return value.decode("latin-1") if isinstance(value, bytes) else value


def _basic_auth(auth: object) -> tuple[str, str] | None:
    match auth:
        case None:
            return None
        case (str() | bytes() as username, str() | bytes() as password):
            return _text(username), _text(password)
        case _:
            raise TypeError(
                "httpx_client: auth must be a (username, password) pair; set any other "
                "credential per request (client.map_request(lambda r: r.bearer_token(...))) "
                "so follow_redirects can drop it on a hop to another origin"
            )


def _cookie_header(cookies: object) -> tuple[tuple[str, str], ...]:
    match cookies:
        case None:
            return ()
        case Mapping():
            pairs = [(str(name), str(value)) for name, value in cookies.items()]  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]
            return (
                (("cookie", "; ".join(f"{name}={value}" for name, value in pairs)),)
                if pairs
                else ()
            )
        case _:
            raise TypeError(
                "httpx_client: cookies must be a mapping of names to values; "
                "use HttpClientService.with_cookies_ref for a cookie jar"
            )


def import_httpx():  # the inferred return type is the httpx module
    """The ``httpx`` module, imported when a client is made, so that
    ``pyfect.http`` imports without the ``httpx`` extra."""
    try:
        import httpx
    except ImportError as error:
        raise missing_extra("pyfect.http.httpx_client", "httpx") from error
    return httpx


def _header_pairs(headers: Any) -> tuple[tuple[str, str], ...]:
    if headers is None:
        return ()
    return tuple(
        (name.lower(), value) for name, value in import_httpx().Headers(headers).multi_items()
    )


def _param_pairs(params: Any) -> tuple[tuple[str, str], ...]:
    if params is None:
        return ()
    return tuple(import_httpx().QueryParams(params).multi_items())


def split_options(options: Mapping[str, Any]) -> tuple[RequestDefaults, dict[str, Any]]:
    """``options`` split into the request defaults and the rest (passed to
    ``httpx.AsyncClient``). Raises ``TypeError`` for a default pyfect could
    not keep from following a redirect to another origin."""
    transport = {
        name: value for name, value in options.items() if name not in REQUEST_DEFAULT_OPTIONS
    }
    defaults = RequestDefaults(
        headers=_header_pairs(options.get("headers")) + _cookie_header(options.get("cookies")),
        params=_param_pairs(options.get("params")),
        basic_auth=_basic_auth(options.get("auth")),
    )
    return defaults, transport
