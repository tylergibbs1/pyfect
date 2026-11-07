"""Ports of Effect's ``test/ai/LanguageModel.test.ts`` and
``test/ai/LanguageModelRepresentation.test.ts``.

Each test's docstring is the Effect test title (with its ``describe``). A
provider's canned parts come from ``_ai.with_language_model``; options are
keyword arguments (``tool_choice={"one_of": [...]}``,
``disable_tool_call_resolution=True``).

Omitted:

- ``resolves the canonical top-level $ref for class schemas in
  defaultCodecTransformer``: pyfect's class schemas have no separate
  ``PersonEncoded`` definition.
"""

from __future__ import annotations

# pyright: reportPrivateUsage=false
from collections.abc import Callable
from typing import Any, TypedDict

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.ai import ai_error as E
from pyfect.ai import language_model as lm
from pyfect.ai import prompt as P
from pyfect.ai import response as R
from pyfect.ai import response_id_tracker as tracker
from pyfect.ai import tool as T
from pyfect.ai import toolkit as K
from pyfect.json_schema import JsonSchema
from pyfect.stream import _constructors as streams
from pyfect.stream import _sources as stream_sources

from ._ai import Generate, StreamText, with_language_model


class MyParams(TypedDict):
    testParam: str


class MySuccess(TypedDict):
    testSuccess: str


class Count(TypedDict):
    count: float


MyTool = T.make("MyTool", parameters=S.Struct(MyParams), success=S.Struct(MySuccess))
TransformTool = T.make("TransformTool", parameters=S.FiniteFromString, success=S.Finite)
TransformToolkit = K.make(TransformTool)
TransformLayer = TransformToolkit.to_layer(
    TransformTool.handler(lambda value, _: fx.succeed(value * 2))
)

FINISH: lm.EncodedPart = {
    "type": "finish",
    "reason": "stop",
    "usage": {"inputTokens": {"uncached": 5, "total": 5}, "outputTokens": {"total": 5}},
}
_CALL: lm.EncodedPart = {
    "type": "tool-call",
    "id": "call",
    "name": "MyTool",
    "params": {"testParam": "test-param"},
}


def _counting_layer(toolkit: K.AnyToolkit, calls: list[int]) -> fx.Layer[Any]:
    return toolkit.to_layer(
        MyTool.handler(
            lambda _, __: fx.sync(lambda: calls.append(1)).as_(
                MySuccess(testSuccess="test-success")
            )
        )
    )


def _provided[A, E, R](
    eff: fx.Effect[A, E, R],
    *,
    generate_text: Generate | None = None,
    stream_text: StreamText | None = None,
) -> fx.Effect[A, Any, Any]:
    return eff.pipe(with_language_model(generate_text=generate_text, stream_text=stream_text))


def _is_result(part: object) -> bool:
    return isinstance(part, R.ToolResultSuccess | R.ToolResultFailure)


def _first_result(
    method: str, toolkit: K.AnyToolkit, disable: bool
) -> fx.Effect[R.AnyPart | None, Any, Any]:
    if method == "generateText":
        return lm.generate_text("hi", toolkit=toolkit, disable_tool_call_resolution=disable).map(
            lambda response: response.tool_results[0] if response.tool_results else None
        )
    return (
        lm.stream_text("hi", toolkit=toolkit, disable_tool_call_resolution=disable)
        .run_collect()
        .map(lambda parts: next((p for p in parts if _is_result(p)), None))
    )


@pytest.mark.parametrize(
    "method",
    [
        pytest.param(
            "generateText", id="generateText uses current tool schemas and handlers across requests"
        ),
        pytest.param(
            "streamText", id="streamText uses current tool schemas and handlers across requests"
        ),
    ],
)
@testing.effect
def test_uses_current_tool_schemas(method: str):
    """<method> uses current tool schemas and handlers across requests"""

    def run(tool: T.AnyTool, result: str, disable: bool = False) -> fx.Effect[Any, Any, Any]:
        toolkit = K.make(tool)
        success: dict[str, object] = {"testSuccess": result}
        layer = toolkit.to_layer(tool.handler(lambda _, __: fx.succeed(success)))
        return _first_result(method, toolkit, disable).pipe(fx.provide(layer))

    def body() -> Any:
        for result in ("first", "second"):
            tool_result = yield from run(MyTool, result)
            assert tool_result is not None
            assert tool_result.result == {"testSuccess": result}
        yield from run(MyTool, "unused", True)
        changed = MyTool.set_parameters(
            S.Struct(MyParams, testParam=S.String.check(S.is_pattern(r"^changed$")))
        )
        error = yield from run(changed, "unused", True).flip()
        assert error.reason._tag == "InvalidOutputError"
        assert error.is_retryable is True

    yield from _provided(fx.gen(body), generate_text=[_CALL], stream_text=[_CALL])


@testing.effect
def test_records_request_options_on_span():
    """generateText / records resolved request options on a client span"""
    seen: list[Any] = []

    def generate(options: lm.ProviderOptions) -> list[lm.EncodedPart]:
        seen.append(options.span)
        return []

    yield from _provided(lm.generate_text("hi"), generate_text=generate)
    (span,) = seen
    assert span.kind == "client"
    assert span.attributes["gen_ai.output.type"] == "text"
    assert span.attributes["effect.ai.tool_choice"] == "auto"
    assert span.attributes["effect.ai.concurrency"] == "unbounded"


@testing.effect
def test_json_encodes_object_tool_choices():
    """generateText / JSON-encodes object tool choices"""
    toolkit = K.make(MyTool)
    seen: list[object] = []

    def generate(options: lm.ProviderOptions) -> list[lm.EncodedPart]:
        assert options.span is not None
        seen.append(options.span.attributes["effect.ai.tool_choice"])
        return []

    yield from _provided(
        lm.generate_text("hi", toolkit=toolkit, tool_choice={"one_of": ["MyTool"]}).pipe(
            fx.provide(_counting_layer(toolkit, []))
        ),
        generate_text=generate,
    )
    assert seen == ['{"oneOf":["MyTool"]}']


@testing.effect
def test_no_resolution_after_incomplete_finish():
    """generateText / does not resolve tool calls after an incomplete finish"""
    toolkit = K.make(MyTool)
    calls: list[int] = []
    for reason in ("length", "content-filter", "error", "unknown", "other"):
        response = yield from _provided(
            lm.generate_text([], toolkit=toolkit).pipe(fx.provide(_counting_layer(toolkit, calls))),
            generate_text=[{**_CALL, "id": f"tool-{reason}"}, {**FINISH, "reason": reason}],
        )
        assert response.finish_reason == reason
        assert len(response.tool_calls) == 1
        (result,) = response.tool_results
        assert result.is_failure is True
        assert result.result == {
            "type": "execution-interrupted",
            "reason": "Tool call execution was interrupted because the response finished "
            f'with reason "{reason}"',
        }
    assert calls == []


@testing.effect
def test_validates_response_before_resolving():
    """generateText / validates the complete response before resolving tool calls"""
    toolkit = K.make(MyTool)
    calls: list[int] = []
    error = yield from _provided(
        lm.generate_text([], toolkit=toolkit).pipe(fx.provide(_counting_layer(toolkit, calls))),
        generate_text=[_CALL, {"type": "text", "text": 123}],
    ).flip()
    assert error.reason._tag == "InvalidOutputError"
    assert calls == []


@testing.effect
def test_missing_params_field():
    """generateText / fails cleanly for a tool call with a missing params field"""
    toolkit = K.make(MyTool)
    calls: list[int] = []
    error = yield from _provided(
        lm.generate_text([], toolkit=toolkit).pipe(fx.provide(_counting_layer(toolkit, calls))),
        generate_text=[{"type": "tool-call", "id": "tool-no-params", "name": "MyTool"}, FINISH],
    ).flip()
    assert error.reason._tag == "InvalidOutputError"
    assert calls == []


