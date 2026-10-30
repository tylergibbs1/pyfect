"""Prompts for language models (Effect's ``Prompt``).

A ``Prompt`` is a sequence of messages: a ``SystemMessage``, ``UserMessage``
(text and files), ``AssistantMessage`` (text, files, reasoning, tool calls,
results and approval requests) and ``ToolMessage`` (tool results and
approval responses). Each part and message carries provider ``options``.

``make`` accepts a string (one user message), messages, encoded messages
(``{"role": "user", "content": "hi"}``, Effect's wire form) or a prompt::

    prompt = make([
        {"role": "system", "content": "Be brief."},
        {"role": "user", "content": "Hello"},
    ]).append_system(" Answer in French.")

Every class is a schema of its wire form (camelCase keys, as Effect's), so
``S.encode_sync(Prompt)(prompt)`` exports a conversation.
"""

from __future__ import annotations

import base64
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, ClassVar, Literal, Self, cast
from urllib.parse import SplitResult

from pyfect import schema as S
from pyfect._json_value import JsonValue
from pyfect._wire_codec import Const, Key, key, wire_codec
from pyfect.exit import Success
from pyfect.schema import getter as G
from pyfect.schema import issue as I
from pyfect.schema import transformation as T
from pyfect.schema._options import ParseOptions

if TYPE_CHECKING:
    from pyfect.ai import response as Response

type ProviderOptions = dict[str, JsonValue]
"""Options for each provider, by provider name."""

PROVIDER_OPTIONS = S.Record(S.String, S.NullOr(S.Json))


def _options() -> ProviderOptions:
    return {}


def _options_key() -> Key:
    return key("options", "options", PROVIDER_OPTIONS, default=dict)


class _Wire:
    """A part or message: a schema of its wire form."""

    _wire: ClassVar[S.Bottom[Any, Mapping[str, object]]]

    @classmethod
    def __codec__(cls) -> S.Bottom[Self, Mapping[str, object]]:
        return cls.__dict__["_wire"]

    def pipe[B](self, f: Callable[[Self], B], /) -> B:
        return f(self)


def _define(cls: type[_Wire], identifier: str, *specs: Key | Const) -> None:
    type.__setattr__(cls, "_wire", wire_codec(cls, specs, identifier=identifier))


# Parts --------------------------------------------------------------------------------


@dataclass(frozen=True, eq=True)
class TextPart(_Wire):
    """Text."""

    type: ClassVar[Literal["text"]] = "text"
    text: str
    options: ProviderOptions = field(default_factory=_options)


@dataclass(frozen=True, eq=True)
class ReasoningPart(_Wire):
    """A model's reasoning."""

    type: ClassVar[Literal["reasoning"]] = "reasoning"
    text: str
    options: ProviderOptions = field(default_factory=_options)


type FileData = str | bytes | SplitResult
"""A file's data: base64 text, bytes or a URL (``urllib.parse.urlsplit``)."""


@dataclass(frozen=True, eq=True)
class FilePart(_Wire):
    """A file (an image, a document, ...)."""

    type: ClassVar[Literal["file"]] = "file"
    media_type: str
    data: FileData
    file_name: str | None = None
    options: ProviderOptions = field(default_factory=_options)


@dataclass(frozen=True, eq=True)
class ToolCallPart(_Wire):
    """A tool call the model made (its ``params`` as the model sent them)."""

    type: ClassVar[Literal["tool-call"]] = "tool-call"
    id: str
    name: str
    params: object
    provider_executed: bool = False
    options: ProviderOptions = field(default_factory=_options)


@dataclass(frozen=True, eq=True)
class ToolResultPart(_Wire):
    """A tool's result (encoded) for the call ``id``."""

    type: ClassVar[Literal["tool-result"]] = "tool-result"
    id: str
    name: str
    is_failure: bool
    result: object
    provider_executed: bool = False
    options: ProviderOptions = field(default_factory=_options)


@dataclass(frozen=True, eq=True)
class ToolApprovalResponsePart(_Wire):
    """The user's answer to an approval request."""

    type: ClassVar[Literal["tool-approval-response"]] = "tool-approval-response"
    approval_id: str
    approved: bool
    reason: str | None = None
    options: ProviderOptions = field(default_factory=_options)


