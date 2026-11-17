"""Serves Agent User Interaction (AG-UI) runs over HTTP (Effect's ``AgUiServer``).

AG-UI clients POST a ``RunAgentInput`` as JSON and read the run's events as Server-Sent
Events, one JSON event per ``data:`` line. ``endpoint`` declares that binding as an
``HttpApiEndpoint``, so it can join an existing ``HttpApi``, and ``layer_http`` mounts a
single run on the ``HttpRouter``. ``agent`` serves the current ``LanguageModel`` with
server tools, frontend tools and several model rounds::

    AgentRoute = ag_ui_server.layer_http(
        path="/agent",
        agent=ag_ui_server.agent(toolkit=Tools, system="Be brief", max_steps=5),
    )
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Generic, Literal, LiteralString, Never, TypedDict, TypeVar, cast, overload

import pyfect as fx
from pyfect import layer as L
from pyfect import schema as S
from pyfect._core import Effect
from pyfect.ai import ag_ui
from pyfect.ai import chat as C
from pyfect.ai import language_model as lm
from pyfect.ai import response as R
from pyfect.ai import tool as T
from pyfect.ai import toolkit as K
from pyfect.ai.ag_ui_schema import EVENT, RUN_AGENT_INPUT, Event, RunAgentInput, TokenUsage
from pyfect.ai.id_generator import IdGenerator, default_id_generator
from pyfect.context import Context, Tag
from pyfect.http.router import HttpRouter
from pyfect.http_api import builder
from pyfect.http_api import endpoint as ep
from pyfect.http_api import schema as api_schema
from pyfect.http_api._handlers import HttpApiRequest
from pyfect.http_api.api import HttpApi
from pyfect.http_api.endpoint import HttpApiEndpoint
from pyfect.http_api.error import BadRequest
from pyfect.http_api.group import HttpApiGroup
from pyfect.json_schema import JsonSchema
from pyfect.layer import Layer
from pyfect.stream import Stream
from pyfect.stream import _constructors as StreamC
from pyfect.stream import _context as StreamContext

R_co = TypeVar("R_co", covariant=True)

_CacheControl = TypedDict("_CacheControl", {"cache-control": Literal["no-cache"]})

_NO_CACHE: _CacheControl = {"cache-control": "no-cache"}

type Response = api_schema.WithHeadersValue[Stream[Event, Never], _CacheControl]
"""What an AG-UI endpoint's handler answers: the run's events, not cached."""

type Request = HttpApiRequest[Any, Any, RunAgentInput, Any]


def endpoint(
    name: str, path: str
) -> HttpApiEndpoint[None, None, RunAgentInput, Any, None, Response, Any, BadRequest]:
    """The ``POST`` endpoint declaration of AG-UI runs, to add to an existing ``HttpApi``
    and implement with ``handler`` or ``agent_handler``.

    The payload is a JSON ``RunAgentInput``, so an invalid body is rejected with 400 before
    the event stream opens, as is input an ``agent`` rejects. The success response is a
    ``text/event-stream`` of AG-UI events sent as ``data:`` lines, with
    ``Cache-Control: no-cache`` and a keepalive comment every 15 seconds."""
    success = api_schema.WithHeaders(
        api_schema.StreamSse(data=EVENT, keep_alive="15 seconds"), S.Struct(_CacheControl)
    )
    return cast(
        "Any", ep.post(name, path, payload=RUN_AGENT_INPUT, success=success, error=BadRequest)
    )


_EVENT_JSON = S.from_json_string(EVENT)
_encode_event = S.encode_unknown_effect(_EVENT_JSON)
_decode_event = S.decode_unknown_effect(_EVENT_JSON)


def _normalize_event(event: Event) -> Effect[Event, S.SchemaError]:
    """The event round-tripped through its JSON text, so an event that cannot be encoded
    fails the run (a sanitized ``RUN_ERROR``) here rather than as an HttpApi stream failure,
    and what HttpApi encodes again is plain JSON data that already passed it."""
    return _encode_event(event).flat_map(_decode_event)


def _respond[E, RR](
    input: RunAgentInput, events: Stream[Event, E, RR], context: Context[RR]
) -> Response:
    body = (
        events.map_effect(_normalize_event)
        .pipe(ag_ui.with_run_lifecycle(input))
        .pipe(StreamContext.provide_context(context))
    )
    return api_schema.with_headers(body, _NO_CACHE)


def handler[E, RR](
    run: Callable[[RunAgentInput], Stream[Event, E, RR]],
) -> Callable[[Request], Effect[Response, Never, RR]]:
    """An ``HttpApiBuilder`` handler for an ``endpoint`` from a function streaming the
    events of one run.

    The stream is wrapped with ``ag_ui.with_run_lifecycle``, so the client receives
    ``RUN_STARTED`` first and exactly one ``RUN_FINISHED`` or ``RUN_ERROR`` last. Failures
    of the stream, events that cannot be encoded as JSON included, are logged and
    reported, and reach the client as a ``RUN_ERROR`` without error details. The stream
    runs with the services available to the handler."""

    def handle(request: Request) -> Effect[Response, Never, RR]:
        payload = request.payload
        return fx.context().map(
            lambda context: _respond(payload, run(payload), cast("Context[RR]", context))
        )

    return handle


# --- agent ---------------------------------------------------------------------------------


class RunInput(Tag[RunAgentInput], key="effect/ai/AgUiServer/RunInput"):
    """The input of the AG-UI run being served, for a server tool's handler that reads the
    run's ``threadId``, ``runId``, ``state`` or ``forwardedProps``: declare it in the
    tool's ``dependencies`` and ``agent`` provides it for each run."""