@testing.effect
def test_validates_encoded_params_when_disabled():
    """generateText / validates encoded tool parameters when tool call resolution is disabled"""
    error = yield from _provided(
        lm.generate_text([], toolkit=TransformToolkit, disable_tool_call_resolution=True).pipe(
            fx.provide(TransformLayer)
        ),
        generate_text=[
            {"type": "tool-call", "id": "t", "name": "TransformTool", "params": {"invalid": True}}
        ],
    ).flip()
    assert error.reason._tag == "InvalidOutputError"


_TRANSFORM_CALL: lm.EncodedPart = {
    "type": "tool-call",
    "id": "tool-transform",
    "name": "TransformTool",
    "params": "21",
}


@testing.effect
def test_preserves_encoded_params_when_disabled():
    """generateText / preserves encoded tool parameters when tool call resolution is disabled"""

    def body() -> Any:
        response = yield from lm.generate_text(
            [], toolkit=TransformToolkit, disable_tool_call_resolution=True
        )
        (call,) = response.tool_calls
        assert call.params == "21"
        kit = yield from TransformToolkit
        stream = yield from kit.handle(call.name, call.params)
        results = yield from stream.run_collect()
        assert results[0].result == 42

    yield from _provided(
        fx.gen(body).pipe(fx.provide(TransformLayer)), generate_text=[_TRANSFORM_CALL]
    )


@testing.effect
def test_preserves_encoded_params_when_enabled():
    """generateText / preserves encoded tool parameters when tool call resolution is enabled"""
    response = yield from _provided(
        lm.generate_text([], toolkit=TransformToolkit).pipe(fx.provide(TransformLayer)),
        generate_text=[_TRANSFORM_CALL],
    )
    assert response.tool_calls[0].params == "21"
    assert response.tool_results[0].result == 42
    assert response.tool_results[0].encoded_result == 42


@testing.effect
def test_validates_provider_executed_params():
    """generateText / validates provider-executed tool call parameters"""
    toolkit = K.make(MyTool)
    error = yield from _provided(
        lm.generate_text([], toolkit=toolkit).pipe(fx.provide(_counting_layer(toolkit, []))),
        generate_text=[{**_CALL, "params": {"testParam": 1}, "providerExecuted": True}],
    ).flip()
    assert error.reason._tag == "InvalidOutputError"


@testing.effect
def test_accepts_valid_provider_executed_calls():
    """generateText / accepts provider-executed tool calls with valid parameters"""
    toolkit = K.make(MyTool)
    calls: list[int] = []
    response = yield from _provided(
        lm.generate_text([], toolkit=toolkit).pipe(fx.provide(_counting_layer(toolkit, calls))),
        generate_text=[{**_CALL, "providerExecuted": True}],
    )
    assert len(response.tool_calls) == 1
    assert response.tool_results == []
    assert calls == []


@testing.effect
def test_stream_validates_encoded_params_when_disabled():
    """streamText / validates encoded tool parameters when tool call resolution is disabled"""
    error = yield from _provided(
        lm.stream_text([], toolkit=TransformToolkit, disable_tool_call_resolution=True)
        .run_collect()
        .pipe(fx.provide(TransformLayer)),
        stream_text=[
            {"type": "tool-call", "id": "t", "name": "TransformTool", "params": {"invalid": True}}
        ],
    ).flip()
    assert error.reason._tag == "InvalidOutputError"


@testing.effect
def test_stream_preserves_encoded_params_when_enabled():
    """streamText / preserves encoded tool parameters when tool call resolution is enabled"""
    parts = yield from _provided(
        lm.stream_text([], toolkit=TransformToolkit).run_collect().pipe(fx.provide(TransformLayer)),
        stream_text=[_TRANSFORM_CALL],
    )
    call = next(p for p in parts if isinstance(p, R.ToolCallPart))
    result = next(p for p in parts if isinstance(p, R.ToolResultSuccess))
    assert (call.params, result.result) == ("21", 42)


@testing.effect
def test_stream_invalid_params_in_return_mode():
    """streamText / emits a failed tool result and keeps streaming when tool params are invalid and failure mode is return"""  # noqa: E501

    class ReturnFailure(TypedDict):
        testFailure: str

    tool = T.make(
        "ReturnModeTool",
        failure_mode="return",
        parameters=S.Struct(MyParams),
        success=S.Struct(MySuccess),
        failure=S.Struct(ReturnFailure),
    )
    toolkit = K.make(tool)
    calls: list[int] = []
    layer = toolkit.to_layer(
        tool.handler(lambda _, __: fx.sync(lambda: calls.append(1)).as_(MySuccess(testSuccess="x")))
    )
    parts = yield from _provided(
        lm.stream_text([], toolkit=toolkit).run_collect().pipe(fx.provide(layer)),
        stream_text=[
            {
                "type": "tool-call",
                "id": "tool-invalid-params",
                "name": "ReturnModeTool",
                "params": {"testParam": 123},
            },
            FINISH,
        ],
    )
    results = [p for p in parts if _is_result(p)]
    assert len(results) == 1
    (result,) = results
    assert isinstance(result, R.ToolResultFailure)
    assert isinstance(result.result, E.AiError)
    assert result.result.reason._tag == "ToolParameterValidationError"
    assert any(p.type == "finish" for p in parts)
    assert calls == []


@testing.effect
def test_stream_invalid_params_in_error_mode():
    """streamText / fails the stream when tool params are invalid and failure mode is error"""
    toolkit = K.make(MyTool)
    calls: list[int] = []
    error = yield from _provided(
        lm.stream_text([], toolkit=toolkit)
        .run_drain()
        .pipe(fx.provide(_counting_layer(toolkit, calls))),
        stream_text=[
            {**_CALL, "id": "tool-invalid-params", "params": {"testParam": 123}},
            FINISH,
        ],
    ).flip()
    assert isinstance(error, E.AiError)
    assert error.reason._tag == "ToolParameterValidationError"
    assert calls == []


@testing.effect
def test_stream_finish_after_tool_results():
    """streamText / emits finish after resolved tool results"""
    toolkit = K.make(MyTool)
    layer = toolkit.to_layer(
        MyTool.handler(lambda _, __: fx.succeed(MySuccess(testSuccess="test-success")).delay(10))
    )
    parts: list[Any] = []
    first = fx.Latch()
    fiber = yield from _provided(
        lm.stream_text([], toolkit=toolkit)
        .run_for_each(lambda part: first.open().and_then(fx.sync(lambda: parts.append(part))))
        .pipe(fx.provide(layer)),
        stream_text=[{**_CALL, "id": "tool-finish-order"}, FINISH],
    ).fork_scoped()
    yield from first.wait()
    assert parts[0].type == "tool-call"
    assert not any(p.type == "finish" for p in parts)
    yield from testing.adjust(10)
    yield from fiber.join()
    assert [p.type for p in parts] == ["tool-call", "tool-result", "finish"]


@testing.effect
def test_stream_malformed_content():
    """streamText / does not execute tool handlers when response content is malformed"""
    toolkit = K.make(MyTool)
    calls: list[int] = []
    error = yield from _provided(
        lm.stream_text([], toolkit=toolkit)
        .run_collect()
        .pipe(fx.provide(_counting_layer(toolkit, calls))),
        stream_text=[_CALL, {"type": "text-delta", "id": "t", "delta": 1}],
    ).flip()
    assert error.reason._tag == "InvalidOutputError"
    assert calls == []


@testing.effect
def test_object_span_output_type():
    """generateObject / records json output type on the span"""
    seen: list[object] = []

    def generate(options: lm.ProviderOptions) -> list[lm.EncodedPart]:
        assert options.span is not None
        seen.append(options.span.attributes["gen_ai.output.type"])
        return [{"type": "text", "text": '{"count":1}'}]

    response = yield from _provided(
        lm.generate_object("hi", schema=S.Struct(Count)), generate_text=generate
    )
    assert seen == ["json"]
    assert response.value == {"count": 1}


@testing.effect
def test_structured_output_error_text():
    """generateObject / includes full generated text in StructuredOutputError"""
    error = yield from _provided(
        lm.generate_object([], schema=S.Struct(Count)),
        generate_text=[{"type": "text", "text": '{"count":"oops"}'}],
    ).flip()
    assert isinstance(error.reason, E.StructuredOutputError)
    assert error.reason.response_text == '{"count":"oops"}'


