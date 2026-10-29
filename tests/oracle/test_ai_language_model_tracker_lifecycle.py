"""Ports of Effect's ``test/ai/LanguageModelTrackerLifecycle.test.ts``.

Each test's docstring is the Effect test title (with its ``describe``).
"""

from __future__ import annotations

# pyright: reportPrivateUsage=false
from collections.abc import Callable
from typing import Any, TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.ai import language_model as lm
from pyfect.ai import prompt as P
from pyfect.ai import response_id_tracker as tracker
from pyfect.ai import tool as T
from pyfect.ai import toolkit as K
from pyfect.stream import _constructors as streams

FINISH: lm.EncodedPart = {
    "type": "finish",
    "reason": "stop",
    "usage": {"inputTokens": {"uncached": 5, "total": 5}, "outputTokens": {"total": 5}},
}


def metadata(id: str) -> lm.EncodedPart:
    return {"type": "response-metadata", "id": id}


def user(text: str) -> P.UserMessage:
    return P.UserMessage(content=[P.TextPart(text=text)])


def assistant(text: str) -> P.AssistantMessage:
    return P.AssistantMessage(content=[P.TextPart(text=text)])


class Count(TypedDict):
    count: float


SYSTEM = P.SystemMessage(content="system")


def _recording_model(
    ids: list[str], text: str, options: list[lm.ProviderOptions]
) -> fx.Effect[lm.Service]:
    def generate(o: lm.ProviderOptions) -> fx.Effect[list[lm.EncodedPart]]:
        def run() -> list[lm.EncodedPart]:
            response_id = ids[len(options)]
            options.append(o)
            return [metadata(response_id), {"type": "text", "text": text or response_id}, FINISH]

        return fx.sync(run)

    return lm.make(generate_text=generate, stream_text=lambda _: streams.empty)


def _with(
    model: lm.Service, t: tracker.Service | None
) -> Callable[[fx.Effect[Any, Any, Any]], fx.Effect[Any, Any, Any]]:
    def provide(eff: fx.Effect[Any, Any, Any]) -> fx.Effect[Any, Any, Any]:
        provided = eff.pipe(fx.provide_service(lm.LanguageModel, model))
        return (
            provided
            if t is None
            else provided.pipe(fx.provide_service(tracker.ResponseIdTracker, t))
        )

    return provide


@testing.effect
def test_generate_text_across_turns():
    """LanguageModel tracker lifecycle integration / tracks generateText across turns and recovers after session drop"""  # noqa: E501
    t = yield from tracker.make
    options: list[lm.ProviderOptions] = []
    model = yield from _recording_model(["resp_1", "resp_2", "resp_3", "resp_4"], "", options)
    provide = _with(model, t)
    user1, assistant1, user2 = user("user1"), assistant("assistant1"), user("user2")
    assistant2, user3, assistant3, user4 = (
        assistant("assistant2"),
        user("user3"),
        assistant("assistant3"),
        user("user4"),
    )

    yield from lm.generate_text(P.from_messages([SYSTEM, user1])).pipe(provide)
    first = options[0].prompt
    yield from lm.generate_text(P.from_messages([*first.content, assistant1, user2])).pipe(provide)
    t.clear_unsafe()
    second = options[1].prompt
    yield from lm.generate_text(P.from_messages([*second.content, assistant2, user3])).pipe(provide)
    third = options[2].prompt
    yield from lm.generate_text(P.from_messages([*third.content, assistant3, user4])).pipe(provide)

    assert len(options) == 4
    assert (options[0].previous_response_id, options[0].incremental_prompt) == (None, None)
    assert options[1].previous_response_id == "resp_1"
    assert options[1].incremental_prompt == P.from_messages([user2])
    assert (options[2].previous_response_id, options[2].incremental_prompt) == (None, None)
    assert options[2].prompt == P.from_messages([*second.content, assistant2, user3])
    assert options[3].previous_response_id == "resp_3"
    assert options[3].incremental_prompt == P.from_messages([user4])


@testing.effect
def test_generate_object_keeps_tracking():
    """LanguageModel tracker lifecycle integration / falls back to full prompt after stale previous response id and keeps tracking"""  # noqa: E501
    t = yield from tracker.make
    options: list[lm.ProviderOptions] = []
    model = yield from _recording_model(["resp_object_1", "resp_object_2"], '{"count":1}', options)
    provide = _with(model, t)
    schema = S.Struct(Count)
    user1, assistant1, user2 = user("user1"), assistant("assistant1"), user("user2")

    yield from lm.generate_object(P.from_messages([SYSTEM, user1]), schema=schema).pipe(provide)
    first = options[0].prompt
    yield from lm.generate_object(
        P.from_messages([*first.content, assistant1, user2]), schema=schema
    ).pipe(provide)

    assert len(options) == 2
    assert (options[0].previous_response_id, options[0].incremental_prompt) == (None, None)
    assert options[1].previous_response_id == "resp_object_1"
    assert options[1].incremental_prompt == P.from_messages([user2])


@testing.effect
def test_stream_text_across_turns():
    """LanguageModel tracker lifecycle integration / tracks streamText with metadata parts across turns"""  # noqa: E501
    t = yield from tracker.make
    options: list[lm.ProviderOptions] = []
    ids = ["resp_stream_1", "resp_stream_2"]

    def stream(o: lm.ProviderOptions) -> Any:
        response_id = ids[len(options)]
        options.append(o)
        return streams.from_iterable([metadata(response_id), FINISH])

    model = yield from lm.make(generate_text=lambda _: fx.succeed([]), stream_text=stream)
    provide = _with(model, t)
    user1, assistant1, user2 = user("user1"), assistant("assistant1"), user("user2")

    yield from lm.stream_text(P.from_messages([SYSTEM, user1])).run_drain().pipe(provide)
    first = options[0].prompt
    yield from (
        lm.stream_text(P.from_messages([*first.content, assistant1, user2]))
        .run_drain()
        .pipe(provide)
    )

    assert len(options) == 2
    assert (options[0].previous_response_id, options[0].incremental_prompt) == (None, None)
    assert options[1].previous_response_id == "resp_stream_1"
    assert options[1].incremental_prompt == P.from_messages([user2])


