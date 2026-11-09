"""A prompt as Anthropic's ``system`` blocks and ``messages`` (Effect's
``prepareMessages``)."""

from __future__ import annotations

import base64
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

from pyfect._url import Url
from pyfect.ai import _provider as P
from pyfect.ai import prompt as Pr
from pyfect.ai._provider_tools import UnsupportedInput
from pyfect.ai.ai_error import AiError, InvalidUserInputError
from pyfect.ai.tool import NameMapper

type Block = dict[str, Any]

_DATA_URL = re.compile(r"^data:[^;]+;base64,")
_HTTP_URL = re.compile(r"^https?://", re.IGNORECASE)
_SERVER_TOOLS = frozenset(
    {"code_execution", "tool_search_tool_regex", "tool_search_tool_bm25", "web_fetch", "web_search"}
)
_CODE_EXECUTION_RESULTS = {
    "code_execution_result": "code_execution_tool_result",
    "bash_code_execution_result": "bash_code_execution_tool_result",
    "bash_code_execution_tool_result_error": "bash_code_execution_tool_result",
    "text_editor_code_execution_tool_result": "text_editor_code_execution_tool_result",
    "text_editor_code_execution_tool_result_error": "text_editor_code_execution_tool_result",
}
_SERVER_RESULTS = {
    "web_fetch": "web_fetch_tool_result",
    "web_search": "web_search_tool_result",
    "tool_search_tool_regex": "tool_search_tool_result",
    "tool_search_tool_bm25": "tool_search_tool_result",
}


def anthropic_options(options: Pr.ProviderOptions) -> dict[str, Any]:
    return P.obj(options.get("anthropic"))


def cache_control(options: Pr.ProviderOptions) -> Any:
    return anthropic_options(options).get("cacheControl")


def is_url_data(data: Pr.FileData) -> bool:
    return isinstance(data, Url) or (isinstance(data, str) and bool(_HTTP_URL.match(data)))


def url_string(data: Pr.FileData) -> str:
    return data.href if isinstance(data, Url) else str(data)


def _base64(data: Pr.FileData) -> str:
    return base64.b64encode(data).decode() if isinstance(data, bytes) else str(data)


def citations_enabled(part: Pr.FilePart) -> bool:
    return P.obj(anthropic_options(part.options).get("citations")).get("enabled") is True


def is_citation_part(part: object) -> bool:
    return (
        isinstance(part, Pr.FilePart)
        and part.media_type in ("application/pdf", "text/plain")
        and citations_enabled(part)
    )


@dataclass
class Group:
    role: Literal["system", "assistant", "user"]
    messages: list[Pr.Message] = field(default_factory=list[Pr.Message])


def group_messages(prompt: Pr.Prompt) -> list[Group]:
    """Consecutive messages of a role together; tool messages join user
    ones."""
    groups: list[Group] = []
    for message in prompt.content:
        role = "user" if message.role == "tool" else message.role
        if not groups or groups[-1].role != role:
            groups.append(Group(role))
        groups[-1].messages.append(message)
    return groups


def set_last_cache_control(content: list[Block], start: int, control: Any) -> None:
    """Put ``control`` on the last block from ``start`` that is not
    thinking, unless that block already has one."""
    if control is None:
        return
    for i in range(len(content) - 1, start - 1, -1):
        block = content[i]
        if block["type"] in ("thinking", "redacted_thinking"):
            continue
        if block.get("cache_control") is None:
            content[i] = {**block, "cache_control": control}
        return


# User content ---------------------------------------------------------------------------


def _image(part: Pr.FilePart, control: Any) -> Block:
    if is_url_data(part.data):
        source: Block = {"type": "url", "url": url_string(part.data)}
    else:
        data = part.data
        source = {
            "type": "base64",
            "media_type": "image/jpeg" if part.media_type == "image/*" else part.media_type,
            "data": _DATA_URL.sub("", data, count=1) if isinstance(data, str) else _base64(data),
        }
    return {"type": "image", "source": source, "cache_control": control}


