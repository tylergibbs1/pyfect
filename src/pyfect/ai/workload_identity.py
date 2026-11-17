"""Workload identity federation (Effect's ``effect/ai/WorkloadIdentity``):
authenticate an ``HttpClient`` with access tokens obtained by exchanging a
workload's identity token (a Kubernetes service account token, a cloud
OIDC token, ...) at a token endpoint, cached until shortly before they
expire.

For Anthropic, OpenAI or OpenRouter use the provider's own module
(``pyfect.ai.anthropic.workload_identity``, ``pyfect.ai.openai.workload_identity``,
``pyfect.ai.openrouter.workload_identity``), which builds the exchange
request that provider expects::

    from pyfect.ai import workload_identity

    transform = yield from workload_identity.make(
        token_url="https://auth.example.com/oauth/token",
        identity_token=file_system.read_file_string(TOKEN_PATH).map(redacted.make),
        exchange_request=lambda request, token: request.body_json_unsafe(
            {"grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
             "subject_token": token,
             "subject_token_type": "urn:ietf:params:oauth:token-type:jwt"}
        ),
        default_expires_in="1 hour",
    )
    client = transform(base_client)
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from typing import Any, Final, Never

import pyfect as fx
from pyfect import duration
from pyfect._effect_args import require_effect
from pyfect._js import trim
from pyfect._json_text import Json, stringify
from pyfect._json_text import parse as parse_json
from pyfect._url import Url
from pyfect.ai._provider import ClientTransform
from pyfect.cache import Cache
from pyfect.effect import Effect
from pyfect.exit import Exit, Success
from pyfect.http import request as http_request
from pyfect.http import response as http_response
from pyfect.http.client import HttpClient, HttpClientService, transform_response
from pyfect.http.error import (
    DecodeError,
    EncodeError,
    HttpClientError,
    StatusCodeError,
    TransportError,
)
from pyfect.http.httpx_client import FollowRedirects
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse
from pyfect.redacted import Redacted
from pyfect.redacted import make as redact_value
from pyfect.redacted import value as redacted_value

_MAX_RESPONSE_BYTES: Final = 1024 * 1024
_CACHE_KEY: Final = "accessToken"
# Printable ASCII only, so the token is safe to send in a header.
_ACCESS_TOKEN: Final = re.compile(r"[\x21-\x7e]+")
_LOOPBACK: Final = frozenset(("localhost", "127.0.0.1", "[::1]"))

type ExchangeRequest = Callable[[HttpClientRequest, str], HttpClientRequest]
"""Completes the exchange request (a JSON-accepting ``POST`` to the token
URL) with the trimmed identity token: its body and headers only."""


class _Token:
    __slots__ = ("expires_in", "value")

    def __init__(self, value: Redacted[str], expires_in: float) -> None:
        self.value = value
        self.expires_in = expires_in


def _check_token_url(url: str) -> None:
    parsed = Url(url)
    if parsed.protocol == "https:":
        return
    if parsed.protocol == "http:" and parsed.hostname in _LOOPBACK:
        return
    raise ValueError(f'Refusing to send an identity token to the non-https token URL "{url}"')


def _expires_in_seconds(input: duration.Input | None) -> float | None:
    if input is None:
        return None
    seconds = duration.to_seconds(input)
    if not 0 < seconds < math.inf:
        raise ValueError("`default_expires_in` must be a positive finite duration")
    return seconds


def _error_messages(error: object) -> list[str]:
    """The messages of ``error`` and its causes; never the errors, which may
    hold requests carrying the identity token."""
    messages: list[str] = []
    cause = error
    depth = 0
    while isinstance(cause, BaseException) and depth < 5:
        message = getattr(cause, "message", None)
        text = message if isinstance(message, str) else str(cause)
        if text:
            messages.append(text)
        cause = cause.__cause__ if cause.__cause__ is not None else getattr(cause, "cause", None)
        depth += 1
    return messages


def _redact_values(json: Json, redact: Callable[[str], str]) -> Json:
    match json:
        case str():
            return redact(json)
        case dict():
            return {key: _redact_values(value, redact) for key, value in json.items()}
        case list():
            return [_redact_values(value, redact) for value in json]
        case _:
            return json


def _redact_body(body: str, redact: Callable[[str], str]) -> str:
    """Escaped tokens are decoded before values are redacted; the second
    pass covers keys."""
    try:
        json = parse_json(body)
    except ValueError:
        return redact(body)
    return redact(stringify(_redact_values(json, redact)))


def _read_body(response: HttpClientResponse) -> Effect[str | None]:
    """The body, or ``None`` when it is missing, unreadable or over the limit."""

    def read() -> Effect[str | None]:
        size = 0

        def within(chunk: bytes) -> bool:
            nonlocal size
            size += len(chunk)
            return size <= _MAX_RESPONSE_BYTES

        body: Effect[str | None, HttpClientError] = (
            response.stream.take_while(within)
            .decode_text()
            .run_string()
            .map(lambda text: None if size > _MAX_RESPONSE_BYTES else text)
        )
        return body.catch_all(lambda _: fx.succeed(None))

    return fx.suspend(read)


def _positive_finite(value: Json) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    try:
        seconds = float(value)
    except OverflowError:
        return None
    return seconds if 0 < seconds < math.inf else None


def _decode_token(body: str | None) -> tuple[str, float | None] | None:
    """The access token and its ``expires_in`` of a token response, or
    ``None`` for an invalid one."""
    try:
        json = None if body is None else parse_json(body)
    except ValueError:
        json = None
    if not isinstance(json, dict):
        return None
    access_token = json.get("access_token")
    if not isinstance(access_token, str) or _ACCESS_TOKEN.fullmatch(access_token) is None:
        return None
    if "expires_in" not in json:
        return access_token, None
    expires_in = _positive_finite(json["expires_in"])
    return None if expires_in is None else (access_token, expires_in)


def _time_to_live(exit: Exit[_Token, HttpClientError], _key: str) -> duration.Duration:
    # Stop using a token up to 30 seconds early to allow for clock differences and request
    # latency. Failed exchanges are not cached.
    if isinstance(exit, Success):
        expires_in = exit.value.expires_in
        return duration.seconds(max(expires_in - 30, expires_in * 0.75))
    return duration.zero


def make[E = Never, R = Never](
    *,
    token_url: str,
    identity_token: Effect[Redacted[str], E, R],
    exchange_request: ExchangeRequest,
    default_expires_in: duration.Input | None = None,
) -> Effect[ClientTransform, Never, HttpClient | R]:
    """A transform of an ``HttpClient`` that sends each request with
    ``Authorization: Bearer`` and an access token, obtained by exchanging
    the identity token ``identity_token`` gives at ``token_url``.

    Each exchange runs ``identity_token`` again and hands its trimmed value
    and a JSON-accepting ``POST`` to ``token_url`` to ``exchange_request``.
    The response's ``access_token`` lives ``expires_in`` seconds, or
    ``default_expires_in`` when the response has none (and the exchange
    fails without either). Tokens are kept until 30 seconds before they
    expire or three quarters of their lifetime, whichever is later;
    concurrent requests share one exchange. A 401 response discards the
    token that request carried, without sending it again.

    Exchanges go through the ``HttpClient`` service, never following a
    redirect, and fail with an ``HttpClientError``: ``StatusCodeError`` for a
    rejected exchange, ``TransportError`` for a transport failure or a
    redirect, ``DecodeError`` for an invalid token response and
    ``EncodeError`` for an identity token that fails (its error is the
    cause) or is empty. The errors keep neither the exchange's body nor its
    transport errors (only their messages), and the identity token is
    replaced with ``<redacted>`` in those messages and in a rejection's
    headers and body (JSON-escaped occurrences included).

    ``token_url`` must be ``https``, or ``http`` on ``localhost``,
    ``127.0.0.1`` or ``[::1]``; ``exchange_request`` may change only the
    body and headers (put query parameters in ``token_url``); and
    ``default_expires_in`` must be positive and finite. Anything else is a
    defect. The response is read up to 1 MiB, and the access token must be
    printable ASCII."""

    require_effect(identity_token, "identity_token")

    @fx.gen
    def build():
        _check_token_url(token_url)
        default_seconds = _expires_in_seconds(default_expires_in)
        http: HttpClientService[HttpClientError] = yield from HttpClient()
        # Errors must not keep the exchange request's body.
        error_request = http_request.post(token_url)
        prepared = error_request.accept_json()

        def request_error(description: str) -> HttpClientError:
            return HttpClientError(TransportError(error_request, description=description))

        def identity_token_error(description: str, cause: object = None) -> HttpClientError:
            return HttpClientError(EncodeError(error_request, cause, description))

        def exchange(token: str) -> Effect[_Token, HttpClientError]:
            def redact(text: str) -> str:
                return text.replace(token, "<redacted>")

            def error_response(
                response: HttpClientResponse, body: str | None = None
            ) -> HttpClientResponse:
                return http_response.make(
                    error_request,
                    None if body is None else _redact_body(body, redact),
                    status=response.status,
                    headers={name: redact(value) for name, value in response.headers.items()},
                )

            def invalid_response(response: HttpClientResponse) -> Effect[Never, HttpClientError]:
                return fx.fail(
                    HttpClientError(
                        DecodeError(
                            error_request,
                            error_response(response),
                            description="The token endpoint returned an invalid token response",
                        )
                    )
                )

            def unsent(error: HttpClientError) -> Effect[HttpClientResponse, HttpClientError]:
                response = error.response
                if response is not None:
                    return fx.succeed(response)
                description = error.reason.description
                messages = [*([description] if description else []), *_error_messages(error.cause)]
                return fx.fail(
                    request_error(
                        redact(": ".join(messages)) or "Failed to reach the token endpoint"
                    )
                )

            def on_body(
                response: HttpClientResponse, body: str | None
            ) -> Effect[_Token, HttpClientError]:
                if response.status >= 300:
                    rejected = StatusCodeError(error_request, error_response(response, body))
                    return fx.fail(HttpClientError(rejected))
                decoded = _decode_token(body)
                if decoded is None:
                    return invalid_response(response)
                access_token, expires_in = decoded
                seconds = default_seconds if expires_in is None else expires_in
                if seconds is None:
                    return invalid_response(response)
                return fx.succeed(_Token(redact_value(access_token), seconds))

            def on_response(response: HttpClientResponse) -> Effect[_Token, HttpClientError]:
                status = response.status
                if status < 200 or status >= 600 or 300 <= status < 400:
                    return fx.fail(
                        request_error(
                            f"The token endpoint responded with the status {status}. "
                            "Redirects are not followed"
                        )
                    )
                return _read_body(response).flat_map(lambda body: on_body(response, body))

            request = exchange_request(prepared, token)
            # Keep the identity token confined to the validated endpoint.
            if (
                request.method != prepared.method
                or request.url != prepared.url
                or len(request.url_params) > 0
                or request.hash is not None
            ):
                return fx.die(
                    ValueError(
                        "`exchange_request` must keep the method, URL, URL parameters and hash "
                        f'of the "POST {token_url}" request'
                    )
                )
            return (
                http.execute(request)
                # Redirects would forward the identity token.
                .pipe(fx.provide_service(FollowRedirects, False))
                .catch_all(unsent)
                .flat_map(on_response)
            )

        def with_token(value: Redacted[str]) -> Effect[_Token, HttpClientError]:
            token = trim(redacted_value(value))
            if token == "":
                return fx.fail(identity_token_error("The identity token is empty"))
            return exchange(token)

        def lookup(_key: str) -> Effect[_Token, HttpClientError, R]:
            loaded: Effect[Redacted[str], HttpClientError, R] = identity_token.map_error(
                lambda cause: identity_token_error("Failed to load the identity token", cause)
            )
            return loaded.flat_map(with_token)

        cache: Cache[str, _Token, HttpClientError] = yield from Cache.make(
            lookup, capacity=1, time_to_live=_time_to_live
        )

        def invalidate(request: HttpClientRequest) -> Effect[bool]:
            return cache.invalidate_when(
                _CACHE_KEY,
                lambda token: (
                    request.headers.get("authorization") == f"Bearer {redacted_value(token.value)}"
                ),
            )

        def authenticate(request: HttpClientRequest) -> Effect[HttpClientRequest, HttpClientError]:
            return cache.get(_CACHE_KEY).map(lambda token: request.bearer_token(token.value))

        def on_rejection(
            sending: Effect[HttpClientResponse, HttpClientError],
        ) -> Effect[HttpClientResponse, HttpClientError]:
            def on_error(error: HttpClientError) -> Effect[Any]:
                response = error.response
                return invalidate(error.request) if response and response.status == 401 else fx.void

            return sending.tap(
                lambda response: invalidate(response.request) if response.status == 401 else fx.void
            ).tap_error(on_error)

        def transform(
            client: HttpClientService[HttpClientError],
        ) -> HttpClientService[HttpClientError]:
            return client.map_request_effect(authenticate).pipe(transform_response(on_rejection))

        return transform

    return build


__all__ = ["ClientTransform", "ExchangeRequest", "make"]
