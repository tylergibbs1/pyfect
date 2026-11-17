"""Schemas of the Agent User Interaction (AG-UI) protocol (Effect's ``AgUiSchema``).

AG-UI connects an agent backend to a user-facing application: the application posts a
``RunAgentInput`` and the agent answers with a stream of events describing the run.
These schemas follow the AG-UI 1.0 specification (https://docs.ag-ui.com) and describe
the request body, the conversation messages it carries, and every event type.
Converting to and from ``pyfect.ai`` values lives in ``ag_ui``, the HTTP binding in
``ag_ui_server``.

As in ``mcp_schema``, values are ``TypedDict`` s in the wire form, with AG-UI's camelCase
keys (``threadId``, ``toolCallId``); each has a schema named in capitals
(``RUN_AGENT_INPUT`` for ``RunAgentInput``).

AG-UI consumers remove list elements they do not recognise (a message role, a content
part type or a closed-set value added by a newer protocol version) instead of rejecting
the value holding them. A recognised but malformed element still fails to decode.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Literal, Never, NotRequired, TypedDict, cast

import pyfect as fx
from pyfect import schema as S
from pyfect.json_schema import JsonSchema
from pyfect.schema.transformation import transform

PROTOCOL_VERSION = "1.0"
"""The AG-UI protocol version these schemas implement."""

# --- shared ----------------------------------------------------------------------------

type Metadata = dict[str, object]
"""Open-ended metadata attached to events, messages, tools and other protocol values.
The ``ag-ui`` key is reserved for the protocol's own use."""

METADATA = S.Record(S.String, S.Unknown)


class _BaseEvent(TypedDict):
    timestamp: NotRequired[int]
    rawEvent: NotRequired[object]
    metadata: NotRequired[Metadata]


class _SubagentEvent(_BaseEvent):
    subagentRunId: NotRequired[str]


_TOKEN_COUNT = S.Int.check(S.is_greater_than_or_equal_to(0))


def _without_unknown_members[A](
    item: S.Codec[A, Any, Any, Any], is_unknown: Callable[[object], bool]
) -> S.Bottom[list[A], list[Any]]:
    """A list of ``item`` that drops the elements ``is_unknown`` calls unrecognised.

    The fallback branch accepts only unrecognised material, so it never hides a malformed
    item. JSON Schema documents the canonical model: the fallback is only an empty
    ``anyOf``, which a union splices away, so generated clients keep the item's
    discriminated variants."""

    def empty_any_of(_context: object) -> JsonSchema:
        return {"anyOf": []}

    unrecognised = S.Any.check(S.make_filter(is_unknown, to_json_schema=empty_any_of))

    def decode(values: Any) -> Any:
        return [value for value in values if not is_unknown(value)]

    items: S.Top = S.List(S.Union(item, unrecognised))
    known: S.Top = S.List(S.to_type(item))
    return cast("Any", items).pipe(S.decode_to(known, transform(decode=decode, encode=_same)))


def _same(value: Any) -> Any:
    return value


def _has_unknown_tag(value: object, key: str, tags: frozenset[str]) -> bool:
    """Only a string outside the closed set is unrecognised; a missing or mistyped value
    is malformed."""
    if not isinstance(value, Mapping):
        return False
    tag = cast("Mapping[str, object]", value).get(key)
    return isinstance(tag, str) and tag not in tags


# --- content ---------------------------------------------------------------------------


class DataSource(TypedDict):
    """Media bytes carried inline as base64 data."""

    type: Literal["data"]
    value: str
    mimeType: str


class UrlSource(TypedDict):
    """Media bytes referenced by URL."""

    type: Literal["url"]
    value: str
    mimeType: NotRequired[str]


class FileSource(TypedDict):
    """Media bytes already stored at a provider and named by a handle it issued."""

    type: Literal["file"]
    value: str
    provider: NotRequired[str]
    mimeType: NotRequired[str]


type PartSource = DataSource | UrlSource | FileSource
"""The source of a media content part."""

