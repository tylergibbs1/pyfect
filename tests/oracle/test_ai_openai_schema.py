"""Ports of Effect's ``packages/ai/openai/test/OpenAiSchema.test.ts``. Each
docstring is the Effect test title (with its ``describe``). The decoders
are the client's (``_schema``) and the generated schemas; SSE bodies go
through ``OpenAiClient.create_response_stream`` over a mocked
``HttpClient``."""

from __future__ import annotations

# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false, reportUnknownLambdaType=false
import json
from typing import Any

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import stream as St
from pyfect import testing
from pyfect.ai import language_model as lm
from pyfect.ai import response as R
from pyfect.ai.openai import _schema as W
from pyfect.ai.openai import client
from pyfect.ai.openai import generated as G
from pyfect.ai.openai import language_model as olm
from pyfect.http import request as http_request
from pyfect.http import response as http_response
from pyfect.layer import succeed as layer_succeed
from pyfect.redacted import make as redact

from ._ai_http import mock_raw_sse


def make_response(**overrides: Any) -> dict[str, Any]:
    return {
        "id": "resp_123",
        "object": "response",
        "model": "gpt-4o-mini",
        "status": "completed",
        "created_at": 1,
        "output": [],
        **overrides,
    }


def _decode(schema: Any, value: object) -> Any:
    return S.decode_unknown_sync(schema)(value)


def plain(value: Any) -> Any:
    if isinstance(value, tuple | list):
        return [plain(v) for v in value]
    if isinstance(value, dict):
        return {k: plain(v) for k, v in value.items()}
    return value


def _sse_events(events: list[dict[str, Any]]) -> fx.Effect[list[Any], Any, Any]:
    body = "".join(f"data: {json.dumps(event)}\n\n" for event in events)
    return (
        client.OpenAiClient()
        .flat_map(
            lambda c: c.create_response_stream({"model": "gpt-4o-mini", "input": "test"}).flat_map(
                lambda sent: sent[1].run_collect()
            )
        )
        .pipe(fx.provide(client.layer(api_key=redact("sk-test-key"))))
        .pipe(fx.provide(mock_raw_sse(body).layer))
    )


# web search sources ---------------------------------------------------------------------


def test_api_sources_in_history():
    """web search sources / preserves API sources in response history"""
    item = {
        "type": "web_search_call",
        "id": "ws_123",
        "status": "completed",
        "action": {"type": "search", "sources": [{"type": "api", "name": "oai-weather"}]},
    }
    assert plain(_decode(G.InputItem, item)) == item


@pytest.mark.parametrize(
    "source",
    [
        {"type": "url"},
        {"type": "api"},
        {"type": "api", "name": None},
        {"type": "unknown", "name": "oai-weather"},
    ],
)
def test_malformed_search_sources(source: dict[str, Any]):
    """web search sources / rejects malformed search sources: %j"""
    item = {
        "type": "web_search_call",
        "id": "ws_123",
        "status": "completed",
        "action": {"type": "search", "sources": [source]},
    }
    with pytest.raises(S.SchemaError):
        _decode(G.WebSearchToolCall, item)
    with pytest.raises(S.SchemaError):
        _decode(G.InputItem, item)


# requests and responses -----------------------------------------------------------------


def test_max_reasoning_effort():
    """accepts max reasoning effort"""
    decoded = _decode(G.CreateResponse, {"reasoning": {"effort": "max"}})
    assert decoded["reasoning"]["effort"] == "max"


def test_safety_and_cache_retention():
    """accepts safety and prompt cache retention request options"""
    options = {"safety_identifier": "user-hash-123", "prompt_cache_retention": "24h"}
    assert _decode(G.CreateResponse, options) == options


@testing.effect
def test_representative_response():
    """decodes a representative response payload"""
    citation = {
        "type": "url_citation",
        "url": "https://example.com",
        "start_index": 0,
        "end_index": 5,
        "title": "example",
    }
    decoded = yield from W.decode_response(
        make_response(
            output=[
                {
                    "id": "msg_1",
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [
                        {"type": "output_text", "text": "hello", "annotations": [citation]},
                        {"type": "refusal", "refusal": "cannot comply"},
                    ],
                },
                {
                    "id": "fc_1",
                    "type": "function_call",
                    "call_id": "call_1",
                    "name": "lookup",
                    "arguments": "{}",
                    "status": "completed",
                },
                {
                    "id": "reasoning_1",
                    "type": "reasoning",
                    "summary": [{"type": "summary_text", "text": "thinking"}],
                },
            ],
            usage={"input_tokens": 10, "output_tokens": 20, "total_tokens": 30},
        )
    )
    assert decoded["id"] == "resp_123"
    assert len(decoded["output"]) == 3
    assert decoded["output"][0]["type"] == "message"
    assert decoded["output"][0]["content"][0]["type"] == "output_text"


