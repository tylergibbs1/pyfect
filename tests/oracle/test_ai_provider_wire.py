"""Provider wire JSON read as Effect's generated schemas read it (QA
ai-workflow PROV-1, PROV-2, PROV-3): a whole float (``1.0``) is an
integer to ``Schema.Int``, embeddings are ``Schema.Finite``, and an
Anthropic content block or delta of a type Effect does not know fails the
response. Expected outcomes are Effect 4.0.6's under Node."""

from __future__ import annotations

# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false
from typing import Any

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.ai import ai_error as E
from pyfect.ai import embedding_model as em
from pyfect.ai import language_model as lm
from pyfect.ai import response as R
from pyfect.ai.anthropic import client as aclient
from pyfect.ai.anthropic import language_model as alm
from pyfect.ai.openai_compat import client as oclient
from pyfect.ai.openai_compat import embedding_model as oem
from pyfect.ai.openai_compat import language_model as olm
from pyfect.redacted import make as redact

from ._ai_http import MockHttp, mock_json, mock_sse, text_response


def _openai(effect: Any, mock: MockHttp) -> Any:
    return (
        effect.pipe(fx.provide(olm.model("m").layer))
        .pipe(fx.provide(oclient.layer(api_key=redact("sk"))))
        .pipe(fx.provide(mock.layer))
    )


def _anthropic(effect: Any, mock: MockHttp) -> Any:
    return (
        effect.pipe(fx.provide(alm.model("claude-sonnet-4-5").layer))
        .pipe(fx.provide(aclient.layer(api_key=redact("sk"))))
        .pipe(fx.provide(mock.layer))
    )


def _chunk(content: str, **fields: object) -> dict[str, object]:
    choice: dict[str, object] = {"index": 0, "delta": {"content": content}, "finish_reason": None}
    chunk: dict[str, object] = {
        "id": "c",
        "object": "chat.completion.chunk",
        "model": "m",
        "created": 1,
        "choices": [choice],
    }
    return {**chunk, **fields}


@testing.effect
def test_openai_chunks_with_whole_float_integers_are_read():
    usage = {"prompt_tokens": 5.0, "completion_tokens": 3, "total_tokens": 8}
    events: list[object] = [
        _chunk("Hello "),
        _chunk("world", created=1.0),
        _chunk("!", usage=usage),
        "[DONE]",
    ]
    parts = yield from _openai(lm.stream_text("x").run_collect(), mock_sse(events))
    text = "".join(p.delta for p in parts if isinstance(p, R.TextDeltaPart))
    assert text == "Hello world!"
    [finish] = [p for p in parts if isinstance(p, R.FinishPart)]
    assert finish.usage.input_tokens.total == 5


@testing.effect
def test_openai_completion_with_a_whole_float_created_is_read():
    body = {
        "id": "c",
        "object": "chat.completion",
        "model": "m",
        "created": 1.0,
        "choices": [
            {"index": 0, "finish_reason": "stop", "message": {"role": "assistant", "content": "hi"}}
        ],
        "usage": {"prompt_tokens": 5.0, "completion_tokens": 1, "total_tokens": 6},
    }
    response = yield from _openai(lm.generate_text("x"), mock_json(body))
    assert response.text == "hi"


@pytest.mark.parametrize("value", ["1e400", "-1e999"])
@testing.effect
def test_openai_embeddings_overflowing_to_infinity_are_invalid(value: str):
    """``JSON.parse`` reads these as infinities, which ``Schema.Finite``
    rejects."""
    body = (
        f'{{"data":[{{"index":0,"embedding":[{value}]}}],"model":"e",'
        '"usage":{"prompt_tokens":1,"total_tokens":1}}'
    )
    mock = MockHttp(
        lambda request: fx.succeed(text_response(request, body, content_type="application/json"))
    )
    error = yield from (
        em.EmbeddingModel()
        .flat_map(lambda model: model.embed_many(["a"]))
        .flip()
        .pipe(fx.provide(oem.layer(model="e")))
        .pipe(fx.provide(oclient.layer(api_key=redact("sk"))))
        .pipe(fx.provide(mock.layer))
    )
    assert isinstance(error.reason, E.InvalidResponseError)


def _anthropic_events(block: dict[str, object], delta: dict[str, object]) -> list[object]:
    message = {
        "id": "m",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-4-5",
        "content": [],
        "stop_reason": None,
        "stop_sequence": None,
        "usage": {"input_tokens": 3, "output_tokens": 1},
    }
    return [
        {"type": "message_start", "message": message},
        {"type": "content_block_start", "index": 0, "content_block": block},
        {"type": "content_block_delta", "index": 0, "delta": delta},
        {"type": "content_block_stop", "index": 0},
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn", "stop_sequence": None},
            "usage": {"output_tokens": 2},
        },
        {"type": "message_stop"},
    ]


ANTHROPIC_CASES = [
    ({"type": "future_block", "x": 1}, {"type": "text_delta", "text": "hi"}),
    ({"type": "text", "text": ""}, {"type": "future_delta", "x": 1}),
]


@pytest.mark.parametrize(("block", "delta"), ANTHROPIC_CASES, ids=["block", "delta"])
@testing.effect
def test_anthropic_unknown_stream_block_or_delta_fails(
    block: dict[str, object], delta: dict[str, object]
):
    error = yield from _anthropic(
        lm.stream_text("x").run_collect().flip(), mock_sse(_anthropic_events(block, delta))
    )
    assert isinstance(error.reason, E.InvalidResponseError)


@testing.effect
def test_anthropic_unknown_message_block_fails():
    body = {
        "id": "m",
        "type": "message",
        "role": "assistant",
        "model": "claude-sonnet-4-5",
        "content": [{"type": "future_block"}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {"input_tokens": 3, "output_tokens": 1},
    }
    error = yield from _anthropic(lm.generate_text("x").flip(), mock_json(body))
    assert isinstance(error.reason, E.InvalidResponseError)


@testing.effect
def test_anthropic_compaction_delta_is_known():
    """Effect's stream reads ``BetaContentBlockDeltaEvent``, whose delta union
    includes ``compaction_delta``: the stream is not an invalid response."""
    events = _anthropic_events(
        {"type": "compaction", "content": None}, {"type": "compaction_delta", "content": "c"}
    )
    parts = yield from _anthropic(lm.stream_text("x").run_collect(), mock_sse(events))
    assert parts[-1].type == "finish"