def _capture(seen: list[lm.ProviderOptions], parts: list[lm.EncodedPart]) -> Any:
    def generate(options: lm.ProviderOptions) -> list[lm.EncodedPart]:
        seen.append(options)
        return parts

    return generate


@testing.effect
def test_incremental_fields_generate_text():
    """provider options / initialize incremental fields as undefined in generateText"""
    seen: list[lm.ProviderOptions] = []
    yield from _provided(lm.generate_text([]), generate_text=_capture(seen, [FINISH]))
    assert (seen[0].previous_response_id, seen[0].incremental_prompt) == (None, None)


@testing.effect
def test_incremental_fields_generate_object():
    """provider options / initialize incremental fields as undefined in generateObject"""
    seen: list[lm.ProviderOptions] = []
    parts: list[lm.EncodedPart] = [{"type": "text", "text": '{"count":1}'}, FINISH]
    yield from _provided(
        lm.generate_object([], schema=S.Struct(Count)), generate_text=_capture(seen, parts)
    )
    assert (seen[0].previous_response_id, seen[0].incremental_prompt) == (None, None)


@testing.effect
def test_incremental_fields_stream_text():
    """provider options / initialize incremental fields as undefined in streamText"""
    seen: list[lm.ProviderOptions] = []
    yield from _provided(lm.stream_text([]).run_drain(), stream_text=_capture(seen, [FINISH]))
    assert (seen[0].previous_response_id, seen[0].incremental_prompt) == (None, None)


_FULL = P.make(
    [
        P.SystemMessage(content="system"),
        P.UserMessage(content=[P.TextPart(text="user")]),
        P.AssistantMessage(content=[P.TextPart(text="assistant")]),
        P.UserMessage(content=[P.TextPart(text="next")]),
    ]
)
_INCREMENTAL = P.make([P.UserMessage(content=[P.TextPart(text="next")])])


class _FixedTracker(tracker.Service):
    def prepare_unsafe(self, prompt: P.Prompt) -> tracker.PrepareResult | None:
        return tracker.PrepareResult("resp_prev", _INCREMENTAL)


_INVALID_REQUEST = E.make(
    module="LanguageModelTest",
    method="generateText",
    reason=E.InvalidRequestError(description="invalid previous response id"),
)


@testing.effect
def test_generate_text_falls_back_to_full_prompt():
    """provider options / falls back to full prompt in generateText when incremental request fails"""  # noqa: E501
    calls: list[lm.ProviderOptions] = []

    def generate(options: lm.ProviderOptions) -> fx.Effect[list[lm.EncodedPart], E.AiError]:
        calls.append(options)
        return fx.fail(_INVALID_REQUEST) if len(calls) == 1 else fx.succeed([FINISH])

    model = lm.make(generate_text=generate, stream_text=lambda _: streams.empty)
    yield from (
        lm.generate_text(_FULL)
        .pipe(fx.provide_service_effect(lm.LanguageModel, model))
        .pipe(fx.provide_service(tracker.ResponseIdTracker, _FixedTracker()))
    )
    assert len(calls) == 2
    assert calls[0].previous_response_id == "resp_prev"
    assert calls[0].incremental_prompt is _INCREMENTAL
    assert (calls[1].previous_response_id, calls[1].incremental_prompt) == (None, None)
    assert calls[1].prompt == _FULL


@testing.effect
def test_stream_text_falls_back_to_full_prompt():
    """provider options / falls back to full prompt in streamText when incremental request fails"""
    calls: list[lm.ProviderOptions] = []

    def stream(options: lm.ProviderOptions) -> Any:
        calls.append(options)
        return streams.fail(_INVALID_REQUEST) if len(calls) == 1 else streams.make(FINISH)

    model = lm.make(generate_text=lambda _: fx.succeed([]), stream_text=stream)
    yield from (
        lm.stream_text(_FULL)
        .run_drain()
        .pipe(fx.provide_service_effect(lm.LanguageModel, model))
        .pipe(fx.provide_service(tracker.ResponseIdTracker, _FixedTracker()))
    )
    assert len(calls) == 2
    assert calls[0].previous_response_id == "resp_prev"
    assert calls[1].incremental_prompt is None
    assert calls[1].prompt == _FULL


_METADATA: lm.EncodedPart = {"type": "response-metadata", "id": "resp_1"}


_TRACKED_INCREMENTAL = P.make([P.UserMessage(content=[P.TextPart(text="incremental")])])


class _RecordingTracker(tracker.Service):
    """Effect's test tracker: prepares ``resp_prev`` with an incremental
    prompt and records what it is asked."""

    def __init__(self) -> None:
        super().__init__()
        self.prepared: list[P.Prompt] = []
        self.marked: list[tuple[object, str]] = []

    def prepare_unsafe(self, prompt: P.Prompt) -> tracker.PrepareResult | None:
        self.prepared.append(prompt)
        return tracker.PrepareResult("resp_prev", _TRACKED_INCREMENTAL)

    def mark_parts(self, parts: Any, response_id: str) -> None:
        self.marked.append((parts, response_id))


_TRACKED_METADATA: lm.EncodedPart = {"type": "response-metadata", "id": "resp_next"}


def _assert_tracked(recording: _RecordingTracker, seen: list[lm.ProviderOptions]) -> None:
    (options,) = seen
    (prepared,) = recording.prepared
    assert prepared is options.prompt
    assert options.previous_response_id == "resp_prev"
    assert options.incremental_prompt is _TRACKED_INCREMENTAL
    ((parts, response_id),) = recording.marked
    assert parts is options.prompt.content
    assert response_id == "resp_next"


def _tracked(eff: Any, recording: _RecordingTracker, **kwargs: Any) -> Any:
    return _provided(eff, **kwargs).pipe(fx.provide_service(tracker.ResponseIdTracker, recording))


_HELLO = [P.UserMessage(content=[P.TextPart(text="hello")])]


@testing.effect
def test_tracker_generate_text_without_toolkit():
    """provider options / uses tracker prepareUnsafe and markParts in generateText without toolkit"""  # noqa: E501
    recording, seen = _RecordingTracker(), list[lm.ProviderOptions]()
    yield from _tracked(
        lm.generate_text(_HELLO),
        recording,
        generate_text=_capture(seen, [_TRACKED_METADATA, FINISH]),
    )
    _assert_tracked(recording, seen)


@testing.effect
def test_tracker_generate_text_with_empty_toolkit():
    """provider options / uses tracker prepareUnsafe and markParts in generateText with empty toolkit"""  # noqa: E501
    recording, seen = _RecordingTracker(), list[lm.ProviderOptions]()
    yield from _tracked(
        lm.generate_text(_HELLO, toolkit=K.empty).pipe(fx.provide(K.empty.to_layer())),
        recording,
        generate_text=_capture(seen, [_TRACKED_METADATA, FINISH]),
    )
    _assert_tracked(recording, seen)


@testing.effect
def test_tracker_stream_text_without_toolkit():
    """provider options / uses tracker prepareUnsafe and markParts in streamText without toolkit"""
    recording, seen = _RecordingTracker(), list[lm.ProviderOptions]()
    yield from _tracked(
        lm.stream_text(_HELLO).run_drain(),
        recording,
        stream_text=_capture(seen, [_TRACKED_METADATA, FINISH]),
    )
    _assert_tracked(recording, seen)


@testing.effect
def test_tracker_stream_text_with_empty_toolkit():
    """provider options / uses tracker prepareUnsafe and markParts in streamText with empty toolkit"""  # noqa: E501
    recording, seen = _RecordingTracker(), list[lm.ProviderOptions]()
    yield from _tracked(
        lm.stream_text(_HELLO, toolkit=K.empty).run_drain().pipe(fx.provide(K.empty.to_layer())),
        recording,
        stream_text=_capture(seen, [_TRACKED_METADATA, FINISH]),
    )
    _assert_tracked(recording, seen)


def test_representation_projects_encoded_side():
    """LanguageModel representation v2 / projects the encoded side before JSON Schema generation"""
    _, json_schema = lm.default_codec_transformer(S.FiniteFromString)
    assert json_schema["type"] == "string"


