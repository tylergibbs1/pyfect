"""Ports of Effect's ``test/ai/AgUiServer.test.ts``.

Each test's docstring is the Effect test title (with its ``describe``). Requests go
through ``router.to_web_handler``, as Effect's go through ``HttpRouter.toWebHandler``.

Omitted: ``reports an event that is invalid once serialized as RUN_ERROR``. Its event
(a ``CUSTOM`` whose required ``value`` is ``undefined``) loses a key only because
``JSON.stringify`` drops ``undefined``; Python has no ``undefined`` and JSON keeps every
key, so no event passes encoding and fails once serialized.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, TypedDict, cast

import pyfect as fx
from pyfect import layer
from pyfect import schema as S
from pyfect.ai import ag_ui_schema, ag_ui_server
from pyfect.ai import language_model as lm
from pyfect.ai import prompt as P
from pyfect.ai import tool as T
from pyfect.ai import toolkit as K
from pyfect.http import router, server
from pyfect.http.web import WebRequest, WebResponse
from pyfect.http_api import builder, openapi
from pyfect.http_api.api import HttpApi
from pyfect.http_api.group import HttpApiGroup
from pyfect.stream import _constructors as streams

type Handler = Callable[[WebRequest], Awaitable[WebResponse]]


def _serve[A](app: fx.Layer[Any, Any, Any], use: Callable[[Handler], Awaitable[A]]) -> A:
    async def main() -> A:
        made = router.to_web_handler(
            app.pipe(layer.provide(server.layer_services)), disable_logger=True
        )
        try:
            return await use(made.handler)
        finally:
            await made.dispose()

    return asyncio.run(main())


def _post(body: object) -> WebRequest:
    return WebRequest(
        "http://test/agent",
        method="POST",
        headers={"content-type": "application/json", "accept": "text/event-stream"},
        body=json.dumps(body).encode(),
    )


async def _read_events(response: WebResponse) -> list[Any]:
    """Every frame must be a single ``data:`` line, because AG-UI clients such as TanStack
    AI read only ``data:`` lines."""
    text = await response.text()
    assert text.endswith("\n\n")
    events: list[Any] = []
    for frame in text[:-2].split("\n\n"):
        assert frame.startswith("data: "), frame
        assert "\n" not in frame, frame
        events.append(json.loads(frame.removeprefix("data: ")))
    return events


def _with_run(run: Callable[[ag_ui_schema.RunAgentInput], Any]) -> fx.Layer[Any, Any, Any]:
    return ag_ui_server.layer_http(path="/agent", run=run)


_INPUT = {
    "threadId": "thread-1",
    "runId": "run-1",
    "messages": [{"id": "1", "role": "user", "content": "Hi"}],
}
_STARTED = {
    "type": "RUN_STARTED",
    "threadId": "thread-1",
    "runId": "run-1",
    "protocolVersion": "1.0",
}
_FINISHED = {"type": "RUN_FINISHED", "threadId": "thread-1", "runId": "run-1"}


class LookupParams(TypedDict):
    key: str


# A server tool that reads the run it serves
Lookup = T.make(
    "Lookup",
    parameters=S.Struct(LookupParams),
    success=S.String,
    dependencies=[ag_ui_server.RunInput],
)

AgentToolkit = K.make(Lookup)


def _lookup(_params: LookupParams, _ctx: T.HandlerContext[str]) -> fx.Effect[str, Any, Any]:
    return ag_ui_server.RunInput().map(lambda input: input["threadId"])


AgentToolkitLayer = AgentToolkit.to_layer(Lookup.handler(_lookup))


class Question(TypedDict):
    question: str


# A client-executed tool configured on the server rather than sent by the application
Confirm = T.make("Confirm", parameters=S.Struct(Question), success=S.Boolean, execution="client")


def _finish(reason: str) -> lm.EncodedPart:
    return {
        "type": "finish",
        "reason": reason,
        "usage": {"inputTokens": {"total": 3}, "outputTokens": {"total": 2}},
    }


@dataclass
class _Request:
    prompt: P.Prompt
    tools: list[str]


@dataclass
class _FakeModel:
    """A model answering each request with the next round, recording the prompt and tool
    names it was given."""

    rounds: Sequence[Sequence[lm.EncodedPart]]
    requests: list[_Request] = field(default_factory=list[_Request])

    @property
    def layer(self) -> fx.Layer[Any, Any, Any]:
        def stream_text(options: lm.ProviderOptions) -> Any:
            names = sorted(tool.name for tool in options.tools)
            self.requests.append(_Request(options.prompt, names))
            index = len(self.requests) - 1
            parts = self.rounds[index] if index < len(self.rounds) else [_finish("stop")]
            return streams.from_iterable(parts)

        model = lm.make(generate_text=lambda _: fx.succeed([]), stream_text=stream_text)
        return fx.layer.effect(lm.LanguageModel, model)


def _serve_agent(
    rounds: Sequence[Sequence[lm.EncodedPart]], agent: ag_ui_server.Agent[Any] | None = None
) -> tuple[_FakeModel, fx.Layer[Any, Any, Any]]:
    model = _FakeModel(rounds)
    served = agent or ag_ui_server.agent(toolkit=AgentToolkit, system="Be brief", max_steps=5)
    app = (
        ag_ui_server.layer_http(path="/agent", agent=served)
        .pipe(layer.provide(model.layer))
        .pipe(layer.provide(AgentToolkitLayer))
    )
    return model, app


def _stable_ids(events: list[Any]) -> list[Any]:
    """Generated message ids differ per run."""
    return [
        {**event, "messageId": "<id>"} if event["type"] == "TOOL_CALL_RESULT" else event
        for event in events
    ]


def test_streams_a_run_hooks_events_as_ag_ui_server_sent_events() -> None:
    """AgUiServer / streams a run hook's events as AG-UI server-sent events"""

    def run(input: ag_ui_schema.RunAgentInput) -> Any:
        delta = f"tools: {len(input['tools'])}"
        events: list[ag_ui_schema.Event] = [
            {"type": "TEXT_MESSAGE_START", "messageId": input["runId"], "role": "assistant"},
            {"type": "TEXT_MESSAGE_CONTENT", "messageId": input["runId"], "delta": delta},
        ]
        return streams.from_iterable(events)

    async def use(handler: Handler) -> None:
        response = await handler(_post(_INPUT))
        assert response.status == 200
        assert (response.get("content-type") or "").startswith("text/event-stream")
        assert response.get("cache-control") == "no-cache"
        assert await _read_events(response) == [
            _STARTED,
            {"type": "TEXT_MESSAGE_START", "messageId": "run-1", "role": "assistant"},
            {"type": "TEXT_MESSAGE_CONTENT", "messageId": "run-1", "delta": "tools: 0"},
            {"type": "TEXT_MESSAGE_END", "messageId": "run-1"},
            _FINISHED,
        ]

    _serve(_with_run(run), use)