@testing.effect
def test_image_generation_statuses():
    """decodes image generation lifecycle statuses"""
    for status in ["generating", "failed"]:
        item = {"id": "image_1", "type": "image_generation_call", "status": status, "result": None}
        decoded = yield from W.decode_response(make_response(output=[item]))
        assert decoded["output"][0]["type"] == "image_generation_call"
        assert decoded["output"][0]["status"] == status


# stream events --------------------------------------------------------------------------


def _at(type_: str, sequence: int, **fields: Any) -> dict[str, Any]:
    return {"type": type_, "sequence_number": sequence, **fields}


_APPLY_PATCH_ITEM = {
    "id": "ap_1",
    "type": "apply_patch_call",
    "call_id": "call_ap",
    "operation": {"type": "update_file", "path": "README.md", "diff": "@@"},
}
_SUMMARY = {"type": "summary_text", "text": "thinking"}
_REQUIRED_EVENTS = [
    _at("response.created", 1, response=make_response(status="in_progress")),
    _at("response.completed", 2, response=make_response()),
    _at("response.incomplete", 3, response=make_response(status="incomplete")),
    _at("response.failed", 4, response=make_response(status="failed")),
    _at("response.output_item.added", 5, output_index=0, item=_APPLY_PATCH_ITEM),
    _at("response.output_item.done", 6, output_index=0, item=_APPLY_PATCH_ITEM),
    _at(
        "response.output_text.delta",
        7,
        item_id="msg_1",
        output_index=0,
        content_index=0,
        delta="hel",
    ),
    _at(
        "response.output_text.annotation.added",
        8,
        item_id="msg_1",
        output_index=0,
        content_index=0,
        annotation_index=0,
        annotation={"type": "file_path", "file_id": "file_1", "index": 0},
    ),
    _at(
        "response.reasoning_summary_part.added",
        9,
        item_id="reasoning_1",
        output_index=1,
        summary_index=0,
        part=_SUMMARY,
    ),
    _at(
        "response.reasoning_summary_part.done",
        10,
        item_id="reasoning_1",
        output_index=1,
        summary_index=0,
        part=_SUMMARY,
    ),
    _at(
        "response.reasoning_summary_text.delta",
        11,
        item_id="reasoning_1",
        output_index=1,
        summary_index=0,
        delta="...",
    ),
    _at("response.function_call_arguments.delta", 12, item_id="fc_1", output_index=2, delta="{"),
    _at(
        "response.function_call_arguments.done", 13, item_id="fc_1", output_index=2, arguments="{}"
    ),
    _at(
        "response.code_interpreter_call_code.delta",
        14,
        item_id="code_1",
        output_index=3,
        delta="print",
    ),
    _at(
        "response.code_interpreter_call_code.done",
        15,
        item_id="code_1",
        output_index=3,
        code="print('ok')",
    ),
    _at(
        "response.apply_patch_call_operation_diff.delta",
        16,
        item_id="ap_1",
        output_index=4,
        delta="@@",
    ),
    _at(
        "response.apply_patch_call_operation_diff.done",
        17,
        item_id="ap_1",
        output_index=4,
        delta="@@",
    ),
    _at(
        "response.image_generation_call.partial_image",
        18,
        item_id="img_1",
        output_index=5,
        partial_image_b64="AQID",
    ),
]


@testing.effect
def test_required_stream_events():
    """decodes required stream events"""
    for event in _REQUIRED_EVENTS:
        decoded = yield from W.decode_event(event)
        assert decoded["type"] == event["type"]


@testing.effect
def test_keepalive_and_unknown_events():
    """keeps keepalive and unknown events tolerant in SSE decoding"""
    events = yield from _sse_events(
        [
            _at("response.created", 1, response=make_response(status="in_progress")),
            _at("keepalive", 2, heartbeat=True),
            _at("provider.future_event", 3, nested={"ok": True}),
            _at("response.completed", 4, response=make_response()),
        ]
    )
    assert len(events) == 4
    assert events[1]["type"] == "keepalive"
    assert events[2]["type"] == "provider.future_event"
    assert events[1]["sequence_number"] == 2


