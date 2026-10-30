"""Turning text into vectors (Effect's ``EmbeddingModel``).

``make(embed_many=...)`` builds the service from a provider's batch call.
``embed`` goes through a ``RequestResolver``, so concurrent ``embed`` calls
become one provider call (grouped by ``batch_key`` of the caller's
context); ``embed_many`` calls the provider directly.
"""

from __future__ import annotations

from collections.abc import Callable, Hashable, Sequence
from dataclasses import dataclass, field
from typing import Any

import pyfect as fx
from pyfect import schema as S
from pyfect._core import Effect
from pyfect._wire_codec import key, wire_codec
from pyfect.ai import ai_error as E
from pyfect.batching import Entry, Request, RequestResolver
from pyfect.batching import request as _request
from pyfect.context import Context, Tag


class Dimensions(Tag[int], key="effect/ai/EmbeddingModel/Dimensions"):
    """The size of the current model's vectors."""


@dataclass(frozen=True)
class EmbeddingUsage:
    input_tokens: float | None = None


@dataclass(frozen=True)
class EmbedResponse:
    vector: tuple[float, ...]


@dataclass(frozen=True)
class EmbedManyResponse:
    embeddings: tuple[EmbedResponse, ...]
    usage: EmbeddingUsage = field(default_factory=EmbeddingUsage)


EMBEDDING_USAGE = wire_codec(
    EmbeddingUsage,
    [key("inputTokens", "input_tokens", S.Finite, optional=True)],
    identifier="effect/ai/EmbeddingModel/EmbeddingUsage",
)
EMBED_RESPONSE = wire_codec(
    EmbedResponse,
    [key("vector", "vector", S.Array(S.Finite))],
    identifier="effect/ai/EmbeddingModel/EmbedResponse",
)
EMBED_MANY_RESPONSE = wire_codec(
    EmbedManyResponse,
    [
        key("embeddings", "embeddings", S.Array(EMBED_RESPONSE)),
        key("usage", "usage", EMBEDDING_USAGE),
    ],
    identifier="effect/ai/EmbeddingModel/EmbedManyResponse",
)


@dataclass(frozen=True)
class ProviderOptions:
    inputs: tuple[str, ...]


@dataclass(frozen=True)
class ProviderResponse:
    """A provider's vectors, one per input, in order."""

    results: Sequence[Sequence[float]]
    input_tokens: float | None = None


type EmbedMany = Callable[[ProviderOptions], Effect[ProviderResponse, E.AiError]]


@dataclass(frozen=True)
class EmbeddingRequest(Request[EmbedResponse, E.AiError]):
    input: str


@dataclass(frozen=True)
class Service:
    resolver: RequestResolver[EmbeddingRequest, E.AiError]
    _embed_many: EmbedMany

    def embed(self, input: str) -> Effect[EmbedResponse, E.AiError]:
        return _request(EmbeddingRequest(input), self.resolver).with_span("EmbeddingModel.embed")

    def embed_many(self, inputs: Sequence[str]) -> Effect[EmbedManyResponse, E.AiError]:
        inputs = tuple(inputs)
        if not inputs:
            return fx.succeed(EmbedManyResponse(())).with_span("EmbeddingModel.embedMany")
        return (
            fx.suspend(lambda: self._embed_many(ProviderOptions(inputs)))
            .flat_map(
                lambda response: _vectors(len(inputs), response).map(
                    lambda embeddings: EmbedManyResponse(
                        embeddings, EmbeddingUsage(response.input_tokens)
                    )
                )
            )
            .with_span("EmbeddingModel.embedMany")
        )


class EmbeddingModel(Tag[Service], key="effect/ai/EmbeddingModel"):
    """The current embedding model."""


def _vectors(
    expected: int, response: ProviderResponse
) -> Effect[tuple[EmbedResponse, ...], E.AiError]:
    if len(response.results) != expected:
        return fx.fail(
            E.make(
                module="EmbeddingModel",
                method="embedMany",
                reason=E.InvalidOutputError(
                    description=f"Provider returned {len(response.results)} embeddings "
                    f"but expected {expected}"
                ),
            )
        )
    return fx.succeed(tuple(EmbedResponse(tuple(v)) for v in response.results))


def make(
    *, embed_many: EmbedMany, batch_key: Callable[[Context], Hashable] | None = None
) -> Effect[Service]:
    """An embedding model from a provider's batch call."""

    def resolve(entries: Sequence[Entry[EmbeddingRequest]], _: object) -> Effect[None, E.AiError]:
        options = ProviderOptions(tuple(entry.request.input for entry in entries))

        def complete(embeddings: tuple[EmbedResponse, ...]) -> None:
            for entry, embedding in zip(entries, embeddings, strict=True):
                entry.complete_unsafe(fx.Success(embedding))

        return (
            fx.suspend(lambda: embed_many(options))
            .flat_map(lambda response: _vectors(len(entries), response))
            .map(complete)
        )

    def group(entry: Entry[EmbeddingRequest]) -> Hashable:
        return None if batch_key is None else batch_key(entry.context)

    def build() -> Service:
        resolver: Any = RequestResolver[EmbeddingRequest, Any].make_grouped(
            key=group, resolver=resolve
        )
        return Service(resolver.with_span("EmbeddingModel.resolver"), embed_many)

    return fx.sync(build)