def test_serves_the_run_overload_when_an_undefined_agent_property_is_present() -> None:
    """AgUiServer / serves the run overload when an undefined agent property is present"""
    app = ag_ui_server.layer_http(path="/agent", agent=None, run=lambda _: streams.empty)

    async def use(handler: Handler) -> None:
        response = await handler(_post(_INPUT))
        assert response.status == 200
        assert await _read_events(response) == [_STARTED, _FINISHED]

    _serve(app, use)


def test_rejects_an_invalid_run_agent_input_before_opening_the_stream() -> None:
    """AgUiServer / rejects an invalid RunAgentInput before opening the stream"""

    async def use(handler: Handler) -> None:
        response = await handler(_post({"threadId": "thread-1"}))
        assert response.status == 400
        assert not (response.get("content-type") or "").startswith("text/event-stream")

    _serve(_with_run(lambda _: streams.empty), use)


def test_reports_a_failing_run_hook_as_run_error() -> None:
    """AgUiServer / reports a failing run hook as RUN_ERROR"""

    async def use(handler: Handler) -> None:
        response = await handler(_post(_INPUT))
        events = await _read_events(response)
        assert response.status == 200
        assert events[0] == _STARTED
        assert len(events) == 2
        assert events[1] == {"type": "RUN_ERROR", "message": "The agent run failed."}

    _serve(_with_run(lambda _: streams.fail(RuntimeError("boom"))), use)


