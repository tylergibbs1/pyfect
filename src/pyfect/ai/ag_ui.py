"""Converts between ``pyfect.ai`` values and the Agent User Interaction (AG-UI) protocol
(Effect's ``AgUi``).

An AG-UI run starts from a ``RunAgentInput`` and answers with a stream of events.
``to_prompt`` turns the input's conversation into a ``Prompt``, ``from_stream_parts``
turns the parts ``language_model.stream_text`` streams into AG-UI events, and
``with_run_lifecycle`` wraps an event stream in the run lifecycle AG-UI clients expect.
It performs no I/O; ``ag_ui_server`` serves runs over HTTP::

    def run(input: ag_ui_schema.RunAgentInput):
        return (
            language_model.stream_text(ag_ui.to_prompt(input))
            .pipe(ag_ui.from_stream_parts)
            .pipe(ag_ui.with_run_lifecycle(input))
        )
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from typing import Any, Never, TypedDict, cast

import pyfect as fx
from pyfect import error_reporter
from pyfect._core import Effect
from pyfect._json_text import parse as parse_json_text
from pyfect._json_text import stringify
from pyfect._url import Url
from pyfect.ai import prompt as P
from pyfect.ai import response as R
from pyfect.ai.ag_ui_schema import (
    PROTOCOL_VERSION,
    ContentPart,
    Event,
    Metadata,
    RunAgentInput,
    ToolCallStartEvent,
)
from pyfect.ai.id_generator import IdGenerator
from pyfect.ai.id_generator import Service as IdService
from pyfect.cause import Cause
from pyfect.stream import Stream
from pyfect.stream import _constructors as StreamC

# --- prompt ----------------------------------------------------------------------------


def to_prompt(input: RunAgentInput, *, trust_client_instructions: bool = False) -> P.Prompt:
    """The conversation of an AG-UI run input as a ``Prompt``.

    - User and assistant messages keep their text. Assistant tool calls become tool-call
      parts with their JSON arguments parsed.
    - Each tool message becomes a tool message with one tool-result part, named after the
      latest preceding assistant tool call with its id, since providers may reuse call ids
      across turns. Content that is valid JSON is parsed. A message with an ``error`` is a
      failed result carrying the error text, as is one carrying the failure metadata
      ``from_stream_parts`` emits (with its content).
    - User image, audio, video and document parts with inline data or a valid URL become
      file parts.
    - Activity and reasoning messages, provider file handles and tool messages that answer
      no preceding tool call are dropped.

    The whole conversation comes from the client, so ``system`` and ``developer`` messages
    and the input's ``context`` are dropped by default: a browser cannot replace the
    server's instructions. With ``trust_client_instructions`` they are kept: ``system`` and
    ``developer`` messages become system messages in place, and ``context`` a leading
    system message."""
    # Filled as messages are consumed, so each result is named after the latest preceding
    # call with its id.
    tool_names: dict[str, str] = {}
    messages: list[Mapping[str, object]] = []
    contexts = input["context"]
    if trust_client_instructions and contexts:
        text = "\n\n".join(f"{context['description']}:\n{context['value']}" for context in contexts)
        messages.append({"role": "system", "content": text})
    for message in input["messages"]:
        match message["role"]:
            case "system" | "developer":
                if trust_client_instructions:
                    messages.append({"role": "system", "content": message["content"]})
            case "user":
                content = message["content"]
                messages.append(
                    {
                        "role": "user",
                        "content": content if isinstance(content, str) else _user_parts(content),
                    }
                )
            case "assistant":
                parts: list[Mapping[str, object]] = []
                text = message.get("content")
                if text:
                    parts.append({"type": "text", "text": text})
                for call in message.get("toolCalls", []):
                    function = call["function"]
                    tool_names[call["id"]] = function["name"]
                    parts.append(
                        {
                            "type": "tool-call",
                            "id": call["id"],
                            "name": function["name"],
                            "params": _parse_json(function["arguments"]),
                        }
                    )
                if parts:
                    messages.append({"role": "assistant", "content": parts})
            case "tool":
                name = tool_names.get(message["toolCallId"])
                if name is None:
                    continue
                error = message.get("error")
                content = message["content"]
                result: object = (
                    error
                    if error is not None
                    else _parse_json(content)
                    if isinstance(content, str)
                    else content
                )
                failed = error is not None or _has_failure_marker(message.get("metadata"))
                part = {
                    "type": "tool-result",
                    "id": message["toolCallId"],
                    "name": name,
                    "isFailure": failed,
                    "result": result,
                }
                messages.append({"role": "tool", "content": [part]})
            case "activity" | "reasoning":
                pass
    return P.make(messages)


def _has_failure_marker(metadata: Metadata | None) -> bool:
    """The marker ``from_stream_parts`` puts on failed results, which AG-UI clients keep on
    the tool message they send back."""
    marker = (metadata or {}).get("effect/ai")
    return (
        isinstance(marker, Mapping)
        and cast("Mapping[str, object]", marker).get("isFailure") is True
    )


def _parse_json(text: str) -> object:
    try:
        return parse_json_text(text)
    except ValueError:
        return text


_DEFAULT_MEDIA_TYPE = {
    "image": "image/*",
    "audio": "audio/*",
    "video": "video/*",
    "document": "application/octet-stream",
}


def _user_parts(parts: Sequence[ContentPart]) -> list[Mapping[str, object]]:
    out: list[Mapping[str, object]] = []
    for part in parts:
        if part["type"] == "text":
            out.append({"type": "text", "text": part["text"]})
            continue
        source = part["source"]
        if source["type"] == "data":
            out.append({"type": "file", "mediaType": source["mimeType"], "data": source["value"]})
        elif source["type"] == "url":
            url = Url.parse(source["value"])
            if url is not None:
                media_type = source.get("mimeType", _DEFAULT_MEDIA_TYPE[part["type"]])
                out.append({"type": "file", "mediaType": media_type, "data": url})
    return out


# --- events ----------------------------------------------------------------------------

_NO_EVENTS: Effect[Sequence[Event]] = fx.succeed(())

_MODEL_ERROR_MESSAGE = "The model reported an error."


class _PartsToEvents:
    """One run's conversion: its step count and the step's latest text message, which
    names the parent of the step's tool calls."""

    def __init__(self, ids: IdService) -> None:
        self.ids = ids
        self.step = 0
        self.in_step = False
        self.parent_message_id: str | None = None
        self.streamed_tool_calls: set[str] = set()

    def tool_call_start(self, id: str, name: str) -> ToolCallStartEvent:
        if self.parent_message_id is None:
            return {"type": "TOOL_CALL_START", "toolCallId": id, "toolCallName": name}
        return {
            "type": "TOOL_CALL_START",
            "toolCallId": id,
            "toolCallName": name,
            "parentMessageId": self.parent_message_id,
        }

    def events(self, part: R.AnyPart) -> Effect[Sequence[Event]]:
        if self.in_step:
            return self.to_events(part)
        self.in_step = True
        self.step += 1
        started: Event = {"type": "STEP_STARTED", "stepName": f"step-{self.step}"}
        return self.to_events(part).map(lambda events: (started, *events))

    def to_events(self, part: R.AnyPart) -> Effect[Sequence[Event]]:  # noqa: PLR0911, PLR0912
        match part:
            case R.TextStartPart(id=id):
                self.parent_message_id = id
                return fx.succeed(
                    [{"type": "TEXT_MESSAGE_START", "messageId": id, "role": "assistant"}]
                )
            case R.TextDeltaPart(id=id, delta=delta):
                return fx.succeed(
                    [{"type": "TEXT_MESSAGE_CONTENT", "messageId": id, "delta": delta}]
                )
            case R.TextEndPart(id=id):
                return fx.succeed([{"type": "TEXT_MESSAGE_END", "messageId": id}])
            case R.ReasoningStartPart(id=id):
                return fx.succeed(
                    [
                        {"type": "REASONING_START", "messageId": id},
                        {"type": "REASONING_MESSAGE_START", "messageId": id, "role": "reasoning"},
                    ]
                )
            case R.ReasoningDeltaPart(id=id, delta=delta):
                return fx.succeed(
                    [{"type": "REASONING_MESSAGE_CONTENT", "messageId": id, "delta": delta}]
                )
            case R.ReasoningEndPart(id=id):
                return fx.succeed(
                    [
                        {"type": "REASONING_MESSAGE_END", "messageId": id},
                        {"type": "REASONING_END", "messageId": id},
                    ]
                )
            case R.ToolParamsStartPart(id=id, name=name):
                self.streamed_tool_calls.add(id)
                return fx.succeed([self.tool_call_start(id, name)])
            case R.ToolParamsDeltaPart(id=id, delta=delta):
                return fx.succeed([{"type": "TOOL_CALL_ARGS", "toolCallId": id, "delta": delta}])
            case R.ToolParamsEndPart(id=id):
                return fx.succeed([{"type": "TOOL_CALL_END", "toolCallId": id}])
            case R.ToolCallPart():
                return self.tool_call(part)
            case R.ToolResultSuccess() | R.ToolResultFailure():
                return self.tool_result(part)
            case R.FinishPart():
                self.in_step = False
                self.parent_message_id = None
                return fx.succeed([{"type": "STEP_FINISHED", "stepName": f"step-{self.step}"}])
            case R.ErrorPart(error=error):
                return fx.log_error(error).as_(
                    [{"type": "RUN_ERROR", "message": _MODEL_ERROR_MESSAGE}]
                )
            case _:
                return _NO_EVENTS

    def tool_call(self, part: R.AnyToolCallPart) -> Effect[Sequence[Event]]:
        if part.id in self.streamed_tool_calls:
            return _NO_EVENTS
        params: object = {} if part.params is None else part.params
        return fx.succeed(
            [
                self.tool_call_start(part.id, part.name),
                {"type": "TOOL_CALL_ARGS", "toolCallId": part.id, "delta": stringify(params)},
                {"type": "TOOL_CALL_END", "toolCallId": part.id},
            ]
        )

    def tool_result(self, part: R.AnyToolResultPart) -> Effect[Sequence[Event]]:
        if part.preliminary:
            return _NO_EVENTS
        encoded = part.encoded_result
        content = encoded if isinstance(encoded, str) else stringify(encoded)

        def event(message_id: str) -> Sequence[Event]:
            if part.is_failure:
                return [
                    {
                        "type": "TOOL_CALL_RESULT",
                        "messageId": message_id,
                        "toolCallId": part.id,
                        "content": content,
                        "metadata": {"effect/ai": {"isFailure": True}},
                    }
                ]
            return [
                {
                    "type": "TOOL_CALL_RESULT",
                    "messageId": message_id,
                    "toolCallId": part.id,
                    "content": content,
                }
            ]

        return self.ids.generate_id().map(event)