@testing.effect
def test_malformed_known_events():
    """does not silently decode malformed known events as unknown"""
    malformed = yield from W.decode_event(_at("response.completed", 1)).flip()
    assert isinstance(malformed, S.SchemaError)


@testing.effect
def test_flat_and_nested_error_events():
    """decodes the error event whether the payload is flat or nested under `error`"""
    flat = {"type": "error", "code": "ERR", "message": "boom", "param": None, "sequence_number": 1}
    assert (yield from W.decode_event(flat)) == flat
    nested = yield from W.decode_event(
        {
            "type": "error",
            "error": {
                "type": "insufficient_quota",
                "code": "credit_balance_exhausted",
                "message": "You have no credits remaining.",
                "param": None,
            },
            "sequence_number": 2,
        }
    )
    assert nested == {
        "type": "error",
        "code": "credit_balance_exhausted",
        "message": "You have no credits remaining.",
        "param": None,
        "sequence_number": 2,
    }
    with_status = yield from W.decode_event(
        {
            "type": "error",
            "error": {"code": "rate_limited", "message": "Too many requests.", "param": None},
            "sequence_number": 3,
            "status": 429,
        }
    )
    assert with_status == {
        "type": "error",
        "code": "rate_limited",
        "message": "Too many requests.",
        "param": None,
        "sequence_number": 3,
        "status": 429,
    }


@testing.effect
def test_error_events_missing_fields():
    """rejects error events missing spec-required fields"""
    for event in [
        {"type": "error"},
        {"type": "error", "error": {}, "sequence_number": 3},
        {"type": "error", "error": {"code": "x"}, "sequence_number": 3},
    ]:
        failure = yield from W.decode_event(event).flip()
        assert isinstance(failure, S.SchemaError)


@testing.effect
def test_nested_error_events_in_sse():
    """surfaces nested error events in SSE decoding instead of aborting the stream"""
    events = yield from _sse_events(
        [
            _at("response.created", 1, response=make_response(status="in_progress")),
            {
                "type": "error",
                "error": {
                    "type": "insufficient_quota",
                    "code": "credit_balance_exhausted",
                    "message": "You have no credits remaining.",
                    "param": None,
                },
                "sequence_number": 2,
            },
        ]
    )
    assert len(events) == 2
    assert events[1] == {
        "type": "error",
        "code": "credit_balance_exhausted",
        "message": "You have no credits remaining.",
        "param": None,
        "sequence_number": 2,
    }


def test_embedding_variants():
    """decodes embedding response variants (numeric + string/base64)"""

    def response(embedding: object) -> dict[str, Any]:
        return {
            "object": "list",
            "model": "text-embedding-3-small",
            "data": [{"object": "embedding", "index": 0, "embedding": embedding}],
            "usage": {"prompt_tokens": 2, "total_tokens": 2},
        }

    numeric = _decode(W.CREATE_EMBEDDING_RESPONSE, response([0.1, 0.2]))
    base64 = _decode(W.CREATE_EMBEDDING_RESPONSE, response("AQID"))
    assert numeric["data"][0]["embedding"][0] == 0.1
    assert base64["data"][0]["embedding"] == "AQID"


@testing.effect
def test_response_failed_error_payload():
    """exposes the response.failed error payload"""
    raw = http_response.make(http_request.get("https://api.openai.com/v1/responses"), "")
    failed = yield from W.decode_event(
        _at(
            "response.failed",
            1,
            response={
                "id": "resp_1",
                "object": "response",
                "created_at": 1,
                "model": "gpt-4o-mini",
                "status": "failed",
                "output": [],
                "error": {"code": "server_error", "message": "provider exploded"},
            },
        )
    )

    def unexpected(_: object) -> Any:
        return fx.die(RuntimeError("unexpected"))

    stub = client.Service(
        http_client=None,  # pyright: ignore[reportArgumentType]
        create_response=unexpected,
        create_response_stream=lambda _: fx.succeed((raw, St.from_iterable([failed]))),
        create_embedding=unexpected,
        create_decisions=unexpected,
    )
    parts = (
        yield from lm.stream_text(prompt="test")
        .run_collect()
        .pipe(fx.provide(olm.model("gpt-4o-mini").layer))
        .pipe(fx.provide(layer_succeed(client.OpenAiClient, stub)))
    )
    error = next(part for part in parts if isinstance(part, R.ErrorPart))
    assert plain(error.error) == {"code": "server_error", "message": "provider exploded"}
    finish = next(part for part in parts if isinstance(part, R.FinishPart))
    assert finish.reason == "error"