def _document(part: Pr.FilePart, control: Any, betas: dict[str, None]) -> Block:
    betas["pdfs-2024-09-25"] = None
    data = part.data
    if is_url_data(data):
        source: Block = {"type": "url", "url": url_string(data)}
    elif part.media_type == "application/pdf":
        source = {"type": "base64", "media_type": "application/pdf", "data": _base64(data)}
    else:
        text = data.decode() if isinstance(data, bytes) else str(data)
        source = {"type": "text", "media_type": "text/plain", "data": text}
    options = anthropic_options(part.options)
    has_options = "anthropic" in part.options
    title = options.get("documentTitle") if has_options else None
    block: Block = {
        "type": "document",
        "source": source,
        "title": title if title is not None else part.file_name,
        "cache_control": control,
    }
    context = options.get("documentContext") if has_options else None
    if context:
        block["context"] = context
    if citations_enabled(part):
        block["citations"] = {"enabled": True}
    return block


def _file(part: Pr.FilePart, control: Any, betas: dict[str, None]) -> Block:
    if part.media_type.startswith("image/"):
        return _image(part, control)
    if part.media_type in ("application/pdf", "text/plain"):
        return _document(part, control, betas)
    raise UnsupportedInput(
        AiError(
            module="AnthropicLanguageModel",
            method="prepareMessages",
            reason=InvalidUserInputError(
                description=f"Detected unsupported media type for file: '{part.media_type}'"
            ),
        )
    )


def _user_content(message: Pr.Message, betas: dict[str, None]) -> list[Block]:
    content: list[Block] = []
    parts: Sequence[Any] = message.content if not isinstance(message, Pr.SystemMessage) else ()
    for j, part in enumerate(parts):
        if isinstance(part, Pr.ToolApprovalResponsePart):
            continue
        control = cache_control(part.options)
        if control is None and j == len(parts) - 1:
            control = cache_control(message.options)
        match part:
            case Pr.TextPart():
                content.append({"type": "text", "text": part.text, "cache_control": control})
            case Pr.FilePart():
                content.append(_file(part, control, betas))
            case Pr.ToolResultPart():
                result = part.result if isinstance(part.result, str) else P.dumps(part.result)
                content.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": part.id,
                        "content": result,
                        "is_error": part.is_failure,
                        "cache_control": control,
                    }
                )
            case _:
                pass
    return content


# Assistant content ----------------------------------------------------------------------


def _reasoning(part: Pr.ReasoningPart) -> Block | None:
    info = P.obj(anthropic_options(part.options).get("info"))
    if not info:
        return None
    if info.get("type") == "thinking":
        return {"type": "thinking", "thinking": part.text, "signature": info.get("signature")}
    return {"type": "redacted_thinking", "data": info.get("redactedData")}


def _server_tool_use(part: Pr.ToolCallPart, tool_name: str) -> Block | None:
    params = part.params
    kind = P.obj(params).get("type")
    if tool_name == "code_execution" and kind in (
        "bash_code_execution",
        "text_editor_code_execution",
    ):
        return {"type": "server_tool_use", "id": part.id, "name": kind, "input": params}
    if tool_name == "code_execution" and kind == "programmatic-tool-call":
        rest = {k: v for k, v in P.obj(params).items() if k != "type"}
        return {"type": "server_tool_use", "id": part.id, "name": tool_name, "input": rest}
    if tool_name in _SERVER_TOOLS:
        return {"type": "server_tool_use", "id": part.id, "name": tool_name, "input": params}
    return None


def _caller(options: dict[str, Any]) -> Block | None:
    caller = P.obj(options.get("caller"))
    if caller.get("type") == "code_execution_20250825" and caller.get("toolId") is not None:
        return {"type": "code_execution_20250825", "tool_id": caller["toolId"]}
    if caller.get("type") == "direct":
        return {"type": "direct"}
    return None


def _tool_call(part: Pr.ToolCallPart, names: NameMapper, mcp_ids: set[str]) -> Block | None:
    options = anthropic_options(part.options)
    if not part.provider_executed:
        block: Block = {"type": "tool_use", "id": part.id, "name": part.name, "input": part.params}
        caller = _caller(options)
        if caller is not None:
            block["caller"] = caller
        return block
    mcp_tool = P.obj(options.get("mcp_tool"))
    if mcp_tool:
        mcp_ids.add(part.id)
        return {
            "type": "mcp_tool_use",
            "id": part.id,
            "name": part.name,
            "input": part.params,
            "server_name": mcp_tool.get("server"),
        }
    return _server_tool_use(part, names.get_provider_name(part.name))


