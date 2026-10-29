"""Ports of Effect's ``test/ai/EmbeddingModel.test.ts``.

Each test's docstring is the Effect test title (with its ``describe``). A
provider response's ``usage.inputTokens`` is ``ProviderResponse``'s
``input_tokens``.
"""

from __future__ import annotations

# pyright: reportPrivateUsage=false
import json
from collections.abc import Callable

import pyfect as fx
from pyfect import layer as L
from pyfect import schema as S
from pyfect import testing
from pyfect.ai import ai_error as E
from pyfect.ai import embedding_model as em

type EmbedMany = Callable[[em.ProviderOptions], fx.Effect[em.ProviderResponse, E.AiError]]


def _layer(embed_many: EmbedMany) -> fx.Layer[em.EmbeddingModel]:
    return L.effect(em.EmbeddingModel, em.make(embed_many=embed_many))


@testing.effect
def test_usage_round_trip():
    """EmbeddingModel / round trips usage with undefined input tokens through JSON"""
    usage = em.EmbeddingUsage(input_tokens=None)
    encoded = yield from S.encode_effect(em.EMBEDDING_USAGE)(usage)
    data = json.loads(json.dumps(encoded))
    decoded = yield from S.decode_unknown_effect(em.EMBEDDING_USAGE)(data)
    assert data == {}
    assert decoded == em.EmbeddingUsage()


@testing.effect
def test_embed_returns_vector():
    """EmbeddingModel / embed returns a vector"""
    calls: list[tuple[str, ...]] = []

    def embed_many(options: em.ProviderOptions) -> fx.Effect[em.ProviderResponse, E.AiError]:
        def run() -> em.ProviderResponse:
            calls.append(options.inputs)
            return em.ProviderResponse([[1, 2, 3]], input_tokens=5)

        return fx.sync(run)

    model = yield from em.EmbeddingModel().pipe(fx.provide(_layer(embed_many)))
    response = yield from model.embed("hello")
    assert response.vector == (1, 2, 3)
    assert calls == [("hello",)]


@testing.effect
def test_embed_many_ordered_with_usage():
    """EmbeddingModel / embedMany returns ordered vectors with usage"""
    calls: list[tuple[str, ...]] = []

    def embed_many(options: em.ProviderOptions) -> fx.Effect[em.ProviderResponse, E.AiError]:
        calls.append(options.inputs)
        return fx.succeed(em.ProviderResponse([[1, 2], [3, 4]], input_tokens=9))

    model = yield from em.EmbeddingModel().pipe(fx.provide(_layer(embed_many)))
    response = yield from model.embed_many(["hello", "world"])
    assert [e.vector for e in response.embeddings] == [(1, 2), (3, 4)]
    assert response.usage.input_tokens == 9
    assert calls == [("hello", "world")]


@testing.effect
def test_concurrent_embeds_batched():
    """EmbeddingModel / concurrent embed calls are batched into one provider embedMany call"""
    batches: list[tuple[str, ...]] = []

    def embed_many(options: em.ProviderOptions) -> fx.Effect[em.ProviderResponse, E.AiError]:
        batches.append(options.inputs)
        return fx.succeed(em.ProviderResponse([[ord(i[0])] for i in options.inputs]))

    model = yield from em.EmbeddingModel().pipe(fx.provide(_layer(embed_many)))
    responses = yield from fx.for_each(["a", "b", "c"], model.embed, concurrency="unbounded")
    assert batches == [("a", "b", "c")]
    assert [r.vector for r in responses] == [(97,), (98,), (99,)]


_BOOM = E.make(
    module="EmbeddingModelTest", method="embedMany", reason=E.UnknownError(description="boom")
)


@testing.effect
def test_provider_error_propagates():
    """EmbeddingModel / provider AiError propagates through embed"""
    model = yield from em.EmbeddingModel().pipe(fx.provide(_layer(lambda _: fx.fail(_BOOM))))
    error = yield from model.embed("hello").flip()
    assert error is _BOOM


@testing.effect
def test_embed_missing_results():
    """EmbeddingModel / embed fails with InvalidOutputError when provider misses results"""
    layer = _layer(lambda _: fx.succeed(em.ProviderResponse([], input_tokens=0)))
    model = yield from em.EmbeddingModel().pipe(fx.provide(layer))
    error = yield from model.embed("hello").flip()
    assert error.reason._tag == "InvalidOutputError"


@testing.effect
def test_embed_many_missing_results():
    """EmbeddingModel / embedMany fails with InvalidOutputError when provider misses results"""
    layer = _layer(lambda _: fx.succeed(em.ProviderResponse([[1, 2, 3]], input_tokens=3)))
    model = yield from em.EmbeddingModel().pipe(fx.provide(layer))
    error = yield from model.embed_many(["hello", "world"]).flip()
    assert isinstance(error.reason, E.InvalidOutputError)
    assert error.reason.description == "Provider returned 1 embeddings but expected 2"


@testing.effect
def test_embed_many_empty_bypasses_provider():
    """EmbeddingModel / embedMany([]) bypasses provider"""
    calls: list[int] = []

    def embed_many(_: em.ProviderOptions) -> fx.Effect[em.ProviderResponse, E.AiError]:
        calls.append(1)
        return fx.die(AssertionError("provider should not be called"))

    model = yield from em.EmbeddingModel().pipe(fx.provide(_layer(embed_many)))
    response = yield from model.embed_many([])
    assert calls == []
    assert response.embeddings == ()
    assert response.usage.input_tokens is None