@dataclass(frozen=True, eq=True)
class ToolApprovalRequestPart(_Wire):
    """The model asked to run the tool call ``tool_call_id``, which needs
    approval."""

    type: ClassVar[Literal["tool-approval-request"]] = "tool-approval-request"
    approval_id: str
    tool_call_id: str
    options: ProviderOptions = field(default_factory=_options)


type Part = (
    TextPart
    | ReasoningPart
    | FilePart
    | ToolCallPart
    | ToolResultPart
    | ToolApprovalResponsePart
    | ToolApprovalRequestPart
)
type UserMessagePart = TextPart | FilePart
type AssistantMessagePart = (
    TextPart | FilePart | ReasoningPart | ToolCallPart | ToolResultPart | ToolApprovalRequestPart
)
type ToolMessagePart = ToolResultPart | ToolApprovalResponsePart


def _tagged_object(tag: str, field_name: str, schema: S.Top) -> S.Bottom[Any, Mapping[str, object]]:
    node = S.ast.Objects(
        (
            S.ast.PropertySignature("_tag", S.ast.Literal(tag)),
            S.ast.PropertySignature(field_name, schema.__codec__().ast),
        )
    )
    return S.Bottom(node)


def _unwrap(field_name: str, tag: str, to: S.Top) -> S.Bottom[Any, Any]:
    return _tagged_object(tag, field_name, to).pipe(
        S.decode_to(
            S.to_type(cast("Any", to)),
            T.transform(
                decode=lambda wrapped: wrapped[field_name],
                encode=lambda value: {"_tag": tag, field_name: value},
            ),
        )
    )


_FILE_DATA: S.Bottom[FileData, object] = cast(
    "Any",
    S.Union(
        S.String,
        _unwrap("base64", "Uint8Array", S.BytesFromBase64),
        _unwrap("href", "URL", S.URLFromString),
        S.Bytes,
        S.URL,
    ),
)

_define(TextPart, "TextPart", Const("type", "text"), key("text", "text", S.String), _options_key())
_define(
    ReasoningPart,
    "ReasoningPart",
    Const("type", "reasoning"),
    key("text", "text", S.String),
    _options_key(),
)
_define(
    FilePart,
    "FilePart",
    Const("type", "file"),
    key("mediaType", "media_type", S.String),
    key("fileName", "file_name", S.String, optional=True),
    key("data", "data", _FILE_DATA),
    _options_key(),
)
_define(
    ToolCallPart,
    "ToolCallPart",
    Const("type", "tool-call"),
    key("id", "id", S.String),
    key("name", "name", S.String),
    key("params", "params", S.Unknown),
    key("providerExecuted", "provider_executed", S.Boolean, default=lambda: False),
    _options_key(),
)
_define(
    ToolResultPart,
    "ToolResultPart",
    Const("type", "tool-result"),
    key("id", "id", S.String),
    key("name", "name", S.String),
    key("isFailure", "is_failure", S.Boolean),
    key("result", "result", S.Unknown),
    key("providerExecuted", "provider_executed", S.Boolean, default=lambda: False),
    _options_key(),
)
_define(
    ToolApprovalResponsePart,
    "ToolApprovalResponsePart",
    Const("type", "tool-approval-response"),
    key("approvalId", "approval_id", S.String),
    key("approved", "approved", S.Boolean),
    key("reason", "reason", S.String, optional=True),
    _options_key(),
)
_define(
    ToolApprovalRequestPart,
    "ToolApprovalRequestPart",
    Const("type", "tool-approval-request"),
    key("approvalId", "approval_id", S.String),
    key("toolCallId", "tool_call_id", S.String),
    _options_key(),
)

PART: S.Bottom[Part, Mapping[str, object]] = cast(
    "Any",
    S.Union(
        TextPart,
        ReasoningPart,
        FilePart,
        ToolCallPart,
        ToolResultPart,
        ToolApprovalResponsePart,
        ToolApprovalRequestPart,
    ),
)
USER_MESSAGE_PART: S.Bottom[UserMessagePart, Mapping[str, object]] = cast(
    "Any", S.Union(TextPart, FilePart)
)
ASSISTANT_MESSAGE_PART: S.Bottom[AssistantMessagePart, Mapping[str, object]] = cast(
    "Any",
    S.Union(
        TextPart, FilePart, ReasoningPart, ToolCallPart, ToolResultPart, ToolApprovalRequestPart
    ),
)
TOOL_MESSAGE_PART: S.Bottom[ToolMessagePart, Mapping[str, object]] = cast(
    "Any", S.Union(ToolResultPart, ToolApprovalResponsePart)
)