class Action(TypedDict):
    action: str


class Result(TypedDict):
    result: str


@testing.effect
def test_stream_text_finish_with_toolkit():
    """LanguageModel tracker lifecycle integration / emits finish parts in streamText when toolkit is provided and no tool calls are returned"""  # noqa: E501
    tool = T.make("ApprovalTool", parameters=S.Struct(Action), success=S.Struct(Result))
    toolkit = K.make(tool)
    layer = toolkit.to_layer(
        tool.handler(lambda _, __: fx.succeed(Result(result="approved-result")))
    )
    model = yield from lm.make(
        generate_text=lambda _: fx.succeed([]),
        stream_text=lambda _: streams.from_iterable([FINISH]),
    )
    parts = yield from (
        lm.stream_text([user("hello")], toolkit=toolkit)
        .run_collect()
        .pipe(fx.provide_service(lm.LanguageModel, model))
        .pipe(fx.provide(layer))
    )
    assert [p.type for p in parts] == ["finish"]


@testing.effect
def test_no_tracker_keeps_incremental_fields_empty():
    """LanguageModel tracker lifecycle integration / keeps incremental provider fields undefined when tracker is omitted"""  # noqa: E501
    generate_options: list[lm.ProviderOptions] = []
    stream_options: list[lm.ProviderOptions] = []

    def generate(o: lm.ProviderOptions) -> fx.Effect[list[lm.EncodedPart]]:
        generate_options.append(o)
        return fx.succeed([metadata("resp_none"), {"type": "text", "text": '{"count":1}'}, FINISH])

    def stream(o: lm.ProviderOptions) -> Any:
        stream_options.append(o)
        return streams.from_iterable([metadata("resp_none_stream"), FINISH])

    model = yield from lm.make(generate_text=generate, stream_text=stream)
    provide = _with(model, None)
    user1, assistant1, user2 = user("user1"), assistant("assistant1"), user("user2")
    first: list[P.Message] = [SYSTEM, user1]
    second: list[P.Message] = [SYSTEM, user1, assistant1, user2]
    for messages in (first, second):
        yield from lm.generate_text(messages).pipe(provide)
        yield from lm.generate_object(messages, schema=S.Struct(Count)).pipe(provide)
        yield from lm.stream_text(messages).run_drain().pipe(provide)
    assert len(generate_options) == 4
    assert len(stream_options) == 2
    for options in (*generate_options, *stream_options):
        assert (options.previous_response_id, options.incremental_prompt) == (None, None)


class ApprovalParams(TypedDict):
    action: str


class ApprovalResult(TypedDict):
    result: str


ApprovalTool = T.make(
    "ApprovalTool",
    parameters=S.Struct(ApprovalParams),
    success=S.Struct(ApprovalResult),
    needs_approval=True,
)
ApprovalToolkit = K.make(ApprovalTool)


@testing.effect
def test_prepares_after_approval_pre_resolution():
    """LanguageModel tracker lifecycle integration / prepares after approval pre-resolution using stripped prompt"""  # noqa: E501
    t = yield from tracker.make
    options: list[lm.ProviderOptions] = []
    ids = ["resp_tool_1", "resp_tool_2"]

    def generate(o: lm.ProviderOptions) -> fx.Effect[list[lm.EncodedPart]]:
        def run() -> list[lm.EncodedPart]:
            response_id = ids[len(options)]
            options.append(o)
            return [metadata(response_id), FINISH]

        return fx.sync(run)

    model = yield from lm.make(generate_text=generate, stream_text=lambda _: streams.empty)
    provide = _with(model, t)
    yield from lm.generate_text(P.from_messages([SYSTEM, user("user1")])).pipe(provide)
    first = options[0].prompt
    pending = [
        *first.content,
        P.AssistantMessage(
            content=[
                P.ToolCallPart(
                    id="call-approval", name="ApprovalTool", params={"action": "delete"}
                ),
                P.ToolApprovalRequestPart(approval_id="approval-1", tool_call_id="call-approval"),
            ]
        ),
        P.ToolMessage(
            content=[P.ToolApprovalResponsePart(approval_id="approval-1", approved=True)]
        ),
    ]
    layer = ApprovalToolkit.to_layer(
        ApprovalTool.handler(lambda _, __: fx.succeed(ApprovalResult(result="approved-result")))
    )
    yield from (
        lm.generate_text(P.from_messages(pending), toolkit=ApprovalToolkit)
        .pipe(provide)
        .pipe(fx.provide(layer))
    )
    assert len(options) == 2
    second = options[1]
    assert second.previous_response_id == "resp_tool_1"
    assert second.incremental_prompt == P.from_messages(
        [
            P.ToolMessage(
                content=[
                    P.ToolResultPart(
                        id="call-approval",
                        name="ApprovalTool",
                        result={"result": "approved-result"},
                        is_failure=False,
                    )
                ]
            )
        ]
    )
    for message in second.prompt.content:
        if isinstance(message, P.AssistantMessage | P.ToolMessage):
            kinds = [part.type for part in message.content]
            assert "tool-approval-request" not in kinds
            assert "tool-approval-response" not in kinds