def from_stream_parts[E, RR](
    self: Stream[R.AnyPart, E, RR],
) -> Stream[Event, E, RR | IdGenerator]:
    """The parts ``language_model.stream_text`` streams as AG-UI events.

    - Each model round becomes a step named ``step-1``, ``step-2`` and so on; the round's
      ``finish`` part closes the step.
    - Text parts become ``TEXT_MESSAGE_*`` events from the ``assistant`` role, and
      reasoning parts a reasoning span holding one reasoning message.
    - Streamed tool parameters become ``TOOL_CALL_START``, ``TOOL_CALL_ARGS`` and
      ``TOOL_CALL_END``. A tool call that arrives without streamed parameters becomes the
      same sequence with its parameters as one JSON fragment. Tool calls name the step's
      latest text message as their parent.
    - Final tool results become ``TOOL_CALL_RESULT`` events with a fresh message id from
      ``IdGenerator``; failed ones carry ``{"effect/ai": {"isFailure": True}}`` as
      metadata.
    - An ``error`` part is logged and becomes a ``RUN_ERROR`` with a generic message.
    - Preliminary tool results, approval requests, files, sources and response metadata
      are dropped.

    Failures of the input stream are kept: ``with_run_lifecycle`` opens and closes the
    run and reports failures to the client."""

    def convert(ids: IdService) -> Stream[Event, E, RR]:
        state = _PartsToEvents(ids)
        return self.map_effect(state.events).flatten_iterable()

    return StreamC.unwrap(IdGenerator().map(convert))


