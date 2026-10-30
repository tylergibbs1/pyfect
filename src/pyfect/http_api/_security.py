"""Reading credentials from a request (Effect's ``HttpApiBuilder``
``securityDecode``) and running a security middleware's handlers."""

from __future__ import annotations

import base64
import binascii
from collections.abc import Callable, Mapping
from typing import Any, Never, Unpack, overload

from pyfect import redacted
from pyfect._core import Effect
from pyfect.effect import fail
from pyfect.http.cookies import CookieOptionsInput
from pyfect.http.http_effect import append_pre_response_handler
from pyfect.http.server_request import HttpServerRequest, ParsedSearchParams, ServerRequest
from pyfect.http.server_response import HttpServerResponse
from pyfect.http_api.middleware import SecurityMiddlewareFn, SecurityOptions
from pyfect.http_api.security import ApiKey, Basic, Credentials, Http, HttpApiSecurity
from pyfect.redacted import Redacted

_EMPTY_CREDENTIALS = Credentials("", redacted.make(""))


@overload
def security_decode(
    security: Basic,
) -> Effect[Credentials, Never, HttpServerRequest | ParsedSearchParams]: ...
@overload
def security_decode(
    security: Http | ApiKey,
) -> Effect[Redacted[str], Never, HttpServerRequest | ParsedSearchParams]: ...
def security_decode(
    security: HttpApiSecurity,
) -> Effect[Redacted[str] | Credentials, Never, HttpServerRequest | ParsedSearchParams]:
    """The credential ``security`` reads from the request; empty when it
    is missing or malformed."""
    match security:
        case Http():
            scheme = security.scheme
            return HttpServerRequest().map(
                lambda request: redacted.make(
                    authorization_credential(request.headers.get("authorization"), scheme) or ""
                )
            )
        case ApiKey():
            return _api_key(security)
        case Basic():
            return HttpServerRequest().map(_basic)


def _api_key(
    security: ApiKey,
) -> Effect[Redacted[str], Never, HttpServerRequest | ParsedSearchParams]:
    key = security.key
    match security.in_:
        case "header":
            name = key.lower()
            return HttpServerRequest().map(
                lambda request: redacted.make(request.headers.get(name) or "")
            )
        case "query":
            return ParsedSearchParams().map(lambda query: redacted.make(_string(query.get(key))))
        case "cookie":
            return HttpServerRequest().map(
                lambda request: redacted.make(request.cookies.get(key) or "")
            )


def _string(value: object) -> str:
    return value if isinstance(value, str) else ""


def _basic(request: ServerRequest) -> Credentials:
    encoded = authorization_credential(request.headers.get("authorization"), "Basic")
    if encoded is None:
        return _EMPTY_CREDENTIALS
    try:
        decoded = base64.b64decode(encoded, validate=True).decode("utf-8", "replace")
    except (binascii.Error, ValueError):
        return _EMPTY_CREDENTIALS
    # RFC 7617, Section 2: only the first colon separates the user-id from the password.
    username, colon, password = decoded.partition(":")
    if not colon:
        return _EMPTY_CREDENTIALS
    return Credentials(username, redacted.make(password))


def authorization_credential(authorization: str | None, scheme: str) -> str | None:
    """The credential of an ``Authorization`` header with ``scheme``. RFC
    9110, Section 11.1: schemes are case-insensitive and credentials follow
    1*SP."""
    length = len(scheme)
    if (
        authorization is None
        or len(authorization) <= length
        or authorization[length] != " "
        or authorization[:length].lower() != scheme.lower()
    ):
        return None
    credential = authorization[length:].lstrip(" ")
    return credential or None


def security_set_cookie(
    security: ApiKey, value: str | Redacted[str], **options: Unpack[CookieOptionsInput]
) -> Effect[None, Never, HttpServerRequest]:
    """Set ``security``'s cookie on the response (secure, HTTP-only and
    ``SameSite=Lax`` unless ``options`` say otherwise; Effect sets no
    ``SameSite``)."""
    text = value if isinstance(value, str) else redacted.value(value)
    cookie: CookieOptionsInput = {"secure": True, "http_only": True, "same_site": "lax", **options}

    def handler(
        _request: ServerRequest, response: HttpServerResponse
    ) -> Effect[HttpServerResponse]:
        return response.set_cookie(security.key, text, **cookie).or_die()

    return append_pre_response_handler(handler)


# --- running a security middleware -----------------------------------------------------


class _HandlerError:
    """A failure of the handler itself: the next security is not tried."""

    __slots__ = ("error",)

    def __init__(self, error: object) -> None:
        self.error = error


type Middleware = Callable[[Effect[Any, Any, Any], Any], Effect[Any, Any, Any]]


def security_middleware(
    securities: Mapping[str, HttpApiSecurity],
    service: Mapping[str, SecurityMiddlewareFn[Any, Any, Any]],
) -> Middleware:
    """Tries each security in order: the first whose middleware succeeds
    answers, a failure of the handler is the answer, and when every one
    fails the last failure is."""
    entries = [(security_decode(security), service[key]) for key, security in securities.items()]

    def middleware(handler: Effect[Any, Any, Any], options: Any) -> Effect[Any, Any, Any]:
        wrapped: Effect[Any, Any, Any] = handler.map_error(_HandlerError)

        def attempt(index: int, last: object) -> Effect[Any, Any, Any]:
            if index == len(entries):
                return fail(last)
            decode, run = entries[index]

            def with_credential(credential: Any) -> Effect[Any, Any, Any]:
                return run(wrapped, SecurityOptions(credential, options.endpoint, options.group))

            def on_error(error: object) -> Effect[Any, Any, Any]:
                if isinstance(error, _HandlerError):
                    return fail(error.error)
                return attempt(index + 1, error)

            return decode.flat_map(with_credential).catch_all(on_error)

        return attempt(0, None)

    return middleware


__all__ = [
    "authorization_credential",
    "security_decode",
    "security_middleware",
    "security_set_cookie",
]