def _min_length(_: object) -> JsonSchema:
    return {"minLength": 2}


def test_representation_custom_compiler_annotations():
    """LanguageModel representation v2 / uses custom JSON Schema compiler annotations in the default transformer"""  # noqa: E501
    schema = S.String.check(
        S.make_filter(
            lambda value: len(value) >= 2,
            representation={"id": "test/ai/language-model/minTwoCharacters", "payload": None},
            to_json_schema=_min_length,
        )
    )
    _, json_schema = lm.default_codec_transformer(schema)
    assert json_schema == {"type": "string", "minLength": 2}


# --- streamText tool-call timing (Effect's queue + FiberSet resolution) -------------------


def _queue_stream() -> fx.Effect[fx.Queue[lm.EncodedPart, Any]]:
    return fx.Queue[lm.EncodedPart, Any].unbounded()


def _blocking_layer(started: fx.Latch, interrupted: fx.Latch) -> fx.Layer[Any]:
    def handler(_: Any, __: Any) -> fx.Effect[MySuccess]:
        body = started.open().and_then(fx.never).on_interrupt(interrupted.open())
        return body.as_(MySuccess(testSuccess="test-success"))

    return K.make(MyTool).to_layer(MyTool.handler(handler))


def _collecting(
    parts: list[Any], on_part: Callable[[Any], fx.Effect[object]] | None = None
) -> Callable[[Any], fx.Effect[object]]:
    def each(part: Any) -> fx.Effect[object]:
        parts.append(part)
        return on_part(part) if on_part is not None else fx.void

    return each


@testing.effect
def test_stream_interrupts_handlers_on_incomplete_finish():
    """streamText / interrupts in-flight tool handlers on an incomplete finish"""
    observed, started, interrupted = fx.Latch(), fx.Latch(), fx.Latch()
    provider = yield from _queue_stream()
    parts: list[Any] = []
    fiber = yield from _provided(
        lm.stream_text([], toolkit=K.make(MyTool))
        .run_for_each(
            _collecting(parts, lambda p: observed.open() if p.type == "tool-call" else fx.void)
        )
        .pipe(fx.provide(_blocking_layer(started, interrupted))),
        stream_text=lambda _: stream_sources.from_queue(provider),
    ).fork_scoped()
    yield from provider.offer({**_CALL, "id": "tool-interrupted"})
    yield from observed.wait()
    yield from provider.offer({"type": "text-delta", "id": "text-1", "delta": "more"})
    yield from started.wait()
    yield from provider.offer({**FINISH, "reason": "length"})
    yield from provider.end()
    yield from fiber.join()
    yield from interrupted.wait()
    assert [p.type for p in parts] == ["tool-call", "text-delta", "tool-result", "finish"]
    assert parts[3].reason == "length"
    result = parts[2]
    assert (result.id, result.is_failure) == ("tool-interrupted", True)
    assert result.result == {
        "type": "execution-interrupted",
        "reason": 'Tool call execution was interrupted because the response finished with reason "length"',  # noqa: E501
    }


@testing.effect
def test_stream_no_handlers_on_incomplete_finish_same_chunk():
    """streamText / does not start tool handlers when an incomplete finish arrives in the same chunk"""  # noqa: E501
    toolkit = K.make(MyTool)
    calls: list[int] = []
    for reason in ("length", "content-filter", "error", "unknown", "other"):
        parts = yield from _provided(
            lm.stream_text([], toolkit=toolkit)
            .run_collect()
            .pipe(fx.provide(_counting_layer(toolkit, calls))),
            stream_text=[{**_CALL, "id": f"tool-{reason}"}, {**FINISH, "reason": reason}],
        )
        assert [p.type for p in parts] == ["tool-call", "tool-result", "finish"]
        result = parts[1]
        assert isinstance(result, R.ToolResultFailure)
        assert result.result == {
            "type": "execution-interrupted",
            "reason": "Tool call execution was interrupted because the response finished "
            f'with reason "{reason}"',
        }
    assert calls == []


@testing.effect
def test_stream_no_handlers_on_incomplete_finish_next_chunk():
    """streamText / does not start tool handlers when an incomplete finish arrives in the next chunk"""  # noqa: E501
    toolkit = K.make(MyTool)
    calls: list[int] = []
    provider = yield from _queue_stream()
    fiber = yield from _provided(
        lm.stream_text([], toolkit=toolkit)
        .run_collect()
        .pipe(fx.provide(_counting_layer(toolkit, calls))),
        stream_text=lambda _: stream_sources.from_queue(provider),
    ).fork_scoped()
    yield from provider.offer({**_CALL, "id": "tool-next-chunk"})
    yield from provider.offer({**FINISH, "reason": "length"})
    yield from provider.end()
    parts = yield from fiber.join()
    assert calls == []
    assert [p.type for p in parts] == ["tool-call", "tool-result", "finish"]
    result = parts[1]
    assert isinstance(result, R.ToolResultFailure)
    assert result.result == {
        "type": "execution-interrupted",
        "reason": 'Tool call execution was interrupted because the response finished with reason "length"',  # noqa: E501
    }


@testing.effect
def test_stream_keeps_results_before_incomplete_finish():
    """streamText / keeps results of handlers that completed before an incomplete finish"""
    toolkit = K.make(MyTool)
    observed, result_seen = fx.Latch(), fx.Latch()
    provider = yield from _queue_stream()
    parts: list[Any] = []

    def on_part(part: Any) -> fx.Effect[object]:
        if part.type == "tool-call":
            return observed.open()
        return result_seen.open() if part.type == "tool-result" else fx.void

    fiber = yield from _provided(
        lm.stream_text([], toolkit=toolkit)
        .run_for_each(_collecting(parts, on_part))
        .pipe(fx.provide(_counting_layer(toolkit, []))),
        stream_text=lambda _: stream_sources.from_queue(provider),
    ).fork_scoped()
    yield from provider.offer({**_CALL, "id": "tool-completed"})
    yield from observed.wait()
    yield from provider.offer({"type": "text-delta", "id": "text-1", "delta": "more"})
    yield from result_seen.wait()
    yield from provider.offer({**FINISH, "reason": "length"})
    yield from provider.end()
    yield from fiber.join()
    assert [p.type for p in parts] == ["tool-call", "text-delta", "tool-result", "finish"]
    assert parts[2].is_failure is False
    assert parts[2].result == {"testSuccess": "test-success"}


@testing.effect
def test_stream_preserves_encoded_params_when_disabled():
    """streamText / preserves encoded tool parameters when tool call resolution is disabled"""

    def body() -> Any:
        parts = yield from lm.stream_text(
            [], toolkit=TransformToolkit, disable_tool_call_resolution=True
        ).run_collect()
        call = next(p for p in parts if isinstance(p, R.ToolCallPart))
        assert call.params == "21"
        kit = yield from TransformToolkit
        stream = yield from kit.handle(call.name, call.params)
        results = yield from stream.run_collect()
        assert results[0].result == 42

    yield from _provided(
        fx.gen(body).pipe(fx.provide(TransformLayer)), stream_text=[_TRANSFORM_CALL]
    )


@testing.effect
def test_stream_validates_provider_executed_params():
    """streamText / validates provider-executed tool call parameters"""
    toolkit = K.make(MyTool)
    calls: list[int] = []
    error = yield from _provided(
        lm.stream_text([], toolkit=toolkit)
        .run_drain()
        .pipe(fx.provide(_counting_layer(toolkit, calls))),
        stream_text=[
            {
                **_CALL,
                "id": "tool-provider-executed",
                "params": {"testParam": 123},
                "providerExecuted": True,
            },
            FINISH,
        ],
    ).flip()
    assert isinstance(error, E.AiError)
    assert error.reason._tag == "InvalidOutputError"
    assert calls == []


