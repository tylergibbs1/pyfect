"""The Responses, Embeddings and Decisions wire format the client sends and
reads (Effect's hand-written ``OpenAiSchema``). Requests are typed only:
the client sends them as JSON. Responses and stream events are decoded,
which drops the keys a schema does not declare, as Effect's do; usage
keeps every key, and a stream event of a type this library does not know
passes through as it came (``UnknownResponseStreamEvent``)."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Literal, NotRequired, TypedDict, TypeIs, cast

from pyfect import schema as S
from pyfect._core import Effect
from pyfect.ai._provider import wire_parser, wire_parser_option
from pyfect.ai.openai._generated_support import struct

type JsonObject = dict[str, Any]

MessageStatus = Literal["in_progress", "completed", "incomplete"]
IncludeEnum = Literal[
    "message.input_image.image_url",
    "reasoning.encrypted_content",
    "message.output_text.logprobs",
    "code_interpreter_call.outputs",
    "web_search_call.action.sources",
]


class PromptCacheBreakpoint(TypedDict):
    mode: Literal["explicit"]


# --- requests ---------------------------------------------------------------------------


class _ReasoningConfig(TypedDict, total=False):
    effort: Literal["none", "minimal", "low", "medium", "high", "xhigh", "max"]
    summary: Literal["auto", "concise", "detailed"]
    generate_summary: Literal["auto", "concise", "detailed"]


class _PromptCacheOptions(TypedDict, total=False):
    mode: Literal["implicit", "explicit"]
    ttl: Literal["30m"]
    comparison_response_id: str | None


class _TextConfig(TypedDict, total=False):
    format: JsonObject
    verbosity: Literal["low", "medium", "high"]


class CreateResponse(TypedDict, total=False):
    """A ``POST /responses`` body."""

    metadata: dict[str, str]
    top_logprobs: int
    temperature: float
    top_p: float
    user: str
    safety_identifier: str
    prompt_cache_key: str
    prompt_cache_retention: Literal["in_memory", "24h"]
    prompt_cache_options: _PromptCacheOptions
    service_tier: str
    previous_response_id: str
    model: str
    reasoning: _ReasoningConfig
    background: bool
    max_output_tokens: int
    max_tool_calls: int
    text: _TextConfig
    tools: list[JsonObject]
    tool_choice: str | JsonObject
    truncation: Literal["auto", "disabled"]
    input: str | list[JsonObject]
    include: list[IncludeEnum]
    store: bool
    instructions: str
    stream: bool
    conversation: str
    modalities: list[Literal["text", "audio"]]
    seed: int


class CreateEmbeddingRequest(TypedDict):
    """A ``POST /embeddings`` body."""

    input: str | Sequence[str] | Sequence[int] | Sequence[Sequence[int]]
    model: str
    encoding_format: NotRequired[Literal["float", "base64"]]
    dimensions: NotRequired[int]
    user: NotRequired[str]


class CreateDecisionsRequest(TypedDict):
    """A ``POST /decisions`` body."""

    model: str
    input: str | list[JsonObject]
    questions: list[JsonObject]


# --- responses --------------------------------------------------------------------------


class Annotation(TypedDict):
    """A file or URL citation, or a file path, in output text."""

    type: Literal["file_citation", "url_citation", "container_file_citation", "file_path"]
    file_id: NotRequired[str]
    index: NotRequired[int]
    filename: NotRequired[str]
    url: NotRequired[str]
    start_index: NotRequired[int]
    end_index: NotRequired[int]
    title: NotRequired[str]
    container_id: NotRequired[str]


class _FileCitation(TypedDict):
    type: Literal["file_citation"]
    file_id: str
    index: int
    filename: str


class _UrlCitation(TypedDict):
    type: Literal["url_citation"]
    url: str
    start_index: int
    end_index: int
    title: str


class _ContainerFileCitation(TypedDict):
    type: Literal["container_file_citation"]
    container_id: str
    file_id: str
    start_index: int
    end_index: int
    filename: str


class _FilePath(TypedDict):
    type: Literal["file_path"]
    file_id: str
    index: int


ANNOTATION = S.Union(
    S.Struct(_FileCitation),
    S.Struct(_UrlCitation),
    S.Struct(_ContainerFileCitation),
    S.Struct(_FilePath),
)


class _InputText(TypedDict):
    type: Literal["input_text"]
    text: str
    prompt_cache_breakpoint: NotRequired[PromptCacheBreakpoint]


class _InputImage(TypedDict):
    type: Literal["input_image"]
    image_url: NotRequired[str | None]
    file_id: NotRequired[str | None]
    detail: NotRequired[Literal["low", "high", "auto"] | None]
    prompt_cache_breakpoint: NotRequired[PromptCacheBreakpoint]


class _InputFile(TypedDict):
    type: Literal["input_file"]
    file_id: NotRequired[str | None]
    filename: NotRequired[str]
    file_url: NotRequired[str]
    file_data: NotRequired[str]
    prompt_cache_breakpoint: NotRequired[PromptCacheBreakpoint]


class SummaryText(TypedDict):
    type: Literal["summary_text"]
    text: str


class _ReasoningText(TypedDict):
    type: Literal["reasoning_text"]
    text: str


class _Refusal(TypedDict):
    type: Literal["refusal"]
    refusal: str


class _Text(TypedDict):
    type: Literal["text"]
    text: str


class _ComputerScreenshot(TypedDict):
    type: Literal["computer_screenshot"]
    image_url: str | None
    file_id: str | None


class _OutputText(TypedDict):
    type: Literal["output_text"]
    text: str
    annotations: list[Annotation]
    logprobs: NotRequired[list[object]]


_OUTPUT_TEXT = S.Struct(_OutputText, annotations=S.List(ANNOTATION))

type OutputItem = dict[str, Any]
"""An item of a response's ``output``, decoded by its ``type``."""


