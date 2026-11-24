"""The Bot Framework Connector client, the bot's token, and the one way
requests leave: redirects off, and a response refused unless it came from
the URL the request went to."""

from __future__ import annotations

from collections.abc import Callable, Generator, Mapping, Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Never
from urllib.parse import quote

import pyfect as fx
from pyfect._core import Effect, _call_user
from pyfect._json_value import JsonValue
from pyfect._url import Url
from pyfect.chat.chat_adapter import retry_safe
from pyfect.chat.chat_error import AnyReason, ChatError
from pyfect.chat.teams import _errors, _json
from pyfect.chat.teams._cloud import Cloud, Credentials, TokenGrant
from pyfect.clock import current_time_millis
from pyfect.http import request as http_request
from pyfect.http.client import HttpClientService
from pyfect.http.error import HttpClientError
from pyfect.http.httpx_client import FollowRedirects
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse
from pyfect.http.url import set_hash
from pyfect.redacted import Redacted
from pyfect.redacted import make as redacted
from pyfect.redacted import value as redacted_value
from pyfect.semaphore import Semaphore

type Method = Literal["GET", "POST", "PUT", "DELETE"]
type Http = HttpClientService[HttpClientError, Never]

_REFRESH_MARGIN_MILLIS = 5 * 60 * 1000
"""How long before ``expires_at`` a cached token is dropped."""
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


def trusted_service_url(url: str, hosts: Sequence[str]) -> str | None:
    """The trust step for a Connector base URL: ``https:``, the default port,
    no userinfo, query or fragment, and an exact host in the allowlist. The
    URL without a trailing slash, or ``None``."""
    parsed = Url.parse(url)
    if (
        parsed is None
        or parsed.protocol != "https:"
        or parsed.port
        or parsed.username
        or parsed.password
        or parsed.search
        or parsed.hash
        or parsed.hostname not in hosts
    ):
        return None
    return parsed.origin + parsed.pathname.rstrip("/")


def no_redirects[A, E, R](effect: Effect[A, E, R]) -> Effect[A, E, R]:
    """``effect`` with the client's redirects off for every request it sends,
    including those made by code the adapter hands the client to."""
    return effect.pipe(fx.provide_service(FollowRedirects, False))


def without_redirects(http: Http) -> Http:
    """The client with redirects off, for each request it sends."""
    return http.transform(lambda sending, _request: no_redirects(sending))


def effective_url(request: HttpClientRequest) -> str | None:
    """The URL a request goes to, with its query parameters and without a hash."""
    url = request.to_url()
    return None if url is None else set_hash(url, "").href


def send(
    http: Http, request: HttpClientRequest, *, write: bool, op: str
) -> Effect[HttpClientResponse, ChatError]:
    """Sends one request with redirects off. A response from another URL than
    the request's, query included, means something followed a redirect, and
    is refused."""

    def checked(response: HttpClientResponse) -> Effect[HttpClientResponse, ChatError]:
        if response.url != effective_url(request):
            return fx.fail(_errors.chat_error(op, _errors.untrusted_url()))
        return fx.succeed(response)

    return (
        no_redirects(http.execute(request))
        .map_error(
            lambda error: _errors.chat_error(
                op, _errors.transport(write, type(error.reason).__name__, error)
            )
        )
        .flat_map(checked)
    )


type Tokens = Callable[[str], Effect[Redacted[str], ChatError]]


def make_tokens(
    *, http: Http, cloud: Cloud, app_id: str, tenant_id: str, credentials: Credentials
) -> Tokens:
    """Gets a token by client credentials, or from the consumer's provider,
    and caches it until five minutes before it expires. A token with no
    expiry is not cached."""
    cache: dict[str, tuple[Redacted[str], float]] = {}
    lock = Semaphore(1)

    def fail(reason: AnyReason) -> Effect[Never, ChatError]:
        return fx.fail(_errors.chat_error("token", reason))

    def client_credentials(secret: Redacted[str], scope: str) -> Effect[TokenGrant, ChatError]:
        @fx.gen
        def run() -> Generator[Effect[Any, ChatError, Any], Any, TokenGrant]:
            url = f"{cloud.login_url}/{_segment(tenant_id)}/oauth2/v2.0/token"
            request = http_request.post(url).body_url_params(
                {
                    "grant_type": "client_credentials",
                    "client_id": app_id,
                    "client_secret": redacted_value(secret),
                    "scope": scope,
                }
            )
            response = yield from fx.scoped(send(http, request, write=False, op="token"))
            if response.status != 200:
                return (yield from fail(_errors.reason_for_status(response.status, write=False)))
            text = yield from response.text.map_error(
                lambda cause: _errors.chat_error(
                    "token", _errors.invalid_response(False, "invalid_json", cause)
                )
            )
            answer = _json.as_object(_json.parse(text))
            token = None if answer is None else answer.get("access_token")
            if answer is None or not isinstance(token, str) or not token:
                return (yield from fail(_errors.invalid_response(False, "missing_access_token")))
            now = yield from current_time_millis()
            expires_in = _seconds(answer.get("expires_in"))
            expires_at = (
                None
                if expires_in is None
                else _EPOCH + timedelta(milliseconds=now + expires_in * 1000)
            )
            return TokenGrant(redacted(token), expires_at)

        return run

    def provider(scope: str) -> Effect[TokenGrant, ChatError]:
        if isinstance(credentials, Redacted):
            return client_credentials(credentials, scope)
        return _call_user(credentials, scope)

    def get(scope: str) -> Effect[Redacted[str], ChatError]:
        @fx.gen
        def run() -> Generator[Effect[Any, ChatError, Any], Any, Redacted[str]]:
            now = yield from current_time_millis()
            cached = cache.get(scope)
            if cached is not None and cached[1] > now:
                return cached[0]
            cache.pop(scope, None)
            grant = yield from retry_safe(provider(scope))
            if grant.expires_at is not None:
                until = (grant.expires_at - _EPOCH) / timedelta(milliseconds=1)
                until -= _REFRESH_MARGIN_MILLIS
                if until > now:
                    cache[scope] = (grant.token, until)
            return grant.token

        return lock.with_permits(run)

    return get


