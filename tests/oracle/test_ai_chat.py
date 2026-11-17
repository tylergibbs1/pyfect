"""Ports of Effect's ``test/ai/Chat.test.ts``.

Each test's docstring is the Effect test title (with its ``describe``).
``Chat.Persistence.key`` is ``chat.PERSISTENCE_KEY``; a file's ``URL`` data
is a ``Url``; ``TestClock.adjust("30 days")`` is
``testing.adjust(30 * 86400)``.
"""

from __future__ import annotations

import json
from typing import Any, TypedDict

import pytest

import pyfect as fx
from pyfect import layer, testing
from pyfect import schema as S
from pyfect.ai import chat as C
from pyfect.ai import id_generator
from pyfect.ai import prompt as P
from pyfect.ai import response as R
from pyfect.ai import tool as T
from pyfect.ai import toolkit as K
from pyfect.duration import millis
from pyfect.http.url import Url
from pyfect.persistence import key_value_store, persistence
from pyfect.persistence.persistence import BackingPersistence

from ._ai import ProvideModel, with_language_model


def _constant_ids(id: str) -> Any:
    return fx.provide_service(
        id_generator.IdGenerator, id_generator.Service(lambda: fx.succeed(id))
    )


PERSISTENCE_LAYER = C.layer_persisted(store_id="chat").pipe(
    layer.provide_merge(persistence.layer_backing_memory)
)

_FILE_DATA = [
    pytest.param(bytes([0, 137, 255, 65]), id="bytes"),
    pytest.param("dGVzdA==", id="string"),
    pytest.param(Url("https://example.com/file.txt"), id="URL"),
]


def _file_prompt(data: P.FileData) -> P.Prompt:
    return P.make([P.UserMessage(content=(P.FilePart(media_type="text/plain", data=data),))])


@pytest.mark.parametrize("data", _FILE_DATA)
@testing.effect
def test_round_trips_file_through_export_json(data: P.FileData):
    """Chat / round-trips file <name> through exportJson/fromJson"""
    prompt = _file_prompt(data)
    chat = yield from C.from_prompt(prompt)
    restored = yield from C.from_json((yield from chat.export_json))
    assert (yield from restored.history.get()) == prompt


@pytest.mark.parametrize("data", _FILE_DATA)
@testing.effect
def test_round_trips_file_through_serialized_export(data: P.FileData):
    """Chat / round-trips file <name> through JSON-serialized export/fromExport"""
    prompt = _file_prompt(data)
    chat = yield from C.from_prompt(prompt)
    exported = json.loads(json.dumps((yield from chat.export)))
    restored = yield from C.from_export(exported)
    assert (yield from restored.history.get()) == prompt


@pytest.mark.parametrize("data", _FILE_DATA)
@testing.effect
def test_round_trips_file_through_json_backed_persistence(data: P.FileData):
    """Chat / round-trips file <name> through JSON-backed persistence"""

    def body():
        chats = yield from C.Persistence()
        chat = yield from chats.get_or_create("1")
        yield from chat.generate_text(_file_prompt(data)).pipe(
            with_language_model(generate_text=[{"type": "text", "text": "Received"}])
        )
        expected = yield from chat.history.get()
        restored = yield from chats.get("1")
        reopened = yield from chats.get_or_create("1")
        assert (yield from restored.history.get()) == expected
        assert (yield from reopened.history.get()) == expected

    kvs = C.layer_persisted(store_id="chat").pipe(
        layer.provide(
            persistence.layer_backing_kvs.pipe(layer.provide(key_value_store.layer_memory))
        )
    )
    yield from fx.gen(body).pipe(fx.provide(kvs))


@testing.effect
def test_keeps_partial_text_when_interrupted():
    """Chat / keeps partial assistant text when streamText is interrupted"""
    chat = yield from C.empty
    from pyfect.stream import _constructors as streams

    parts = [
        {"type": "text-start", "id": "t1"},
        {"type": "text-delta", "id": "t1", "delta": "Hello"},
        {"type": "text-end", "id": "t1"},
    ]
    yield from (
        chat.stream_text("hi")
        .take(2)
        .run_drain()
        .pipe(with_language_model(stream_text=lambda _: streams.from_iterable(parts).rechunk(1)))
    )
    assert (yield from chat.history.get()) == P.make(
        [
            {"role": "user", "content": "hi"},
            {"role": "assistant", "content": [{"type": "text", "text": "Hello"}]},
        ]
    )


class _Empty(TypedDict):
    pass