@dataclass(frozen=True)
class Agent(Generic[R_co]):
    """An AG-UI agent ``layer_http`` serves: ``run`` either rejects the input, answering
    the request with 400, or returns the run's event stream. ``R_co`` is the services the
    agent needs."""

    run: Callable[[RunAgentInput], Effect[Stream[Event, object, R_co], BadRequest]]


def agent_handler[RR](
    agent: Agent[RR],
) -> Effect[Callable[[Request], Effect[Response, BadRequest]], Never, RR]:
    """An ``HttpApiBuilder`` handler for an ``endpoint`` that serves ``agent``; yield it
    while building the ``builder.group`` implementing the endpoint.

    The services the agent needs are captured when the handler is made. Each request
    first runs the agent's validation, so a rejected input is answered with 400 before the
    event stream opens; the events are then served as ``handler`` describes."""

    def make(context: Context[Any]) -> Callable[[Request], Effect[Response, BadRequest]]:
        def handle(request: Request) -> Effect[Response, BadRequest]:
            payload = request.payload
            return agent.run(payload).map(lambda events: _respond(payload, events, context))

        return handle

    return fx.context().map(make)


def _from_run(run: Callable[[RunAgentInput], Stream[Event, Any, Any]]) -> Agent[Any]:
    return Agent(lambda input: fx.succeed(run(input)))


@overload
def layer_http[RR](
    *, path: str, agent: Agent[RR], run: None = None
) -> Layer[Never, Never, HttpRouter | RR]: ...
@overload
def layer_http[E, RR](
    *, path: str, run: Callable[[RunAgentInput], Stream[Event, E, RR]], agent: None = None
) -> Layer[Never, Never, HttpRouter | RR]: ...
def layer_http(
    *,
    path: str,
    agent: Agent[Any] | None = None,
    run: Callable[[RunAgentInput], Stream[Event, Any, Any]] | None = None,
) -> Layer[Never, Never, Any]:
    """Serves AG-UI runs at ``path`` of the current ``HttpRouter``, answering each with
    ``agent`` or the events ``run`` streams (see ``handler``).

    Every field of the input comes from the client: convert it with ``ag_ui.to_prompt``,
    which drops client-supplied instructions by default."""
    if agent is None and run is None:
        raise TypeError("ag_ui_server.layer_http needs an agent or a run function")
    group = HttpApiGroup.make("agUi").add(endpoint("run", path))
    api = HttpApi.make("effect/ai/AgUiServer").add(group)
    served = agent if agent is not None else _from_run(cast("Any", run))
    run_endpoint = group.endpoints["run"]
    handlers = builder.group(
        api,
        group,
        lambda empty: agent_handler(served).map(empty.handle(run_endpoint)),
    )
    return cast("Any", builder.layer(api)).pipe(L.provide(handlers))


