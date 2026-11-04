"""The Cloudflare Workers AI client (Effect's ``CloudflareClient``): Clef
decisions over the ``HttpClient`` service.

``layer(account_id=..., api_key=...)`` provides ``CloudflareClient``;
requests go to ``api_url`` (``https://api.cloudflare.com/client/v4``) with
the token as a bearer token, through the AI Gateway ``gateway_id`` names
(the ``cf-aig-gateway-id`` header). ``create_decisions`` unwraps
Cloudflare's result envelope; every failure is an ``AiError``, and nothing
is retried.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Never, TypedDict, cast
from urllib.parse import quote

import pyfect as fx
from pyfect import byte_size
from pyfect import config as C
from pyfect import layer as L
from pyfect import schema as S
from pyfect._core import Effect
from pyfect._js import or_default
from pyfect.ai import _provider as P
from pyfect.ai._provider import ClientTransform
from pyfect.ai.ai_error import AiError
from pyfect.ai.cloudflare import _errors as Errors
from pyfect.ai.cloudflare import schema as W
from pyfect.config import Config, ConfigError
from pyfect.context import Tag
from pyfect.http import request as http_request
from pyfect.http.client import HttpClient, HttpClientService
from pyfect.http.error import HttpClientError
from pyfect.http.response import HttpClientResponse
from pyfect.redacted import Redacted
from pyfect.redacted import value as redacted_value

DEFAULT_API_URL = "https://api.cloudflare.com/client/v4"


@dataclass(frozen=True)
class Service:
    """The client: the configured ``HttpClient`` and the decisions call."""

    http_client: HttpClientService[HttpClientError]
    create_decisions: Callable[[W.DecisionsRequest], Effect[W.DecisionsResponse, AiError]]


class CloudflareClient(Tag[Service], key="@effect/ai-cloudflare/CloudflareClient"):
    """The Cloudflare client."""


class _Success(TypedDict):
    success: Literal[True]
    result: W.DecisionsResponse


class _Failure(TypedDict):
    success: Literal[False]


type _Envelope = _Success | _Failure

_decode_envelope: Callable[[object], Effect[_Envelope, S.SchemaError]] = P.wire_parser(
    S.Union(S.Struct(_Success, result=W.DECISIONS_RESPONSE), S.Struct(_Failure)),
    cast("type[_Envelope]", dict),
)

_redacted = P.with_redacted_headers(Errors.SECRET_HEADERS)


def make(
    *,
    account_id: str,
    api_key: Redacted[str],
    gateway_id: str | None = None,
    api_url: str | None = None,
    transform_client: ClientTransform | None = None,
    max_response_bytes: byte_size.Input | None = None,
) -> Effect[Service, Never, HttpClient]:
    """A client over the ``HttpClient`` service for ``account_id``. A
    response body larger than ``max_response_bytes`` (256 MiB) fails."""
    limit = P.response_limit(max_response_bytes)
    path = f"/accounts/{quote(account_id, safe="-_.!~*'()")}/ai/run/@cf/cloudflare/"

    def prepare(request: http_request.HttpClientRequest) -> http_request.HttpClientRequest:
        request = (
            request.prepend_url(or_default(api_url, DEFAULT_API_URL))
            .bearer_token(redacted_value(api_key))
            .accept_json()
        )
        return (
            request if gateway_id is None else request.set_header("cf-aig-gateway-id", gateway_id)
        )

    def build(base: HttpClientService[HttpClientError]) -> Service:
        mapped = base.map_request(prepare).filter_status_ok()
        http_client = mapped if transform_client is None else transform_client(mapped)
        limited = P.limit_responses(http_client, limit)

        def unwrap(response: HttpClientResponse) -> Effect[W.DecisionsResponse, Any]:
            def read(envelope: _Envelope) -> Effect[W.DecisionsResponse, AiError]:
                if envelope["success"] is True:
                    return fx.succeed(envelope["result"])
                return Errors.map_response_error(response)

            return response.json.flat_map(_decode_envelope).flat_map(read)

        def create_decisions(payload: W.DecisionsRequest) -> Effect[W.DecisionsResponse, AiError]:
            request = http_request.post(path + payload["model"]).body_json_unsafe(payload)
            sent: Effect[Any, Any] = limited.execute(request).flat_map(unwrap)
            return sent.catch_all(Errors.map_error).pipe(_redacted)

        return Service(http_client, create_decisions)

    return HttpClient().map(build).pipe(_redacted)


def layer(
    *,
    account_id: str,
    api_key: Redacted[str],
    gateway_id: str | None = None,
    api_url: str | None = None,
    transform_client: ClientTransform | None = None,
    max_response_bytes: byte_size.Input | None = None,
) -> L.Layer[CloudflareClient, Never, HttpClient]:
    """``CloudflareClient`` from these options (see ``make``)."""
    return L.effect(
        CloudflareClient,
        make(
            account_id=account_id,
            api_key=api_key,
            gateway_id=gateway_id,
            api_url=api_url,
            transform_client=transform_client,
            max_response_bytes=max_response_bytes,
        ),
    )


def layer_config(
    *,
    account_id: Config[str] | None = None,
    api_key: Config[Redacted[str]] | None = None,
    gateway_id: Config[str] | Config[str | None] | None = None,
    api_url: Config[str] | None = None,
    transform_client: ClientTransform | None = None,
    max_response_bytes: byte_size.Input | None = None,
) -> L.Layer[CloudflareClient, ConfigError, HttpClient]:
    """``CloudflareClient`` with its options read from ``Config``: by
    default ``CLOUDFLARE_ACCOUNT_ID``, ``CLOUDFLARE_API_TOKEN`` and the
    optional ``CLOUDFLARE_AI_GATEWAY_ID``."""
    built: Effect[Service, ConfigError, HttpClient] = fx.all(
        account_id or C.string("CLOUDFLARE_ACCOUNT_ID"),
        api_key or C.redacted("CLOUDFLARE_API_TOKEN"),
        gateway_id or C.string("CLOUDFLARE_AI_GATEWAY_ID").with_default(None),
        P.optional_config(api_url),
    ).flat_map(
        lambda values: make(
            account_id=values[0],
            api_key=values[1],
            gateway_id=values[2],
            api_url=values[3],
            transform_client=transform_client,
            max_response_bytes=max_response_bytes,
        )
    )
    return L.effect(CloudflareClient, built)


__all__ = ["DEFAULT_API_URL", "CloudflareClient", "Service", "layer", "layer_config", "make"]