DATA_SOURCE = S.Struct(DataSource)
URL_SOURCE = S.Struct(UrlSource)
FILE_SOURCE = S.Struct(FileSource)
PART_SOURCE = S.Union(DATA_SOURCE, URL_SOURCE, FILE_SOURCE)


class TextPart(TypedDict):
    """A text content part."""

    type: Literal["text"]
    id: NotRequired[str]
    text: str
    metadata: NotRequired[object]


class ImagePart(TypedDict):
    type: Literal["image"]
    id: NotRequired[str]
    source: PartSource
    metadata: NotRequired[object]


class AudioPart(TypedDict):
    type: Literal["audio"]
    id: NotRequired[str]
    source: PartSource
    metadata: NotRequired[object]


class VideoPart(TypedDict):
    type: Literal["video"]
    id: NotRequired[str]
    source: PartSource
    metadata: NotRequired[object]


class DocumentPart(TypedDict):
    type: Literal["document"]
    id: NotRequired[str]
    source: PartSource
    metadata: NotRequired[object]


type MediaPart = ImagePart | AudioPart | VideoPart | DocumentPart
type ContentPart = TextPart | MediaPart
"""Any content part of a user or tool message."""

TEXT_PART = S.Struct(TextPart)
IMAGE_PART = S.Struct(ImagePart, source=PART_SOURCE)
AUDIO_PART = S.Struct(AudioPart, source=PART_SOURCE)
VIDEO_PART = S.Struct(VideoPart, source=PART_SOURCE)
DOCUMENT_PART = S.Struct(DocumentPart, source=PART_SOURCE)
CONTENT_PART = S.Union(TEXT_PART, IMAGE_PART, AUDIO_PART, VIDEO_PART, DOCUMENT_PART)

_CONTENT_PART_TYPES = frozenset({"text", "image", "audio", "video", "document"})
_PART_SOURCE_TYPES = frozenset({"data", "url", "file"})
_MEDIA_PART_TYPES = frozenset({"image", "audio", "video", "document"})


def _is_unknown_content_part(value: object) -> bool:
    """A recognised media part whose required source is unrecognised goes with it."""
    if _has_unknown_tag(value, "type", _CONTENT_PART_TYPES):
        return True
    if not isinstance(value, Mapping):
        return False
    part = cast("Mapping[str, object]", value)
    return part.get("type") in _MEDIA_PART_TYPES and _has_unknown_tag(
        part.get("source"), "type", _PART_SOURCE_TYPES
    )


type Content = str | list[ContentPart]

_CONTENT = S.Union(S.String, _without_unknown_members(CONTENT_PART, _is_unknown_content_part))

# --- messages --------------------------------------------------------------------------


class _MessageFields(TypedDict):
    subagentRunId: NotRequired[str]
    id: str
    metadata: NotRequired[Metadata]


class DeveloperMessage(_MessageFields):
    """Instructions from the application developer."""

    role: Literal["developer"]
    name: NotRequired[str]
    encryptedValue: NotRequired[str]
    content: str


class SystemMessage(_MessageFields):
    """Instructions from the system."""

    role: Literal["system"]
    name: NotRequired[str]
    encryptedValue: NotRequired[str]
    content: str


class ToolCallFunction(TypedDict):
    name: str
    arguments: str
    """The JSON text of the call's arguments."""


class ToolCall(TypedDict):
    """A tool call made by an assistant message."""

    id: str
    type: Literal["function"]
    function: ToolCallFunction
    encryptedValue: NotRequired[str]
    metadata: NotRequired[Metadata]


TOOL_CALL = S.Struct(ToolCall)
_TOOL_CALL_TYPES = frozenset({"function"})


class AssistantMessage(_MessageFields):
    """A message from the agent."""

    role: Literal["assistant"]
    name: NotRequired[str]
    encryptedValue: NotRequired[str]
    content: NotRequired[str]
    toolCalls: NotRequired[list[ToolCall]]


class UserMessage(_MessageFields):
    """A message from the person using the application."""

    role: Literal["user"]
    name: NotRequired[str]
    encryptedValue: NotRequired[str]
    content: Content


