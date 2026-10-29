"""The Chat Completions and Embeddings wire format an OpenAI-compatible
provider answers with (Effect's ``ChatCompletionResponse``,
``ChatCompletionChunk`` and ``CreateEmbeddingResponse`` schemas). A decoded
value is the JSON itself, checked against the schema, so fields the schema
leaves out (``prompt_tokens_details``, provider extras) stay readable."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, NotRequired, TypedDict, cast

from pyfect import schema as S
from pyfect._core import Effect


class ToolFunction(TypedDict):
    name: NotRequired[str | None]
    arguments: NotRequired[str]


class ToolCall(TypedDict):
    id: NotRequired[str | None]
    index: NotRequired[int]
    type: NotRequired[str]
    extra_content: NotRequired[dict[str, Any] | None]
    function: NotRequired[ToolFunction]


class Message(TypedDict):
    role: NotRequired[str | None]
    content: NotRequired[str | None]
    reasoning: NotRequired[str | None]
    reasoning_content: NotRequired[str | None]
    tool_calls: NotRequired[list[ToolCall] | None]


class Choice(TypedDict):
    index: int
    finish_reason: NotRequired[str | None]
    message: NotRequired[Message]
    delta: NotRequired[Message]


class Usage(TypedDict):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class ChatCompletion(TypedDict):
    """A response, or one streamed chunk of it."""

    id: str
    model: str
    created: int
    choices: list[Choice]
    usage: NotRequired[Usage | None]
    service_tier: NotRequired[str]


class Embedding(TypedDict):
    embedding: list[float] | str
    index: int
    object: NotRequired[str]


class EmbeddingUsage(TypedDict):
    prompt_tokens: int
    total_tokens: int


class EmbeddingResponse(TypedDict):
    data: list[Embedding]
    model: str
    object: NotRequired[Literal["list"]]
    usage: NotRequired[EmbeddingUsage]


CHAT_COMPLETION = S.Struct(ChatCompletion)
EMBEDDING_RESPONSE = S.Struct(EmbeddingResponse)

_check_completion = S.decode_unknown_effect(CHAT_COMPLETION)
_check_embedding = S.decode_unknown_effect(EMBEDDING_RESPONSE)
is_chunk = S.is_(CHAT_COMPLETION)


def decode_completion(json: object) -> Effect[ChatCompletion, S.SchemaError]:
    return _check_completion(json).map(lambda _: cast("ChatCompletion", json))


def decode_embedding(json: object) -> Effect[EmbeddingResponse, S.SchemaError]:
    return _check_embedding(json).map(lambda _: cast("EmbeddingResponse", json))


@dataclass(frozen=True)
class UnknownEvent:
    """A streamed event that is not a chunk, kept for direct client users."""

    data: object


type StreamEvent = ChatCompletion | UnknownEvent | Literal["[DONE]"]