class _OutputMessage(TypedDict):
    id: str
    type: Literal["message"]
    role: Literal["assistant"]
    content: list[dict[str, Any]]
    status: MessageStatus


class ReasoningItem(TypedDict):
    type: Literal["reasoning"]
    id: str
    encrypted_content: NotRequired[str | None]
    summary: list[SummaryText]
    content: NotRequired[list[_ReasoningText]]
    status: NotRequired[MessageStatus]


class _FunctionCall(TypedDict):
    id: NotRequired[str]
    type: Literal["function_call"]
    call_id: str
    name: str
    arguments: str
    status: NotRequired[MessageStatus]


class _LocalShellCall(TypedDict):
    id: NotRequired[str]
    type: Literal["local_shell_call"]
    call_id: str
    action: object
    status: NotRequired[MessageStatus]


class _ShellCall(TypedDict):
    id: NotRequired[str]
    type: Literal["shell_call"]
    call_id: str
    action: object
    status: NotRequired[MessageStatus]


class _ApplyPatchOperation(TypedDict):
    type: str
    path: str
    diff: NotRequired[str]


class _ApplyPatchCall(TypedDict):
    id: str
    type: Literal["apply_patch_call"]
    call_id: str
    operation: _ApplyPatchOperation
    status: NotRequired[MessageStatus]


class _CodeInterpreterCall(TypedDict):
    id: str
    type: Literal["code_interpreter_call"]
    code: NotRequired[str | None]
    container_id: str
    outputs: NotRequired[list[object] | None]
    status: NotRequired[Literal["in_progress", "completed", "incomplete", "interpreting", "failed"]]


class _ComputerCall(TypedDict):
    id: str
    type: Literal["computer_call"]
    status: NotRequired[MessageStatus]


class _FileSearchCall(TypedDict):
    id: str
    type: Literal["file_search_call"]
    status: NotRequired[str]
    queries: NotRequired[list[str]]
    results: NotRequired[object]


class _ImageGenerationCall(TypedDict):
    id: str
    type: Literal["image_generation_call"]
    result: NotRequired[str | None]
    status: NotRequired[Literal["in_progress", "completed", "generating", "failed"]]


class _McpCall(TypedDict):
    id: str
    type: Literal["mcp_call"]
    approval_request_id: NotRequired[str | None]
    name: str
    arguments: object
    output: NotRequired[object]
    error: NotRequired[object]
    server_label: NotRequired[str | None]


