"""The TypeSafe client (Effect's ``TypeSafeClient``): System One decisions
and the model list over the ``HttpClient`` service.

``layer(api_key=...)`` provides ``TypeSafeClient``; requests go to
``api_url`` (``https://api.typesafe.ai/v1``) with the key as a bearer
token, through ``transform_client`` and then a provided
``TypeSafeConfig``'s transform. Every failure is an ``AiError``, and
nothing is retried.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Never

from pyfect import byte_size
from pyfect import config as C
from pyfect import layer as L
from pyfect._core import Effect
from pyfect._js import or_default
from pyfect.ai import _provider as P
from pyfect.ai._provider import ClientTransform
from pyfect.ai.ai_error import AiError
from pyfect.ai.typesafe import _errors as Errors
from pyfect.ai.typesafe import schema as W
from pyfect.ai.typesafe.config import TypeSafeConfig
from pyfect.config import Config, ConfigError
from pyfect.context import Tag
from pyfect.http import request as http_request
from pyfect.http.client import HttpClient, HttpClientService
from pyfect.http.error import HttpClientError
from pyfect.redacted import Redacted
from pyfect.redacted import value as redacted_value

DEFAULT_API_URL = "https://api.typesafe.ai/v1"

_decode_system_one = P.wire_parser(W.SYSTEM_ONE_RESPONSE, W.SystemOneResponse)
_decode_models = P.wire_parser(W.LIST_MODELS_RESPONSE, W.ListModelsResponse)
_redacted = P.with_redacted_headers(Errors.SECRET_HEADERS)


def _uses_images(request: W.SystemOneRequest) -> bool:
    """Whether the request needs ``TypeSafe-Danger-Zone-Images: true``: it
    has assets or a box question."""
    return "assets" in request or any(q["type"] == "box" for q in request["questions"].values())


@dataclass(frozen=True)
class Service:
    """The client: the configured ``HttpClient`` and its calls."""

    http_client: HttpClientService[HttpClientError]
    system_one: Callable[[W.SystemOneRequest], Effect[W.SystemOneResponse, AiError]]
    """Sends ``TypeSafe-Danger-Zone-Images: true`` when the request has
    assets or a box question."""
    list_models: Callable[[], Effect[W.ListModelsResponse, AiError]]


class TypeSafeClient(Tag[Service], key="@effect/ai-typesafe/TypeSafeClient"):
    """The TypeSafe client."""


def make(
    *,
    api_key: Redacted[str] | None = None,
    api_url: str | None = None,
    transform_client: ClientTransform | None = None,
    max_response_bytes: byte_size.Input | None = None,
) -> Effect[Service, Never, HttpClient]:
    """A client over the ``HttpClient`` service. A response body larger
    than ``max_response_bytes`` (256 MiB) fails the call."""
    limit = P.response_limit(max_response_bytes)

    def prepare(request: http_request.HttpClientRequest) -> http_request.HttpClientRequest:
        request = request.prepend_url(or_default(api_url, DEFAULT_API_URL))
        if api_key is not None:
            request = request.bearer_token(redacted_value(api_key))
        return request.accept_json()

    def build(base: HttpClientService[HttpClientError]) -> Service:
        mapped = base.map_request(prepare).filter_status_ok()
        http_client = mapped if transform_client is None else transform_client(mapped)
        limited = P.limit_responses(http_client, limit)

        def execute[T](
            request: http_request.HttpClientRequest,
            decode: Callable[[object], Effect[T, Any]],
            method: str,
        ) -> Effect[T, AiError]:
            sent: Effect[Any, Any] = (
                P.resolve_client(TypeSafeConfig, limited)
                .flat_map(lambda client: client.execute(request))
                .flat_map(lambda response: response.json.flat_map(decode))
            )
            return sent.catch_all(Errors.mapper(method)).pipe(_redacted)

        def system_one(payload: W.SystemOneRequest) -> Effect[W.SystemOneResponse, AiError]:
            request = http_request.post("/systemone")
            if _uses_images(payload):
                request = request.set_header("TypeSafe-Danger-Zone-Images", "true")
            request = request.body_json_unsafe(payload)
            return execute(request, _decode_system_one, "systemOne")

        def list_models() -> Effect[W.ListModelsResponse, AiError]:
            return execute(http_request.get("/models"), _decode_models, "listModels")

        return Service(http_client, system_one, list_models)

    return HttpClient().map(build).pipe(_redacted)


def layer(
    *,
    api_key: Redacted[str] | None = None,
    api_url: str | None = None,
    transform_client: ClientTransform | None = None,
    max_response_bytes: byte_size.Input | None = None,
) -> L.Layer[TypeSafeClient, Never, HttpClient]:
    """``TypeSafeClient`` from these options (see ``make``)."""
    return L.effect(
        TypeSafeClient,
        make(
            api_key=api_key,
            api_url=api_url,
            transform_client=transform_client,
            max_response_bytes=max_response_bytes,
        ),
    )


def layer_config(
    *,
    api_key: Config[Redacted[str]] | Config[Redacted[str] | None] | None = None,
    api_url: Config[str] | None = None,
    transform_client: ClientTransform | None = None,
    max_response_bytes: byte_size.Input | None = None,
) -> L.Layer[TypeSafeClient, ConfigError, HttpClient]:
    """``TypeSafeClient`` with its options read from ``Config``; the key is
    ``TYPESAFE_API_KEY`` by default."""
    key: Config[Redacted[str]] | Config[Redacted[str] | None] = api_key or C.redacted(
        "TYPESAFE_API_KEY"
    )
    built: Effect[Service, ConfigError, HttpClient] = key.flat_map(
        lambda found: P.optional_config(api_url).flat_map(
            lambda url: make(
                api_key=found,
                api_url=url,
                transform_client=transform_client,
                max_response_bytes=max_response_bytes,
            )
        )
    )
    return L.effect(TypeSafeClient, built)


__all__ = ["DEFAULT_API_URL", "Service", "TypeSafeClient", "layer", "layer_config", "make"]
