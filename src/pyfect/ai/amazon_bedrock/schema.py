"""The part of the Amazon Bedrock Converse API this provider uses (Effect's
``AmazonBedrockSchema``): the Converse request, its response and the
ConverseStream events, as ``TypedDict`` types in the wire's camelCase.

The Converse API's unions (content blocks, deltas, stream events) are
objects whose members are all optional. A decoded response or event is the
JSON object itself, checked against its schema, so a block member, field or
event this provider does not model reaches the caller unchanged instead of
failing the response or being dropped. Blobs travel as base64 strings.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, Literal, NewType, NotRequired, TypedDict, TypeIs, cast, final

from pyfect import schema as S
from pyfect.ai._provider import wire_decoder

# Common ---------------------------------------------------------------------------------

type KnownStopReason = Literal[
    "end_turn",
    "tool_use",
    "max_tokens",
    "stop_sequence",
    "guardrail_intervened",
    "content_filtered",
    "malformed_model_output",
    "malformed_tool_use",
    "model_context_window_exceeded",
]
"""The stop reasons the Converse API's Smithy model names."""

type StopReason = KnownStopReason | str
"""Why the model stopped; any string, so a reason Bedrock adds later does
not fail the response."""


class TokenUsage(TypedDict):
    """Bedrock token counts: input, output, total and prompt cache reads and writes."""

    inputTokens: int
    outputTokens: int
    totalTokens: int
    cacheReadInputTokens: NotRequired[int]
    cacheWriteInputTokens: NotRequired[int]


# Content blocks -------------------------------------------------------------------------


class ToolUseBlock(TypedDict):
    """The model's request to call a tool."""

    toolUseId: str
    name: str
    input: Any


class ToolResultContentBlock(TypedDict, total=False):
    """A piece of a tool result: text or a JSON document."""

    text: str
    json: Any


class ToolResultBlock(TypedDict):
    """The outcome of a tool call, sent back to the model."""

    toolUseId: str
    content: Sequence[ToolResultContentBlock]
    status: NotRequired[Literal["success", "error"]]


class ReasoningTextBlock(TypedDict):
    """Reasoning text, with the ``signature`` proving the model wrote it
    (sent back unchanged in a later turn)."""

    text: str
    signature: NotRequired[str]


class ReasoningContentBlock(TypedDict, total=False):
    """Reasoning text, or reasoning the model provider redacted (base64)."""

    reasoningText: ReasoningTextBlock
    redactedContent: str


class CachePointBlock(TypedDict):
    """The end of a reusable prefix of a request. Converse caches what
    precedes the block, so it follows the content it covers; ``ttl`` opts
    into extended caching."""

    type: Literal["default"]
    ttl: NotRequired[Literal["5m", "1h"]]


type ImageFormat = Literal["png", "jpeg", "gif", "webp"]
type DocumentFormat = Literal["pdf", "csv", "doc", "docx", "xls", "xlsx", "html", "txt", "md"]


class BytesSource(TypedDict):
    """Bedrock content given inline as base64 bytes."""

    bytes: str


class ImageBlock(TypedDict):
    """A Bedrock image content block: its format and bytes."""

    format: ImageFormat
    source: BytesSource


class DocumentBlock(TypedDict):
    """A document. Bedrock restricts ``name`` to alphanumerics, single runs
    of whitespace, hyphens, parentheses and square brackets."""

    format: DocumentFormat
    name: str
    source: BytesSource


class ContentBlock(TypedDict, total=False):
    """A block of a message; a member this provider does not model (such as
    ``citationsContent``) is kept as it was sent."""

    text: str
    toolUse: ToolUseBlock
    toolResult: ToolResultBlock
    reasoningContent: ReasoningContentBlock
    image: ImageBlock
    document: DocumentBlock
    cachePoint: CachePointBlock


class Message(TypedDict):
    """A Bedrock Converse message: a user or assistant role and its content blocks."""

    role: Literal["user", "assistant"]
    content: Sequence[ContentBlock]


