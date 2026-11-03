"""OpenAI's Embeddings API as an ``EmbeddingModel`` (Effect's
``OpenAiEmbeddingModel``)::

    program.pipe(
        fx.provide(embedding_model.model("text-embedding-3-small", dimensions=1536).layer)
    )

Requests with the same ``Config`` and ``OpenAiConfig`` are batched into
one call.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, Never, TypedDict, cast

from pyfect import layer as L
from pyfect._core import Effect
from pyfect.ai import _provider as P
from pyfect.ai import embedding_model as em
from pyfect.ai import model as M
from pyfect.ai.ai_error import AiError
from pyfect.ai.openai.client import OpenAiClient
from pyfect.ai.openai.client import Service as ClientService
from pyfect.ai.openai.config import OpenAiConfig
from pyfect.ai.openai_compat.embedding_model import provider_response
from pyfect.context import Context, Tag

type Model = Literal["text-embedding-ada-002", "text-embedding-3-small", "text-embedding-3-large"]
"""Model names (any other string is accepted too)."""


class ConfigService(TypedDict, total=False):
    model: str
    encoding_format: Literal["float", "base64"]
    dimensions: int
    user: str


type ModelConfig = ConfigService | Mapping[str, Any]


class Config(Tag[ConfigService], key="@effect/ai-openai/OpenAiEmbeddingModel/Config"):
    """Per-request overrides of the model's options."""


def _batch_key(context: Context) -> Any:
    config = context.get_option(Config)
    client_config = context.get_option(OpenAiConfig)
    return (
        None if config is None else P.dumps(config.value),
        None if client_config is None else id(client_config.value),
    )


def make(
    *, model: Model | str, config: ModelConfig | None = None
) -> Effect[em.Service, Never, OpenAiClient]:
    """An ``EmbeddingModel`` for ``model``; a provided ``Config`` overrides
    ``config`` per request. Vectors come back in input order; a missing,
    duplicate or non-vector entry fails with ``InvalidOutputError``."""

    def build(client: ClientService) -> Effect[em.Service]:
        def embed_many(options: em.ProviderOptions) -> Effect[em.ProviderResponse, AiError]:
            return (
                P.current_config(Config, {"model": model}, config)
                .flat_map(
                    lambda cfg: client.create_embedding(
                        cast("Any", {**cfg, "input": list(options.inputs)})
                    )
                )
                .flat_map(
                    lambda response: provider_response(len(options.inputs), cast("Any", response))
                )
            )

        return em.make(embed_many=embed_many, batch_key=_batch_key)

    return OpenAiClient().flat_map(build)


def layer(
    *, model: Model | str, config: ModelConfig | None = None
) -> L.Layer[em.EmbeddingModel, Never, OpenAiClient]:
    return L.effect(em.EmbeddingModel, make(model=model, config=config))


def model(
    model: Model | str, *, dimensions: int, config: ModelConfig | None = None
) -> M.Model[em.EmbeddingModel | em.Dimensions, OpenAiClient]:
    """The model and its ``Dimensions`` as a ``Model`` (provider
    ``"openai"``); ``dimensions`` is sent with each request."""
    merged = {**(config or {}), "dimensions": dimensions}
    return M.make(
        "openai",
        model,
        L.merge(layer(model=model, config=merged), L.succeed(em.Dimensions, dimensions)),
    )


def with_config_override(overrides: ConfigService) -> P.WithConfigOverride[ConfigService]:
    """Run an effect with ``overrides`` merged over the current ``Config``.
    Use with ``.pipe``."""
    return P.WithConfigOverride(Config, overrides)


__all__ = [
    "Config",
    "ConfigService",
    "Model",
    "ModelConfig",
    "layer",
    "make",
    "model",
    "with_config_override",
]
