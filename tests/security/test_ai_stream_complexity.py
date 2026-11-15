"""(pyfect) Streamed deltas from a provider endpoint are folded in time linear in their number.

The endpoint is a peer: a compatible server or proxy can send millions of tiny deltas within
the response size limit. Folding them with ``+=`` on an attribute, or parsing everything
received so far after each one, costs quadratic time on the fiber's thread (#34, #36, #37).
"""

from __future__ import annotations

# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false
import json
from typing import Any, TypedDict, cast

from _growth import Work, assert_near_linear
from oracle._ai_http import MockHttp, sse_response

import pyfect as fx
from pyfect import schema as S
from pyfect import stream
from pyfect.ai import language_model as lm
from pyfect.ai import prompt as Pr
from pyfect.ai import response as R
from pyfect.ai import tool as T
from pyfect.ai import toolkit as K
from pyfect.ai.openai import client as openai_client
from pyfect.ai.openai import language_model as openai_model
from pyfect.ai.openai import tool as openai_tool
from pyfect.ai.openrouter import client as openrouter_client
from pyfect.ai.openrouter import language_model as openrouter_model
from pyfect.http import request as http_request
from pyfect.http import response as http_response
from pyfect.layer import succeed as layer_succeed
from pyfect.redacted import make as redact


def test_text_deltas_fold_into_a_prompt_in_linear_time() -> None:
    """#37: ``Chat`` folds a streamed response into its history with ``from_response_parts``."""

    def make(n: int) -> Work:
        parts: list[Any] = [
            R.TextStartPart(id="t"),
            *(R.TextDeltaPart(id="t", delta="x") for _ in range(n)),
            R.TextEndPart(id="t"),
        ]
        return lambda: Pr.from_response_parts(parts)

    assert_near_linear(make, 1000)
    folded = Pr.from_response_parts(
        [
            R.TextStartPart(id="t"),
            R.TextDeltaPart(id="t", delta="a"),
            R.TextDeltaPart(id="t", delta="b"),
        ]
    )
    assert folded == Pr.from_messages([Pr.AssistantMessage(content=(Pr.TextPart(text="ab"),))])


def _openai_response(**overrides: Any) -> dict[str, Any]:
    return {
        "id": "resp_1",
        "object": "response",
        "created_at": 1,
        "model": "gpt-4o-mini",
        "status": "completed",
        "output": [],
        "metadata": None,
        "temperature": None,
        "top_p": None,
        "tools": [],
        "tool_choice": "auto",
        "error": None,
        "incomplete_details": None,
        "instructions": None,
        "parallel_tool_calls": False,
        **overrides,
    }


def _code_interpreter_events(deltas: int) -> list[dict[str, Any]]:
    item = {
        "type": "code_interpreter_call",
        "id": "ci_1",
        "code": None,
        "container_id": "c",
        "outputs": None,
        "status": "in_progress",
    }
    delta = {"type": "response.code_interpreter_call_code.delta", "item_id": "ci_1"}
    return [
        {"type": "response.created", "sequence_number": 1, "response": _openai_response()},
        {
            "type": "response.output_item.added",
            "sequence_number": 2,
            "output_index": 0,
            "item": item,
        },
        *(
            {**delta, "sequence_number": 3 + i, "output_index": 0, "delta": "x"}
            for i in range(deltas)
        ),
        {
            "type": "response.code_interpreter_call_code.done",
            "sequence_number": deltas + 3,
            "item_id": "ci_1",
            "output_index": 0,
            "code": "x" * deltas,
        },
        {
            "type": "response.completed",
            "sequence_number": deltas + 4,
            "response": _openai_response(),
        },
    ]


def _openai_stub(events: list[dict[str, Any]]) -> Any:
    response = http_response.make(
        http_request.get("https://api.openai.com/v1/responses"),
        "",
        headers={"content-type": "text/event-stream"},
    )

    def unexpected(_: object) -> Any:
        return fx.die(RuntimeError("unexpected call"))

    service = openai_client.Service(
        http_client=None,  # pyright: ignore[reportArgumentType]
        create_response=unexpected,
        create_response_stream=lambda _: fx.succeed((response, stream.from_iterable(events))),
        create_embedding=unexpected,
        create_decisions=unexpected,
    )
    return layer_succeed(openai_client.OpenAiClient, service)


