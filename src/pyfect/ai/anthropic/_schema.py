"""The parts of Anthropic's Messages API wire format the language model
reads (Effect's generated ``BetaMessage``, its stream events and the error
envelope). A decoded value is the JSON object itself, checked against the
schema, so the fields the schema leaves out reach provider metadata
unchanged; content blocks are read field by field where they are used.
"""

from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict, cast

from pyfect import schema as S
from pyfect.ai._provider import wire_decoder, wire_match

type ContentBlock = dict[str, Any]


class Usage(TypedDict):
    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: NotRequired[int | None]
    cache_read_input_tokens: NotRequired[int | None]
    inference_geo: NotRequired[str | None]


class Message(TypedDict):
    id: str
    type: Literal["message"]
    role: Literal["assistant"]
    content: list[ContentBlock]
    model: str
    stop_reason: str | None
    stop_sequence: str | None
    usage: Usage
    container: NotRequired[dict[str, Any] | None]
    context_management: NotRequired[dict[str, Any] | None]


type ErrorType = Literal[
    "invalid_request_error",
    "authentication_error",
    "billing_error",
    "permission_error",
    "not_found_error",
    "rate_limit_error",
    "timeout_error",
    "api_error",
    "overloaded_error",
]


class ErrorDetail(TypedDict):
    type: ErrorType
    message: str


class ErrorResponse(TypedDict):
    """Anthropic's error envelope (``BetaErrorResponse``)."""

    type: Literal["error"]
    error: ErrorDetail
    request_id: str | None


class _ErrorBodyDetail(TypedDict):
    type: str
    message: str


class ErrorBody(TypedDict):
    """The error body ``map_status_code_error`` reads (looser than the
    envelope: any error type, no request id)."""

    type: Literal["error"]
    error: _ErrorBodyDetail


class MessageStartEvent(TypedDict):
    type: Literal["message_start"]
    message: Message


class MessageDeltaUsage(TypedDict):
    output_tokens: int
    input_tokens: NotRequired[int | None]
    cache_creation_input_tokens: NotRequired[int | None]
    cache_read_input_tokens: NotRequired[int | None]


class MessageDelta(TypedDict):
    stop_reason: str | None
    stop_sequence: str | None
    container: NotRequired[dict[str, Any] | None]


class MessageDeltaEvent(TypedDict):
    type: Literal["message_delta"]
    delta: MessageDelta
    usage: MessageDeltaUsage
    context_management: NotRequired[dict[str, Any] | None]


class MessageStopEvent(TypedDict):
    type: Literal["message_stop"]


class ContentBlockStartEvent(TypedDict):
    type: Literal["content_block_start"]
    index: int
    content_block: ContentBlock


class ContentBlockDeltaEvent(TypedDict):
    type: Literal["content_block_delta"]
    index: int
    delta: dict[str, Any]


class ContentBlockStopEvent(TypedDict):
    type: Literal["content_block_stop"]
    index: int


class PingEvent(TypedDict):
    type: Literal["ping"]


type MessageStreamEvent = (
    MessageStartEvent
    | MessageDeltaEvent
    | MessageStopEvent
    | ContentBlockStartEvent
    | ContentBlockDeltaEvent
    | ContentBlockStopEvent
    | ErrorResponse
)
"""An event of a streamed message (Effect's ``MessageStreamEvent``)."""

BLOCK_TYPES = frozenset(
    {
        "text",
        "thinking",
        "redacted_thinking",
        "tool_use",
        "server_tool_use",
        "web_search_tool_result",
        "web_fetch_tool_result",
        "advisor_tool_result",
        "code_execution_tool_result",
        "bash_code_execution_tool_result",
        "text_editor_code_execution_tool_result",
        "tool_search_tool_result",
        "mcp_tool_use",
        "mcp_tool_result",
        "container_upload",
        "compaction",
        "fallback",
        "mcp_tool_listing",
    }
)
"""The content blocks Effect's ``BetaContentBlock`` knows; another fails
the response."""
DELTA_TYPES = frozenset(
    {
        "text_delta",
        "input_json_delta",
        "citations_delta",
        "thinking_delta",
        "signature_delta",
        "compaction_delta",
    }
)
"""The deltas Effect's ``BetaContentBlockDeltaEvent`` (what its stream
reads) knows."""


def _tagged(types: frozenset[str], title: str) -> S.Codec[dict[str, Any], Any, Any, Any]:
    def known(value: dict[str, Any]) -> bool:
        return value.get("type") in types

    expected = f"a {title} of type {' | '.join(sorted(types))}"
    return S.Record(S.String, S.Any).check(S.make_filter(known, expected=expected))


CONTENT_BLOCK = _tagged(BLOCK_TYPES, "content block")
DELTA = _tagged(DELTA_TYPES, "delta")
MESSAGE = S.Struct(Message, content=S.List(CONTENT_BLOCK))
ERROR_RESPONSE = S.Struct(ErrorResponse)
STREAM_EVENT = S.Union(
    S.Struct(PingEvent),
    S.Struct(MessageStartEvent, message=MESSAGE),
    S.Struct(MessageDeltaEvent),
    S.Struct(MessageStopEvent),
    S.Struct(ContentBlockStartEvent, content_block=CONTENT_BLOCK),
    S.Struct(ContentBlockDeltaEvent, delta=DELTA),
    S.Struct(ContentBlockStopEvent),
    ERROR_RESPONSE,
)

decode_message = wire_decoder(MESSAGE, Message)
decode_event = wire_decoder(STREAM_EVENT, cast("type[MessageStreamEvent | PingEvent]", dict))
decode_error_response = wire_decoder(ERROR_RESPONSE, ErrorResponse)
_match_error_response = wire_match(ERROR_RESPONSE, ErrorResponse)
error_body = wire_match(S.Struct(ErrorBody), ErrorBody)


def is_error_response(json: object) -> bool:
    return _match_error_response(json) is not None