@testing.effect
def test_does_not_replay_completed_approved_tool():
    """Chat / does not replay a completed approved tool"""
    executions = [0]
    counter = T.make("Counter", parameters=S.Struct(_Empty), success=S.Number, needs_approval=True)
    kit = K.make(counter)

    def count(_: object, __: object) -> fx.Effect[float]:
        def run() -> float:
            executions[0] += 1
            return executions[0]

        return fx.sync(run)

    def body():
        chat = yield from C.empty
        initial = yield from chat.generate_text("Run the counter", toolkit=kit).pipe(
            with_language_model(
                generate_text=[
                    {"type": "tool-call", "id": "counter-call", "name": "Counter", "params": {}}
                ]
            )
        )
        approval = next(p for p in initial.content if p.type == "tool-approval-request")
        yield from chat.generate_text(
            [
                P.ToolMessage(
                    content=(
                        P.ToolApprovalResponsePart(approval_id=approval.approval_id, approved=True),
                    )
                )
            ],
            toolkit=kit,
        ).pipe(with_language_model(generate_text=[{"type": "text", "text": "Complete"}]))
        yield from chat.generate_text("Continue", toolkit=kit).pipe(
            with_language_model(generate_text=[{"type": "text", "text": "Continued"}])
        )
        assert executions[0] == 1

    yield from fx.gen(body).pipe(fx.provide(kit.to_layer(counter.handler(count))))


_FINISH: Any = {
    "type": "finish",
    "reason": "stop",
    "usage": {"inputTokens": {"uncached": 5, "total": 5}, "outputTokens": {"total": 5}},
}


@testing.effect
def test_preserves_approval_results_when_streaming_with_tool_call_resolution_disabled():
    """Chat / preserves approval results when streaming with tool call resolution disabled"""
    executions = [0]
    counter = T.make("Counter", parameters=S.Struct(_Empty), success=S.Number, needs_approval=True)
    kit = K.make(counter)

    def count(_: object, __: object) -> fx.Effect[float]:
        def run() -> float:
            executions[0] += 1
            return executions[0]

        return fx.sync(run)

    provide = with_language_model(stream_text=[_FINISH])

    def body():
        chat = yield from C.empty
        initial = yield from chat.generate_text("Run the counters", toolkit=kit).pipe(
            with_language_model(
                generate_text=[
                    {"type": "tool-call", "id": "approved", "name": "Counter", "params": {}},
                    {"type": "tool-call", "id": "denied", "name": "Counter", "params": {}},
                ]
            )
        )
        responses = tuple(
            P.ToolApprovalResponsePart(
                approval_id=part.approval_id, approved=part.tool_call_id == "approved"
            )
            for part in initial.content
            if part.type == "tool-approval-request"
        )
        parts = (
            yield from chat.stream_text(
                [P.ToolMessage(content=responses)], toolkit=kit, disable_tool_call_resolution=True
            )
            .run_collect()
            .pipe(provide)
        )

        assert [part.id if part.type == "tool-result" else part.type for part in parts] == [
            "approved",
            "denied",
            "finish",
        ]
        assert executions[0] == 1

        yield from (
            chat.stream_text("Continue", toolkit=kit, disable_tool_call_resolution=True)
            .run_drain()
            .pipe(provide)
        )

        assert executions[0] == 1

    yield from fx.gen(body).pipe(fx.provide(kit.to_layer(counter.handler(count))))


def _stored(store_id: str, chat_id: str) -> fx.Effect[P.Prompt | None, Any, Any]:
    def body():
        backing = yield from BackingPersistence()
        store = yield from backing.make(store_id)
        encoded = yield from store.get(chat_id)
        if encoded is None:
            return None
        return (yield from S.decode_unknown_effect(P.Prompt)(encoded))

    return fx.gen(body)


OPTIONS = {C.PERSISTENCE_KEY: {"messageId": "msg_abc123"}}


def _expected(options: dict[str, Any]) -> P.Prompt:
    return P.make(
        [
            {
                "role": "user",
                "content": [{"type": "text", "text": "test user message"}],
                "options": options,
            },
            {
                "role": "assistant",
                "content": [{"type": "text", "text": "test assistant message"}],
                "options": options,
            },
        ]
    )


class _Key(TypedDict):
    key: str


class _Answer(TypedDict):
    answer: str


Lookup = T.make("Lookup", parameters=S.Struct(_Key), success=S.String)
LoopToolkit = K.make(Lookup)
LoopToolkitLayer = LoopToolkit.to_layer(
    Lookup.handler(lambda params, _: fx.succeed(f"value of {params['key']}"))
)