class ToolMessage(_MessageFields):
    """The result of a tool call as a message; ``error`` is present when it failed."""

    role: Literal["tool"]
    content: Content
    toolCallId: str
    error: NotRequired[str]
    encryptedValue: NotRequired[str]


class ActivityMessage(_MessageFields):
    """Structured progress kept in the conversation as a message."""

    role: Literal["activity"]
    activityType: str
    content: dict[str, object]


class ReasoningMessage(_MessageFields):
    """A span of the agent's reasoning, kept in the conversation as a message."""

    role: Literal["reasoning"]
    content: str
    encryptedValue: NotRequired[str]


type Message = (
    DeveloperMessage
    | SystemMessage
    | AssistantMessage
    | UserMessage
    | ToolMessage
    | ActivityMessage
    | ReasoningMessage
)
"""Any message in an AG-UI conversation, discriminated by ``role``."""

DEVELOPER_MESSAGE = S.Struct(DeveloperMessage)
SYSTEM_MESSAGE = S.Struct(SystemMessage)
ASSISTANT_MESSAGE = S.Struct(
    AssistantMessage,
    toolCalls=_without_unknown_members(
        TOOL_CALL, lambda value: _has_unknown_tag(value, "type", _TOOL_CALL_TYPES)
    ),
)
USER_MESSAGE = S.Struct(UserMessage, content=_CONTENT)
TOOL_MESSAGE = S.Struct(ToolMessage, content=_CONTENT)
ACTIVITY_MESSAGE = S.Struct(ActivityMessage)
REASONING_MESSAGE = S.Struct(ReasoningMessage)
MESSAGE = S.Union(
    DEVELOPER_MESSAGE,
    SYSTEM_MESSAGE,
    ASSISTANT_MESSAGE,
    USER_MESSAGE,
    TOOL_MESSAGE,
    ACTIVITY_MESSAGE,
    REASONING_MESSAGE,
)

_MESSAGE_ROLES = frozenset(
    {"developer", "system", "assistant", "user", "tool", "activity", "reasoning"}
)
_MESSAGES = _without_unknown_members(
    MESSAGE, lambda value: _has_unknown_tag(value, "role", _MESSAGE_ROLES)
)

# --- run input -------------------------------------------------------------------------


class Tool(TypedDict):
    """A tool the application offers to the agent; ``parameters`` is a JSON Schema of
    its arguments."""

    name: str
    description: str
    parameters: NotRequired[object]
    metadata: NotRequired[Metadata]


class Context(TypedDict):
    """A piece of context the application gives the agent."""

    description: str
    value: str


class ResumeEntry(TypedDict):
    """The application's answer to an interrupt."""

    interruptId: str
    status: Literal["resolved", "cancelled"]
    payload: NotRequired[object]
    metadata: NotRequired[Metadata]


TOOL = S.Struct(Tool)
CONTEXT = S.Struct(Context)
RESUME_ENTRY = S.Struct(ResumeEntry)
_RESUME_STATUSES = frozenset({"resolved", "cancelled"})


class RunAgentInput(TypedDict):
    """The body of a request starting an AG-UI run. ``tools`` and ``context`` default to
    empty lists."""

    threadId: str
    runId: str
    protocolVersion: NotRequired[str]
    parentRunId: NotRequired[str]
    state: NotRequired[object]
    messages: list[Message]
    tools: list[Tool]
    context: list[Context]
    forwardedProps: NotRequired[object]
    resume: NotRequired[list[ResumeEntry]]


def _empty_list() -> fx.Effect[list[Any]]:
    return fx.sync(list[Any])


RUN_AGENT_INPUT = S.Struct(
    RunAgentInput,
    messages=_MESSAGES,
    tools=S.List(TOOL).pipe(S.with_decoding_default_type_key(_empty_list())),
    context=S.List(CONTEXT).pipe(S.with_decoding_default_type_key(_empty_list())),
    resume=_without_unknown_members(
        RESUME_ENTRY, lambda value: _has_unknown_tag(value, "status", _RESUME_STATUSES)
    ),
)

# --- text message events ---------------------------------------------------------------