class SystemContentBlock(TypedDict, total=False):
    """System text or a cache point."""

    text: str
    cachePoint: CachePointBlock


# Request --------------------------------------------------------------------------------


class InferenceConfiguration(TypedDict, total=False):
    """Bedrock inference settings: max tokens, stop sequences, temperature and top-p."""

    maxTokens: int
    stopSequences: Sequence[str]
    temperature: float
    topP: float


class ToolInputSchema(TypedDict):
    """The JSON Schema of a Bedrock tool's input."""

    json: Mapping[str, Any]


class ToolSpecification(TypedDict):
    """A Bedrock tool: its name, description and input schema."""

    name: str
    description: NotRequired[str]
    inputSchema: ToolInputSchema


class Tool(TypedDict, total=False):
    """A tool, or a cache point ending the cacheable prefix of the tools."""

    toolSpec: ToolSpecification
    cachePoint: CachePointBlock


class _Empty(TypedDict):
    pass


class AutoToolChoice(TypedDict):
    """Bedrock tool choice: the model decides whether to call a tool."""

    auto: _Empty


class AnyToolChoice(TypedDict):
    """Bedrock tool choice: the model must call some tool."""

    any: _Empty


class _ToolName(TypedDict):
    name: str


class SpecificToolChoice(TypedDict):
    """Bedrock tool choice: the model must call the named tool."""

    tool: _ToolName


type ToolChoice = AutoToolChoice | AnyToolChoice | SpecificToolChoice
"""Let the model decide (``auto``), force some tool (``any``) or one tool."""


class ToolConfiguration(TypedDict):
    """A Bedrock request's tools and how the model may choose among them."""

    tools: Sequence[Tool]
    toolChoice: NotRequired[ToolChoice]


class JsonSchemaDefinition(TypedDict):
    """The JSON Schema the output must follow, serialized to a string."""

    schema: str
    name: NotRequired[str]
    description: NotRequired[str]


class _Structure(TypedDict):
    jsonSchema: JsonSchemaDefinition


class OutputFormat(TypedDict):
    """A Bedrock structured output format: a JSON Schema the response must match."""

    type: Literal["json_schema"]
    structure: _Structure


class OutputConfig(TypedDict, total=False):
    """Native structured output (``textFormat``) and the model's effort."""

    textFormat: OutputFormat
    effort: str


class GuardrailConfiguration(TypedDict):
    """A request's guardrail; ``streamProcessingMode`` applies to
    ConverseStream only and is left out of Converse requests."""

    guardrailIdentifier: str
    guardrailVersion: str
    trace: NotRequired[Literal["enabled", "disabled", "enabled_full"]]
    streamProcessingMode: NotRequired[Literal["sync", "async"]]


class ConverseRequest(TypedDict):
    """A Converse or ConverseStream request. ``modelId`` goes in the URL,
    the rest is the body; ``additionalModelRequestFields`` carries the
    target model's own parameters (extended thinking on Anthropic models)."""

    modelId: str
    messages: Sequence[Message]
    system: NotRequired[Sequence[SystemContentBlock]]
    toolConfig: NotRequired[ToolConfiguration]
    inferenceConfig: NotRequired[InferenceConfiguration]
    outputConfig: NotRequired[OutputConfig]
    additionalModelRequestFields: NotRequired[Mapping[str, Any]]
    guardrailConfig: NotRequired[GuardrailConfiguration]


# Response -------------------------------------------------------------------------------


class ConverseMetrics(TypedDict):
    """Bedrock Converse metrics: the request's latency in milliseconds."""

    latencyMs: float


class ConverseOutput(TypedDict):
    """A Bedrock Converse response's output: the assistant's message."""

    message: Message


class ConverseResponse(TypedDict):
    """A Converse answer; ``trace`` and fields this provider does not model
    (``additionalModelResponseFields``, ...) are kept as Bedrock sent them."""

    output: ConverseOutput
    usage: TokenUsage
    stopReason: StopReason
    metrics: NotRequired[ConverseMetrics]
    trace: NotRequired[Any]