def _tool_result(part: Pr.ToolResultPart, names: NameMapper, mcp_ids: set[str]) -> Block | None:
    if part.id in mcp_ids:
        return {
            "type": "mcp_tool_result",
            "tool_use_id": part.id,
            "is_error": part.is_failure,
            "content": part.result,
        }
    tool_name = names.get_provider_name(part.name)
    result = part.result
    if tool_name == "code_execution":
        kind = P.obj(result).get("type")
        block_type = _CODE_EXECUTION_RESULTS.get(kind) if isinstance(kind, str) else None
        if block_type is None:
            return None
        return {"type": block_type, "tool_use_id": part.id, "content": result}
    block_type = _SERVER_RESULTS.get(tool_name)
    if block_type is None:
        return None
    return {"type": block_type, "tool_use_id": part.id, "content": result}


def _assistant_part(
    part: Pr.AssistantMessagePart,
    names: NameMapper,
    mcp_ids: set[str],
    trim: bool,
) -> Block | None:
    match part:
        case Pr.TextPart():
            return {"type": "text", "text": part.text.strip() if trim else part.text}
        case Pr.ReasoningPart():
            return _reasoning(part)
        case Pr.ToolCallPart():
            return _tool_call(part, names, mcp_ids)
        case Pr.ToolResultPart():
            return _tool_result(part, names, mcp_ids)
        case _:
            return None


def _assistant_content(group: Group, names: NameMapper, is_last_group: bool) -> list[Block]:
    content: list[Block] = []
    mcp_ids: set[str] = set()
    for j, message in enumerate(group.messages):
        assert isinstance(message, Pr.AssistantMessage)
        is_last_message = j == len(group.messages) - 1
        message_start = len(content)
        for k, part in enumerate(message.content):
            if isinstance(part, Pr.FilePart | Pr.ToolApprovalRequestPart):
                continue
            part_start = len(content)
            trim = is_last_group and is_last_message and k == len(message.content) - 1
            block = _assistant_part(part, names, mcp_ids, trim)
            if block is not None:
                content.append(block)
            set_last_cache_control(content, part_start, cache_control(part.options))
        set_last_cache_control(content, message_start, cache_control(message.options))
    return content


# Messages -------------------------------------------------------------------------------


def _inline_system(groups: list[Group], supported: bool) -> bool:
    """Whether every later system message can sit between a user turn and
    the next assistant turn (else all go in the top-level ``system``)."""
    if not supported:
        return False
    for i, group in enumerate(groups):
        if i == 0 or group.role != "system":
            continue
        follows_user = groups[i - 1].role == "user"
        precedes_user = i + 1 < len(groups) and groups[i + 1].role == "user"
        if not (follows_user or precedes_user):
            return False
    return True


@dataclass(frozen=True)
class Prepared:
    system: list[Block] | None
    messages: list[Block]


def prepare_messages(
    prompt: Pr.Prompt,
    names: NameMapper,
    betas: dict[str, None],
    mid_conversation_system_messages: bool,
) -> Prepared:
    """Raises ``UnsupportedInput`` for a file Anthropic cannot take."""
    groups = group_messages(prompt)
    inline = _inline_system(groups, mid_conversation_system_messages)
    system: list[Block] = []
    messages: list[Block] = []
    pending: list[Block] = []
    for i, group in enumerate(groups):
        match group.role:
            case "system":
                target = system if i == 0 or not inline else pending
                for message in group.messages:
                    assert isinstance(message, Pr.SystemMessage)
                    target.append(
                        {
                            "type": "text",
                            "text": message.content,
                            "cache_control": cache_control(message.options),
                        }
                    )
            case "user":
                content = [
                    block for message in group.messages for block in _user_content(message, betas)
                ]
                messages.append({"role": "user", "content": content})
            case "assistant":
                if pending:
                    messages.append({"role": "system", "content": pending})
                    pending = []
                content = _assistant_content(group, names, i == len(groups) - 1)
                messages.append({"role": "assistant", "content": content})
    if pending:
        messages.append({"role": "system", "content": pending})
    return Prepared(system or None, messages)