class _McpListTools(TypedDict):
    id: str
    type: Literal["mcp_list_tools"]


class _McpApprovalRequest(TypedDict):
    id: str
    type: Literal["mcp_approval_request"]
    approval_request_id: NotRequired[str]
    name: str
    arguments: object


class _WebSearchCall(TypedDict):
    id: str
    type: Literal["web_search_call"]
    action: NotRequired[object]
    status: NotRequired[str]


_OUTPUT_MESSAGE_CONTENT = S.Union(
    S.Struct(_InputText),
    _OUTPUT_TEXT,
    S.Struct(_Text),
    S.Struct(SummaryText),
    S.Struct(_ReasoningText),
    S.Struct(_Refusal),
    S.Struct(_InputImage),
    S.Struct(_ComputerScreenshot),
    S.Struct(_InputFile),
)

OUTPUT_ITEM = S.Union(
    S.Struct(_ApplyPatchCall),
    S.Struct(_CodeInterpreterCall),
    S.Struct(_ComputerCall),
    S.Struct(_FileSearchCall),
    S.Struct(_FunctionCall),
    S.Struct(_ImageGenerationCall),
    S.Struct(_LocalShellCall),
    S.Struct(_McpCall),
    S.Struct(_McpListTools),
    S.Struct(_McpApprovalRequest),
    S.Struct(_OutputMessage, content=S.List(_OUTPUT_MESSAGE_CONTENT)),
    S.Struct(ReasoningItem),
    S.Struct(_ShellCall),
    S.Struct(_WebSearchCall),
)


class ResponseUsage(TypedDict):
    """Token usage; keys beyond these are kept."""

    input_tokens: int
    output_tokens: int
    total_tokens: int
    input_tokens_details: NotRequired[object]
    output_tokens_details: NotRequired[object]


class _ResponseError(TypedDict):
    code: str
    message: str


class _IncompleteDetails(TypedDict):
    reason: NotRequired[Literal["max_output_tokens", "content_filter"]]


class _CacheMiss(TypedDict):
    type: Literal["cache_miss"]
    reason: Literal[
        "model_changed",
        "prompt_cache_key_changed",
        "tools_changed",
        "text_format_changed",
        "reasoning_effort_changed",
        "verbosity_changed",
        "context_compacted",
        "input_changed",
        "service_tier_changed",
    ]
    cache_missed_tokens: int
    comparison_reusable_tokens: NotRequired[int]


class _CacheOutcome(TypedDict):
    type: Literal["cache_hit", "comparison_response_not_found", "unavailable"]


type PromptCacheDiagnostics = _CacheMiss | _CacheOutcome

PROMPT_CACHE_DIAGNOSTICS = S.Union(S.Struct(_CacheMiss), S.Struct(_CacheOutcome))


class Response(TypedDict):
    """A Responses API response."""

    id: str
    object: NotRequired[Literal["response"]]
    model: str
    created_at: int
    output: list[OutputItem]
    usage: NotRequired[ResponseUsage | None]
    error: NotRequired[_ResponseError | None]
    incomplete_details: NotRequired[_IncompleteDetails | None]
    service_tier: NotRequired[str]
    prompt_cache_diagnostics: NotRequired[PromptCacheDiagnostics]


_USAGE = S.StructWithRest(S.Struct(ResponseUsage), S.Record(S.String, S.Unknown))

RESPONSE = S.Struct(
    Response,
    output=S.List(OUTPUT_ITEM),
    usage=S.NullOr(_USAGE),
    prompt_cache_diagnostics=PROMPT_CACHE_DIAGNOSTICS,
)

# --- stream events ----------------------------------------------------------------------

type ResponseStreamEvent = dict[str, Any]
"""A streamed Responses event: one this library reads, decoded, or any
other with a string ``type``, as it came."""

KNOWN_EVENT_TYPES = frozenset(
    {
        "response.created",
        "response.completed",
        "response.incomplete",
        "response.failed",
        "response.output_item.added",
        "response.output_item.done",
        "response.output_text.delta",
        "response.output_text.annotation.added",
        "response.reasoning_summary_part.added",
        "response.reasoning_summary_part.done",
        "response.reasoning_summary_text.delta",
        "response.function_call_arguments.delta",
        "response.function_call_arguments.done",
        "response.code_interpreter_call_code.delta",
        "response.code_interpreter_call_code.done",
        "response.apply_patch_call_operation_diff.delta",
        "response.apply_patch_call_operation_diff.done",
        "response.image_generation_call.partial_image",
        "error",
    }
)
TERMINAL_EVENT_TYPES = frozenset({"response.completed", "response.incomplete", "response.failed"})