# Stream events --------------------------------------------------------------------------


class MessageStartEvent(TypedDict):
    """Bedrock stream event body: a message starts, with its role."""

    role: Literal["user", "assistant"]


class ToolUseStart(TypedDict):
    """The start of a Bedrock tool use block: the call's id and tool name."""

    toolUseId: str
    name: str


class ContentBlockStart(TypedDict, total=False):
    """What a streamed Bedrock content block starts with, such as a tool use."""

    toolUse: ToolUseStart


class ContentBlockStartEvent(TypedDict):
    """A block's start; tool-use blocks announce their id and name here,
    text and reasoning blocks start with their first delta."""

    contentBlockIndex: int
    start: NotRequired[ContentBlockStart]


class ToolUseDelta(TypedDict):
    """The next piece of a streamed Bedrock tool call's JSON input."""

    input: str


class ReasoningContentDelta(TypedDict, total=False):
    """The next piece of streamed Bedrock reasoning: text, a signature or redacted content."""

    text: str
    signature: str
    redactedContent: str


class ContentBlockDelta(TypedDict, total=False):
    """Text, a fragment of a tool's input JSON, or reasoning; a member this
    provider does not model (such as ``citation``) is kept as it was sent."""

    text: str
    toolUse: ToolUseDelta
    reasoningContent: ReasoningContentDelta


class ContentBlockDeltaEvent(TypedDict):
    """Bedrock stream event body: a delta for the content block at an index."""

    contentBlockIndex: int
    delta: ContentBlockDelta


class ContentBlockStopEvent(TypedDict):
    """Bedrock stream event body: the content block at an index is complete."""

    contentBlockIndex: int


class MessageStopEvent(TypedDict):
    """Bedrock stream event body: the message ends, with its stop reason."""

    stopReason: StopReason


class ConverseStreamMetadataEvent(TypedDict):
    """The stream's last event, after ``messageStop``: usage and metrics."""

    usage: TokenUsage
    metrics: NotRequired[ConverseMetrics]
    trace: NotRequired[Any]


@final
class MessageStart(TypedDict):
    """A ConverseStream event that starts a message."""

    messageStart: MessageStartEvent


@final
class ContentBlockStartStreamEvent(TypedDict):
    """A ConverseStream event that starts a content block."""

    contentBlockStart: ContentBlockStartEvent


@final
class ContentBlockDeltaStreamEvent(TypedDict):
    """A ConverseStream event that carries a content block delta."""

    contentBlockDelta: ContentBlockDeltaEvent


@final
class ContentBlockStopStreamEvent(TypedDict):
    """A ConverseStream event that ends a content block."""

    contentBlockStop: ContentBlockStopEvent


@final
class MessageStop(TypedDict):
    """A ConverseStream event that ends a message."""

    messageStop: MessageStopEvent


@final
class Metadata(TypedDict):
    """A ConverseStream event with the response's usage and metrics."""

    metadata: ConverseStreamMetadataEvent


type KnownConverseStreamEvent = (
    MessageStart
    | ContentBlockStartStreamEvent
    | ContentBlockDeltaStreamEvent
    | ContentBlockStopStreamEvent
    | MessageStop
    | Metadata
)

KNOWN_STREAM_EVENT_TYPES = frozenset(
    {
        "messageStart",
        "contentBlockStart",
        "contentBlockDelta",
        "contentBlockStop",
        "messageStop",
        "metadata",
    }
)

UnknownConverseStreamEvent = NewType("UnknownConverseStreamEvent", dict[str, object])
"""An event this provider does not model, keyed by its ``:event-type`` like
the others: ``{event_type: payload}``."""

type ConverseStreamEvent = KnownConverseStreamEvent | UnknownConverseStreamEvent
"""A ConverseStream event keyed by its ``:event-type``, as the AWS SDK shapes
it (``{"messageStart": ...}``); an event type this provider does not model is
an ``UnknownConverseStreamEvent``, a malformed known one fails."""