_CODE = K.make(openai_tool.CodeInterpreter(container={"type": "auto"}))


def test_openai_code_interpreter_code_is_folded_in_linear_time() -> None:
    """#34: the code of a code interpreter call arrives as deltas."""

    def run(n: int) -> list[Any]:
        program = (
            lm.stream_text(prompt="x", toolkit=_CODE, disable_tool_call_resolution=True)
            .run_collect()
            .pipe(fx.provide(openai_model.model("gpt-4o-mini").layer))
            .pipe(fx.provide(_openai_stub(_code_interpreter_events(n))))
        )
        return fx.run_blocking(program)

    calls = [p for p in run(3) if isinstance(p, R.ToolCallPart)]
    assert [call.params["code"] for call in calls] == ["xxx"]
    assert_near_linear(lambda n: lambda: run(n), 1000)


class _Args(TypedDict):
    a: str


_KIT = K.make(T.make("t", parameters=S.Struct(_Args)))


def _openrouter_chunk(delta: dict[str, Any], **extra: Any) -> dict[str, Any]:
    return {
        "id": "gen",
        "created": 1,
        "model": "m",
        "object": "chat.completion.chunk",
        "choices": [{"index": 0, "delta": delta, **extra}],
    }


def _openrouter_events(deltas: int, delta: str) -> list[object]:
    start = {
        "index": 0,
        "type": "function",
        "id": "c",
        "function": {"name": "t", "arguments": '{"a":"'},
    }
    more = {"index": 0, "function": {"arguments": delta}}
    return [
        _openrouter_chunk({"tool_calls": [start]}),
        *(_openrouter_chunk({"tool_calls": [more]}) for _ in range(deltas)),
        _openrouter_chunk({"tool_calls": [{"index": 0, "function": {"arguments": '"}'}}]}),
        _openrouter_chunk({}, finish_reason="tool_calls"),
        "[DONE]",
    ]


def _openrouter_calls(events: list[object]) -> list[R.ToolCallPart[Any, Any]]:
    http = MockHttp(lambda request: fx.succeed(sse_response(request, events)))
    program = (
        lm.stream_text(prompt="x", toolkit=_KIT, disable_tool_call_resolution=True)
        .run_collect()
        .pipe(fx.provide(openrouter_model.layer(model="m")))
        .pipe(fx.provide(openrouter_client.layer(api_key=redact("k"))))
        .pipe(fx.provide(http.layer))
    )
    parts: list[Any] = fx.run_blocking(cast("Any", program))
    return [p for p in parts if isinstance(p, R.ToolCallPart)]


def test_openrouter_tool_arguments_are_parsed_in_linear_time() -> None:
    """#36: each delta of a tool call's arguments is not a reason to parse them all again,
    also when every delta closes a bracket inside a string."""
    for delta in ("x", "}"):
        calls = _openrouter_calls(_openrouter_events(3, delta))
        assert [call.params for call in calls] == [{"a": delta * 3}]
        assert_near_linear(
            lambda n, d=delta: lambda: _openrouter_calls(_openrouter_events(n, d)), 500
        )


def test_openrouter_tool_arguments_emit_as_soon_as_they_parse() -> None:
    """As in Effect, the call is emitted at the first delta after which the text parses,
    escaped quotes and brackets inside strings included."""
    arguments = json.dumps({"a": 'x"}{[\\'})
    pieces = [arguments[i : i + 2] for i in range(0, len(arguments), 2)]
    start = {"index": 0, "type": "function", "id": "c", "function": {"name": "t", "arguments": ""}}
    events: list[object] = [
        _openrouter_chunk({"tool_calls": [start]}),
        *(
            _openrouter_chunk({"tool_calls": [{"index": 0, "function": {"arguments": piece}}]})
            for piece in pieces
        ),
        _openrouter_chunk({}, finish_reason="tool_calls"),
        "[DONE]",
    ]
    assert [call.params for call in _openrouter_calls(events)] == [json.loads(arguments)]