_INT = S.Int
_SEQUENCE = {"sequence_number": S.optional_key(_INT)}


def _event(type_: str, **fields: Any) -> S.Top:
    """A struct for the event ``type_`` with these field schemas (each a
    schema, or ``S.optional_key`` of one)."""
    declared: dict[str, Any] = {"type": S.Literal(cast("Any", type_)), **fields, **_SEQUENCE}
    optional: list[str] = []
    schemas: dict[str, Any] = {}
    for name, schema in declared.items():
        if isinstance(schema, S.OptionalKey):
            optional.append(name)
            schemas[name] = cast("S.OptionalKey[Any, Any, Any, Any]", schema).schema
        else:
            schemas[name] = schema
    return struct(None, schemas, tuple(optional))


def _response_event(type_: str) -> S.Top:
    return _event(type_, response=RESPONSE)


def _item_event(type_: str) -> S.Top:
    return _event(type_, output_index=_INT, item=OUTPUT_ITEM)


def _delta(type_: str, **fields: Any) -> S.Top:
    return _event(type_, item_id=S.String, output_index=_INT, **fields)


_SUMMARY = S.Struct(SummaryText)
_NULLABLE_STRING = S.NullOr(S.String)
_OPTIONAL_INT = S.optional_key(_INT)


def _is_unknown_event(value: object) -> TypeIs[dict[str, Any]]:
    if not isinstance(value, dict):
        return False
    kind = cast("dict[str, Any]", value).get("type")
    return isinstance(kind, str) and kind not in KNOWN_EVENT_TYPES


RESPONSE_STREAM_EVENT = S.Union(
    *(_response_event(kind) for kind in sorted(TERMINAL_EVENT_TYPES | {"response.created"})),
    _item_event("response.output_item.added"),
    _item_event("response.output_item.done"),
    _delta(
        "response.output_text.delta",
        content_index=_INT,
        delta=S.String,
        logprobs=S.optional_key(S.List(S.Unknown)),
    ),
    _delta(
        "response.output_text.annotation.added",
        content_index=_INT,
        annotation_index=_INT,
        annotation=ANNOTATION,
    ),
    _delta("response.reasoning_summary_part.added", summary_index=_INT, part=_SUMMARY),
    _delta("response.reasoning_summary_part.done", summary_index=_INT, part=_SUMMARY),
    _delta("response.reasoning_summary_text.delta", summary_index=_INT, delta=S.String),
    _delta("response.function_call_arguments.delta", delta=S.String),
    _delta("response.function_call_arguments.done", arguments=S.String),
    _delta("response.code_interpreter_call_code.delta", delta=S.String),
    _delta("response.code_interpreter_call_code.done", code=S.String),
    _delta("response.apply_patch_call_operation_diff.delta", delta=S.String),
    _delta("response.apply_patch_call_operation_diff.done", delta=S.optional_key(S.String)),
    _delta("response.image_generation_call.partial_image", partial_image_b64=S.String),
    _event(
        "error",
        code=_NULLABLE_STRING,
        message=S.String,
        param=_NULLABLE_STRING,
        status=_OPTIONAL_INT,
    ),
    S.declare(_is_unknown_event, identifier="UnknownResponseStreamEvent"),
)

_check_event = wire_parser(RESPONSE_STREAM_EVENT, dict[str, Any])
_parse_event = wire_parser_option(RESPONSE_STREAM_EVENT, dict[str, Any])
_check_response = wire_parser(RESPONSE, Response)


_ERROR_DETAILS = ("code", "message", "param")