def test_reports_an_event_that_cannot_be_encoded_as_run_error() -> None:
    """AgUiServer / reports an event that cannot be encoded as RUN_ERROR"""
    # A set has no JSON form, as a bigint has none in JavaScript.
    event: Any = {"type": "CUSTOM", "name": "progress", "value": {1}}

    async def use(handler: Handler) -> None:
        events = await _read_events(await handler(_post(_INPUT)))
        assert len(events) == 2
        assert events[0]["type"] == "RUN_STARTED"
        assert events[1]["type"] == "RUN_ERROR"

    _serve(_with_run(lambda _: streams.from_iterable([event])), use)


def test_never_serializes_an_event_outside_the_runs_error_handling() -> None:
    """AgUiServer / never serializes an event outside the run's error handling: a value
    whose JSON form can only be computed once may be delivered, serialized once, or fail
    the run, but a second serialization must not leak an HttpApi failure frame."""
    serialized = [0]

    class Once:
        def to_json(self) -> object:
            serialized[0] += 1
            if serialized[0] > 1:
                raise RuntimeError("serialized twice")
            return {"done": 1}

    event: ag_ui_schema.Event = {"type": "CUSTOM", "name": "progress", "value": Once()}

    async def use(handler: Handler) -> None:
        events = await _read_events(await handler(_post(_INPUT)))
        assert events[0]["type"] == "RUN_STARTED"
        assert events[-1]["type"] in ("RUN_FINISHED", "RUN_ERROR")
        for custom in (e for e in events if e["type"] == "CUSTOM"):
            assert custom == {"type": "CUSTOM", "name": "progress", "value": {"done": 1}}

    _serve(_with_run(lambda _: streams.from_iterable([event])), use)


def test_runs_the_model_with_server_tools_until_it_answers() -> None:
    """AgUiServer / agent / runs the model with server tools until it answers"""
    model, app = _serve_agent(
        [
            [
                {"type": "tool-call", "id": "call-1", "name": "Lookup", "params": {"key": "a"}},
                _finish("tool-calls"),
            ],
            [
                {"type": "text-start", "id": "m1"},
                {"type": "text-delta", "id": "m1", "delta": "Done"},
                {"type": "text-end", "id": "m1"},
                _finish("stop"),
            ],
        ]
    )

    async def use(handler: Handler) -> None:
        events = await _read_events(await handler(_post(_INPUT)))
        # The server's system prompt comes first, ahead of the client's conversation
        assert len(model.requests) == 2
        first = model.requests[0].prompt.content
        assert [message.role for message in first] == ["system", "user"]
        assert first[0] == P.SystemMessage(content="Be brief")
        assert _stable_ids(events) == [
            _STARTED,
            {"type": "STEP_STARTED", "stepName": "step-1"},
            {"type": "TOOL_CALL_START", "toolCallId": "call-1", "toolCallName": "Lookup"},
            {"type": "TOOL_CALL_ARGS", "toolCallId": "call-1", "delta": '{"key":"a"}'},
            {"type": "TOOL_CALL_END", "toolCallId": "call-1"},
            {
                "type": "TOOL_CALL_RESULT",
                "messageId": "<id>",
                "toolCallId": "call-1",
                "content": "thread-1",
            },
            {"type": "STEP_FINISHED", "stepName": "step-1"},
            {"type": "STEP_STARTED", "stepName": "step-2"},
            {"type": "TEXT_MESSAGE_START", "messageId": "m1", "role": "assistant"},
            {"type": "TEXT_MESSAGE_CONTENT", "messageId": "m1", "delta": "Done"},
            {"type": "TEXT_MESSAGE_END", "messageId": "m1"},
            {"type": "STEP_FINISHED", "stepName": "step-2"},
            {**_FINISHED, "usage": [{"inputTokens": 6, "outputTokens": 4, "totalTokens": 10}]},
        ]

    _serve(app, use)