# Messages -----------------------------------------------------------------------------


@dataclass(frozen=True, eq=True)
class SystemMessage(_Wire):
    """Instructions for the model."""

    role: ClassVar[Literal["system"]] = "system"
    content: str
    options: ProviderOptions = field(default_factory=_options)


@dataclass(frozen=True, eq=True)
class UserMessage(_Wire):
    """What the user said: text and files."""

    role: ClassVar[Literal["user"]] = "user"
    content: Sequence[UserMessagePart]
    options: ProviderOptions = field(default_factory=_options)

    def __post_init__(self) -> None:
        object.__setattr__(self, "content", tuple(self.content))


@dataclass(frozen=True, eq=True)
class AssistantMessage(_Wire):
    """What the model said."""

    role: ClassVar[Literal["assistant"]] = "assistant"
    content: Sequence[AssistantMessagePart]
    options: ProviderOptions = field(default_factory=_options)

    def __post_init__(self) -> None:
        object.__setattr__(self, "content", tuple(self.content))


@dataclass(frozen=True, eq=True)
class ToolMessage(_Wire):
    """Tool results and approval responses."""

    role: ClassVar[Literal["tool"]] = "tool"
    content: Sequence[ToolMessagePart]
    options: ProviderOptions = field(default_factory=_options)

    def __post_init__(self) -> None:
        object.__setattr__(self, "content", tuple(self.content))


type Message = SystemMessage | UserMessage | AssistantMessage | ToolMessage


def _single_text(content: object) -> bool:
    parts = cast("tuple[TextPart, ...]", content)
    return len(parts) == 1 and not parts[0].options


_CONTENT_FROM_STRING: S.Bottom[Any, Any] = S.String.pipe(
    S.decode_to(
        S.NonEmptyArray(S.to_type(TextPart)).check(S.make_filter(_single_text)),
        T.transform(
            decode=lambda text: (TextPart(text=text),),
            encode=lambda content: cast("tuple[TextPart, ...]", content)[0].text,
        ),
    )
)


def _content(part: S.Top) -> S.Bottom[Any, Any]:
    return cast("Any", S.Union(_CONTENT_FROM_STRING, S.Array(part)))


_define(
    SystemMessage,
    "SystemMessage",
    Const("role", "system"),
    key("content", "content", S.String),
    _options_key(),
)
_define(
    UserMessage,
    "UserMessage",
    Const("role", "user"),
    key("content", "content", _content(USER_MESSAGE_PART)),
    _options_key(),
)
_define(
    AssistantMessage,
    "AssistantMessage",
    Const("role", "assistant"),
    key("content", "content", _content(ASSISTANT_MESSAGE_PART)),
    _options_key(),
)
_define(
    ToolMessage,
    "ToolMessage",
    Const("role", "tool"),
    key("content", "content", S.Array(TOOL_MESSAGE_PART)),
    _options_key(),
)

MESSAGE: S.Bottom[Message, Mapping[str, object]] = cast(
    "Any", S.Union(SystemMessage, UserMessage, AssistantMessage, ToolMessage)
)
_MESSAGES = S.Array(MESSAGE)


# Prompt -------------------------------------------------------------------------------

type RawInput = str | Iterable[Message | Mapping[str, object]] | Prompt
"""What ``make`` accepts: a user's text, messages (or their wire form), or
a prompt."""