def _flatten_error(json: object) -> object:
    """OpenAI can nest a stream error's details under ``error``."""
    if not isinstance(json, dict):
        return json
    event = cast("dict[str, Any]", json)
    nested = event.get("error")
    if event.get("type") != "error" or not isinstance(nested, dict):
        return event
    rest = {key: value for key, value in event.items() if key != "error"}
    details = cast("dict[str, Any]", nested)
    # Only the details Effect's ``NestedResponseErrorEvent`` declares; the
    # nested ``type`` (``insufficient_quota``, ...) must not replace ``error``.
    return {**rest, **{key: details[key] for key in _ERROR_DETAILS if key in details}}


def _with_output(json: object) -> object:
    """A response without ``output`` has none (Effect's decoding default)."""
    if not isinstance(json, dict):
        return json
    body = cast("dict[str, Any]", json)
    return body if "output" in body else {**body, "output": []}


def _defaults(json: object) -> object:
    event = _flatten_error(json)
    if not isinstance(event, dict):
        return event
    body = cast("dict[str, Any]", event)
    if body.get("type") in TERMINAL_EVENT_TYPES | {"response.created"}:
        return {**body, "response": _with_output(body.get("response"))}
    return body


def decode_event(json: object) -> Effect[ResponseStreamEvent, S.SchemaError]:
    return _check_event(_defaults(json))


def parse_event(json: object) -> ResponseStreamEvent | None:
    """``decode_event`` run at once; ``None`` for JSON that is no event."""
    return _parse_event(_defaults(json))


def decode_response(json: object) -> Effect[Response, S.SchemaError]:
    return _check_response(_with_output(json))


# --- embeddings and decisions -----------------------------------------------------------


class Embedding(TypedDict):
    embedding: list[float] | str
    index: int
    object: NotRequired[str]


class _EmbeddingUsage(TypedDict):
    prompt_tokens: int
    total_tokens: int


class CreateEmbeddingResponse(TypedDict):
    data: list[Embedding]
    model: str
    object: NotRequired[Literal["list"]]
    usage: NotRequired[_EmbeddingUsage]


CREATE_EMBEDDING_RESPONSE = S.Struct(
    CreateEmbeddingResponse,
    data=S.List(S.Struct(Embedding, embedding=S.Union(S.List(S.Finite), S.String))),
)


class _DecisionUsage(TypedDict):
    input_tokens: NotRequired[int]
    output_tokens: NotRequired[int]


class CreateDecisionsResponse(TypedDict):
    answers: list[JsonObject]
    usage: NotRequired[_DecisionUsage]


class _PredicateAnswer(TypedDict):
    type: Literal["predicate"]
    name: str
    probability: float


class _ChoiceProbability(TypedDict):
    value: str
    probability: float


class _ChoiceAnswer(TypedDict):
    type: Literal["choice"]
    name: str
    choice: str
    probabilities: list[_ChoiceProbability]
    confidence: float


class _ScoreProbability(TypedDict):
    value: int
    label: str
    probability: float


class _ScoreAnswer(TypedDict):
    type: Literal["score"]
    name: str
    score: float
    probabilities: list[_ScoreProbability]
    confidence: float


class _RefusalAnswer(TypedDict):
    type: Literal["refusal"]
    name: str


CREATE_DECISIONS_RESPONSE = S.Struct(
    CreateDecisionsResponse,
    answers=S.List(
        S.Union(
            S.Struct(_PredicateAnswer),
            S.Struct(_ChoiceAnswer),
            S.Struct(_ScoreAnswer),
            S.Struct(_RefusalAnswer),
        )
    ),
)


decode_embedding = wire_parser(CREATE_EMBEDDING_RESPONSE, CreateEmbeddingResponse)
decode_decisions = wire_parser(CREATE_DECISIONS_RESPONSE, CreateDecisionsResponse)

__all__ = [
    "Annotation",
    "CreateDecisionsRequest",
    "CreateDecisionsResponse",
    "CreateEmbeddingRequest",
    "CreateEmbeddingResponse",
    "CreateResponse",
    "Embedding",
    "IncludeEnum",
    "MessageStatus",
    "PromptCacheBreakpoint",
    "PromptCacheDiagnostics",
    "ReasoningItem",
    "Response",
    "ResponseStreamEvent",
    "ResponseUsage",
    "decode_decisions",
    "decode_embedding",
    "decode_event",
    "decode_response",
]