def is_known_stream_event(event: ConverseStreamEvent) -> TypeIs[KnownConverseStreamEvent]:
    """Whether ``event`` is one this provider models (so ``in`` narrows it)."""
    return next(iter(event), None) in KNOWN_STREAM_EVENT_TYPES


class ConverseStreamException(TypedDict):
    """The body of an exception frame (a ``throttlingException``, ...)."""

    message: NotRequired[str]


def _is_unknown_event(value: object) -> TypeIs[UnknownConverseStreamEvent]:
    if not isinstance(value, dict):
        return False
    keys = list(cast("dict[object, object]", value))
    return len(keys) == 1 and keys[0] not in KNOWN_STREAM_EVENT_TYPES


UNKNOWN_CONVERSE_STREAM_EVENT = S.declare(
    _is_unknown_event,
    identifier="UnknownConverseStreamEvent",
    description="Fallback for unknown future stream events",
)
CONVERSE_RESPONSE = S.Struct(ConverseResponse)
CONVERSE_STREAM_EVENT = S.Union(
    S.Struct(MessageStart),
    S.Struct(ContentBlockStartStreamEvent),
    S.Struct(ContentBlockDeltaStreamEvent),
    S.Struct(ContentBlockStopStreamEvent),
    S.Struct(MessageStop),
    S.Struct(Metadata),
    UNKNOWN_CONVERSE_STREAM_EVENT,
)
CONVERSE_STREAM_EXCEPTION = S.Struct(ConverseStreamException)

decode_converse_response = wire_decoder(CONVERSE_RESPONSE, ConverseResponse)
"""A Converse response checked against its schema, fields it leaves out kept."""
decode_converse_stream_event = wire_decoder(
    CONVERSE_STREAM_EVENT, cast("type[ConverseStreamEvent]", dict)
)
"""A stream event checked against its schema, fields it leaves out kept."""
decode_converse_stream_exception = wire_decoder(CONVERSE_STREAM_EXCEPTION, ConverseStreamException)

__all__ = [
    "CONVERSE_RESPONSE",
    "CONVERSE_STREAM_EVENT",
    "CONVERSE_STREAM_EXCEPTION",
    "KNOWN_STREAM_EVENT_TYPES",
    "UNKNOWN_CONVERSE_STREAM_EVENT",
    "AnyToolChoice",
    "AutoToolChoice",
    "BytesSource",
    "CachePointBlock",
    "ContentBlock",
    "ContentBlockDelta",
    "ContentBlockDeltaEvent",
    "ContentBlockDeltaStreamEvent",
    "ContentBlockStart",
    "ContentBlockStartEvent",
    "ContentBlockStartStreamEvent",
    "ContentBlockStopEvent",
    "ContentBlockStopStreamEvent",
    "ConverseMetrics",
    "ConverseOutput",
    "ConverseRequest",
    "ConverseResponse",
    "ConverseStreamEvent",
    "ConverseStreamException",
    "ConverseStreamMetadataEvent",
    "DocumentBlock",
    "DocumentFormat",
    "GuardrailConfiguration",
    "ImageBlock",
    "ImageFormat",
    "InferenceConfiguration",
    "JsonSchemaDefinition",
    "KnownConverseStreamEvent",
    "KnownStopReason",
    "Message",
    "MessageStart",
    "MessageStartEvent",
    "MessageStop",
    "MessageStopEvent",
    "Metadata",
    "OutputConfig",
    "OutputFormat",
    "ReasoningContentBlock",
    "ReasoningContentDelta",
    "ReasoningTextBlock",
    "SpecificToolChoice",
    "StopReason",
    "SystemContentBlock",
    "TokenUsage",
    "Tool",
    "ToolChoice",
    "ToolConfiguration",
    "ToolInputSchema",
    "ToolResultBlock",
    "ToolResultContentBlock",
    "ToolSpecification",
    "ToolUseBlock",
    "ToolUseDelta",
    "ToolUseStart",
    "UnknownConverseStreamEvent",
    "decode_converse_response",
    "decode_converse_stream_event",
    "decode_converse_stream_exception",
    "is_known_stream_event",
]
