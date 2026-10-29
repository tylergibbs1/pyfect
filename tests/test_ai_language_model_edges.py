"""``LanguageModel`` edges Effect's tests leave open. Each case was run
under Node against Effect's ``LanguageModel.make`` and pins what it
printed."""

from __future__ import annotations

from typing import Any, TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.ai import id_generator as ids
from pyfect.ai import language_model as lm
from pyfect.ai import response_id_tracker as tracker
from pyfect.ai import tool as T
from pyfect.ai import toolkit as K
from pyfect.stream import _constructors as streams


class Params(TypedDict):
    testParam: str


class Success(TypedDict):
    testSuccess: str


class Empty(TypedDict):
    pass


MyTool = T.make("MyTool", parameters=S.Struct(Params), success=S.Struct(Success))
OtherTool = T.make("OtherTool", parameters=S.Struct(Empty), success=S.String)
KIT = K.make(MyTool, OtherTool)
FINISH: lm.EncodedPart = {
    "type": "finish",
    "reason": "stop",
    "usage": {"inputTokens": {"uncached": 1, "total": 1}, "outputTokens": {"total": 1}},
}
CALL: lm.EncodedPart = {
    "type": "tool-call",
    "id": "c1",
    "name": "MyTool",
    "params": {"testParam": "x"},
}


def _succeed(_: Params, __: T.HandlerContext[Success]) -> fx.Effect[Success, str]:
    return fx.succeed(Success(testSuccess="s"))


def _boom(_: Params, __: T.HandlerContext[Success]) -> fx.Effect[Success, str]:
    return fx.fail("boom")


def handlers(my_tool: Any = _succeed) -> fx.Layer[Any]:
    return KIT.to_layer(
        MyTool.handler(my_tool),
        OtherTool.handler(lambda _, __: fx.succeed("o")),
    )


def model(
    generate: lm.GenerateFn = lambda _: fx.succeed([]),
    stream: lm.StreamFn = lambda _: streams.empty,
) -> fx.Effect[lm.Service]:
    return lm.make(generate_text=generate, stream_text=stream)


@testing.effect
def test_stream_text_span():
    """streamText runs in a ``LanguageModel.streamText`` client span with the
    request's attributes."""
    seen: list[lm.ProviderOptions] = []

    def stream(options: lm.ProviderOptions) -> Any:
        seen.append(options)
        return streams.make(FINISH)

    yield from (
        lm.stream_text("hi", toolkit=KIT, tool_choice="required", concurrency=2)
        .run_drain()
        .pipe(fx.provide(handlers()))
        .pipe(fx.provide_service_effect(lm.LanguageModel, model(stream=stream)))
    )
    span = seen[0].span
    assert span is not None
    assert (span.name, span.kind) == ("LanguageModel.streamText", "client")
    assert dict(span.attributes) == {
        "gen_ai.output.type": "text",
        "effect.ai.tool_choice": "required",
        "effect.ai.concurrency": 2,
    }


class _Recording(tracker.Service):
    def __init__(self) -> None:
        super().__init__()
        self.marked: list[str] = []

    def mark_parts(self, parts: Any, response_id: str) -> None:
        self.marked.append(response_id)


@testing.effect
def test_failed_tool_call_leaves_tracker_unmarked():
    """generateText marks the response only once its tool calls resolve: a
    failing handler leaves the tracker unmarked."""
    recording = _Recording()
    error = yield from (
        lm.generate_text("hi", toolkit=KIT)
        .pipe(fx.provide(handlers(_boom)))
        .pipe(
            fx.provide_service_effect(
                lm.LanguageModel,
                model(
                    generate=lambda _: fx.succeed(
                        [{"type": "response-metadata", "id": "resp_1"}, CALL, FINISH]
                    )
                ),
            )
        )
        .pipe(fx.provide_service(tracker.ResponseIdTracker, recording))
        .flip()
    )
    assert error == "boom"
    assert recording.marked == []


@testing.effect
def test_stream_one_of_excluding_a_called_tool():
    """streamText offers only the ``one_of`` tools but still resolves a call
    to another tool of the toolkit."""
    offered: list[list[str]] = []

    def stream(options: lm.ProviderOptions) -> Any:
        offered.append([tool.name for tool in options.tools])
        return streams.make(CALL, FINISH)

    parts = yield from (
        lm.stream_text("hi", toolkit=KIT, tool_choice={"one_of": ["OtherTool"]})
        .run_collect()
        .pipe(fx.provide(handlers()))
        .pipe(fx.provide_service_effect(lm.LanguageModel, model(stream=stream)))
    )
    assert offered == [["OtherTool"]]
    assert [part.type for part in parts] == ["tool-call", "tool-result", "finish"]


@testing.effect
def test_stream_empty_toolkit_sends_no_tool_choice():
    """streamText with an empty toolkit sends tool choice ``"none"``."""
    choices: list[object] = []

    def stream(options: lm.ProviderOptions) -> Any:
        choices.append(options.tool_choice)
        return streams.make(FINISH)

    yield from (
        lm.stream_text("hi", toolkit=K.empty, tool_choice="required")
        .run_drain()
        .pipe(fx.provide(K.empty.to_layer()))
        .pipe(fx.provide_service_effect(lm.LanguageModel, model(stream=stream)))
    )
    assert choices == ["none"]


@testing.effect
def test_id_generator_is_the_one_at_make():
    """A model's requests use the ``IdGenerator`` in context when it was
    made, not the caller's."""
    made: list[str] = []

    def record(id: str) -> list[lm.EncodedPart]:
        made.append(id)
        return []

    def generate(_: lm.ProviderOptions) -> fx.Effect[list[lm.EncodedPart], Any, Any]:
        return ids.IdGenerator().flat_map(lambda generator: generator.generate_id()).map(record)

    custom = ids.Service(lambda: fx.succeed("custom"))
    service = yield from model(generate=generate)
    yield from (
        lm.generate_text("hi")
        .pipe(fx.provide_service(lm.LanguageModel, service))
        .pipe(fx.provide_service(ids.IdGenerator, custom))
    )
    service = yield from model(generate=generate).pipe(fx.provide_service(ids.IdGenerator, custom))
    yield from lm.generate_text("hi").pipe(fx.provide_service(lm.LanguageModel, service))
    assert made[0].startswith("id_")
    assert made[1] == "custom"


@testing.effect(asyncio=True)
def test_stream_resolution_on_asyncio():
    """streamText resolves tool calls the same way on the asyncio runtime."""
    calls = [{**CALL, "id": f"c{i}"} for i in range(3)]
    parts = yield from (
        lm.stream_text("hi", toolkit=KIT, concurrency=2)
        .run_collect()
        .pipe(fx.provide(handlers()))
        .pipe(
            fx.provide_service_effect(
                lm.LanguageModel, model(stream=lambda _: streams.make(*calls, FINISH))
            )
        )
    )
    assert [part.type for part in parts] == [
        "tool-call",
        "tool-call",
        "tool-call",
        "tool-result",
        "tool-result",
        "tool-result",
        "finish",
    ]