def _seconds(value: object) -> float | None:
    """A positive, finite ``expires_in``, a number or a numeric string."""
    if isinstance(value, bool):
        return None
    if isinstance(value, str):
        try:
            value = float(value.strip()) if value.strip() else None
        except ValueError:
            return None
    if not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if 0 < number < float("inf") else None


def _segment(value: str) -> str:
    return quote(value, safe="-_.!~*'()")


segment = _segment
"""Encodes one path segment as ``encodeURIComponent`` does."""


class Connector:
    """The Connector client. ``path`` starts with ``/v3/`` and has its
    segments encoded by the caller."""

    def __init__(self, *, http: Http, cloud: Cloud, token: Tokens) -> None:
        self._http = http
        self._cloud = cloud
        self._token = token

    def call(
        self,
        method: Method,
        path: str,
        body: object = None,
        *,
        write: bool = False,
        retry: bool = True,
        service_url: str | None = None,
        query: Mapping[str, str] | None = None,
        op: str | None = None,
    ) -> Effect[JsonValue | None, ChatError]:
        """One request with the bot's token. ``service_url`` is an inbound
        activity's own, checked against the allowlist before a token is
        attached; without it the cloud's ``connector_url`` is used. A write
        is never retried once sent, and a failure that may have landed is
        ``uncertain``."""
        once = self._once(method, path, body, write, service_url, query, op)
        return retry_safe(once) if retry else once

    def _once(  # noqa: PLR0917
        self,
        method: Method,
        path: str,
        body: object,
        write: bool,
        service_url: str | None,
        query: Mapping[str, str] | None,
        op: str | None,
    ) -> Effect[JsonValue | None, ChatError]:
        name = op or f"{method} {'/'.join(path.split('/')[:3])}"

        def fail(reason: AnyReason) -> Effect[Never, ChatError]:
            return fx.fail(_errors.chat_error(name, reason))

        @fx.gen
        def run() -> Generator[Effect[Any, ChatError, Any], Any, JsonValue | None]:
            base = (
                self._cloud.connector_url
                if service_url is None
                else trusted_service_url(service_url, self._cloud.connector_hosts)
            )
            if base is None:
                return (yield from fail(_errors.untrusted_url()))
            token = yield from self._token(self._cloud.connector_scope).map_error(
                lambda error: _errors.with_op(name, error)
            )
            request = (
                http_request.make(method, base + path)
                .bearer_token(token)
                .set_header("accept", "application/json")
            )
            if query is not None:
                request = request.set_url_params(dict(query))
            if body is not None:
                request = request.body_json_unsafe(body)
            response = yield from send(self._http, request, write=write, op=name)
            retry_after = _errors.parse_retry_after(response.headers.get("retry-after"))
            if not 200 <= response.status < 300:
                text = yield from response.text.or_else_succeed(lambda _: "")
                error = _json.object_(_json.parse(text), "error")
                code = _json.string(error, "code")
                return (
                    yield from fail(
                        _errors.reason_for_status(
                            response.status, write=write, code=code, retry_after=retry_after
                        )
                    )
                )
            text = yield from response.text.map_error(
                lambda cause: _errors.chat_error(
                    name, _errors.invalid_response(write, "invalid_body", cause)
                )
            )
            if not text.strip():
                return None
            parsed = _json.parse(text)
            if parsed is None and text.strip() != "null":
                return (yield from fail(_errors.invalid_response(write, "invalid_json")))
            return parsed  # pyright: ignore[reportReturnType]

        return fx.scoped(run)
