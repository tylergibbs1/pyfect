"""An ``EmbeddingModel`` over an OpenAI-compatible Embeddings API
(Effect's ``OpenAiEmbeddingModel`` in ``@effect/ai-openai-compat``)::

    program.pipe(fx.provide(embedding_model.model("text-embedding-3-small", dimensions=1536).layer))
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, Never, TypedDict

import pyfect as fx
from pyfect import layer as L
from pyfect._core import Effect
from pyfect.ai import _provider as P
from pyfect.ai import embedding_model as em
from pyfect.ai import model as M
from pyfect.ai.ai_error import AiError, InvalidOutputError
from pyfect.ai.openai_compat import _schema as W
from pyfect.ai.openai_compat.client import OpenAiClient
from pyfect.ai.openai_compat.client import Service as ClientService
from pyfect.ai.openai_compat.config import OpenAiConfig
from pyfect.context import Context, Tag


class ConfigService(TypedDict, total=False):
    model: str
    encoding_format: Literal["float", "base64"]
    dimensions: int
    user: str


type ModelConfig = ConfigService | Mapping[str, Any]


class Config(Tag[ConfigService], key="@effect/ai-openai-compat/OpenAiEmbeddingModel/Config"):
    """Per-request overrides of the model's options."""


def _invalid(description: str) -> Effect[Never, AiError]:
    return fx.fail(
        AiError(
            module="OpenAiEmbeddingModel",
            method="embedMany",
            reason=InvalidOutputError(description=description),
        )
    )


def provider_response(
    count: int, response: W.EmbeddingResponse
) -> Effect[em.ProviderResponse, AiError]:
    """The vectors in input order; a missing, duplicate, out-of-range or
    non-vector entry fails."""
    data = response["data"]
    if len(data) != count:
        return _invalid(f"Provider returned {len(data)} embeddings but expected {count}")
    results: list[list[float]] = [[] for _ in range(count)]
    seen: set[int] = set()
    for entry in data:
        index = entry["index"]
        if not 0 <= index < count:
            return _invalid(f"Provider returned invalid embedding index: {index}")
        if index in seen:
            return _invalid(f"Provider returned duplicate embedding index: {index}")
        vector = entry["embedding"]
        if isinstance(vector, str):
            return _invalid(f"Provider returned non-vector embedding at index {index}")
        seen.add(index)
        results[index] = list(vector)
    usage = response.get("usage")
    return fx.succeed(
        em.ProviderResponse(results, None if usage is None else usage["prompt_tokens"])
    )


def _batch_key(context: Context) -> Any:
    config = context.get_option(Config)
    client_config = context.get_option(OpenAiConfig)
    return (
        None if config is None else P.dumps(config.value),
        None if client_config is None else id(client_config.value),
    )


def make(
    *, model: str, config: ModelConfig | None = None
) -> Effect[em.Service, Never, OpenAiClient]:
    def build(client: ClientService) -> Effect[em.Service]:
        def embed_many(options: em.ProviderOptions) -> Effect[em.ProviderResponse, AiError]:
            return (
                P.current_config(Config, {"model": model}, config)
                .flat_map(
                    lambda cfg: client.create_embedding({**cfg, "input": list(options.inputs)})
                )
                .flat_map(lambda response: provider_response(len(options.inputs), response))
            )

        return em.make(embed_many=embed_many, batch_key=_batch_key)

    return OpenAiClient().flat_map(build)


def layer(
    *, model: str, config: ModelConfig | None = None
) -> L.Layer[em.EmbeddingModel, Never, OpenAiClient]:
    return L.effect(em.EmbeddingModel, make(model=model, config=config))


def model(
    model: str, *, dimensions: int, config: ModelConfig | None = None
) -> M.Model[em.EmbeddingModel | em.Dimensions, OpenAiClient]:
    """The model and its ``Dimensions`` as a ``Model`` (provider
    ``"openai"``)."""
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
    "ModelConfig",
    "layer",
    "make",
    "model",
    "provider_response",
    "with_config_override",
]