@testing.effect
def test_stream_runs_handlers_past_tool_call():
    """streamText / executes tool handlers once the stream moves past the tool call"""
    toolkit = K.make(MyTool)
    observed, called = fx.Latch(), fx.Latch()
    provider = yield from _queue_stream()
    parts: list[Any] = []
    calls: list[int] = []
    layer = toolkit.to_layer(
        MyTool.handler(
            lambda _, __: (
                fx.sync(lambda: calls.append(1))
                .and_then(called.open())
                .as_(MySuccess(testSuccess="test-success"))
            )
        )
    )
    fiber = yield from _provided(
        lm.stream_text([], toolkit=toolkit)
        .run_for_each(
            _collecting(parts, lambda p: observed.open() if p.type == "tool-call" else fx.void)
        )
        .pipe(fx.provide(layer)),
        stream_text=lambda _: stream_sources.from_queue(provider),
    ).fork_scoped()
    yield from provider.offer({**_CALL, "id": "tool-abc123"})
    yield from observed.wait()
    yield from provider.offer({"type": "text-delta", "id": "text-1", "delta": "more"})
    yield from called.wait()
    assert calls == [1]
    yield from provider.offer(FINISH)
    yield from provider.end()
    yield from fiber.join()
    assert [p.type for p in parts] == ["tool-call", "text-delta", "tool-result", "finish"]


@testing.effect
def test_stream_interrupts_handlers_when_provider_fails():
    """streamText / interrupts in-flight tool handlers when the provider stream fails"""
    observed, started, interrupted = fx.Latch(), fx.Latch(), fx.Latch()
    provider = yield from _queue_stream()
    provider_error = E.make(
        module="LanguageModelTest",
        method="streamText",
        reason=E.InvalidRequestError(description="provider stream failed"),
    )
    fiber = yield from _provided(
        lm.stream_text([], toolkit=K.make(MyTool))
        .run_for_each(lambda p: observed.open() if p.type == "tool-call" else fx.void)
        .pipe(fx.provide(_blocking_layer(started, interrupted))),
        stream_text=lambda _: stream_sources.from_queue(provider).concat(
            streams.fail(provider_error)
        ),
    ).fork_scoped()
    yield from provider.offer({**_CALL, "id": "tool-before-failure"})
    yield from observed.wait()
    yield from provider.offer({"type": "text-delta", "id": "text-1", "delta": "more"})
    yield from started.wait()
    yield from provider.end()
    error = yield from fiber.join().flip()
    assert error is provider_error
    yield from interrupted.wait()


def _tracking_layer(
    toolkit: K.AnyToolkit,
    active: list[int],
    peak: list[int],
    release: fx.Latch,
    on_start: Callable[[int], fx.Effect[object]],
) -> fx.Layer[Any]:
    def handler(_: Any, __: Any) -> fx.Effect[MySuccess]:
        def start() -> fx.Effect[object]:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
            return on_start(active[0])

        def done() -> None:
            active[0] -= 1

        body = fx.suspend(start).and_then(release.wait())
        return body.ensuring(fx.sync(done)).as_(MySuccess(testSuccess="test-success"))

    return toolkit.to_layer(MyTool.handler(handler))


def _three_calls() -> list[lm.EncodedPart]:
    return [{**_CALL, "id": f"tool-{i}", "params": {"testParam": f"test-{i}"}} for i in (1, 2, 3)]


@testing.effect
def test_stream_sequential_handlers():
    """streamText / runs tool handlers sequentially with concurrency: 1"""
    toolkit = K.make(MyTool)
    started, release = fx.Latch(), fx.Latch()
    active, peak = [0], [0]
    layer = _tracking_layer(toolkit, active, peak, release, lambda _: started.open())
    fiber = yield from _provided(
        lm.stream_text([], toolkit=toolkit, concurrency=1).run_drain().pipe(fx.provide(layer)),
        stream_text=_three_calls(),
    ).fork_scoped()
    yield from started.wait()
    assert (active[0], peak[0]) == (1, 1)
    yield from release.open()
    yield from fiber.join()
    assert (active[0], peak[0]) == (0, 1)


@testing.effect
def test_stream_bounded_handler_overlap():
    """streamText / allows tool handler overlap up to a bounded concurrency"""
    toolkit = K.make(MyTool)
    two_started, release = fx.Latch(), fx.Latch()
    active, peak = [0], [0]
    layer = _tracking_layer(
        toolkit, active, peak, release, lambda n: two_started.open() if n == 2 else fx.void
    )
    fiber = yield from _provided(
        lm.stream_text([], toolkit=toolkit, concurrency=2).run_drain().pipe(fx.provide(layer)),
        stream_text=_three_calls(),
    ).fork_scoped()
    yield from two_started.wait()
    assert (active[0], peak[0]) == (2, 2)
    yield from release.open()
    yield from fiber.join()
    assert (active[0], peak[0]) == (0, 2)


@testing.effect
def test_stream_tool_call_ids_to_concurrent_handlers():
    """streamText / provides tool call IDs to concurrent identical tool handlers"""
    toolkit = K.make(MyTool)
    two_started, release = fx.Latch(), fx.Latch()
    ids: list[str] = []

    def handler(_: Any, ctx: T.HandlerContext[Any]) -> fx.Effect[MySuccess]:
        def start() -> fx.Effect[object]:
            assert ctx.tool_call_id is not None
            ids.append(ctx.tool_call_id)
            return two_started.open() if len(ids) == 2 else fx.void

        return fx.suspend(start).and_then(release.wait()).as_(MySuccess(testSuccess="x"))

    fiber = yield from _provided(
        lm.stream_text([], toolkit=toolkit)
        .run_drain()
        .pipe(fx.provide(toolkit.to_layer(MyTool.handler(handler)))),
        stream_text=[
            {**_CALL, "id": "tool-1", "params": {"testParam": "identical"}},
            {**_CALL, "id": "tool-2", "params": {"testParam": "identical"}},
        ],
    ).fork_scoped()
    yield from two_started.wait()
    assert sorted(ids) == ["tool-1", "tool-2"]
    yield from release.open()
    yield from fiber.join()


@testing.effect
def test_generate_validates_params_per_request():
    """generateText / validates tool parameters against the schemas of each request"""

    class Value(TypedDict):
        value: float

    struct_tool = T.make("TransformTool", parameters=S.Struct(Value), success=S.Finite)
    struct_toolkit = K.make(struct_tool)

    def body() -> Any:
        yield from lm.generate_text(
            [], toolkit=TransformToolkit, disable_tool_call_resolution=True
        ).pipe(fx.provide(TransformLayer))
        error = yield from (
            lm.generate_text([], toolkit=struct_toolkit, disable_tool_call_resolution=True)
            .pipe(
                fx.provide(
                    struct_toolkit.to_layer(
                        struct_tool.handler(lambda params, _: fx.succeed(params["value"]))
                    )
                )
            )
            .flip()
        )
        assert error.reason._tag == "InvalidOutputError"

    yield from _provided(fx.gen(body), generate_text=[_TRANSFORM_CALL])


@testing.effect
def test_generate_validates_encoded_params_after_resolution():
    """generateText / validates encoded tool parameters after a request with tool call resolution enabled"""  # noqa: E501
    tool = T.make("TransformTool", parameters=S.FiniteFromString, success=S.Finite)
    toolkit = K.make(tool)
    responses: list[list[lm.EncodedPart]] = [
        [{"type": "tool-call", "id": "tool-valid", "name": "TransformTool", "params": "21"}],
        [
            {
                "type": "tool-call",
                "id": "tool-invalid",
                "name": "TransformTool",
                "params": {"invalid": True},
            }
        ],
    ]

    def body() -> Any:
        yield from lm.generate_text([], toolkit=toolkit)
        error = yield from lm.generate_text(
            [], toolkit=toolkit, disable_tool_call_resolution=True
        ).flip()
        assert error.reason._tag == "InvalidOutputError"

    yield from _provided(
        fx.gen(body).pipe(
            fx.provide(toolkit.to_layer(tool.handler(lambda value, _: fx.succeed(value * 2))))
        ),
        generate_text=lambda _: responses.pop(0),
    )