type TextMessageRole = Literal["developer", "system", "assistant", "user"]

TEXT_MESSAGE_ROLE = S.Literals("developer", "system", "assistant", "user")


class TextMessageStartEvent(_SubagentEvent):
    type: Literal["TEXT_MESSAGE_START"]
    messageId: str
    role: NotRequired[TextMessageRole]
    name: NotRequired[str]


class TextMessageContentEvent(_SubagentEvent):
    type: Literal["TEXT_MESSAGE_CONTENT"]
    messageId: str
    delta: str


class TextMessageEndEvent(_SubagentEvent):
    type: Literal["TEXT_MESSAGE_END"]
    messageId: str


class TextMessageChunkEvent(_SubagentEvent):
    type: Literal["TEXT_MESSAGE_CHUNK"]
    messageId: NotRequired[str]
    role: NotRequired[TextMessageRole]
    delta: NotRequired[str]
    name: NotRequired[str]


# --- tool call events ------------------------------------------------------------------


class ToolCallStartEvent(_SubagentEvent):
    type: Literal["TOOL_CALL_START"]
    toolCallId: str
    toolCallName: str
    parentMessageId: NotRequired[str]


class ToolCallArgsEvent(_SubagentEvent):
    type: Literal["TOOL_CALL_ARGS"]
    toolCallId: str
    delta: str


class ToolCallEndEvent(_SubagentEvent):
    type: Literal["TOOL_CALL_END"]
    toolCallId: str


class ToolCallChunkEvent(_SubagentEvent):
    type: Literal["TOOL_CALL_CHUNK"]
    toolCallId: NotRequired[str]
    toolCallName: NotRequired[str]
    parentMessageId: NotRequired[str]
    delta: NotRequired[str]


class ToolCallResultEvent(_SubagentEvent):
    type: Literal["TOOL_CALL_RESULT"]
    messageId: str
    toolCallId: str
    content: Content
    role: NotRequired[Literal["tool"]]


# --- state and activity events ---------------------------------------------------------


class JsonPatchAdd(TypedDict):
    op: Literal["add"]
    path: str
    value: object


class JsonPatchRemove(TypedDict):
    op: Literal["remove"]
    path: str


class JsonPatchReplace(TypedDict):
    op: Literal["replace"]
    path: str
    value: object


# ``move`` and ``copy`` name their source ``from``, which only the functional syntax spells.
JsonPatchMove = TypedDict("JsonPatchMove", {"op": Literal["move"], "from": str, "path": str})
JsonPatchCopy = TypedDict("JsonPatchCopy", {"op": Literal["copy"], "from": str, "path": str})


class JsonPatchTest(TypedDict):
    op: Literal["test"]
    path: str
    value: object


type JsonPatchOperation = (
    JsonPatchAdd
    | JsonPatchRemove
    | JsonPatchReplace
    | JsonPatchMove
    | JsonPatchCopy
    | JsonPatchTest
)
"""One RFC 6902 JSON Patch operation."""

JSON_PATCH_OPERATION = S.Union(
    S.Struct(JsonPatchAdd),
    S.Struct(JsonPatchRemove),
    S.Struct(JsonPatchReplace),
    S.Struct(JsonPatchMove),
    S.Struct(JsonPatchCopy),
    S.Struct(JsonPatchTest),
)


class StateSnapshotEvent(_SubagentEvent):
    type: Literal["STATE_SNAPSHOT"]
    snapshot: object


class StateDeltaEvent(_SubagentEvent):
    type: Literal["STATE_DELTA"]
    delta: list[JsonPatchOperation]


class MessagesSnapshotEvent(_BaseEvent):
    type: Literal["MESSAGES_SNAPSHOT"]
    messages: list[Message]


class ActivitySnapshotEvent(_SubagentEvent):
    type: Literal["ACTIVITY_SNAPSHOT"]
    messageId: str
    activityType: str
    content: dict[str, object]
    replace: NotRequired[bool]


class ActivityDeltaEvent(_SubagentEvent):
    type: Literal["ACTIVITY_DELTA"]
    messageId: str
    activityType: str
    patch: list[JsonPatchOperation]


