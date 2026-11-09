"""A prompt as Chat Completions messages (Effect's ``prepareMessages`` and
``toChatMessageContent`` in ``@effect/ai-openai-compat``). Provider
options are read under ``"openai-compat"``: a file's ``imageDetail``, a
reasoning part's ``reasoningField`` and a tool call's ``extraContent``."""

from __future__ import annotations

import base64
import re
from collections.abc import Mapping, Sequence
from typing import Any

from pyfect._url import Url
from pyfect.ai import _provider as P
from pyfect.ai import _provider_tools as PT
from pyfect.ai import prompt as Pr
from pyfect.ai.ai_error import InvalidRequestError
from pyfect.ai.tool import NameMapper

MODULE = "OpenAiLanguageModel"
KEY = "openai-compat"
_URL_OR_DATA = re.compile(r"^(data:|https?://)", re.IGNORECASE)

type Block = dict[str, Any]


def compat_options(options: Pr.ProviderOptions) -> P.JsonObject:
    return P.obj(options.get(KEY))


def system_role(model: str) -> str:
    """``developer`` for the reasoning model families, else ``system``."""
    prefixes = ("o", "gpt-5", "codex-", "computer-use")
    return "developer" if model.startswith(prefixes) else "system"


def _is_file_id(data: Pr.FileData, prefixes: Sequence[str] | None) -> bool:
    return isinstance(data, str) and prefixes is not None and data.startswith(tuple(prefixes))


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _image(part: Pr.FilePart, prefixes: Sequence[str] | None) -> Block:
    detail = P.or_default(compat_options(part.options).get("imageDetail"), "auto")
    data = part.data
    if _is_file_id(data, prefixes):
        return {"type": "input_image", "file_id": data, "detail": detail}
    media_type = "image/jpeg" if part.media_type == "image/*" else part.media_type
    if isinstance(data, Url):
        url = data.href
    elif isinstance(data, bytes):
        url = f"data:{media_type};base64,{_b64(data)}"
    else:
        url = data if _URL_OR_DATA.match(data) else f"data:{media_type};base64,{data}"
    return {"type": "input_image", "image_url": url, "detail": detail}


def _pdf(part: Pr.FilePart, index: int, prefixes: Sequence[str] | None) -> list[Block]:
    data = part.data
    if _is_file_id(data, prefixes):
        return [{"type": "input_file", "file_id": data}]
    if isinstance(data, Url):
        return [{"type": "input_file", "file_url": data.href}]
    if isinstance(data, bytes):
        return [
            {
                "type": "input_file",
                "filename": P.or_default(part.file_name, f"part-{index}.pdf"),
                "file_data": f"data:application/pdf;base64,{_b64(data)}",
            }
        ]
    return []


def _user_content(message: Pr.UserMessage, prefixes: Sequence[str] | None) -> list[Block]:
    content: list[Block] = []
    for index, part in enumerate(message.content):
        if isinstance(part, Pr.TextPart):
            content.append({"type": "input_text", "text": part.text})
        elif part.media_type.startswith("image/"):
            content.append(_image(part, prefixes))
        elif part.media_type == "application/pdf":
            content.extend(_pdf(part, index, prefixes))
        else:
            raise PT.unsupported(
                MODULE,
                "prepareMessages",
                InvalidRequestError(
                    description=f"Detected unsupported media type for file: '{part.media_type}'"
                ),
            )
    return content


def _chat_part(part: Block) -> Block | None:
    match part["type"]:
        case "input_text":
            return {"type": "text", "text": part["text"]}
        case "input_image":
            url = part.get("image_url")
            if url is None and part.get("file_id") is not None:
                url = f"openai://file/{part['file_id']}"
            if url is None:
                return None
            image: Block = {"url": url}
            if part.get("detail") is not None:
                image["detail"] = part["detail"]
            return {"type": "image_url", "image_url": image}
        case _:
            for key in ("file_url", "file_data"):
                if key in part:
                    return {"type": "text", "text": part[key]}
            if "file_id" in part:
                return {"type": "text", "text": f"openai://file/{part['file_id']}"}
            return None


def chat_content(content: Sequence[Block]) -> str | list[Block]:
    """Responses-style input content as a chat message's content: one
    text as a string, only texts joined by newlines, else parts."""
    if len(content) == 1 and content[0]["type"] == "input_text":
        return content[0]["text"]
    parts = [part for part in map(_chat_part, content) if part is not None]
    if not parts:
        return ""
    if all(part["type"] == "text" for part in parts):
        return "\n".join(part["text"] for part in parts)
    return parts


def _assistant(message: Pr.AssistantMessage, names: NameMapper) -> Block | None:
    content: str | None = None
    reasoning = ""
    field: str | None = None
    calls: list[Block] = []
    for part in message.content:
        if isinstance(part, Pr.TextPart):
            content = (content or "") + part.text
        elif isinstance(part, Pr.ReasoningPart):
            reasoning += part.text
            field = field or compat_options(part.options).get("reasoningField")
        elif isinstance(part, Pr.ToolCallPart) and not part.provider_executed:
            call: Block = {
                "id": part.id,
                "type": "function",
                "function": {
                    "name": names.get_provider_name(part.name),
                    "arguments": P.dumps(part.params),
                },
            }
            extra = compat_options(part.options).get("extraContent")
            if extra is not None:
                call["extra_content"] = extra
            calls.append(call)
    if content is None and not calls:
        return None
    block: Block = {"role": "assistant", "content": content}
    if reasoning:
        block[field or "reasoning_content"] = reasoning
    if calls:
        block["tool_calls"] = calls
    return block


def prepare_messages(
    prompt: Pr.Prompt, config: Mapping[str, Any], names: NameMapper
) -> list[Block]:
    """Raises ``UnsupportedInput`` for a file the API cannot take."""
    prefixes = config.get("file_id_prefixes")
    messages: list[Block] = []
    for message in prompt.content:
        match message:
            case Pr.SystemMessage():
                role = system_role(P.or_default(config.get("model"), ""))
                messages.append({"role": role, "content": message.content})
            case Pr.UserMessage():
                content = chat_content(_user_content(message, prefixes))
                messages.append({"role": "user", "content": content})
            case Pr.AssistantMessage():
                block = _assistant(message, names)
                if block is not None:
                    messages.append(block)
            case Pr.ToolMessage():
                for part in message.content:
                    if isinstance(part, Pr.ToolResultPart):
                        text = P.tool_result_text(part)
                        messages.append({"role": "tool", "tool_call_id": part.id, "content": text})
    return messages
