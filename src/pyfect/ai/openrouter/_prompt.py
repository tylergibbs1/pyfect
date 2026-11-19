"""A prompt as OpenRouter chat messages (Effect's ``prepareMessages`` in
``OpenRouterLanguageModel``). Provider options are read under
``"openrouter"``: a ``cacheControl`` breakpoint on a message or part (a
message's goes on its last text, or its last tool result), a file's
``fileName`` and the ``reasoningDetails`` an assistant turn replays (the
message's, else its first tool call's or reasoning part's), each detail
sent once per request."""

from __future__ import annotations

import base64
import re
from collections.abc import Mapping, Sequence
from typing import Any

from pyfect._url import Url
from pyfect.ai import _provider as P
from pyfect.ai import _provider_tools as PT
from pyfect.ai import prompt as Pr
from pyfect.ai.ai_error import InvalidUserInputError

MODULE = "OpenRouterLanguageModel"
KEY = "openrouter"

type Block = dict[str, Any]
type ReasoningDetails = Sequence[Mapping[str, Any]]

AUDIO_FORMATS: Mapping[str, str] = {
    "audio/aac": "aac",
    "audio/aiff": "aiff",
    "audio/x-aiff": "aiff",
    "audio/flac": "flac",
    "audio/x-flac": "flac",
    "audio/l16": "pcm16",
    "audio/l24": "pcm24",
    "audio/m4a": "m4a",
    "audio/x-m4a": "m4a",
    "audio/mp4": "m4a",
    "audio/mp3": "mp3",
    "audio/mpeg": "mp3",
    "audio/ogg": "ogg",
    "audio/wav": "wav",
    "audio/wave": "wav",
    "audio/x-wav": "wav",
}
"""Audio media types and OpenRouter's formats for them."""

_SUPPORTED_AUDIO = ", ".join(dict.fromkeys(AUDIO_FORMATS.values()))
_DATA_URL = re.compile("data:[^;]*;base64,([^\\n\\r\\u2028\\u2029]+)")
_MEDIA_TYPE = re.compile(r"data:([^;]+)")


def options(part: Any) -> P.JsonObject:
    return P.obj(part.options.get(KEY))


def cache_control(part: Any) -> object:
    """A message's or part's breakpoint, ``None`` when it has none."""
    return options(part).get("cacheControl")


def base64_from_data_url(data_url: str) -> str:
    """The base64 of a ``data:`` URL, else the text itself."""
    match = _DATA_URL.fullmatch(data_url)
    return data_url if match is None else match.group(1)


def media_type_of(data_url: str, default: str) -> str:
    match = _MEDIA_TYPE.match(data_url)
    return default if match is None else match.group(1)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


_URL_DATA = re.compile(r"^(data:|https?://)", re.IGNORECASE)


def file_url(data: str | bytes | Url, media_type: str) -> str:
    """Effect's ``getFileUrl``: a URL as is, bytes or a bare base64 string
    as a ``data:`` URL."""
    if isinstance(data, Url):
        return str(data)
    if isinstance(data, bytes):
        return f"data:{media_type};base64,{_b64(data)}"
    return data if _URL_DATA.match(data) else f"data:{media_type};base64,{data}"


def _with_cache(block: Block, control: object) -> Block:
    if control is not None:
        block["cache_control"] = control
    return block


def _invalid(description: str) -> PT.UnsupportedInput:
    return PT.unsupported(MODULE, "prepareMessages", InvalidUserInputError(description=description))


def _content_item(part: Pr.TextPart | Pr.FilePart, fallback: object = None) -> Block:
    """A text or file part as a content item, cached as it asks, else as
    ``fallback`` (Effect's ``prepareContentItem``)."""
    if isinstance(part, Pr.TextPart):
        control = cache_control(part)
        block = {"type": "text", "text": part.text}
        return _with_cache(block, fallback if control is None else control)
    return _file(part, fallback)


def _file(part: Pr.FilePart, fallback: object = None) -> Block:
    control = cache_control(part)
    if control is None:
        control = fallback
    data = part.data
    media_type = part.media_type
    if media_type.startswith("image/"):
        image_type = "image/jpeg" if media_type == "image/*" else media_type
        block = {"type": "image_url", "image_url": {"url": file_url(data, image_type)}}
        return _with_cache(block, control)
    if media_type.startswith("audio/"):
        audio_format = AUDIO_FORMATS.get(media_type.lower())
        if audio_format is None:
            raise _invalid(
                f"Detected unsupported media type for audio file: '{media_type}' "
                f"- OpenRouter supports {_SUPPORTED_AUDIO} audio"
            )
        if isinstance(data, Url):
            raise _invalid(
                "Detected URL data for audio file - OpenRouter requires "
                "audio to be provided as base64-encoded data"
            )
        encoded = _b64(data) if isinstance(data, bytes) else base64_from_data_url(data)
        block = {"type": "input_audio", "input_audio": {"data": encoded, "format": audio_format}}
        return _with_cache(block, control)
    name = options(part).get("fileName")
    file_name = name if name is not None else P.or_default(part.file_name, "")
    file = {"filename": file_name, "file_data": file_url(data, media_type)}
    block = {"type": "file", "file": file}
    return _with_cache(block, control)