def test_finishes_with_the_frontend_tool_calls_left_for_the_application() -> None:
    """AgUiServer / agent / finishes with the frontend tool calls left for the application"""
    model, app = _serve_agent(
        [
            [
                {
                    "type": "tool-call",
                    "id": "call-1",
                    "name": "confirm",
                    "params": {"question": "Proceed?"},
                },
                _finish("tool-calls"),
            ]
        ]
    )
    tool = {
        "name": "confirm",
        "description": "Asks the user to confirm",
        "parameters": {
            "type": "object",
            "properties": {"question": {"type": "string"}},
            "required": ["question"],
        },
    }

    async def use(handler: Handler) -> None:
        events = await _read_events(await handler(_post({**_INPUT, "tools": [tool]})))
        assert len(model.requests) == 1
        assert model.requests[0].tools == ["Lookup", "confirm"]
        assert not any(event["type"] == "TOOL_CALL_RESULT" for event in events)
        assert events[-1] == {
            **_FINISHED,
            "outcome": {"type": "success", "pendingToolCallIds": ["call-1"]},
            "usage": [{"inputTokens": 3, "outputTokens": 2, "totalTokens": 5}],
        }

    _serve(app, use)


def test_lists_calls_to_client_executed_toolkit_tools_as_pending() -> None:
    """AgUiServer / agent / lists calls to client-executed toolkit tools as pending"""
    _, app = _serve_agent(
        [
            [
                {
                    "type": "tool-call",
                    "id": "call-1",
                    "name": "Confirm",
                    "params": {"question": "Proceed?"},
                },
                _finish("tool-calls"),
            ]
        ],
        ag_ui_server.agent(toolkit=K.make(Lookup, Confirm), max_steps=5),
    )

    async def use(handler: Handler) -> None:
        events = await _read_events(await handler(_post(_INPUT)))
        assert events[-1]["outcome"] == {"type": "success", "pendingToolCallIds": ["call-1"]}

    _serve(app, use)


def test_serves_an_agent_from_an_endpoint_in_an_existing_http_api() -> None:
    """AgUiServer / agent / serves an agent from an endpoint in an existing HttpApi"""
    model = _FakeModel(
        [
            [
                {"type": "text-start", "id": "m1"},
                {"type": "text-delta", "id": "m1", "delta": "Hi there"},
                {"type": "text-end", "id": "m1"},
                _finish("stop"),
            ]
        ]
    )
    group = HttpApiGroup.make("ai").add(ag_ui_server.endpoint("run", "/agent"))
    api = HttpApi.make("App").add(group)
    served = ag_ui_server.agent(toolkit=AgentToolkit, max_steps=5)
    ai_live = builder.group(
        api,
        group,
        lambda handlers: ag_ui_server.agent_handler(served).map(
            handlers.handle(group.endpoints["run"])
        ),
    )
    app = (
        builder.layer(api)
        .pipe(layer.provide(ai_live))
        .pipe(layer.provide(model.layer))
        .pipe(layer.provide(AgentToolkitLayer))
    )

    async def use(handler: Handler) -> None:
        events = await _read_events(await handler(_post(_INPUT)))
        assert events[0]["type"] == "RUN_STARTED"
        assert events[-1] == {
            **_FINISHED,
            "usage": [{"inputTokens": 3, "outputTokens": 2, "totalTokens": 5}],
        }
        # Validation still answers before the stream opens
        shadow = {"name": "Lookup", "description": "Shadows"}
        rejected = await handler(_post({**_INPUT, "tools": [shadow]}))
        assert rejected.status == 400
        assert len(model.requests) == 1

    _serve(app, use)


