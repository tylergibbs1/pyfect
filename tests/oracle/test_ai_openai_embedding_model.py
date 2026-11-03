"""Ports of Effect's ``packages/ai/openai/test/OpenAiEmbeddingModel.test.ts``.
Each docstring is the Effect test title. Responses are recorded JSON
answered by a mocked ``HttpClient``."""

from __future__ import annotations

# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false, reportUnknownLambdaType=false
from typing import Any

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.ai import ai_error as E
from pyfect.ai import embedding_model as em
from pyfect.ai.openai import client
from pyfect.ai.openai import embedding_model as oem
from pyfect.http.request import HttpClientRequest
from pyfect.redacted import make as redact

from ._ai_http import MockHttp, body_json, json_response, mock_json


def _provided(effect: fx.Effect[Any, Any, Any], mock: MockHttp, **layer: Any) -> Any:
    return (
        effect.pipe(fx.provide(oem.layer(**layer)))
        .pipe(fx.provide(client.layer(api_key=redact("sk-test-key"))))
        .pipe(fx.provide(mock.layer))
    )


def _noop(_: object) -> fx.Effect[Any, Any]:
    return fx.die(RuntimeError("noop"))


def _embeddings(data: list[dict[str, Any]], model: str = "text-embedding-3-small") -> MockHttp:
    tokens = len(data)
    return mock_json(
        {
            "data": [{**entry, "object": "embedding"} for entry in data],
            "model": model,
            "object": "list",
            "usage": {"prompt_tokens": tokens, "total_tokens": tokens},
        }
    )


@testing.effect
def test_dimensions():
    """model provides dimensions service"""
    noop = client.Service(
        None,  # pyright: ignore[reportArgumentType]
        _noop,
        _noop,
        _noop,
        _noop,
    )
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
            "data": [
                {"index": 1, "embedding": [20, 21], "object": "embedding"},
                {"index": 0, "embedding": [10, 11], "object": "embedding"},
            ],
            "model": "text-embedding-3-small",
            "object": "list",
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
    mock = _embeddings([{"index": 0, "embedding": [1, 2, 3]}], "override-model")
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
def test_batches_by_override():
    """concurrent embed calls batch by their withConfigOverride"""
    requests: list[list[str]] = []

    def respond(request: HttpClientRequest) -> Any:
        body = body_json(request)
        requests.append(body["input"])
        return fx.succeed(
            json_response(
                request,
                {
                    "data": [
                        {"index": i, "embedding": [1] * body["dimensions"], "object": "embedding"}
                        for i in range(len(body["input"]))
                    ],
                    "model": body["model"],
                    "object": "list",
                    "usage": {"prompt_tokens": 1, "total_tokens": 1},
                },
            )
        )

    def embed(model: em.Service, text: str, dimensions: int) -> Any:
        return model.embed(text).pipe(oem.with_config_override({"dimensions": dimensions}))

    responses = yield from _provided(
        em.EmbeddingModel().flat_map(
            lambda model: fx.all(
                embed(model, "a", 2),
                embed(model, "b", 3),
                embed(model, "c", 2),
                concurrency="unbounded",
            )
        ),
        MockHttp(respond),
        model="text-embedding-3-small",
    )
    assert [r.vector for r in responses] == [(1, 1), (1, 1, 1), (1, 1)]
    assert requests == [["a", "c"], ["b"]]


@pytest.mark.parametrize(
    ("inputs", "data"),
    [
        (["a", "b"], [{"index": 0, "embedding": [1]}, {"index": 0, "embedding": [2]}]),
        (["a", "b"], [{"index": 0, "embedding": [1]}, {"index": 2, "embedding": [2]}]),
        (["a", "b"], [{"index": 0, "embedding": [1]}]),
        (["a"], [{"index": 0, "embedding": "AQID"}]),
    ],
    ids=[
        "fails with InvalidOutputError when provider returns duplicate indices",
        "fails with InvalidOutputError when provider returns out-of-range indices",
        "fails with InvalidOutputError when provider returns wrong embedding count",
        "fails with InvalidOutputError when provider returns base64 embeddings",
    ],
)
@testing.effect
def test_invalid_output(inputs: list[str], data: list[dict[str, Any]]):
    """fails with InvalidOutputError when provider returns duplicate indices, out-of-range
    indices, wrong embedding count, base64 embeddings"""
    error = yield from _provided(
        em.EmbeddingModel().flat_map(lambda model: model.embed_many(inputs).flip()),
        _embeddings(data),
        model="text-embedding-3-small",
    )
    assert isinstance(error, E.AiError)
    assert isinstance(error.reason, E.InvalidOutputError)