def _user(message: Pr.UserMessage) -> Block:
    message_control = cache_control(message)
    parts = message.content
    if len(parts) == 1 and isinstance(parts[0], Pr.TextPart):
        text = parts[0].text
        if message_control is None:
            return {"role": "user", "content": text}
        content = [{"type": "text", "text": text, "cache_control": message_control}]
        return {"role": "user", "content": content}
    last_text = max(
        (index for index, part in enumerate(parts) if isinstance(part, Pr.TextPart)), default=-1
    )
    blocks: list[Block] = []
    for index, part in enumerate(parts):
        blocks.append(_content_item(part, message_control if index == last_text else None))
    return {"role": "user", "content": blocks}


def _details(value: object) -> ReasoningDetails | None:
    return value if isinstance(value, list) and value else None  # pyright: ignore[reportUnknownVariableType]


def _first_reasoning_details(content: Sequence[Pr.AssistantMessagePart]) -> ReasoningDetails | None:
    """A tool call's details (complete), else a reasoning part's."""
    for part in content:
        if isinstance(part, (Pr.ToolCallPart, Pr.ReasoningPart)):
            details = _details(options(part).get("reasoningDetails"))
            if details is not None:
                return details
    return None


class ReasoningDetailsTracker:
    """The reasoning details already sent (Effect's
    ``ReasoningDetailsDuplicateTracker``, OpenRouter's own deduplication):
    a summary is keyed by its text, an encrypted detail by its id or data,
    a text detail by its text or signature; one without a key is
    dropped."""

    __slots__ = ("_seen",)

    def __init__(self) -> None:
        self._seen: set[str] = set()

    @staticmethod
    def _key(detail: Mapping[str, Any]) -> str | None:
        match detail.get("type"):
            case "reasoning.summary":
                return detail.get("summary")
            case "reasoning.encrypted":
                id = detail.get("id")
                return id if id is not None else detail.get("data")
            case "reasoning.text":
                text = detail.get("text")
                return text if text is not None else detail.get("signature")
            case _:
                return None

    def upsert(self, detail: Mapping[str, Any]) -> bool:
        """Whether ``detail`` is new (and now tracked)."""
        key = self._key(detail)
        if key is None or key in self._seen:
            return False
        self._seen.add(key)
        return True


def _assistant(message: Pr.AssistantMessage, tracker: ReasoningDetailsTracker) -> Block:
    reasoning = ""
    texts: list[Pr.TextPart] = []
    calls: list[Block] = []
    for part in message.content:
        if isinstance(part, Pr.TextPart):
            if part.text:
                texts.append(part)
        elif isinstance(part, Pr.ReasoningPart):
            reasoning += part.text
        elif isinstance(part, Pr.ToolCallPart):
            function = {"name": part.name, "arguments": P.dumps(part.params)}
            calls.append({"type": "function", "id": part.id, "function": function})
    candidates = _details(options(message).get("reasoningDetails"))
    if candidates is None:
        candidates = _first_reasoning_details(message.content)
    unique = [detail for detail in candidates or () if tracker.upsert(detail)]
    message_control = cache_control(message)
    content: list[Block] = []
    for index, part in enumerate(texts):
        control = cache_control(part)
        if control is None and index == len(texts) - 1:
            control = message_control
        content.append(_with_cache({"type": "text", "text": part.text}, control))
    cached = any(block.get("cache_control") is not None for block in content)
    block: Block = {
        "role": "assistant",
        "content": content if cached else "".join(block["text"] for block in content),
        "reasoning": reasoning or None,
    }
    if unique:
        block["reasoning_details"] = unique
    if calls:
        block["tool_calls"] = calls
    return block


def _tool(message: Pr.ToolMessage) -> list[Block]:
    results = [part for part in message.content if isinstance(part, Pr.ToolResultPart)]
    message_control = cache_control(message)
    messages: list[Block] = []
    for index, part in enumerate(results):
        control = cache_control(part)
        if control is None and index == len(results) - 1:
            control = message_control
        content = _tool_content(part, control)
        messages.append({"role": "tool", "tool_call_id": part.id, "content": content})
    return messages


def _tool_content(part: Pr.ToolResultPart, control: object) -> object:
    """A model output with a file as its content items in order, empty text
    dropped and the cache breakpoint on the last; otherwise text."""
    output = part.model_output
    if output is not None and any(isinstance(item, Pr.FilePart) for item in output):
        items = [item for item in output if not isinstance(item, Pr.TextPart) or item.text]
        last = len(items) - 1
        return [
            _content_item(item, control if index == last else None)
            for index, item in enumerate(items)
        ]
    text = P.tool_result_text(part)
    return (
        [{"type": "text", "text": text, "cache_control": control}]
        if control is not None and text
        else text
    )


def prepare_messages(prompt: Pr.Prompt) -> list[Block]:
    """Raises ``UnsupportedInput`` for audio OpenRouter cannot take."""
    tracker = ReasoningDetailsTracker()
    messages: list[Block] = []
    for message in prompt.content:
        match message:
            case Pr.SystemMessage():
                block = {"type": "text", "text": message.content}
                content = [_with_cache(block, cache_control(message))]
                messages.append({"role": "system", "content": content})
            case Pr.UserMessage():
                messages.append(_user(message))
            case Pr.AssistantMessage():
                messages.append(_assistant(message, tracker))
            case Pr.ToolMessage():
                messages.extend(_tool(message))
    return messages