@testing.effect
def test_stream_no_retry_after_tool_call():
    """provider options / does not retry an incremental stream after emitting a tool call"""
    toolkit = K.make(MyTool)
    handler_calls: list[int] = []
    provider_calls: list[int] = []
    provider_error = E.make(
        module="LanguageModelTest",
        method="streamText",
        reason=E.InvalidRequestError(description="incremental stream failed"),
    )

    def stream(_: lm.ProviderOptions) -> Any:
        provider_calls.append(1)
        call = {**_CALL, "id": "tool-before-incremental-failure"}
        return streams.make(call).concat(streams.fail(provider_error))

    yield from (
        _provided(
            lm.stream_text("full prompt", toolkit=toolkit)
            .run_drain()
            .pipe(fx.provide(_counting_layer(toolkit, handler_calls))),
            stream_text=stream,
        )
        .pipe(fx.provide_service(tracker.ResponseIdTracker, _FixedTracker()))
        .flip()
    )
    assert provider_calls == [1]
    assert handler_calls == []


# --- tool approval ------------------------------------------------------------------------


class ApprovalParams(TypedDict):
    action: str


class DynamicParams(TypedDict):
    dangerous: bool


class ApprovalResult(TypedDict):
    result: str


ApprovalTool = T.make(
    "ApprovalTool",
    parameters=S.Struct(ApprovalParams),
    success=S.Struct(ApprovalResult),
    needs_approval=True,
)
DynamicApprovalTool = T.make(
    "DynamicApprovalTool",
    parameters=S.Struct(DynamicParams),
    success=S.Struct(ApprovalResult),
    needs_approval=lambda params, _: params["dangerous"],
)
ApprovalToolkit = K.make(ApprovalTool, DynamicApprovalTool)
ApprovalLayer = ApprovalToolkit.to_layer(
    ApprovalTool.handler(lambda _, __: fx.succeed(ApprovalResult(result="approved-result"))),
    DynamicApprovalTool.handler(lambda _, __: fx.succeed(ApprovalResult(result="dynamic-result"))),
)


def _approval_call(call_id: str, approval_id: str, action: str = "delete") -> P.AssistantMessage:
    return P.AssistantMessage(
        content=[
            P.ToolCallPart(id=call_id, name="ApprovalTool", params={"action": action}),
            P.ToolApprovalRequestPart(approval_id=approval_id, tool_call_id=call_id),
        ]
    )


def _approval_answer(
    approval_id: str, approved: bool, reason: str | None = None, result_for: str | None = None
) -> P.ToolMessage:
    content: list[P.ToolMessagePart] = [
        P.ToolApprovalResponsePart(approval_id=approval_id, approved=approved, reason=reason)
    ]
    if result_for is not None:
        content.append(
            P.ToolResultPart(
                id=result_for,
                name="ApprovalTool",
                result={"result": "approved-result"},
                is_failure=False,
            )
        )
    return P.ToolMessage(content=content)


def _parts_of(prompt: P.Prompt, kind: str) -> list[Any]:
    return [
        part
        for message in prompt.content
        if isinstance(message, P.AssistantMessage | P.ToolMessage)
        for part in message.content
        if part.type == kind
    ]


def _assert_no_approvals(prompt: P.Prompt) -> None:
    assert _parts_of(prompt, "tool-approval-request") == []
    assert _parts_of(prompt, "tool-approval-response") == []


def _capturing(prompts: list[P.Prompt]) -> Any:
    def capture(options: lm.ProviderOptions) -> list[lm.EncodedPart]:
        prompts.append(options.prompt)
        return [FINISH]

    return capture


def _run_method(
    method: str, eff_prompt: Any, prompts: list[P.Prompt], layer: fx.Layer[Any]
) -> fx.Effect[Any, Any, Any]:
    run: fx.Effect[Any, Any, Any] = (
        lm.generate_text(eff_prompt, toolkit=ApprovalToolkit)
        if method == "generateText"
        else lm.stream_text(eff_prompt, toolkit=ApprovalToolkit).run_drain()
    )
    return _provided(
        run.pipe(fx.provide(layer)),
        generate_text=_capturing(prompts),
        stream_text=_capturing(prompts),
    )


@pytest.mark.parametrize(
    "method",
    [
        pytest.param(
            "generateText",
            id="tool approval / resolves only pending approvals in mixed approval history (generateText)",  # noqa: E501
        ),
        pytest.param(
            "streamText",
            id="tool approval / resolves only pending approvals in mixed approval history (streamText)",  # noqa: E501
        ),
    ],
)
@testing.effect
def test_resolves_only_pending_approvals(method: str):
    """tool approval / resolves only pending approvals in mixed approval history (<method>)"""
    executed: list[str] = []
    prompt: list[P.Message] = []
    for id, approved, resolved in (
        ("previous-approved", True, True),
        ("previous-denied", False, True),
        ("pending-approved", True, False),
        ("pending-denied", False, False),
    ):
        answer: list[P.ToolMessagePart] = [
            P.ToolApprovalResponsePart(approval_id=id, approved=approved, reason="User declined")
        ]
        if resolved:
            answer.append(
                P.ToolResultPart(
                    id=id, name="ApprovalTool", result={"result": id}, is_failure=not approved
                )
            )
        prompt += [_approval_call(id, id, action=id), P.ToolMessage(content=answer)]

    def handler(params: ApprovalParams, _: Any) -> fx.Effect[ApprovalResult]:
        def run() -> ApprovalResult:
            executed.append(params["action"])
            return ApprovalResult(result="approved-result")

        return fx.sync(run)

    layer = ApprovalToolkit.to_layer(
        ApprovalTool.handler(handler),
        DynamicApprovalTool.handler(lambda _, __: fx.succeed(ApprovalResult(result="d"))),
    )
    prompts: list[P.Prompt] = []
    yield from _run_method(method, prompt, prompts, layer)
    assert executed == ["pending-approved"]
    (sent,) = prompts
    _assert_no_approvals(sent)
    assert [p.id for p in _parts_of(sent, "tool-call")] == [
        "previous-approved",
        "previous-denied",
        "pending-approved",
        "pending-denied",
    ]
    assert [(p.id, p.result, p.is_failure) for p in _parts_of(sent, "tool-result")] == [
        ("previous-approved", {"result": "previous-approved"}, False),
        ("previous-denied", {"result": "previous-denied"}, True),
        ("pending-approved", {"result": "approved-result"}, False),
        ("pending-denied", {"type": "execution-denied", "reason": "User declined"}, True),
    ]


@testing.effect
def test_emits_approval_request():
    """tool approval / emits tool-approval-request when tool has needsApproval: true"""
    parts = yield from _provided(
        lm.stream_text([], toolkit=ApprovalToolkit).run_collect().pipe(fx.provide(ApprovalLayer)),
        stream_text=[
            {
                "type": "tool-call",
                "id": "call-123",
                "name": "ApprovalTool",
                "params": {"action": "delete"},
            }
        ],
    )
    assert len(parts) == 2
    assert parts[0] == R.ToolCallPart(
        id="call-123", name="ApprovalTool", params={"action": "delete"}
    )
    approval = parts[1]
    assert isinstance(approval, R.ToolApprovalRequestPart)
    assert approval.tool_call_id == "call-123"
    assert approval.approval_id


def _last_tool_results(prompt: P.Prompt) -> list[P.ToolResultPart]:
    last = prompt.content[-1]
    assert isinstance(last, P.ToolMessage)
    return [part for part in last.content if isinstance(part, P.ToolResultPart)]


@testing.effect
def test_pre_resolves_approved_calls():
    """tool approval / pre-resolves approved tool calls before calling LLM"""
    prompts: list[P.Prompt] = []
    yield from _run_method(
        "streamText",
        [_approval_call("call-456", "approval-456"), _approval_answer("approval-456", True)],
        prompts,
        ApprovalLayer,
    )
    (result,) = _last_tool_results(prompts[0])
    assert (result.id, result.result, result.is_failure) == (
        "call-456",
        {"result": "approved-result"},
        False,
    )


@testing.effect
def test_pre_resolves_denied_calls():
    """tool approval / pre-resolves denied tool calls with execution-denied before calling LLM"""
    prompts: list[P.Prompt] = []
    yield from _run_method(
        "streamText",
        [
            _approval_call("call-789", "approval-789"),
            _approval_answer("approval-789", False, "User declined"),
        ],
        prompts,
        ApprovalLayer,
    )
    (result,) = _last_tool_results(prompts[0])
    assert result.id == "call-789"
    assert result.result == {"type": "execution-denied", "reason": "User declined"}
    assert result.is_failure is True


