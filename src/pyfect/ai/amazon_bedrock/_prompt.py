"""A prompt as Converse ``system`` blocks and ``messages`` (Effect's
``prepareMessages``)."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, cast

from pyfect._js import trim
from pyfect._url import Url
from pyfect.ai import _provider as P
from pyfect.ai import prompt as Pr
from pyfect.ai._provider_tools import UnsupportedInput
from pyfect.ai.ai_error import AiError, InvalidUserInputError
from pyfect.ai.amazon_bedrock import schema as W
from pyfect.encoding import base64

MODULE = "AmazonBedrockLanguageModel"
PROVIDER = "amazon-bedrock"

_IMAGE_FORMATS: dict[str, W.ImageFormat] = {
    "image/*": "jpeg",
    "image/jpeg": "jpeg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
}
"""Converse takes a format, not a media type; ``image/*`` is sent as jpeg,
as the other providers do."""

_DOCUMENT_FORMATS: dict[str, W.DocumentFormat] = {
    "application/pdf": "pdf",
    "text/csv": "csv",
    "application/msword": "doc",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.ms-excel": "xls",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "text/html": "html",
    "text/plain": "txt",
    "text/markdown": "md",
}

_URL = re.compile(r"^[a-z][a-z0-9+.-]*://", re.IGNORECASE)
"""Any absolute URL, so one is rejected instead of sent as base64."""
_DATA_URL = re.compile(r"^data:[^,]*?(;base64)?,", re.IGNORECASE)
"""The header of a ``data:`` URL, up to the comma before its payload."""
_EXTENSION = re.compile(r"\.[^.]*$")
_NAME_UNSAFE = re.compile(r"[^a-zA-Z0-9\s\-()[\]]")
_WHITESPACE = re.compile(r"\s+")


def error(method: str, reason: Any) -> AiError:
    return AiError(module=MODULE, method=method, reason=reason)


def invalid_user_input(method: str, description: str) -> UnsupportedInput:
    return UnsupportedInput(error(method, InvalidUserInputError(description=description)))


def _file_bytes(data: Pr.FileData) -> str:
    """A file's data as base64. Text is base64 already, so it is sent as it
    is, and only a base64 ``data:`` URL's payload is sent; Converse fetches
    no remote file, so any other URL fails."""
    if isinstance(data, bytes):
        return base64.encode(data)
    text = data.href if isinstance(data, Url) else data
    data_url = _DATA_URL.match(text)
    if data_url is not None:
        if data_url.group(1) is None:
            raise invalid_user_input(
                "prepareMessages",
                f"Unsupported file url '{data_url.group(0)}...' - "
                "a data url must have a base64 payload",
            )
        return text[data_url.end() :]
    if isinstance(data, Url) or _URL.match(text):
        raise invalid_user_input(
            "prepareMessages",
            f"Unsupported file url '{text}' - Converse does not fetch remote files, "
            "so pass the file bytes instead",
        )
    return text


def _document_name(file_name: str | None, position: int) -> str:
    """Bedrock takes alphanumerics, single runs of whitespace, hyphens,
    parentheses and square brackets in a document name; anything else
    becomes a space. The extension goes, the format is sent apart."""
    if file_name is not None:
        name = trim(
            _WHITESPACE.sub(" ", _NAME_UNSAFE.sub(" ", _EXTENSION.sub("", file_name, count=1)))
        )
        if name:
            return name
    return f"document {position}"


def _tool_result_content(result: object) -> list[W.ToolResultContentBlock]:
    if isinstance(result, str):
        return [{"text": result}]
    if result is None:
        return [{"text": ""}]
    return [{"json": result}]


def _cache_point(options: Pr.ProviderOptions) -> W.CachePointBlock | None:
    found = P.obj(options.get(PROVIDER)).get("cachePoint")
    return cast("W.CachePointBlock", found) if isinstance(found, dict) else None


def _push_cache_point(content: list[Any], options: Pr.ProviderOptions) -> None:
    """The cache point a message or part asks for, after its blocks."""
    cache_point = _cache_point(options)
    if cache_point is not None:
        content.append({"cachePoint": cache_point})


@dataclass
class _SystemGroup:
    messages: list[Pr.SystemMessage] = field(default_factory=list[Pr.SystemMessage])


@dataclass
class _AssistantGroup:
    messages: list[Pr.AssistantMessage] = field(default_factory=list[Pr.AssistantMessage])


@dataclass
class _UserGroup:
    messages: list[Pr.UserMessage | Pr.ToolMessage] = field(
        default_factory=list[Pr.UserMessage | Pr.ToolMessage]
    )


type _Group = _SystemGroup | _AssistantGroup | _UserGroup


def _group_messages(prompt: Pr.Prompt) -> list[_Group]:
    """Converse alternates user and assistant turns and tool results travel
    in a user turn, so consecutive messages of a side are merged."""
    groups: list[_Group] = []
    for message in prompt.content:
        last = groups[-1] if groups else None
        match message:
            case Pr.SystemMessage():
                if not isinstance(last, _SystemGroup):
                    last = _SystemGroup()
                    groups.append(last)
                last.messages.append(message)
            case Pr.AssistantMessage():
                if not isinstance(last, _AssistantGroup):
                    last = _AssistantGroup()
                    groups.append(last)
                last.messages.append(message)
            case Pr.UserMessage() | Pr.ToolMessage():
                if not isinstance(last, _UserGroup):
                    last = _UserGroup()
                    groups.append(last)
                last.messages.append(message)
    return groups


@dataclass
class Prepared:
    system: list[W.SystemContentBlock]
    messages: list[W.Message]


class _Documents:
    """Document names must be present and distinct within a request, so
    unnamed documents are numbered across the conversation."""

    def __init__(self) -> None:
        self.count = 0

    def next(self) -> int:
        self.count += 1
        return self.count


def _user_part(
    part: Pr.UserMessagePart, content: list[W.ContentBlock], documents: _Documents
) -> None:
    if isinstance(part, Pr.TextPart):
        content.append({"text": part.text})
    else:
        image_format = _IMAGE_FORMATS.get(part.media_type)
        document_format = _DOCUMENT_FORMATS.get(part.media_type)
        if image_format is not None:
            content.append(
                {"image": {"format": image_format, "source": {"bytes": _file_bytes(part.data)}}}
            )
        elif document_format is not None:
            name = _document_name(part.file_name, documents.next())
            content.append(
                {
                    "document": {
                        "format": document_format,
                        "name": name,
                        "source": {"bytes": _file_bytes(part.data)},
                    }
                }
            )
        else:
            raise invalid_user_input(
                "prepareMessages",
                f"Unsupported media type '{part.media_type}' for file part - this provider "
                "supports the images and documents Converse has a format for",
            )
    _push_cache_point(content, part.options)


def _user_group(
    messages: Sequence[Pr.UserMessage | Pr.ToolMessage], documents: _Documents
) -> W.Message:
    content: list[W.ContentBlock] = []
    for message in messages:
        if isinstance(message, Pr.UserMessage):
            for part in message.content:
                _user_part(part, content, documents)
        else:
            for part in message.content:
                # Only tool results are Converse blocks; approval responses are skipped.
                if not isinstance(part, Pr.ToolResultPart):
                    continue
                result: W.ToolResultBlock = {
                    "toolUseId": part.id,
                    "content": _tool_result_content(
                        part.result
                        if part.model_output is None
                        else Pr.tool_model_output_to_text(part.model_output)
                    ),
                }
                if part.is_failure:
                    result["status"] = "error"
                content.append({"toolResult": result})
                _push_cache_point(content, part.options)
        _push_cache_point(content, message.options)
    return {"role": "user", "content": content}


def _reasoning(part: Pr.ReasoningPart) -> W.ContentBlock | None:
    """Bedrock verifies a reasoning block's payload, so a reasoning part not
    from this provider carries nothing it would accept and is dropped."""
    info = part.options.get(PROVIDER)
    if not isinstance(info, dict):
        return None
    redacted = info.get("redactedContent")
    if isinstance(redacted, str):
        return {"reasoningContent": {"redactedContent": redacted}}
    text: W.ReasoningTextBlock = {"text": part.text}
    signature = info.get("signature")
    if isinstance(signature, str):
        text["signature"] = signature
    return {"reasoningContent": {"reasoningText": text}}


def _assistant_group(messages: Sequence[Pr.AssistantMessage], is_last_group: bool) -> W.Message:
    content: list[W.ContentBlock] = []
    for j, message in enumerate(messages):
        is_last_message = j == len(messages) - 1
        for k, part in enumerate(message.content):
            is_last_part = k == len(message.content) - 1
            if isinstance(part, Pr.TextPart):
                if not trim(part.text):
                    continue
                # Bedrock refuses trailing whitespace in a pre-filled answer.
                last = is_last_group and is_last_message and is_last_part
                content.append({"text": trim(part.text) if last else part.text})
                _push_cache_point(content, part.options)
            elif isinstance(part, Pr.ReasoningPart):
                block = _reasoning(part)
                if block is not None:
                    content.append(block)
            elif isinstance(part, Pr.ToolCallPart):
                if part.provider_executed:
                    continue
                content.append(
                    {"toolUse": {"toolUseId": part.id, "name": part.name, "input": part.params}}
                )
                _push_cache_point(content, part.options)
            else:
                raise invalid_user_input(
                    "prepareMessages",
                    f"Unsupported assistant content part of type '{part.type}' - this provider "
                    "supports text, reasoning, and tool calls",
                )
        _push_cache_point(content, message.options)
    return {"role": "assistant", "content": content}


def prepare_messages(prompt: Pr.Prompt) -> Prepared:
    """Raises ``UnsupportedInput`` for a prompt Converse cannot take."""
    groups = _group_messages(prompt)
    system: list[W.SystemContentBlock] = []
    messages: list[W.Message] = []
    documents = _Documents()
    for i, group in enumerate(groups):
        if isinstance(group, _SystemGroup):
            if messages:
                raise invalid_user_input(
                    "prepareMessages",
                    "Multiple system messages separated by user / assistant messages",
                )
            for message in group.messages:
                system.append({"text": message.content})
                _push_cache_point(system, message.options)
        elif isinstance(group, _UserGroup):
            messages.append(_user_group(group.messages, documents))
        else:
            messages.append(_assistant_group(group.messages, i == len(groups) - 1))
    return Prepared(system, messages)
