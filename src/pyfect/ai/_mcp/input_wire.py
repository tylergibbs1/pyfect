"""2026-07-28's wire forms of input requests and input responses (Effect's
``mcpSchema/v2026_07_28``). They are narrower than the session revisions' own
sampling, roots and elicitation messages: decoding with them also drops what
this revision does not carry, such as a URL elicitation's ``elicitationId``."""

from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict

from pyfect import schema as S
from pyfect._json_value import JsonValue
from pyfect.ai.mcp_schema import (
    AUDIO_CONTENT,
    CONTENT_BLOCK,
    IMAGE_CONTENT,
    JSON_OBJECT,
    PRIMITIVE_SCHEMA_DEFINITION,
    TEXT_CONTENT,
    TOOL,
    JsonObject,
    PrimitiveSchemaDefinition,
    Role,
)

_META = {"_meta": JSON_OBJECT}

# --- sampling ---------------------------------------------------------------------------


class _ToolUse(TypedDict):
    type: Literal["tool_use"]
    id: str
    name: str
    input: JsonObject
    _meta: NotRequired[JsonObject]


class _ToolResult(TypedDict):
    type: Literal["tool_result"]
    toolUseId: str
    content: list[Any]
    structuredContent: NotRequired[JsonValue]
    isError: NotRequired[bool]
    _meta: NotRequired[JsonObject]


_BLOCK: S.Codec[Any, Any] = S.Union(
    TEXT_CONTENT,
    IMAGE_CONTENT,
    AUDIO_CONTENT,
    S.Struct(_ToolUse, input=JSON_OBJECT, **_META),
    S.Struct(
        _ToolResult,
        content=S.List(CONTENT_BLOCK),
        structuredContent=S.Json,
        **_META,
    ),
)
_CONTENT = S.Union(_BLOCK, S.List(_BLOCK))


class _SamplingMessage(TypedDict):
    role: Role
    content: Any
    _meta: NotRequired[JsonObject]


class _ModelHint(TypedDict, total=False):
    name: str


_PRIORITY = S.Finite.check(S.is_between(minimum=0, maximum=1))


class _ModelPreferences(TypedDict, total=False):
    hints: list[Any]
    costPriority: float
    speedPriority: float
    intelligencePriority: float


class _ToolChoice(TypedDict, total=False):
    mode: Literal["auto", "required", "none"]


class _CreateMessage(TypedDict):
    messages: list[Any]
    maxTokens: int
    modelPreferences: NotRequired[Any]
    systemPrompt: NotRequired[str]
    includeContext: NotRequired[Literal["none", "thisServer", "allServers"]]
    temperature: NotRequired[float]
    stopSequences: NotRequired[list[str]]
    metadata: NotRequired[JsonObject]
    tools: NotRequired[list[Any]]
    toolChoice: NotRequired[_ToolChoice]


_CREATE_MESSAGE = S.Struct(
    _CreateMessage,
    messages=S.List(S.Struct(_SamplingMessage, content=_CONTENT, **_META)),
    modelPreferences=S.Struct(
        _ModelPreferences,
        hints=S.List(S.StructWithRest(S.Struct(_ModelHint), S.Record(S.String, S.Json))),
        costPriority=_PRIORITY,
        speedPriority=_PRIORITY,
        intelligencePriority=_PRIORITY,
    ),
    temperature=S.Finite,
    metadata=JSON_OBJECT,
    tools=S.List(TOOL),
)

# --- elicitation ------------------------------------------------------------------------

_RequestedSchema = TypedDict(
    "_RequestedSchema",
    {
        "$schema": NotRequired[str],
        "type": Literal["object"],
        "properties": dict[str, PrimitiveSchemaDefinition],
        "required": NotRequired[list[str]],
    },
)


class _ElicitForm(TypedDict):
    mode: NotRequired[Literal["form"]]
    message: str
    requestedSchema: _RequestedSchema


class _ElicitUrl(TypedDict):
    mode: Literal["url"]
    message: str
    url: str


_ELICIT_PARAMS = S.Union(
    S.Struct(
        _ElicitForm,
        requestedSchema=S.Struct(
            _RequestedSchema, properties=S.Record(S.String, PRIMITIVE_SCHEMA_DEFINITION)
        ),
    ),
    S.Struct(_ElicitUrl),
)

# --- requests ---------------------------------------------------------------------------


class _RootsParams(TypedDict, total=False):
    _meta: JsonObject


class _Roots(TypedDict):
    method: Literal["roots/list"]
    params: NotRequired[_RootsParams]


class _Sampling(TypedDict):
    method: Literal["sampling/createMessage"]
    params: _CreateMessage


class _Elicitation(TypedDict):
    method: Literal["elicitation/create"]
    params: Any


INPUT_REQUESTS: S.Codec[dict[str, Any], Any] = S.Record(
    S.String,
    S.Union(
        S.Struct(_Sampling, params=_CREATE_MESSAGE),
        S.Struct(_Roots, params=S.Struct(_RootsParams, **_META)),
        S.Struct(_Elicitation, params=_ELICIT_PARAMS),
    ),
)
"""What ``InputRequired.input_requests`` may hold; what it decodes to goes out."""

# --- responses --------------------------------------------------------------------------


class _CreateMessageResult(TypedDict):
    role: Role
    content: Any
    _meta: NotRequired[JsonObject]
    model: str
    stopReason: NotRequired[str]


class _Root(TypedDict):
    uri: str
    name: NotRequired[str]
    _meta: NotRequired[JsonObject]


class _ListRootsResult(TypedDict):
    roots: list[_Root]


class _ElicitResult(TypedDict):
    action: Literal["accept", "decline", "cancel"]
    content: NotRequired[dict[str, str | float | bool | list[str]]]


_INPUT_RESPONSE = S.Union(
    S.Struct(_CreateMessageResult, content=_CONTENT, **_META),
    S.Struct(_ListRootsResult, roots=S.List(S.Struct(_Root, **_META))),
    S.Struct(
        _ElicitResult,
        content=S.Record(S.String, S.Union(S.String, S.Finite, S.Boolean, S.List(S.String))),
    ),
)


class ContinuationParams(TypedDict, total=False):
    """A retried request's answers to its ``InputRequired``."""

    inputResponses: dict[str, Any]
    requestState: str


CONTINUATION_PARAMS = S.Struct(
    ContinuationParams, inputResponses=S.Record(S.String, _INPUT_RESPONSE)
)