def test_rejects_a_frontend_tool_that_shadows_a_server_tool_before_the_stream_opens() -> None:
    """AgUiServer / agent / rejects a frontend tool that shadows a server tool before the stream opens"""  # noqa: E501
    model, app = _serve_agent([])

    async def use(handler: Handler) -> None:
        shadow = {"name": "Lookup", "description": "Shadows the server tool"}
        response = await handler(_post({**_INPUT, "tools": [shadow]}))
        assert response.status == 400
        assert model.requests == []

    _serve(app, use)


_ANNOTATION_KEYS = frozenset(
    {"title", "description", "examples", "default", "$comment", "deprecated"}
)


def _is_unconstrained(schema: object) -> bool:
    return not isinstance(schema, dict) or all(
        key in _ANNOTATION_KEYS
        for key in schema  # type: ignore[union-attr]
    )


def _find_problems(root: object) -> list[str]:
    """Every array must describe its items, and no union may have a branch that accepts
    anything or be empty: generated clients would reduce the union to ``unknown``, and an
    empty ``anyOf`` / ``oneOf`` is invalid JSON Schema."""
    problems: list[str] = []

    def visit(schema: object, path: str) -> None:
        if isinstance(schema, list):
            items = cast("list[object]", schema)
            for index, item in enumerate(items):
                visit(item, f"{path}/{index}")
            return
        if not isinstance(schema, dict):
            return
        node = cast("dict[str, Any]", schema)
        if node.get("type") == "array" and _is_unconstrained(node.get("items")):
            problems.append(f"{path}/items is missing")
        for key in ("anyOf", "oneOf"):
            found = node.get(key)
            if not isinstance(found, list):
                continue
            branches = cast("list[object]", found)
            if not branches:
                problems.append(f"{path}/{key} is empty")
            for index, branch in enumerate(branches):
                if _is_unconstrained(branch):
                    problems.append(f"{path}/{key}/{index} is unconstrained")
        for key, child in node.items():
            visit(child, f"{path}/{key}")

    visit(root, "")
    return problems


def _resolve(spec: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    """``schema``, through its ``$ref`` to the spec's components."""
    while "$ref" in schema:
        name = schema["$ref"].rsplit("/", 1)[-1]
        schema = spec["components"]["schemas"][name]
    return schema


def test_documents_the_item_schemas_of_the_run_input_in_open_api() -> None:
    """AgUiServer / documents the item schemas of the run input in OpenAPI"""
    api = HttpApi.make("Api").add(
        HttpApiGroup.make("agent").add(ag_ui_server.endpoint("run", "/agent"))
    )
    spec: dict[str, Any] = json.loads(json.dumps(openapi.from_api(api)))
    body = spec["paths"]["/agent"]["post"]["requestBody"]["content"]["application/json"]
    payload = _resolve(spec, body["schema"])

    assert "items" in payload["properties"]["messages"]
    assert _find_problems(spec["components"]["schemas"]) == []
    assert _find_problems(payload) == []

    # The check must catch the fallback branch surviving union flattening, at the top of a
    # union and nested inside one
    def injected(inject: Callable[[dict[str, Any]], None]) -> list[str]:
        copy = json.loads(json.dumps(payload))
        inject(copy)
        return _find_problems(copy)

    def messages(copy: dict[str, Any]) -> dict[str, Any]:
        return _resolve(spec, copy["properties"]["messages"]["items"])

    assert injected(lambda copy: messages(copy)["anyOf"].append({"anyOf": []}))
    assert injected(lambda copy: copy["properties"]["resume"].update(items={"anyOf": []}))
