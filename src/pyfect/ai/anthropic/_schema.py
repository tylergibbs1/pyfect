"""The parts of Anthropic's Messages API wire format the language model
reads (Effect's generated ``BetaMessage``, its stream events and the error
envelope). A decoded value is the JSON object itself, checked against the
schema, so the fields the schema leaves out reach provider metadata
unchanged; content blocks are read field by field where they are used.
"""

from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict, cast

from pyfect import schema as S
from pyfect._core import Effect

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

MESSAGE = S.Struct(Message)
ERROR_RESPONSE = S.Struct(ErrorResponse)
STREAM_EVENT = S.Union(
    S.Struct(PingEvent),
    S.Struct(MessageStartEvent),
    S.Struct(MessageDeltaEvent),
    S.Struct(MessageStopEvent),
    S.Struct(ContentBlockStartEvent),
    S.Struct(ContentBlockDeltaEvent),
    S.Struct(ContentBlockStopEvent),
    ERROR_RESPONSE,
)

_check_message = S.decode_unknown_effect(MESSAGE)
_check_event = S.decode_unknown_effect(STREAM_EVENT)
_is_error_response = S.is_(ERROR_RESPONSE)


def decode_message(json: object) -> Effect[Message, S.SchemaError]:
    return _check_message(json).map(lambda _: cast("Message", json))


def decode_event(json: object) -> Effect[MessageStreamEvent | PingEvent, S.SchemaError]:
    return _check_event(json).map(lambda _: cast("MessageStreamEvent | PingEvent", json))


def is_error_response(json: object) -> bool:
    return _is_error_response(json)


_is_error_body = S.is_(S.Struct(ErrorBody))


def error_body(json: object) -> ErrorBody | None:
    return json if _is_error_body(json) else None
