"""Ports of Effect's ``packages/ai/openai-compat/test/OpenAiEmbeddingModel.test.ts``.
Each docstring is the Effect test title. Responses are recorded JSON
answered by a mocked ``HttpClient``."""

from __future__ import annotations

# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false, reportUnknownLambdaType=false
from typing import Any

import pyfect as fx
from pyfect import testing
from pyfect.ai import ai_error as E
from pyfect.ai import embedding_model as em
from pyfect.ai.openai_compat import client
from pyfect.ai.openai_compat import embedding_model as oem
from pyfect.redacted import make as redact

from ._ai_http import MockHttp, mock_json


def _provided(effect: fx.Effect[Any, Any, Any], mock: MockHttp, **layer: Any) -> Any:
    return (
        effect.pipe(fx.provide(oem.layer(**layer)))
        .pipe(fx.provide(client.layer(api_key=redact("sk-test-key"))))
        .pipe(fx.provide(mock.layer))
    )


def _noop(_: object) -> fx.Effect[Any, Any]:
    return fx.die(RuntimeError("noop"))


@testing.effect
def test_dimensions():
    """model provides dimensions service"""
    noop = client.Service(None, _noop, _noop, _noop)  # pyright: ignore[reportArgumentType]
    dimensions = (
        yield from em.Dimensions()
        .pipe(fx.provide(oem.model("text-embedding-3-small", dimensions=1536).layer))
        .pipe(fx.provide_service(client.OpenAiClient, noop))
    )
    assert dimensions == 1536


@testing.effect
def test_reorders_by_index():
    """reorders embeddings by provider index"""
    mock = mock_json(
        {
            "data": [{"index": 1, "embedding": [20, 21]}, {"index": 0, "embedding": [10, 11]}],
            "model": "text-embedding-3-small",
            "usage": {"prompt_tokens": 7, "total_tokens": 7},
        }
    )
    response = yield from _provided(
        em.EmbeddingModel().flat_map(lambda model: model.embed_many(["first", "second"])),
        mock,
        model="text-embedding-3-small",
    )
    assert [e.vector for e in response.embeddings] == [(10, 11), (20, 21)]
    assert response.usage.input_tokens == 7
    body = mock.bodies[0]
    assert body["model"] == "text-embedding-3-small"
    assert body["input"] == ["first", "second"]


@testing.effect
def test_config_precedence():
    """merges config and applies withConfigOverride precedence"""
    mock = mock_json({"data": [{"index": 0, "embedding": [1, 2, 3]}], "model": "override-model"})
    yield from _provided(
        em.EmbeddingModel()
        .flat_map(lambda model: model.embed("hello"))
        .pipe(
            oem.with_config_override(
                {"model": "override-model", "dimensions": 1024, "user": "request-user"}
            )
        ),
        mock,
        model="base-model",
        config={"dimensions": 256, "user": "provider-user"},
    )
    body = mock.bodies[0]
    assert body["model"] == "override-model"
    assert body["dimensions"] == 1024
    assert body["user"] == "request-user"
    assert body["input"] == ["hello"]


@testing.effect
def test_duplicate_indices():
    """fails with InvalidOutputError when provider returns duplicate indices"""
    mock = mock_json(
        {
            "data": [{"index": 0, "embedding": [1]}, {"index": 0, "embedding": [2]}],
            "model": "text-embedding-3-small",
            "usage": {"prompt_tokens": 2, "total_tokens": 2},
        }
    )
    error = yield from _provided(
        em.EmbeddingModel().flat_map(lambda model: model.embed_many(["a", "b"]).flip()),
        mock,
        model="text-embedding-3-small",
    )
    assert isinstance(error, E.AiError)
    assert isinstance(error.reason, E.InvalidOutputError)


@testing.effect
def test_non_vector_payload():
    """fails with InvalidOutputError when provider returns non-vector embedding payload"""
    mock = mock_json(
        {
            "data": [{"index": 0, "embedding": "AQID"}],
            "model": "text-embedding-3-small",
            "usage": {"prompt_tokens": 1, "total_tokens": 1},
        }
    )
    error = yield from _provided(
        em.EmbeddingModel().flat_map(lambda model: model.embed("a").flip()),
        mock,
        model="text-embedding-3-small",
    )
    assert isinstance(error, E.AiError)
    assert isinstance(error.reason, E.InvalidOutputError)