# --- special events --------------------------------------------------------------------


class RawEvent(_SubagentEvent):
    type: Literal["RAW"]
    event: object
    source: NotRequired[str]


class CustomEvent(_SubagentEvent):
    type: Literal["CUSTOM"]
    name: str
    value: object


# --- lifecycle events ------------------------------------------------------------------


class RunStartedEvent(_BaseEvent):
    type: Literal["RUN_STARTED"]
    threadId: str
    runId: str
    protocolVersion: NotRequired[str]
    parentRunId: NotRequired[str]
    input: NotRequired[RunAgentInput]


class Interrupt(TypedDict):
    """Why a run paused for the application, and how to answer."""

    subagentRunId: NotRequired[str]
    id: str
    reason: str
    message: NotRequired[str]
    toolCallId: NotRequired[str]
    responseSchema: NotRequired[dict[str, object]]
    expiresAt: NotRequired[str]
    metadata: NotRequired[Metadata]


INTERRUPT = S.Struct(Interrupt)


class SuccessOutcome(TypedDict):
    type: Literal["success"]
    pendingToolCallIds: NotRequired[list[str]]


class InterruptOutcome(TypedDict):
    type: Literal["interrupt"]
    interrupts: list[Interrupt]
    """At least one."""


class CancelledOutcome(TypedDict):
    type: Literal["cancelled"]


type RunFinishedOutcome = SuccessOutcome | InterruptOutcome | CancelledOutcome

RUN_FINISHED_OUTCOME = S.Union(
    S.Struct(SuccessOutcome),
    S.Struct(InterruptOutcome, interrupts=S.List(INTERRUPT).check(S.is_min_length(1))),
    S.Struct(CancelledOutcome),
)


class TokenUsage(TypedDict, total=False):
    """Token counts of a run, each a non-negative integer."""

    provider: str
    model: str
    inputTokens: int
    outputTokens: int
    totalTokens: int
    reasoningTokens: int
    cachedInputTokens: int
    cacheWriteInputTokens: int


TOKEN_USAGE = S.Struct(
    TokenUsage,
    inputTokens=_TOKEN_COUNT,
    outputTokens=_TOKEN_COUNT,
    totalTokens=_TOKEN_COUNT,
    reasoningTokens=_TOKEN_COUNT,
    cachedInputTokens=_TOKEN_COUNT,
    cacheWriteInputTokens=_TOKEN_COUNT,
)


class RunFinishedEvent(_BaseEvent):
    type: Literal["RUN_FINISHED"]
    threadId: str
    runId: str
    result: NotRequired[object]
    outcome: NotRequired[RunFinishedOutcome]
    usage: NotRequired[list[TokenUsage]]


class RunErrorEvent(_BaseEvent):
    type: Literal["RUN_ERROR"]
    message: str
    code: NotRequired[str]
    usage: NotRequired[list[TokenUsage]]


class StepStartedEvent(_SubagentEvent):
    type: Literal["STEP_STARTED"]
    stepName: str


class StepFinishedEvent(_SubagentEvent):
    type: Literal["STEP_FINISHED"]
    stepName: str


# --- reasoning events ------------------------------------------------------------------


class ReasoningStartEvent(_SubagentEvent):
    type: Literal["REASONING_START"]
    messageId: str


class ReasoningMessageStartEvent(_SubagentEvent):
    type: Literal["REASONING_MESSAGE_START"]
    messageId: str
    role: Literal["reasoning"]


class ReasoningMessageContentEvent(_SubagentEvent):
    type: Literal["REASONING_MESSAGE_CONTENT"]
    messageId: str
    delta: str


class ReasoningMessageEndEvent(_SubagentEvent):
    type: Literal["REASONING_MESSAGE_END"]
    messageId: str


class ReasoningMessageChunkEvent(_SubagentEvent):
    type: Literal["REASONING_MESSAGE_CHUNK"]
    messageId: NotRequired[str]
    delta: NotRequired[str]


class ReasoningEndEvent(_SubagentEvent):
    type: Literal["REASONING_END"]
    messageId: str