@testing.effect
def test_allow_empty_keeps_tool_history():
    """Chat / generateObject with allowEmpty preserves tool calls and results in history"""

    def body():
        chat = yield from C.empty
        response = yield from chat.generate_object(
            "Look it up", schema=S.Struct(_Answer), toolkit=LoopToolkit, allow_empty=True
        ).pipe(
            with_language_model(
                generate_text=[
                    {"type": "tool-call", "id": "call-1", "name": "Lookup", "params": {"key": "a"}},
                    {
                        "type": "finish",
                        "reason": "tool-calls",
                        "usage": {"inputTokens": {}, "outputTokens": {}},
                    },
                ]
            )
        )
        assert response.value is None
        assert (yield from chat.history.get()) == P.make(
            [
                {"role": "user", "content": "Look it up"},
                {
                    "role": "assistant",
                    "content": [
                        {
                            "type": "tool-call",
                            "id": "call-1",
                            "name": "Lookup",
                            "params": {"key": "a"},
                        }
                    ],
                },
                {
                    "role": "tool",
                    "content": [
                        {
                            "type": "tool-result",
                            "id": "call-1",
                            "name": "Lookup",
                            "result": "value of a",
                            "isFailure": False,
                        }
                    ],
                },
            ]
        )

    yield from fx.gen(body).pipe(fx.provide(LoopToolkitLayer))


@testing.effect
def test_persists_history():
    """Chat / should persist chat history to the backing persistence store"""

    def body():
        chats = yield from C.Persistence()
        chat = yield from chats.get_or_create("1")
        yield from chat.generate_text("test user message").pipe(
            with_language_model(generate_text=[{"type": "text", "text": "test assistant message"}])
        )
        history = yield from chat.history.get()
        assert history == _expected(OPTIONS)
        assert history == (yield from _stored("chat", "1"))

    yield from fx.gen(body).pipe(_constant_ids("msg_abc123")).pipe(fx.provide(PERSISTENCE_LAYER))


@testing.effect
def test_respects_time_to_live():
    """Chat / should respect the specified time to live"""

    def body():
        chats = yield from C.Persistence()
        chat = yield from chats.get_or_create("1", time_to_live=millis(2_592_000_000))
        yield from chat.generate_text("test user message").pipe(
            with_language_model(generate_text=[{"type": "text", "text": "test assistant message"}])
        )
        assert (yield from _stored("chat", "1")) == _expected(OPTIONS)
        yield from testing.adjust(millis(2_592_000_000))
        assert (yield from _stored("chat", "1")) is None

    yield from fx.gen(body).pipe(_constant_ids("msg_abc123")).pipe(fx.provide(PERSISTENCE_LAYER))


@testing.effect
def test_prefers_most_recent_assistant_message_id():
    """Chat / should prefer the message identifier of the most recent assistant message"""
    options = {C.PERSISTENCE_KEY: {"messageId": "msg_123abc"}}

    def body():
        chats = yield from C.Persistence()
        chat = yield from chats.get_or_create("2")
        history = P.make(
            [
                {"role": "user", "content": "first user message", "options": options},
                {"role": "assistant", "content": "first assistant message", "options": options},
            ]
        )
        yield from chat.history.set(history)
        yield from chat.save
        yield from chat.generate_text("second user message").pipe(
            with_language_model(
                generate_text=[{"type": "text", "text": "second assistant message"}]
            )
        )
        expected = history.concat(
            [
                {"role": "user", "content": "second user message", "options": options},
                {"role": "assistant", "content": "second assistant message", "options": options},
            ]
        )
        assert (yield from _stored("chat", "2")) == expected

    yield from fx.gen(body).pipe(_constant_ids("msg_abc123")).pipe(fx.provide(PERSISTENCE_LAYER))


@testing.effect
def test_missing_chat_fails():
    """Chat / should raise an error when retrieving a chat that does not exist"""

    def body():
        chats = yield from C.Persistence()
        error = yield from chats.get("chat-321").flip()
        assert isinstance(error, C.ChatNotFoundError)
        assert error.chat_id == "chat-321"

    yield from fx.gen(body).pipe(fx.provide(PERSISTENCE_LAYER))


@testing.effect
def test_invalid_history_fails():
    """Chat / should raise an error when retrieving a chat with invalid history"""

    def body():
        backing = yield from BackingPersistence()
        chats = yield from C.Persistence()
        store = yield from backing.make("chat")
        yield from store.set("1", {"content": [{"role": "unknown"}]}, None)
        error = yield from chats.get("1").flip()
        assert isinstance(error, persistence.PersistenceError)

    yield from fx.gen(body).pipe(fx.provide(PERSISTENCE_LAYER))


class LookupParams(TypedDict):
    key: str