# A toolkit needing nothing gets its own overload: pyright leaves ``RR`` unsolved when it
# matches ``Never`` against ``RunInput | RR``.
@overload
def agent[N: LiteralString, RP, HE](
    *,
    toolkit: K.Toolkit[N, RP, HE, Never],
    system: str | None = None,
    max_steps: int = 1,
) -> Agent[lm.LanguageModel | K.Handlers[N]]: ...
@overload
def agent[N: LiteralString, RP, HE, RR = Never](
    *,
    toolkit: K.Toolkit[N, RP, HE, RunInput | RR],
    system: str | None = None,
    max_steps: int = 1,
) -> Agent[lm.LanguageModel | K.Handlers[N] | RR]: ...
def agent(
    *,
    toolkit: K.Toolkit[Any, Any, Any, Any],
    system: str | None = None,
    max_steps: int = 1,
) -> Agent[Any]:
    """An AG-UI agent answering each run with the current ``LanguageModel`` and
    ``toolkit``.

    - The prompt is ``system``, if given, then the run's conversation as
      ``ag_ui.to_prompt`` converts it, which drops client-supplied instructions.
    - The model is offered the server toolkit and each of the run's tools as a
      client-executed tool. A run whose tools reuse a server tool's name is rejected with
      400.
    - Rounds follow ``Chat.stream_text`` with ``max_steps``, so server tool results go back
      to the model until a round needs no tools, ``max_steps`` rounds have run, or a tool
      call is left for the application.
    - The run finishes with the token usage summed over every round. Frontend tool calls
      left for the application are listed as ``pendingToolCallIds``, and the application
      answers them with tool messages in its next run.
    - Server tool handlers can read the run's input from ``RunInput``."""
    server_tools = toolkit.tools

    def run(input: RunAgentInput) -> Effect[Stream[Event, object, Any], BadRequest]:
        if any(tool["name"] in server_tools for tool in input["tools"]):
            return fx.fail(BadRequest())
        frontend = [
            T.dynamic(
                cast("Any", tool["name"]),
                description=tool["description"],
                parameters=cast(
                    "JsonSchema", tool.get("parameters", {"type": "object", "properties": {}})
                ),
                execution="client",
            )
            for tool in input["tools"]
        ]
        merged = K.merge(toolkit, K.make(*frontend))
        conversation = ag_ui.to_prompt(input)
        prompt = conversation if system is None else conversation.prepend_system(system)
        summary = _RunSummary(input, merged.tools)

        def events(chat: C.Service) -> Stream[Event, object, Any]:
            parts = cast(
                "Stream[R.AnyPart, object, Any]",
                chat.stream_text(prompt, toolkit=merged, max_steps=max_steps),
            )
            ids = fx.service_option(IdGenerator).map(
                lambda found: found.value if found is not None else default_id_generator
            )
            return (
                parts.tap(lambda part: fx.sync(lambda: summary.observe(part)))
                .pipe(ag_ui.from_stream_parts)
                .concat(StreamC.sync(summary.finished))
                .pipe(StreamContext.provide_service(RunInput, input))
                .pipe(StreamContext.provide_service_effect(IdGenerator, ids))
            )

        return C.empty.map(events)

    return Agent(run)


class _RunSummary:
    """What ``RUN_FINISHED`` reports: the token usage of every round and the
    client-executed tool calls nothing answered."""

    def __init__(self, input: RunAgentInput, tools: Mapping[str, T.AnyTool]) -> None:
        self.input = input
        self.client_tools = {tool.name for tool in tools.values() if T.is_client_executed(tool)}
        self.pending: dict[str, None] = {}
        self.usage: dict[str, int] = {}

    def add(self, key: str, value: int | None) -> None:
        if value is not None:
            self.usage[key] = self.usage.get(key, 0) + value

    def observe(self, part: R.AnyPart) -> None:
        match part:
            case R.ToolCallPart(id=id, name=name) if name in self.client_tools:
                self.pending[id] = None
            case R.ToolResultSuccess() | R.ToolResultFailure() if not part.preliminary:
                self.pending.pop(part.id, None)
            case R.FinishPart(usage=usage):
                inputs, outputs = usage.input_tokens, usage.output_tokens
                self.add("inputTokens", inputs.total)
                self.add("outputTokens", outputs.total)
                self.add("reasoningTokens", outputs.reasoning)
                self.add("cachedInputTokens", inputs.cache_read)
                self.add("cacheWriteInputTokens", inputs.cache_write)
                if inputs.total is not None or outputs.total is not None:
                    self.add("totalTokens", (inputs.total or 0) + (outputs.total or 0))
            case _:
                pass

    def finished(self) -> Event:
        event: dict[str, object] = {
            "type": "RUN_FINISHED",
            "threadId": self.input["threadId"],
            "runId": self.input["runId"],
        }
        if self.pending:
            event["outcome"] = {"type": "success", "pendingToolCallIds": list(self.pending)}
        if self.usage:
            event["usage"] = [cast("TokenUsage", dict(self.usage))]
        return cast("Event", event)


__all__ = [
    "Agent",
    "Request",
    "Response",
    "RunInput",
    "agent",
    "agent_handler",
    "endpoint",
    "handler",
    "layer_http",
]