class ReasoningEncryptedValueEvent(_SubagentEvent):
    type: Literal["REASONING_ENCRYPTED_VALUE"]
    subtype: Literal["tool-call", "message"]
    entityId: str
    encryptedValue: str


# --- subagent events -------------------------------------------------------------------


class SubagentStartedEvent(_BaseEvent):
    type: Literal["SUBAGENT_STARTED"]
    subagentRunId: str
    name: str
    description: NotRequired[str]
    parentSubagentRunId: NotRequired[str]
    parentToolCallId: NotRequired[str]
    parentMessageId: NotRequired[str]


class SubagentSuccessOutcome(TypedDict):
    type: Literal["success"]


class SubagentSuspendedOutcome(TypedDict):
    type: Literal["suspended"]
    interruptIds: NotRequired[list[str]]


class SubagentFinishedEvent(_BaseEvent):
    type: Literal["SUBAGENT_FINISHED"]
    subagentRunId: str
    result: NotRequired[object]
    outcome: NotRequired[SubagentSuccessOutcome | SubagentSuspendedOutcome]


class SubagentErrorEvent(_BaseEvent):
    type: Literal["SUBAGENT_ERROR"]
    subagentRunId: str
    message: str
    code: NotRequired[str]


# --- events ----------------------------------------------------------------------------

type Event = (
    TextMessageStartEvent
    | TextMessageContentEvent
    | TextMessageEndEvent
    | TextMessageChunkEvent
    | ToolCallStartEvent
    | ToolCallArgsEvent
    | ToolCallEndEvent
    | ToolCallChunkEvent
    | ToolCallResultEvent
    | StateSnapshotEvent
    | StateDeltaEvent
    | MessagesSnapshotEvent
    | ActivitySnapshotEvent
    | ActivityDeltaEvent
    | RawEvent
    | CustomEvent
    | RunStartedEvent
    | RunFinishedEvent
    | RunErrorEvent
    | StepStartedEvent
    | StepFinishedEvent
    | ReasoningStartEvent
    | ReasoningMessageStartEvent
    | ReasoningMessageContentEvent
    | ReasoningMessageEndEvent
    | ReasoningMessageChunkEvent
    | ReasoningEndEvent
    | ReasoningEncryptedValueEvent
    | SubagentStartedEvent
    | SubagentFinishedEvent
    | SubagentErrorEvent
)
"""Any AG-UI event, discriminated by ``type``."""

_USAGE = S.List(TOKEN_USAGE)

TEXT_MESSAGE_START_EVENT = S.Struct(TextMessageStartEvent)
TEXT_MESSAGE_CONTENT_EVENT = S.Struct(TextMessageContentEvent)
TEXT_MESSAGE_END_EVENT = S.Struct(TextMessageEndEvent)
TEXT_MESSAGE_CHUNK_EVENT = S.Struct(TextMessageChunkEvent)
TOOL_CALL_START_EVENT = S.Struct(ToolCallStartEvent)
TOOL_CALL_ARGS_EVENT = S.Struct(ToolCallArgsEvent)
TOOL_CALL_END_EVENT = S.Struct(ToolCallEndEvent)
TOOL_CALL_CHUNK_EVENT = S.Struct(ToolCallChunkEvent)
TOOL_CALL_RESULT_EVENT = S.Struct(ToolCallResultEvent, content=_CONTENT)
STATE_SNAPSHOT_EVENT = S.Struct(StateSnapshotEvent)
STATE_DELTA_EVENT = S.Struct(StateDeltaEvent, delta=S.List(JSON_PATCH_OPERATION))
MESSAGES_SNAPSHOT_EVENT = S.Struct(MessagesSnapshotEvent, messages=_MESSAGES)
ACTIVITY_SNAPSHOT_EVENT = S.Struct(ActivitySnapshotEvent)
ACTIVITY_DELTA_EVENT = S.Struct(ActivityDeltaEvent, patch=S.List(JSON_PATCH_OPERATION))
RAW_EVENT = S.Struct(RawEvent)
CUSTOM_EVENT = S.Struct(CustomEvent)
RUN_STARTED_EVENT = S.Struct(RunStartedEvent, input=RUN_AGENT_INPUT)
RUN_FINISHED_EVENT = S.Struct(RunFinishedEvent, outcome=RUN_FINISHED_OUTCOME, usage=_USAGE)
RUN_ERROR_EVENT = S.Struct(RunErrorEvent, usage=_USAGE)
STEP_STARTED_EVENT = S.Struct(StepStartedEvent)
STEP_FINISHED_EVENT = S.Struct(StepFinishedEvent)
REASONING_START_EVENT = S.Struct(ReasoningStartEvent)
REASONING_MESSAGE_START_EVENT = S.Struct(ReasoningMessageStartEvent)
REASONING_MESSAGE_CONTENT_EVENT = S.Struct(ReasoningMessageContentEvent)
REASONING_MESSAGE_END_EVENT = S.Struct(ReasoningMessageEndEvent)
REASONING_MESSAGE_CHUNK_EVENT = S.Struct(ReasoningMessageChunkEvent)
REASONING_END_EVENT = S.Struct(ReasoningEndEvent)
REASONING_ENCRYPTED_VALUE_EVENT = S.Struct(ReasoningEncryptedValueEvent)
SUBAGENT_STARTED_EVENT = S.Struct(SubagentStartedEvent)
SUBAGENT_FINISHED_EVENT = S.Struct(SubagentFinishedEvent)
SUBAGENT_ERROR_EVENT = S.Struct(SubagentErrorEvent)