@dataclass(frozen=True, eq=True)
class Prompt:
    """A conversation: its messages, in order."""

    content: tuple[Message, ...]

    @classmethod
    def __codec__(cls) -> S.Bottom[Prompt, Mapping[str, object]]:
        return _PROMPT

    def pipe[B](self, f: Callable[[Self], B], /) -> B:
        return f(self)

    def concat(self, input: RawInput) -> Prompt:
        """This prompt's messages, then ``input``'s."""
        other = make(input)
        if not self.content:
            return other
        if not other.content:
            return self
        return Prompt((*self.content, *other.content))

    def set_system(self, content: str) -> Prompt:
        """A system message ``content`` first, replacing every other one."""
        return Prompt(
            (
                SystemMessage(content=content),
                *(m for m in self.content if not isinstance(m, SystemMessage)),
            )
        )

    def prepend_system(self, content: str) -> Prompt:
        """A leading system message: ``content`` before the first system
        message's text (Effect keeps that message too)."""
        first = next((m for m in self.content if isinstance(m, SystemMessage)), None)
        system = SystemMessage(content=content if first is None else content + first.content)
        return Prompt((system, *self.content))

    def append_system(self, content: str) -> Prompt:
        """A leading system message: the first system message's text, then
        ``content`` (Effect keeps that message too)."""
        first = next((m for m in self.content if isinstance(m, SystemMessage)), None)
        system = SystemMessage(content=content if first is None else first.content + content)
        return Prompt((system, *self.content))


def _decode_prompt(input: object, options: ParseOptions) -> Any:
    content = cast("Mapping[str, object]", input)["content"]
    match S.ast.run_now(_MESSAGES.ast.parse(content, options)):
        case Success(value):
            return Success(Prompt(cast("tuple[Message, ...]", value)))
        case _:
            return _invalid_messages(content, options)


def _encode_prompt(prompt: object, options: ParseOptions) -> Any:
    content = cast("Prompt", prompt).content
    match S.ast.run_now(_MESSAGES.ast.flip().parse(content, options)):
        case Success(value):
            return Success({"content": value})
        case _:
            return _invalid_messages(content, options)


def _invalid_messages(content: object, options: ParseOptions) -> Any:
    from pyfect.exit import fail

    return fail(
        I.InvalidValue(
            annotations={"message": "Invalid Prompt messages"}, input=I.reported(content, options)
        )
    )


_PROMPT_STRUCT: S.Bottom[Any, Mapping[str, object]] = S.Bottom(
    S.ast.Objects((S.ast.PropertySignature("content", S.Array(S.to_encoded(MESSAGE)).ast),))
)
_PROMPT: S.Bottom[Prompt, Mapping[str, object]] = _PROMPT_STRUCT.pipe(
    S.decode_to(
        S.instance_of(Prompt, identifier="Prompt"),
        T.Transformation(G.transform_effect(_decode_prompt), G.transform_effect(_encode_prompt)),
    )
)

empty: Prompt = Prompt(())
"""The prompt with no messages."""

_decode_messages = S.decode_unknown_sync(_MESSAGES)


def make(input: RawInput) -> Prompt:
    """A prompt from text (one user message), messages or their wire form
    (decoded; a bad one raises ``SchemaError``), or a prompt itself."""
    if isinstance(input, str):
        return Prompt((UserMessage(content=(TextPart(text=input),)),))
    if isinstance(input, Prompt):
        return input
    items = list(input)
    if all(
        isinstance(m, SystemMessage | UserMessage | AssistantMessage | ToolMessage) for m in items
    ):
        return Prompt(tuple(cast("list[Message]", items)))
    encoded = [
        S.encode_sync(MESSAGE)(m)
        if isinstance(m, SystemMessage | UserMessage | AssistantMessage | ToolMessage)
        else m
        for m in items
    ]
    return Prompt(_decode_messages(encoded, errors="all"))


def from_messages(messages: Iterable[Message]) -> Prompt:
    return Prompt(tuple(messages))


def _merge_options(left: ProviderOptions, right: Mapping[str, JsonValue]) -> ProviderOptions:
    result = dict(left)
    for provider, metadata in right.items():
        previous = result.get(provider)
        result[provider] = (
            {**previous, **metadata}
            if isinstance(previous, Mapping) and isinstance(metadata, Mapping)
            else metadata
        )
    return result


@dataclass
class _Active:
    index: int
    text: str
    options: ProviderOptions