Lookup = T.make("Lookup", parameters=S.Struct(LookupParams), success=S.String)

# Executed by the application, which answers in a later request
Ask = T.dynamic(
    "Ask",
    parameters={
        "type": "object",
        "properties": {"question": {"type": "string"}},
        "required": ["question"],
    },
    execution="client",
)

LoopToolkit = K.make(Lookup, Ask)

LoopToolkitLayer = LoopToolkit.to_layer(
    Lookup.handler(lambda params, _: fx.succeed(f"value of {params['key']}"))
)


def _finish(reason: str) -> dict[str, Any]:
    return {"type": "finish", "reason": reason, "usage": {"inputTokens": {}, "outputTokens": {}}}


def _lookup_round(id: str) -> list[dict[str, Any]]:
    return [
        {"type": "tool-call", "id": id, "name": "Lookup", "params": {"key": id}},
        _finish("tool-calls"),
    ]


def _with_rounds(rounds: list[list[dict[str, Any]]]) -> tuple[list[P.Prompt], ProvideModel]:
    """Answers each model request with the next round and records its prompt."""
    prompts: list[P.Prompt] = []

    def stream_text(options: Any) -> list[dict[str, Any]]:
        prompts.append(options.prompt)
        index = len(prompts) - 1
        return list(rounds[index]) if index < len(rounds) else [_finish("stop")]

    return prompts, with_language_model(stream_text=stream_text)


@testing.effect
def test_continues_with_tool_results_until_a_round_needs_no_tools():
    """Chat / streamText step loop / continues with tool results until a round needs no tools"""
    prompts, provide = _with_rounds(
        [
            _lookup_round("call-1"),
            [
                {"type": "text-start", "id": "t1"},
                {"type": "text-delta", "id": "t1", "delta": "Done"},
                {"type": "text-end", "id": "t1"},
                _finish("stop"),
            ],
        ]
    )
    chat = yield from C.empty
    parts = yield from provide(
        chat.stream_text("Look it up", toolkit=LoopToolkit, max_steps=5)
        .run_collect()
        .pipe(fx.provide(LoopToolkitLayer))
    )
    assert len(prompts) == 2
    assert [part.reason for part in parts if isinstance(part, R.FinishPart)] == [
        "tool-calls",
        "stop",
    ]
    # The second round sees the first round's tool result
    assert any(
        isinstance(message, P.ToolMessage)
        and any(
            isinstance(part, P.ToolResultPart) and part.id == "call-1" for part in message.content
        )
        for message in prompts[1].content
    )
    # History keeps each round as its own assistant and tool messages
    history = yield from chat.history.get()
    assert [message.role for message in history.content] == [
        "user",
        "assistant",
        "tool",
        "assistant",
    ]


@testing.effect
def test_runs_one_round_by_default_and_at_most_max_steps_rounds():
    """Chat / streamText step loop / runs one round by default and at most maxSteps rounds"""
    rounds = [_lookup_round("call-1"), _lookup_round("call-2"), _lookup_round("call-3")]

    single, provide_single = _with_rounds(rounds)
    chat = yield from C.empty
    yield from provide_single(
        chat.stream_text("Look it up", toolkit=LoopToolkit)
        .run_drain()
        .pipe(fx.provide(LoopToolkitLayer))
    )
    assert len(single) == 1

    limited, provide_limited = _with_rounds(rounds)
    chat = yield from C.empty
    yield from provide_limited(
        chat.stream_text("Look it up", toolkit=LoopToolkit, max_steps=2)
        .run_drain()
        .pipe(fx.provide(LoopToolkitLayer))
    )
    assert len(limited) == 2


@testing.effect
def test_stops_when_a_client_executed_tool_call_is_left_for_the_application():
    """Chat / streamText step loop / stops when a client-executed tool call is left for the application"""  # noqa: E501
    prompts, provide = _with_rounds(
        [
            [
                {"type": "tool-call", "id": "call-1", "name": "Lookup", "params": {"key": "a"}},
                {
                    "type": "tool-call",
                    "id": "call-2",
                    "name": "Ask",
                    "params": {"question": "Proceed?"},
                },
                _finish("tool-calls"),
            ]
        ]
    )
    chat = yield from C.empty
    parts = yield from provide(
        chat.stream_text("Look it up", toolkit=LoopToolkit, max_steps=5)
        .run_collect()
        .pipe(fx.provide(LoopToolkitLayer))
    )
    assert len(prompts) == 1
    assert [
        part.id for part in parts if isinstance(part, R.ToolResultSuccess | R.ToolResultFailure)
    ] == ["call-1"]