EVENT: S.Codec[Event, Mapping[str, object], Never, Never] = cast(
    "Any",
    S.Union(
        TEXT_MESSAGE_START_EVENT,
        TEXT_MESSAGE_CONTENT_EVENT,
        TEXT_MESSAGE_END_EVENT,
        TEXT_MESSAGE_CHUNK_EVENT,
        TOOL_CALL_START_EVENT,
        TOOL_CALL_ARGS_EVENT,
        TOOL_CALL_END_EVENT,
        TOOL_CALL_CHUNK_EVENT,
        TOOL_CALL_RESULT_EVENT,
        STATE_SNAPSHOT_EVENT,
        STATE_DELTA_EVENT,
        MESSAGES_SNAPSHOT_EVENT,
        ACTIVITY_SNAPSHOT_EVENT,
        ACTIVITY_DELTA_EVENT,
        RAW_EVENT,
        CUSTOM_EVENT,
        RUN_STARTED_EVENT,
        RUN_FINISHED_EVENT,
        RUN_ERROR_EVENT,
        STEP_STARTED_EVENT,
        STEP_FINISHED_EVENT,
        REASONING_START_EVENT,
        REASONING_MESSAGE_START_EVENT,
        REASONING_MESSAGE_CONTENT_EVENT,
        REASONING_MESSAGE_END_EVENT,
        REASONING_MESSAGE_CHUNK_EVENT,
        REASONING_END_EVENT,
        REASONING_ENCRYPTED_VALUE_EVENT,
        SUBAGENT_STARTED_EVENT,
        SUBAGENT_FINISHED_EVENT,
        SUBAGENT_ERROR_EVENT,
    ),
)