# --- run lifecycle ---------------------------------------------------------------------

_RUN_ERROR_MESSAGE = "The agent run failed."
_SUBAGENT_UNFINISHED_MESSAGE = "The subagent did not finish."


class RunIds(TypedDict):
    """The ids of one run, as a ``RunAgentInput`` carries them."""

    threadId: str
    runId: str


def _attributed(event: Event, subagent_run_id: str | None) -> Event:
    if subagent_run_id is None:
        return event
    return cast("Event", {**event, "subagentRunId": subagent_run_id})


def _step_key(subagent_run_id: str | None, step_name: str) -> str:
    """Steps are named rather than identified, so they are keyed by owner too."""
    return "step:" + json.dumps([subagent_run_id, step_name])


class _Lifecycle:
    """What one run left open, in opening order, so closing walks it backwards."""

    def __init__(self) -> None:
        self.open: dict[str, Event] = {}
        self.ended = False

    def close_open(self) -> list[Event]:
        events = list(reversed(self.open.values()))
        self.open.clear()
        return events

    def track(self, event: Event) -> Sequence[Event]:  # noqa: PLR0912
        if self.ended:
            return ()
        fields = cast("Mapping[str, Any]", event)
        subagent: str | None = fields.get("subagentRunId")
        closing: Event
        match event["type"]:
            case "RUN_STARTED":
                return ()
            case "RUN_FINISHED":
                self.ended = True
                return [*self.close_open(), event]
            case "RUN_ERROR":
                self.ended = True
                return [event]
            case "TEXT_MESSAGE_START":
                closing = {"type": "TEXT_MESSAGE_END", "messageId": fields["messageId"]}
                self.open[f"text:{fields['messageId']}"] = _attributed(closing, subagent)
            case "TEXT_MESSAGE_END":
                self.open.pop(f"text:{fields['messageId']}", None)
            case "TOOL_CALL_START":
                closing = {"type": "TOOL_CALL_END", "toolCallId": fields["toolCallId"]}
                self.open[f"tool:{fields['toolCallId']}"] = _attributed(closing, subagent)
            case "TOOL_CALL_END":
                self.open.pop(f"tool:{fields['toolCallId']}", None)
            case "REASONING_START":
                closing = {"type": "REASONING_END", "messageId": fields["messageId"]}
                self.open[f"reasoning:{fields['messageId']}"] = _attributed(closing, subagent)
            case "REASONING_END":
                self.open.pop(f"reasoning:{fields['messageId']}", None)
            case "REASONING_MESSAGE_START":
                closing = {"type": "REASONING_MESSAGE_END", "messageId": fields["messageId"]}
                key = f"reasoning-message:{fields['messageId']}"
                self.open[key] = _attributed(closing, subagent)
            case "REASONING_MESSAGE_END":
                self.open.pop(f"reasoning-message:{fields['messageId']}", None)
            case "STEP_STARTED":
                closing = {"type": "STEP_FINISHED", "stepName": fields["stepName"]}
                self.open[_step_key(subagent, fields["stepName"])] = _attributed(closing, subagent)
            case "STEP_FINISHED":
                self.open.pop(_step_key(subagent, fields["stepName"]), None)
            case "SUBAGENT_STARTED":
                self.open[f"subagent:{subagent}"] = {
                    "type": "SUBAGENT_ERROR",
                    "subagentRunId": fields["subagentRunId"],
                    "message": _SUBAGENT_UNFINISHED_MESSAGE,
                }
            case "SUBAGENT_FINISHED" | "SUBAGENT_ERROR":
                self.open.pop(f"subagent:{subagent}", None)
            case _:
                pass
        return [event]


