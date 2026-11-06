"""The generated OpenAI client as a service (Effect's
``OpenAiClientGenerated``): a method per operation of the whole API, with the
same URL, credentials and per-call ``OpenAiConfig`` transform as ``client``::

    openai = yield from OpenAiClientGenerated()
    assistants = yield from openai.list_assistants(params={"limit": 20})

Where ``client`` has the calls the models use and fails with ``AiError``, an
operation here fails as ``generated.client`` says: with the
``HttpClientError``, the ``SchemaError`` or the ``OpenAiClientError`` of a
documented status. A status outside the documented ones is an
``HttpClientError``; there is no response size limit.
"""

from __future__ import annotations

from typing import Never

import pyfect as fx
from pyfect import layer as L
from pyfect._core import Effect
from pyfect.ai import _provider as P
from pyfect.ai.openai._errors import OPENAI
from pyfect.ai.openai._requests import prepare_requests
from pyfect.ai.openai.config import ClientTransform, OpenAiConfig
from pyfect.ai.openai.generated import client as generated_client
from pyfect.config import Config, ConfigError
from pyfect.context import Tag
from pyfect.http.client import HttpClient, HttpClientService
from pyfect.http.error import HttpClientError
from pyfect.redacted import Redacted

Service = generated_client.OpenAiClient
OpenAiClientError = generated_client.OpenAiClientError


class OpenAiClientGenerated(Tag[Service], key="@effect/ai-openai/OpenAiClientGenerated"):
    """The generated OpenAI client."""


def _resolve(
    client: HttpClientService[HttpClientError],
) -> Effect[HttpClientService[HttpClientError]]:
    return P.resolve_client(OpenAiConfig, client)


def make(
    *,
    api_key: Redacted[str] | None = None,
    api_url: str | None = None,
    organization_id: Redacted[str] | None = None,
    project_id: Redacted[str] | None = None,
    transform_client: ClientTransform | None = None,
) -> Effect[Service, Never, HttpClient]:
    """A client over the ``HttpClient`` service. ``transform_client``
    changes the underlying client, before a provided ``OpenAiConfig``'s
    transform."""
    prepare = prepare_requests(api_key, api_url, organization_id, project_id)

    def build(base: HttpClientService[HttpClientError]) -> Service:
        mapped = base.map_request(prepare)
        http_client = mapped if transform_client is None else transform_client(mapped)
        return generated_client.make(http_client, transform_client=_resolve)

    made: Effect[Service, Never, HttpClient] = HttpClient().map(build)
    return made.pipe(P.with_redacted_headers(OPENAI.secret_headers))


def layer(
    *,
    api_key: Redacted[str] | None = None,
    api_url: str | None = None,
    organization_id: Redacted[str] | None = None,
    project_id: Redacted[str] | None = None,
    transform_client: ClientTransform | None = None,
) -> L.Layer[OpenAiClientGenerated, Never, HttpClient]:
    """``OpenAiClientGenerated`` from these options (see ``make``)."""
    return L.effect(
        OpenAiClientGenerated,
        make(
            api_key=api_key,
            api_url=api_url,
            organization_id=organization_id,
            project_id=project_id,
            transform_client=transform_client,
        ),
    )


def layer_config(
    *,
    api_key: Config[Redacted[str]] | Config[Redacted[str] | None] | None = None,
    api_url: Config[str] | None = None,
    organization_id: Config[Redacted[str]] | Config[Redacted[str] | None] | None = None,
    project_id: Config[Redacted[str]] | Config[Redacted[str] | None] | None = None,
    transform_client: ClientTransform | None = None,
) -> L.Layer[OpenAiClientGenerated, ConfigError, HttpClient]:
    """``OpenAiClientGenerated`` with the given options read from ``Config``."""
    built: Effect[Service, ConfigError, HttpClient] = fx.all(
        P.optional_config(api_key),
        P.optional_config(api_url),
        P.optional_config(organization_id),
        P.optional_config(project_id),
    ).flat_map(
        lambda values: make(
            api_key=values[0],
            api_url=values[1],
            organization_id=values[2],
            project_id=values[3],
            transform_client=transform_client,
        )
    )
    return L.effect(OpenAiClientGenerated, built)


__all__ = [
    "OpenAiClientError",
    "OpenAiClientGenerated",
    "Service",
    "layer",
    "layer_config",
    "make",
]
