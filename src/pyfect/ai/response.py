"""The parts of a language model's response (Effect's ``Response``).

A generated response is a list of parts: text, reasoning, tool calls, tool
results, approval requests, files, sources, metadata and a finish part. A
streamed one also has the start / delta / end parts of text, reasoning and
tool parameters, and error parts. Match them by class::

    for part in response.content:
        match part:
            case TextPart(text=text): ...
            case ToolResultSuccess(name="GetWeather", result=weather): ...

Tool calls and results are generic in the tool's name and types, so a
toolkit's results keep their success and failure types. ``all_parts``,
``part`` and ``stream_part`` give the schemas of a toolkit's parts in their
wire form (Effect's, camelCase keys).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, ClassVar, Generic, Literal, Self, TypeVar, cast

from pyfect import schema as S
from pyfect._json_value import JsonValue
from pyfect._url import Url
from pyfect._wire_codec import Const, Key, key, wire_codec
from pyfect.ai import prompt as P
from pyfect.ai.ai_error import HTTP_RESPONSE_DETAILS, HttpResponseDetails
from pyfect.exit import Success
from pyfect.schema import ast
from pyfect.schema import getter as G
from pyfect.schema import transformation as T
from pyfect.schema._options import ParseOptions

if TYPE_CHECKING:
    from pyfect.ai.tool import AnyTool
    from pyfect.ai.toolkit import AnyToolkit

N_co = TypeVar("N_co", bound=str, covariant=True)
P_co = TypeVar("P_co", covariant=True)
S_co = TypeVar("S_co", covariant=True)
F_co = TypeVar("F_co", covariant=True)

type ProviderMetadata = dict[str, JsonValue]
"""Provider-specific details, by provider name."""

PROVIDER_METADATA = S.Record(S.String, S.NullOr(S.Json))


def _metadata() -> ProviderMetadata:
    return {}


def _metadata_key() -> Key:
    return key("metadata", "metadata", PROVIDER_METADATA, default=dict)


class _Wire:
    _wire: ClassVar[S.Bottom[Any, Mapping[str, object]]]

    @classmethod
    def __codec__(cls) -> S.Bottom[Self, Mapping[str, object]]:
        return cls.__dict__["_wire"]


def _define(cls: type[_Wire], identifier: str, *specs: Key | Const) -> None:
    type.__setattr__(cls, "_wire", wire_codec(cls, specs, identifier=identifier))


@dataclass(frozen=True)
class TextPart(_Wire):
    type: ClassVar[Literal["text"]] = "text"
    text: str
    metadata: ProviderMetadata = field(default_factory=_metadata)


@dataclass(frozen=True)
class TextStartPart(_Wire):
    type: ClassVar[Literal["text-start"]] = "text-start"
    id: str
    metadata: ProviderMetadata = field(default_factory=_metadata)


@dataclass(frozen=True)
class TextDeltaPart(_Wire):
    type: ClassVar[Literal["text-delta"]] = "text-delta"
    id: str
    delta: str
    metadata: ProviderMetadata = field(default_factory=_metadata)


@dataclass(frozen=True)
class TextEndPart(_Wire):
    type: ClassVar[Literal["text-end"]] = "text-end"
    id: str
    metadata: ProviderMetadata = field(default_factory=_metadata)


@dataclass(frozen=True)
class ReasoningPart(_Wire):
    type: ClassVar[Literal["reasoning"]] = "reasoning"
    text: str
    metadata: ProviderMetadata = field(default_factory=_metadata)


@dataclass(frozen=True)
class ReasoningStartPart(_Wire):
    type: ClassVar[Literal["reasoning-start"]] = "reasoning-start"
    id: str
    metadata: ProviderMetadata = field(default_factory=_metadata)


@dataclass(frozen=True)
class ReasoningDeltaPart(_Wire):
    type: ClassVar[Literal["reasoning-delta"]] = "reasoning-delta"
    id: str
    delta: str
    metadata: ProviderMetadata = field(default_factory=_metadata)


@dataclass(frozen=True)
class ReasoningEndPart(_Wire):
    type: ClassVar[Literal["reasoning-end"]] = "reasoning-end"
    id: str
    metadata: ProviderMetadata = field(default_factory=_metadata)


@dataclass(frozen=True)
class ToolParamsStartPart(_Wire):
    type: ClassVar[Literal["tool-params-start"]] = "tool-params-start"
    id: str
    name: str
    provider_executed: bool = False
    metadata: ProviderMetadata = field(default_factory=_metadata)


@dataclass(frozen=True)
class ToolParamsDeltaPart(_Wire):
    type: ClassVar[Literal["tool-params-delta"]] = "tool-params-delta"
    id: str
    delta: str
    metadata: ProviderMetadata = field(default_factory=_metadata)


@dataclass(frozen=True)
class ToolParamsEndPart(_Wire):
    type: ClassVar[Literal["tool-params-end"]] = "tool-params-end"
    id: str
    metadata: ProviderMetadata = field(default_factory=_metadata)


@dataclass(frozen=True)
class ToolCallPart(_Wire, Generic[N_co, P_co]):
    """The model called the tool ``name`` with ``params``."""

    type: ClassVar[Literal["tool-call"]] = "tool-call"
    id: str
    name: N_co
    params: P_co
    provider_executed: bool = False
    metadata: ProviderMetadata = field(default_factory=_metadata)


@dataclass(frozen=True)
class ToolResultSuccess(_Wire, Generic[N_co, S_co]):
    """The tool ``name`` succeeded with ``result`` (``encoded_result`` is
    what the model sees, unless the tool's ``to_model_output`` gave
    ``model_output``). ``preliminary``: a progress value streamed before the
    final one."""

    type: ClassVar[Literal["tool-result"]] = "tool-result"
    id: str
    name: N_co
    result: S_co
    encoded_result: object
    is_failure: Literal[False] = False
    provider_executed: bool = False
    preliminary: bool = False
    metadata: ProviderMetadata = field(default_factory=_metadata)
    model_output: tuple[P.ToolModelOutputPart, ...] | None = None


@dataclass(frozen=True)
class ToolResultFailure(_Wire, Generic[N_co, F_co]):
    """The tool ``name`` failed with ``result``."""

    type: ClassVar[Literal["tool-result"]] = "tool-result"
    id: str
    name: N_co
    result: F_co
    encoded_result: object
    is_failure: Literal[True] = True
    provider_executed: bool = False
    preliminary: bool = False
    metadata: ProviderMetadata = field(default_factory=_metadata)
    model_output: tuple[P.ToolModelOutputPart, ...] | None = None


type ToolResultPart[NN: str, SS, FF] = ToolResultSuccess[NN, SS] | ToolResultFailure[NN, FF]


def tool_result_part(
    *,
    id: str,
    name: str,
    is_failure: bool,
    result: object,
    encoded_result: object,
    provider_executed: bool = False,
    preliminary: bool = False,
    metadata: ProviderMetadata | None = None,
    model_output: tuple[P.ToolModelOutputPart, ...] | None = None,
) -> ToolResultSuccess[str, object] | ToolResultFailure[str, object]:
    """A tool result of either kind (Effect's ``makePart("tool-result")``)."""
    cls: Any = ToolResultFailure if is_failure else ToolResultSuccess
    return cls(
        id=id,
        name=name,
        result=result,
        encoded_result=encoded_result,
        provider_executed=provider_executed,
        preliminary=preliminary,
        metadata=metadata if metadata is not None else {},
        model_output=model_output,
    )


@dataclass(frozen=True)
class ToolApprovalRequestPart(_Wire):
    """The tool call ``tool_call_id`` waits for the user's approval."""

    type: ClassVar[Literal["tool-approval-request"]] = "tool-approval-request"
    approval_id: str
    tool_call_id: str
    metadata: ProviderMetadata = field(default_factory=_metadata)


@dataclass(frozen=True)
class FilePart(_Wire):
    type: ClassVar[Literal["file"]] = "file"
    media_type: str
    data: bytes
    metadata: ProviderMetadata = field(default_factory=_metadata)


@dataclass(frozen=True)
class DocumentSourcePart(_Wire):
    type: ClassVar[Literal["source"]] = "source"
    source_type: ClassVar[Literal["document"]] = "document"
    id: str
    media_type: str
    title: str
    file_name: str | None = None
    metadata: ProviderMetadata = field(default_factory=_metadata)


@dataclass(frozen=True)
class UrlSourcePart(_Wire):
    type: ClassVar[Literal["source"]] = "source"
    source_type: ClassVar[Literal["url"]] = "url"
    id: str
    url: Url
    title: str
    metadata: ProviderMetadata = field(default_factory=_metadata)


@dataclass(frozen=True)
class ResponseMetadataPart(_Wire):
    type: ClassVar[Literal["response-metadata"]] = "response-metadata"
    id: str | None = None
    model_id: str | None = None
    timestamp: datetime | None = None
    metadata: ProviderMetadata = field(default_factory=_metadata)


type FinishReason = Literal[
    "stop", "length", "content-filter", "tool-calls", "error", "pause", "other", "unknown"
]
FINISH_REASON = S.Literals(
    "stop", "length", "content-filter", "tool-calls", "error", "pause", "other", "unknown"
)


@dataclass(frozen=True)
class InputTokens(_Wire):
    uncached: int | None = None
    total: int | None = None
    cache_read: int | None = None
    cache_write: int | None = None


@dataclass(frozen=True)
class OutputTokens(_Wire):
    total: int | None = None
    text: int | None = None
    reasoning: int | None = None


@dataclass(frozen=True)
class Usage(_Wire):
    """Token counts of a response."""

    input_tokens: InputTokens = field(default_factory=InputTokens)
    output_tokens: OutputTokens = field(default_factory=OutputTokens)


@dataclass(frozen=True)
class FinishPart(_Wire):
    type: ClassVar[Literal["finish"]] = "finish"
    reason: FinishReason
    usage: Usage = field(default_factory=Usage)
    response: HttpResponseDetails | None = None
    metadata: ProviderMetadata = field(default_factory=_metadata)


@dataclass(frozen=True)
class ErrorPart(_Wire):
    type: ClassVar[Literal["error"]] = "error"
    error: object
    metadata: ProviderMetadata = field(default_factory=_metadata)


type AnyToolCallPart = ToolCallPart[str, object]
type AnyToolResultPart = ToolResultSuccess[str, object] | ToolResultFailure[str, object]

type AnyPart = (
    TextPart
    | TextStartPart
    | TextDeltaPart
    | TextEndPart
    | ReasoningPart
    | ReasoningStartPart
    | ReasoningDeltaPart
    | ReasoningEndPart
    | ToolParamsStartPart
    | ToolParamsDeltaPart
    | ToolParamsEndPart
    | AnyToolCallPart
    | AnyToolResultPart
    | ToolApprovalRequestPart
    | FilePart
    | DocumentSourcePart
    | UrlSourcePart
    | ResponseMetadataPart
    | FinishPart
    | ErrorPart
)

type Part[NN: str, RP_co] = (
    TextPart
    | ReasoningPart
    | ToolCallPart[NN, object]
    | RP_co
    | ToolApprovalRequestPart
    | FilePart
    | DocumentSourcePart
    | UrlSourcePart
    | ResponseMetadataPart
    | FinishPart
)
"""A part of a generated response whose tools are named ``NN`` and whose
tool results are ``RP_co``."""

type StreamPart[NN: str, RP_co] = (
    TextStartPart
    | TextDeltaPart
    | TextEndPart
    | ReasoningStartPart
    | ReasoningDeltaPart
    | ReasoningEndPart
    | ToolParamsStartPart
    | ToolParamsDeltaPart
    | ToolParamsEndPart
    | ToolCallPart[NN, object]
    | RP_co
    | ToolApprovalRequestPart
    | FilePart
    | DocumentSourcePart
    | UrlSourcePart
    | ResponseMetadataPart
    | FinishPart
    | ErrorPart
)
"""A part of a streamed response."""


def _id(cls: type[_Wire], type_: str, identifier: str, *specs: Key | Const) -> None:
    _define(cls, identifier, Const("type", type_), *specs, _metadata_key())


_id(TextPart, "text", "TextPart", key("text", "text", S.String))
_id(TextStartPart, "text-start", "TextStartPart", key("id", "id", S.String))
_id(
    TextDeltaPart,
    "text-delta",
    "TextDeltaPart",
    key("id", "id", S.String),
    key("delta", "delta", S.String),
)
_id(TextEndPart, "text-end", "TextEndPart", key("id", "id", S.String))
_id(ReasoningPart, "reasoning", "ReasoningPart", key("text", "text", S.String))
_id(ReasoningStartPart, "reasoning-start", "ReasoningStartPart", key("id", "id", S.String))
_id(
    ReasoningDeltaPart,
    "reasoning-delta",
    "ReasoningDeltaPart",
    key("id", "id", S.String),
    key("delta", "delta", S.String),
)
_id(ReasoningEndPart, "reasoning-end", "ReasoningEndPart", key("id", "id", S.String))
_id(
    ToolParamsStartPart,
    "tool-params-start",
    "ToolParamsStartPart",
    key("id", "id", S.String),
    key("name", "name", S.String),
    key("providerExecuted", "provider_executed", S.Boolean, default=lambda: False),
)
_id(
    ToolParamsDeltaPart,
    "tool-params-delta",
    "ToolParamsDeltaPart",
    key("id", "id", S.String),
    key("delta", "delta", S.String),
)
_id(ToolParamsEndPart, "tool-params-end", "ToolParamsEndPart", key("id", "id", S.String))
_id(
    ToolApprovalRequestPart,
    "tool-approval-request",
    "ToolApprovalRequestPart",
    key("approvalId", "approval_id", S.String),
    key("toolCallId", "tool_call_id", S.String),
)
_id(
    FilePart,
    "file",
    "FilePart",
    key("mediaType", "media_type", S.String),
    key("data", "data", S.BytesFromBase64),
)
_define(
    DocumentSourcePart,
    "DocumentSourcePart",
    Const("type", "source"),
    Const("sourceType", "document"),
    key("id", "id", S.String),
    key("mediaType", "media_type", S.String),
    key("title", "title", S.String),
    key("fileName", "file_name", S.String, optional=True),
    _metadata_key(),
)
_define(
    UrlSourcePart,
    "UrlSourcePart",
    Const("type", "source"),
    Const("sourceType", "url"),
    key("id", "id", S.String),
    key("url", "url", S.URLFromString),
    key("title", "title", S.String),
    _metadata_key(),
)
_id(
    ResponseMetadataPart,
    "response-metadata",
    "ResponseMetadataPart",
    key("id", "id", S.String, optional=True),
    key("modelId", "model_id", S.String, optional=True),
    key("timestamp", "timestamp", S.DateTimeUtcFromString, optional=True),
)
_define(
    InputTokens,
    "InputTokens",
    key("uncached", "uncached", S.Int, optional=True),
    key("total", "total", S.Int, optional=True),
    key("cacheRead", "cache_read", S.Int, optional=True),
    key("cacheWrite", "cache_write", S.Int, optional=True),
)
_define(
    OutputTokens,
    "OutputTokens",
    key("total", "total", S.Int, optional=True),
    key("text", "text", S.Int, optional=True),
    key("reasoning", "reasoning", S.Int, optional=True),
)
_define(
    Usage,
    "effect/ai/AiResponse/Usage",
    key("inputTokens", "input_tokens", InputTokens),
    key("outputTokens", "output_tokens", OutputTokens),
)
_id(
    FinishPart,
    "finish",
    "FinishPart",
    key("reason", "reason", FINISH_REASON),
    key("usage", "usage", Usage),
    key("response", "response", HTTP_RESPONSE_DETAILS, optional=True),
)
_id(ErrorPart, "error", "ErrorPart", key("error", "error", S.Unknown))


# Tool parts ---------------------------------------------------------------------------


def tool_call_part_schema(name: S.Top | str, params: S.Top) -> S.Bottom[Any, Mapping[str, object]]:
    """The schema of the calls of the tool ``name`` (a literal name, or a
    schema of names) with ``params`` (Effect's ``ToolCallPart``)."""
    name_schema: S.Top = S.Literal(cast("Any", name)) if isinstance(name, str) else name
    return wire_codec(
        cast("type[Any]", ToolCallPart),
        [
            Const("type", "tool-call"),
            key("id", "id", S.String),
            key("name", "name", name_schema),
            key("params", "params", params),
            key("providerExecuted", "provider_executed", S.Boolean, default=lambda: False),
            _metadata_key(),
        ],
        identifier="ToolCallPart",
    )


_MODEL_OUTPUT = S.Array(P.TOOL_MODEL_OUTPUT_PART).ast


def _model_output(
    wire: ast.Objects, value: object, flip: bool, input: object, options: ParseOptions
) -> ast.ParseResult:
    """``modelOutput`` decoded (or, ``flip``, encoded); ``None`` stays."""
    if value is None:
        return Success(None)
    schema = _MODEL_OUTPUT.flip() if flip else _MODEL_OUTPUT
    return ast.parse_at_key(wire, "modelOutput", schema, value, input=input, options=options)


def _wire_branch(name: str | None, result: ast.AST, is_failure: bool) -> ast.Objects:
    return ast.Objects(
        (
            ast.PropertySignature("type", ast.Literal("tool-result")),
            ast.PropertySignature("id", ast.string),
            ast.PropertySignature("name", ast.string if name is None else ast.Literal(name)),
            ast.PropertySignature("isFailure", ast.Literal(is_failure)),
            ast.PropertySignature("result", ast.to_encoded(result)),
            ast.PropertySignature("modelOutput", ast.to_encoded(_MODEL_OUTPUT), optional=True),
            ast.PropertySignature("providerExecuted", ast.boolean, optional=True),
            ast.PropertySignature("metadata", PROVIDER_METADATA.ast, optional=True),
            ast.PropertySignature("preliminary", ast.boolean, optional=True),
        )
    )


def tool_result_part_schema(
    name: str | None, success: S.Top, failure: S.Top
) -> S.Bottom[Any, Mapping[str, object]]:
    """The schema of the tool ``name``'s results (any tool's for ``None``)
    with ``success`` and ``failure`` (Effect's ``ToolResultPart``): the
    branch is the part's ``is_failure``."""
    results = (success.__codec__().ast, failure.__codec__().ast)
    wires = (_wire_branch(name, results[0], False), _wire_branch(name, results[1], True))

    def is_part(u: object) -> bool:
        return isinstance(u, ToolResultSuccess | ToolResultFailure) and (
            name is None or cast("Any", u).name == name
        )

    def decode(input: object, options: ParseOptions) -> Any:
        values = cast("Mapping[str, Any]", input)
        is_failure = bool(values["isFailure"])
        cls: Any = ToolResultFailure if is_failure else ToolResultSuccess
        wire = wires[is_failure]
        decoded = ast.parse_at_key(
            wire, "result", results[is_failure], values["result"], input=input, options=options
        )

        def part(value: object, model_output: object) -> object:
            return cls(
                id=values["id"],
                name=values["name"],
                result=value,
                encoded_result=values["result"],
                provider_executed=values.get("providerExecuted", False),
                preliminary=values.get("preliminary", False),
                metadata=values.get("metadata", {}),
                model_output=model_output,
            )

        return ast.to_effect(
            ast.flat_map(
                decoded,
                lambda value: ast.map_value(
                    _model_output(wire, values.get("modelOutput"), False, input, options),
                    lambda model_output: part(value, model_output),
                ),
            )
        )

    def encode(input: object, options: ParseOptions) -> Any:
        part = cast("ToolResultSuccess[str, object] | ToolResultFailure[str, object]", input)
        wire, result = wires[part.is_failure], results[part.is_failure]
        checked = ast.parse_at_key(
            wire,
            "encodedResult",
            ast.to_encoded(result),
            part.encoded_result,
            input=input,
            options=options,
        )
        return ast.to_effect(
            ast.flat_map(
                checked,
                lambda _: ast.flat_map(
                    ast.parse_at_key(
                        wire, "result", result.flip(), part.result, input=input, options=options
                    ),
                    lambda encoded: ast.map_value(
                        _model_output(wire, part.model_output, True, input, options),
                        lambda model_output: {
                            "type": "tool-result",
                            "id": part.id,
                            "name": part.name,
                            "isFailure": part.is_failure,
                            "result": encoded,
                            **({} if model_output is None else {"modelOutput": model_output}),
                            "providerExecuted": part.provider_executed,
                            "preliminary": part.preliminary,
                            "metadata": part.metadata,
                        },
                    ),
                ),
            )
        )

    target: S.Bottom[Any] = S.declare(
        cast("Any", is_part), expected="ToolResultPart", identifier=f"ToolResultPart({name})"
    )
    wire_union: S.Bottom[Any, Mapping[str, object]] = cast(
        "Any", S.Union(S.Bottom[Any, Any](wires[0]), S.Bottom[Any, Any](wires[1]))
    )
    return wire_union.pipe(
        S.decode_to(
            target, T.Transformation(G.transform_effect(decode), G.transform_effect(encode))
        )
    )


_ANY_TOOL_CALL = tool_call_part_schema(S.String, S.Unknown)
_ANY_TOOL_RESULT = tool_result_part_schema(None, S.Unknown, S.Unknown)

_tool_parts_cache: dict[int, tuple[AnyTool, S.Top, S.Top]] = {}


def _tool_parts(tool: AnyTool) -> tuple[S.Top, S.Top]:
    from pyfect.ai.tool import failure_result_schema

    cached = _tool_parts_cache.get(id(tool))
    if cached is None or cached[0] is not tool:
        cached = (
            tool,
            tool_call_part_schema(tool.name, tool.parameters_schema),
            tool_result_part_schema(tool.name, tool.success_schema, failure_result_schema(tool)),
        )
        _tool_parts_cache[id(tool)] = cached
    return cached[1], cached[2]


def _tool_schemas(toolkit: AnyToolkit | None) -> list[S.Top]:
    if toolkit is None:
        return [_ANY_TOOL_CALL, _ANY_TOOL_RESULT]
    parts = [_tool_parts(tool) for tool in toolkit.tools.values()]
    return [call for call, _ in parts] + [result for _, result in parts]


def all_parts(toolkit: AnyToolkit | None = None) -> S.Bottom[AnyPart, Mapping[str, object]]:
    """The schema of every part (Effect's ``AllParts``): of ``toolkit``'s
    tool calls and results, or of any tool's without one."""
    return cast(
        "Any",
        S.Union(
            TextPart,
            TextStartPart,
            TextDeltaPart,
            TextEndPart,
            ReasoningPart,
            ReasoningStartPart,
            ReasoningDeltaPart,
            ReasoningEndPart,
            ToolParamsStartPart,
            ToolParamsDeltaPart,
            ToolParamsEndPart,
            ToolApprovalRequestPart,
            FilePart,
            DocumentSourcePart,
            UrlSourcePart,
            ResponseMetadataPart,
            FinishPart,
            ErrorPart,
            *_tool_schemas(toolkit),
        ),
    )


def part(toolkit: AnyToolkit | None = None) -> S.Bottom[AnyPart, Mapping[str, object]]:
    """The schema of a generated response's parts (Effect's ``Part``)."""
    return cast(
        "Any",
        S.Union(
            TextPart,
            ReasoningPart,
            ToolApprovalRequestPart,
            FilePart,
            DocumentSourcePart,
            UrlSourcePart,
            ResponseMetadataPart,
            FinishPart,
            *_tool_schemas(toolkit),
        ),
    )


def stream_part(toolkit: AnyToolkit | None = None) -> S.Bottom[AnyPart, Mapping[str, object]]:
    """The schema of a streamed response's parts (Effect's ``StreamPart``)."""
    return cast(
        "Any",
        S.Union(
            TextStartPart,
            TextDeltaPart,
            TextEndPart,
            ReasoningStartPart,
            ReasoningDeltaPart,
            ReasoningEndPart,
            ToolParamsStartPart,
            ToolParamsDeltaPart,
            ToolParamsEndPart,
            ToolApprovalRequestPart,
            FilePart,
            DocumentSourcePart,
            UrlSourcePart,
            ResponseMetadataPart,
            FinishPart,
            ErrorPart,
            *_tool_schemas(toolkit),
        ),
    )


__all__ = [
    "FINISH_REASON",
    "PROVIDER_METADATA",
    "AnyPart",
    "AnyToolCallPart",
    "AnyToolResultPart",
    "DocumentSourcePart",
    "ErrorPart",
    "FilePart",
    "FinishPart",
    "FinishReason",
    "InputTokens",
    "OutputTokens",
    "Part",
    "ProviderMetadata",
    "ReasoningDeltaPart",
    "ReasoningEndPart",
    "ReasoningPart",
    "ReasoningStartPart",
    "ResponseMetadataPart",
    "StreamPart",
    "TextDeltaPart",
    "TextEndPart",
    "TextPart",
    "TextStartPart",
    "ToolApprovalRequestPart",
    "ToolCallPart",
    "ToolParamsDeltaPart",
    "ToolParamsEndPart",
    "ToolParamsStartPart",
    "ToolResultFailure",
    "ToolResultPart",
    "ToolResultSuccess",
    "UrlSourcePart",
    "Usage",
    "all_parts",
    "part",
    "stream_part",
    "tool_call_part_schema",
    "tool_result_part",
    "tool_result_part_schema",
]