@testing.effect
def test_strips_approved_artifacts_stream():
    """tool approval / strips approved approval artifacts from prompt sent to provider (streamText)"""  # noqa: E501
    prompts: list[P.Prompt] = []
    yield from _run_method(
        "streamText",
        [_approval_call("call-strip", "approval-strip"), _approval_answer("approval-strip", True)],
        prompts,
        ApprovalLayer,
    )
    _assert_no_approvals(prompts[0])
    assistant = next(m for m in prompts[0].content if isinstance(m, P.AssistantMessage))
    assert [p.type for p in assistant.content] == ["tool-call"]


@testing.effect
def test_strips_denied_artifacts():
    """tool approval / strips denied approval artifacts from prompt sent to provider"""
    prompts: list[P.Prompt] = []
    yield from _run_method(
        "streamText",
        [
            _approval_call("call-strip-deny", "approval-strip-deny"),
            _approval_answer("approval-strip-deny", False, "Denied"),
        ],
        prompts,
        ApprovalLayer,
    )
    _assert_no_approvals(prompts[0])
    (result,) = _last_tool_results(prompts[0])
    assert result.is_failure is True


@testing.effect
def test_strips_only_resolved_approvals():
    """tool approval / strips only resolved approvals, preserves unrelated parts"""
    prompts: list[P.Prompt] = []
    assistant = P.AssistantMessage(
        content=[
            *_approval_call("call-resolved", "approval-resolved").content,
            *_approval_call("call-unresolved", "approval-unresolved", action="read").content,
        ]
    )
    yield from _run_method(
        "streamText",
        [assistant, _approval_answer("approval-resolved", True)],
        prompts,
        ApprovalLayer,
    )
    sent = next(m for m in prompts[0].content if isinstance(m, P.AssistantMessage))
    requests = [p for p in sent.content if isinstance(p, P.ToolApprovalRequestPart)]
    assert [r.approval_id for r in requests] == ["approval-unresolved"]
    assert len([p for p in sent.content if isinstance(p, P.ToolCallPart)]) == 2


@testing.effect
def test_strips_artifacts_generate_text():
    """tool approval / strips approval artifacts via generateText path"""
    prompts: list[P.Prompt] = []
    yield from _run_method(
        "generateText",
        [_approval_call("call-gen", "approval-gen"), _approval_answer("approval-gen", True)],
        prompts,
        ApprovalLayer,
    )
    _assert_no_approvals(prompts[0])
    assistant = next(m for m in prompts[0].content if isinstance(m, P.AssistantMessage))
    assert [p.type for p in assistant.content] == ["tool-call"]


@pytest.mark.parametrize(
    ("dangerous", "expected"),
    [
        pytest.param(
            True,
            "tool-approval-request",
            id="tool approval / dynamic needsApproval returns true when condition met",
        ),
        pytest.param(
            False,
            "tool-result",
            id="tool approval / dynamic needsApproval returns false when condition not met",
        ),
    ],
)
@testing.effect
def test_dynamic_needs_approval(dangerous: bool, expected: str):
    """tool approval / dynamic needsApproval returns true when condition met / returns false when condition not met"""  # noqa: E501
    parts = yield from _provided(
        lm.stream_text([], toolkit=ApprovalToolkit).run_collect().pipe(fx.provide(ApprovalLayer)),
        stream_text=[
            {
                "type": "tool-call",
                "id": "call-dyn",
                "name": "DynamicApprovalTool",
                "params": {"dangerous": dangerous},
            }
        ],
    )
    assert [p.type for p in parts] == ["tool-call", expected]
    second = parts[1]
    if isinstance(second, R.ToolResultSuccess):
        assert second.result == {"result": "dynamic-result"}
    else:
        assert isinstance(second, R.ToolApprovalRequestPart)
        assert second.tool_call_id == "call-dyn"


@testing.effect
def test_tool_without_needs_approval():
    """tool approval / tool without needsApproval executes normally"""
    toolkit = K.make(MyTool)
    layer = toolkit.to_layer(
        MyTool.handler(lambda _, __: fx.succeed(MySuccess(testSuccess="test-success")).delay(10))
    )
    parts: list[Any] = []
    first = fx.Latch()
    fiber = yield from _provided(
        lm.stream_text([], toolkit=toolkit)
        .run_for_each(lambda part: first.open().and_then(fx.sync(lambda: parts.append(part))))
        .pipe(fx.provide(layer)),
        stream_text=[{**_CALL, "id": "call-normal", "params": {"testParam": "test"}}],
    ).fork_scoped()
    yield from first.wait()
    yield from testing.adjust(10)
    yield from fiber.join()
    assert [p.type for p in parts] == ["tool-call", "tool-result"]
    assert parts[1].result == {"testSuccess": "test-success"}


def _previous_round() -> list[P.Message]:
    return [
        _approval_call("call-prev", "approval-prev"),
        _approval_answer("approval-prev", True, result_for="call-prev"),
        P.UserMessage(content=[P.TextPart(text="continue")]),
    ]


@pytest.mark.parametrize(
    "method",
    [
        pytest.param(
            "streamText",
            id="tool approval / strips previous-round approval artifacts even when no new pending approvals (streamText)",  # noqa: E501
        ),
        pytest.param(
            "generateText",
            id="tool approval / strips previous-round approval artifacts even when no new pending approvals (generateText)",  # noqa: E501
        ),
    ],
)
@testing.effect
def test_strips_previous_round_artifacts(method: str):
    """tool approval / strips previous-round approval artifacts even when no new pending approvals (<method>)"""  # noqa: E501
    prompts: list[P.Prompt] = []
    yield from _run_method(method, _previous_round(), prompts, ApprovalLayer)
    _assert_no_approvals(prompts[0])
    assert len(_parts_of(prompts[0], "tool-call")) == 1
    assert len(_parts_of(prompts[0], "tool-result")) == 1


@testing.effect
def test_stream_emits_pre_resolved_results():
    """tool approval / streamText emits pre-resolved tool results as stream parts"""
    parts = yield from _provided(
        lm.stream_text(
            [_approval_call("call-emit", "approval-emit"), _approval_answer("approval-emit", True)],
            toolkit=ApprovalToolkit,
        )
        .run_collect()
        .pipe(fx.provide(ApprovalLayer)),
        stream_text=[FINISH],
    )
    results = [p for p in parts if isinstance(p, R.ToolResultSuccess | R.ToolResultFailure)]
    assert len(results) == 1
    (result,) = results
    assert (result.id, result.name, result.result, result.is_failure) == (
        "call-emit",
        "ApprovalTool",
        {"result": "approved-result"},
        False,
    )


@testing.effect
def test_stream_no_synthesized_results_for_approvals():
    """streamText / does not synthesize results for tool calls awaiting approval on an incomplete finish"""  # noqa: E501
    observed, approval_seen = fx.Latch(), fx.Latch()
    provider = yield from _queue_stream()
    parts: list[Any] = []

    def on_part(part: Any) -> fx.Effect[object]:
        if part.type == "tool-call":
            return observed.open()
        return approval_seen.open() if part.type == "tool-approval-request" else fx.void

    fiber = yield from _provided(
        lm.stream_text([], toolkit=ApprovalToolkit)
        .run_for_each(_collecting(parts, on_part))
        .pipe(fx.provide(ApprovalLayer)),
        stream_text=lambda _: stream_sources.from_queue(provider),
    ).fork_scoped()
    yield from provider.offer(
        {
            "type": "tool-call",
            "id": "tool-awaiting-approval",
            "name": "ApprovalTool",
            "params": {"action": "test-action"},
        }
    )
    yield from observed.wait()
    yield from provider.offer({"type": "text-delta", "id": "text-1", "delta": "more"})
    yield from approval_seen.wait()
    yield from provider.offer({**FINISH, "reason": "length"})
    yield from provider.end()
    yield from fiber.join()
    assert [p.type for p in parts] == ["tool-call", "text-delta", "tool-approval-request", "finish"]