class _Builder:
    """Folds response parts into an assistant and a tool message."""

    def __init__(self) -> None:
        self.assistant: list[AssistantMessagePart | None] = []
        self.tool: list[ToolMessagePart] = []
        self.active: dict[tuple[str, str], _Active] = {}

    def add(self, part: AssistantMessagePart) -> None:
        self.assistant.append(part)

    def start(self, kind: str, id: str, metadata: Mapping[str, JsonValue]) -> None:
        self.active[kind, id] = _Active(len(self.assistant), "", dict(metadata))
        self.assistant.append(None)

    def delta(self, kind: str, id: str, delta: str, metadata: Mapping[str, JsonValue]) -> None:
        if (active := self.active.get((kind, id))) is not None:
            active.text += delta
            active.options = _merge_options(active.options, metadata)

    def end(self, kind: str, id: str, metadata: Mapping[str, JsonValue]) -> None:
        if (active := self.active.pop((kind, id), None)) is not None:
            active.options = _merge_options(active.options, metadata)
            self.close(kind, active)

    def close(self, kind: str, active: _Active) -> None:
        cls = TextPart if kind == "text" else ReasoningPart
        self.assistant[active.index] = cls(text=active.text, options=active.options)

    def finish(self) -> Prompt:
        for (kind, _), active in self.active.items():
            if kind == "text" and active.text:
                self.close(kind, active)
        content = [p for p in self.assistant if p is not None]
        messages: list[Message] = []
        if content:
            messages.append(AssistantMessage(content=content))
        if self.tool:
            messages.append(ToolMessage(content=self.tool))
        return Prompt(tuple(messages))


def _fold(builder: _Builder, part: Response.AnyPart) -> None:
    from pyfect.ai import response as R

    match part:
        case R.TextPart() | R.ReasoningPart():
            cls = TextPart if isinstance(part, R.TextPart) else ReasoningPart
            builder.add(cls(text=part.text, options=dict(part.metadata)))
        case R.TextStartPart() | R.ReasoningStartPart():
            builder.start(part.type.split("-")[0], part.id, part.metadata)
        case R.TextDeltaPart() | R.ReasoningDeltaPart():
            builder.delta(part.type.split("-")[0], part.id, part.delta, part.metadata)
        case R.TextEndPart() | R.ReasoningEndPart():
            builder.end(part.type.split("-")[0], part.id, part.metadata)
        case R.FilePart():
            data = base64.b64encode(part.data).decode("ascii")
            builder.add(
                FilePart(data=data, media_type=part.media_type, options=dict(part.metadata))
            )
        case R.ToolCallPart():
            builder.add(
                ToolCallPart(
                    id=part.id,
                    name=part.name,
                    params=part.params,
                    provider_executed=part.provider_executed,
                    options=dict(part.metadata),
                )
            )
        case R.ToolResultSuccess() | R.ToolResultFailure() if not part.preliminary:
            result = ToolResultPart(
                id=part.id,
                name=part.name,
                is_failure=part.is_failure,
                result=part.encoded_result,
                provider_executed=part.provider_executed,
                options=dict(part.metadata),
            )
            (builder.add if part.provider_executed else builder.tool.append)(result)
        case R.ToolApprovalRequestPart():
            builder.add(
                ToolApprovalRequestPart(
                    approval_id=part.approval_id, tool_call_id=part.tool_call_id
                )
            )
        case _:
            pass


def from_response_parts(parts: Sequence[Response.AnyPart]) -> Prompt:
    """The prompt continuing a conversation with a response: an assistant
    message of its text, reasoning (streamed deltas folded), files, tool
    calls and provider-executed results, then a tool message of the other
    final tool results."""
    builder = _Builder()
    for part in parts:
        _fold(builder, part)
    return builder.finish()


__all__ = [
    "ASSISTANT_MESSAGE_PART",
    "MESSAGE",
    "PART",
    "PROVIDER_OPTIONS",
    "TOOL_MESSAGE_PART",
    "USER_MESSAGE_PART",
    "AssistantMessage",
    "AssistantMessagePart",
    "FileData",
    "FilePart",
    "Message",
    "Part",
    "Prompt",
    "ProviderOptions",
    "RawInput",
    "ReasoningPart",
    "SystemMessage",
    "TextPart",
    "ToolApprovalRequestPart",
    "ToolApprovalResponsePart",
    "ToolCallPart",
    "ToolMessage",
    "ToolMessagePart",
    "ToolResultPart",
    "UserMessage",
    "UserMessagePart",
    "empty",
    "from_messages",
    "from_response_parts",
    "make",
]