__all__ = [
    "ACTIVITY_DELTA_EVENT",
    "ACTIVITY_MESSAGE",
    "ACTIVITY_SNAPSHOT_EVENT",
    "ASSISTANT_MESSAGE",
    "AUDIO_PART",
    "CONTENT_PART",
    "CONTEXT",
    "CUSTOM_EVENT",
    "DATA_SOURCE",
    "DEVELOPER_MESSAGE",
    "DOCUMENT_PART",
    "EVENT",
    "FILE_SOURCE",
    "IMAGE_PART",
    "INTERRUPT",
    "JSON_PATCH_OPERATION",
    "MESSAGE",
    "MESSAGES_SNAPSHOT_EVENT",
    "METADATA",
    "PART_SOURCE",
    "PROTOCOL_VERSION",
    "RAW_EVENT",
    "REASONING_ENCRYPTED_VALUE_EVENT",
    "REASONING_END_EVENT",
    "REASONING_MESSAGE",
    "REASONING_MESSAGE_CHUNK_EVENT",
    "REASONING_MESSAGE_CONTENT_EVENT",
    "REASONING_MESSAGE_END_EVENT",
    "REASONING_MESSAGE_START_EVENT",
    "REASONING_START_EVENT",
    "RESUME_ENTRY",
    "RUN_AGENT_INPUT",
    "RUN_ERROR_EVENT",
    "RUN_FINISHED_EVENT",
    "RUN_FINISHED_OUTCOME",
    "RUN_STARTED_EVENT",
    "STATE_DELTA_EVENT",
    "STATE_SNAPSHOT_EVENT",
    "STEP_FINISHED_EVENT",
    "STEP_STARTED_EVENT",
    "SUBAGENT_ERROR_EVENT",
    "SUBAGENT_FINISHED_EVENT",
    "SUBAGENT_STARTED_EVENT",
    "SYSTEM_MESSAGE",
    "TEXT_MESSAGE_CHUNK_EVENT",
    "TEXT_MESSAGE_CONTENT_EVENT",
    "TEXT_MESSAGE_END_EVENT",
    "TEXT_MESSAGE_ROLE",
    "TEXT_MESSAGE_START_EVENT",
    "TEXT_PART",
    "TOKEN_USAGE",
    "TOOL",
    "TOOL_CALL",
    "TOOL_CALL_ARGS_EVENT",
    "TOOL_CALL_CHUNK_EVENT",
    "TOOL_CALL_END_EVENT",
    "TOOL_CALL_RESULT_EVENT",
    "TOOL_CALL_START_EVENT",
    "TOOL_MESSAGE",
    "URL_SOURCE",
    "USER_MESSAGE",
    "VIDEO_PART",
    "ActivityDeltaEvent",
    "ActivityMessage",
    "ActivitySnapshotEvent",
    "AssistantMessage",
    "AudioPart",
    "CancelledOutcome",
    "Content",
    "ContentPart",
    "Context",
    "CustomEvent",
    "DataSource",
    "DeveloperMessage",
    "DocumentPart",
    "Event",
    "FileSource",
    "ImagePart",
    "Interrupt",
    "InterruptOutcome",
    "JsonPatchAdd",
    "JsonPatchCopy",
    "JsonPatchMove",
    "JsonPatchOperation",
    "JsonPatchRemove",
    "JsonPatchReplace",
    "JsonPatchTest",
    "MediaPart",
    "Message",
    "MessagesSnapshotEvent",
    "Metadata",
    "PartSource",
    "RawEvent",
    "ReasoningEncryptedValueEvent",
    "ReasoningEndEvent",
    "ReasoningMessage",
    "ReasoningMessageChunkEvent",
    "ReasoningMessageContentEvent",
    "ReasoningMessageEndEvent",
    "ReasoningMessageStartEvent",
    "ReasoningStartEvent",
    "ResumeEntry",
    "RunAgentInput",
    "RunErrorEvent",
    "RunFinishedEvent",
    "RunFinishedOutcome",
    "RunStartedEvent",
    "StateDeltaEvent",
    "StateSnapshotEvent",
    "StepFinishedEvent",
    "StepStartedEvent",
    "SubagentErrorEvent",
    "SubagentFinishedEvent",
    "SubagentStartedEvent",
    "SubagentSuccessOutcome",
    "SubagentSuspendedOutcome",
    "SuccessOutcome",
    "SystemMessage",
    "TextMessageChunkEvent",
    "TextMessageContentEvent",
    "TextMessageEndEvent",
    "TextMessageRole",
    "TextMessageStartEvent",
    "TextPart",
    "TokenUsage",
    "Tool",
    "ToolCall",
    "ToolCallArgsEvent",
    "ToolCallChunkEvent",
    "ToolCallEndEvent",
    "ToolCallFunction",
    "ToolCallResultEvent",
    "ToolCallStartEvent",
    "ToolMessage",
    "UrlSource",
    "UserMessage",
    "VideoPart",
]