@testing.effect
def test_stream_bounds_needs_approval_concurrency():
    """streamText / bounds needsApproval evaluation with the tool handler concurrency"""

    class Input(TypedDict):
        input: str

    class Output(TypedDict):
        output: str

    started, release = fx.Latch(), fx.Latch()
    active, peak = [0], [0]

    def needs(_: Input, __: T.NeedsApprovalContext) -> fx.Effect[bool]:
        def start() -> fx.Effect[object]:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
            return started.open()

        def done() -> None:
            active[0] -= 1

        return fx.suspend(start).and_then(release.wait()).ensuring(fx.sync(done)).as_(False)

    tool = T.make(
        "ApprovalConcurrencyTool",
        parameters=S.Struct(Input),
        success=S.Struct(Output),
        needs_approval=needs,
    )
    toolkit = K.make(tool)
    layer = toolkit.to_layer(tool.handler(lambda _, __: fx.succeed(Output(output="done"))))
    fiber = yield from _provided(
        lm.stream_text([], toolkit=toolkit, concurrency=1).run_drain().pipe(fx.provide(layer)),
        stream_text=[
            {
                "type": "tool-call",
                "id": f"tool-{i}",
                "name": "ApprovalConcurrencyTool",
                "params": {"input": f"test-{i}"},
            }
            for i in (1, 2)
        ],
    ).fork_scoped()
    yield from started.wait()
    assert (active[0], peak[0]) == (1, 1)
    yield from release.open()
    yield from fiber.join()
    assert (active[0], peak[0]) == (0, 1)


def _approved_continue() -> list[P.Message]:
    return [
        _approval_call("call-tracker", "approval-tracker"),
        _approval_answer("approval-tracker", True, result_for="call-tracker"),
        P.UserMessage(content=[P.TextPart(text="continue")]),
    ]


class _NoPrepareTracker(_RecordingTracker):
    def prepare_unsafe(self, prompt: P.Prompt) -> tracker.PrepareResult | None:
        self.prepared.append(prompt)
        return None


@pytest.mark.parametrize(
    "method",
    [
        pytest.param(
            "generateText",
            id="provider options / calls tracker.prepareUnsafe after stripping resolved approvals in toolkit flow",  # noqa: E501
        ),
        pytest.param(
            "streamText",
            id="provider options / calls tracker.prepareUnsafe after stripping resolved approvals in streamText toolkit flow",  # noqa: E501
        ),
    ],
)
@testing.effect
def test_tracker_prepares_stripped_prompt(method: str):
    """provider options / calls tracker.prepareUnsafe after stripping resolved approvals in toolkit flow / in streamText toolkit flow"""  # noqa: E501
    recording = _NoPrepareTracker()
    run = (
        lm.generate_text(_approved_continue(), toolkit=ApprovalToolkit)
        if method == "generateText"
        else lm.stream_text(_approved_continue(), toolkit=ApprovalToolkit).run_drain()
    )
    yield from _tracked(
        run.pipe(fx.provide(ApprovalLayer)),
        recording,
        generate_text=[_TRACKED_METADATA, FINISH],
        stream_text=[_TRACKED_METADATA, FINISH],
    )
    (prepared,) = recording.prepared
    _assert_no_approvals(prepared)
    ((parts, _),) = recording.marked
    assert parts is prepared.content


@testing.effect
def test_tracker_with_resolution_disabled():
    """provider options / uses tracker prepareUnsafe and markParts when disableToolCallResolution is true"""  # noqa: E501
    recording, seen = _RecordingTracker(), list[lm.ProviderOptions]()
    prompt = [
        _approval_call("call-tracker-stream-disable", "approval-tracker-stream-disable"),
        _approval_answer(
            "approval-tracker-stream-disable", True, result_for="call-tracker-stream-disable"
        ),
        P.UserMessage(content=[P.TextPart(text="continue")]),
    ]
    yield from _tracked(
        lm.stream_text(prompt, toolkit=ApprovalToolkit, disable_tool_call_resolution=True)
        .run_drain()
        .pipe(fx.provide(ApprovalLayer)),
        recording,
        stream_text=_capture(seen, [_TRACKED_METADATA, FINISH]),
    )
    _assert_tracked(recording, seen)
    _assert_no_approvals(recording.prepared[0])


# --- deferred tool call validation ------------------------------------------------------

_MY_TOOLKIT = K.make(MyTool)
_MY_LAYER = _MY_TOOLKIT.to_layer(
    MyTool.handler(lambda _, __: fx.succeed(MySuccess(testSuccess="test-success")))
)
_WRITE_CALL: lm.EncodedPart = {
    "type": "tool-call",
    "id": "call_1",
    "name": "Write",
    "params": {"path": "a"},
}


@testing.effect
def test_ignores_deferred_validation_with_resolution():
    """generateText / ignores deferred tool call validation when tool call resolution is enabled"""
    # The types reject deferred validation without disable_tool_call_resolution.
    generate: Any = lm.generate_text
    error = yield from _provided(
        generate([], toolkit=_MY_TOOLKIT, tool_call_validation="deferred")
        .pipe(fx.provide(_MY_LAYER))
        .flip(),
        generate_text=[_WRITE_CALL],
    )
    assert isinstance(error, E.AiError)
    assert isinstance(error.reason, E.InvalidOutputError)


@testing.effect
def test_returns_tool_calls_without_toolkit_when_deferred():
    """generateText / returns tool calls without a toolkit when tool call validation is deferred"""
    seen: list[str] = []

    def generate(options: lm.ProviderOptions) -> list[lm.EncodedPart]:
        seen.append(options.tool_call_validation)
        return [_WRITE_CALL]

    response = yield from _provided(
        lm.generate_text([], disable_tool_call_resolution=True, tool_call_validation="deferred"),
        generate_text=generate,
    )
    assert [(c.name, c.params) for c in response.tool_calls] == [("Write", {"path": "a"})]
    assert seen == ["deferred"]


@testing.effect
def test_validates_provider_executed_calls_when_deferred():
    """streamText / validates provider-executed tool calls when tool call validation is deferred"""
    call = {**_CALL, "id": "call_1", "params": {"testParam": 42}, "providerExecuted": True}
    error = yield from _provided(
        lm.stream_text(
            [],
            toolkit=_MY_TOOLKIT,
            disable_tool_call_resolution=True,
            tool_call_validation="deferred",
        )
        .run_drain()
        .pipe(fx.provide(_MY_LAYER))
        .flip(),
        stream_text=[call],
    )
    assert isinstance(error, E.AiError)
    assert isinstance(error.reason, E.InvalidOutputError)


@testing.effect
def test_deferred_keeps_invalid_and_undeclared_calls():
    """Not an Effect title: the core half of the OpenAI-compatible
    ``returns invalid and undeclared tool calls when tool call validation is
    deferred``: a call with invalid parameters and a call to an undeclared
    tool come back as the provider sent them (generateText and streamText)."""
    invalid = {**_CALL, "params": {"testParam": 42}}
    response = yield from _provided(
        lm.generate_text(
            [],
            toolkit=_MY_TOOLKIT,
            disable_tool_call_resolution=True,
            tool_call_validation="deferred",
        ).pipe(fx.provide(_MY_LAYER)),
        generate_text=[invalid, _WRITE_CALL],
    )
    assert [(c.name, c.params) for c in response.tool_calls] == [
        ("MyTool", {"testParam": 42}),
        ("Write", {"path": "a"}),
    ]
    parts = yield from _provided(
        lm.stream_text(
            [],
            toolkit=_MY_TOOLKIT,
            disable_tool_call_resolution=True,
            tool_call_validation="deferred",
        )
        .run_collect()
        .pipe(fx.provide(_MY_LAYER)),
        stream_text=[invalid, _WRITE_CALL],
    )
    assert [(p.name, p.params) for p in parts if isinstance(p, R.ToolCallPart)] == [
        ("MyTool", {"testParam": 42}),
        ("Write", {"path": "a"}),
    ]