def with_run_lifecycle(run: RunIds) -> _WithRunLifecycle:
    """Wraps a stream of AG-UI events in the lifecycle of one run (``.pipe`` it), so
    clients always see a well-formed run, with ``from_stream_parts`` or any hand-written
    event stream.

    - ``RUN_STARTED`` comes first, with the run's ids and the protocol version;
      ``RUN_STARTED`` events from the input stream are dropped.
    - When the input stream ends, any text message, tool call, reasoning span, step or
      subagent it left open is closed, most recently opened first, and ``RUN_FINISHED``
      follows. Closing events keep the ``subagentRunId`` of the event they close, steps
      are matched by name within each subagent, and a subagent left running ends with a
      ``SUBAGENT_ERROR``.
    - A ``RUN_FINISHED`` from the input stream ends the run, after closing anything left
      open, so a stream can report its own outcome. A ``RUN_ERROR`` from it also ends the
      run.
    - When the input stream fails, the cause is logged and reported, and the run ends
      with a ``RUN_ERROR`` whose message carries no error details. Interruptions are not
      converted.

    To send a specific error to the client, emit a ``RUN_ERROR`` from the input stream
    instead of failing it."""
    return _WithRunLifecycle(run["threadId"], run["runId"])


class _WithRunLifecycle:
    __slots__ = ("run_id", "thread_id")

    def __init__(self, thread_id: str, run_id: str) -> None:
        self.thread_id = thread_id
        self.run_id = run_id

    def __call__[E, RR](self, events: Stream[Event, E, RR], /) -> Stream[Event, Never, RR]:
        thread_id, run_id = self.thread_id, self.run_id

        def start() -> Stream[Event, Never, RR]:
            lifecycle = _Lifecycle()

            def failed(cause: Cause[E]) -> Stream[Event, Never]:
                # An interrupt-only cause carries no failure of type E.
                if cause.has_interrupts_only:
                    return StreamC.fail_cause(cast("Cause[Never]", cause))
                lifecycle.ended = True
                error: Event = {"type": "RUN_ERROR", "message": _RUN_ERROR_MESSAGE}
                reported = fx.log_error(cause).and_then(error_reporter.report(cause))
                return StreamC.from_effect(reported.as_(error))

            def finish() -> Stream[Event, Never]:
                if lifecycle.ended:
                    return StreamC.empty
                finished: Event = {"type": "RUN_FINISHED", "threadId": thread_id, "runId": run_id}
                return StreamC.from_iterable([*lifecycle.close_open(), finished])

            started: Event = {
                "type": "RUN_STARTED",
                "threadId": thread_id,
                "runId": run_id,
                "protocolVersion": PROTOCOL_VERSION,
            }
            return (
                events.map(lifecycle.track)
                .flatten_iterable()
                .take_until(lambda event: event["type"] in ("RUN_FINISHED", "RUN_ERROR"))
                .catch_cause(failed)
                .concat(StreamC.suspend(finish))
                .prepend([started])
            )

        return StreamC.suspend(start)


__all__ = [
    "RunIds",
    "from_stream_parts",
    "to_prompt",
    "with_run_lifecycle",
]
