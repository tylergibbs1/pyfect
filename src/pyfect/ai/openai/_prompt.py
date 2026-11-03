"""A prompt as Responses API input items (Effect's ``prepareMessages`` in
``OpenAiLanguageModel``). Prompt parts read OpenAI options under
``options["openai"]`` in Effect's spelling: ``itemId``, ``status``,
``encryptedContent``, ``imageDetail``, ``promptCacheBreakpoint``,
``annotations``, ``approvalRequestId`` and ``approvalId``.

With ``store`` (and neither ``use_item_references=False`` nor the
incremental fallback) assistant items the API stored are sent as item
references; a ``conversation`` already holds them, so they are left out.
"""

from __future__ import annotations

import base64
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import SplitResult, urlunsplit

from pyfect import schema as S
from pyfect.ai import _provider as P
from pyfect.ai import _provider_tools as PT
from pyfect.ai import language_model as lm
from pyfect.ai import prompt as Pr
from pyfect.ai import tool as T
from pyfect.ai.ai_error import (
    InvalidRequestError,
    ToolParameterValidationError,
    describe_schema_error,
)
from pyfect.ai.tool import NameMapper

MODULE = "OpenAiLanguageModel"
KEY = "openai"
_URL_OR_DATA = re.compile(r"^(data:|https?://)", re.IGNORECASE)
_NON_REASONING = re.compile(r"^(?:gpt-[34]|chatgpt-|chat-latest|gpt-[0-9]+(?:\.[0-9]+)?-chat)")

type Item = dict[str, Any]
type AnyProviderDefined = T.ProviderDefined[Any, Any, Any, Any, Any, Any]


def openai_options(options: Pr.ProviderOptions) -> P.JsonObject:
    return P.obj(options.get(KEY))


def is_reasoning_model(config: Mapping[str, Any]) -> bool:
    """``reasoning_model`` when set; else every model but the GPT-3/4 and
    chat families (new names default to reasoning)."""
    explicit = config.get("reasoning_model")
    if explicit is not None:
        return bool(explicit)
    model = str(P.or_default(config.get("model"), ""))
    return not _NON_REASONING.match(model.removeprefix("ft:"))


def provider_tool(options: lm.ProviderOptions, *names: str) -> AnyProviderDefined | None:
    return next(
        (t for t in options.tools if isinstance(t, T.ProviderDefined) and t.name in names), None
    )


def _item_id(part: Pr.TextPart | Pr.ReasoningPart | Pr.ToolCallPart | Pr.ToolResultPart) -> Any:
    return openai_options(part.options).get("itemId")


def _status(part: Pr.TextPart | Pr.ToolCallPart | Pr.ToolResultPart) -> Any:
    return openai_options(part.options).get("status")


def _breakpoint(options: Pr.ProviderOptions) -> Item:
    found = openai_options(options).get("promptCacheBreakpoint")
    return {} if found is None else {"prompt_cache_breakpoint": found}


def _with_status(item: Item, status: object) -> Item:
    return item if status is None else {**item, "status": status}


def _is_file_id(data: Pr.FileData, prefixes: Sequence[str] | None) -> bool:
    return isinstance(data, str) and prefixes is not None and data.startswith(tuple(prefixes))


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


def _invalid(description: str) -> PT.UnsupportedInput:
    return PT.unsupported(MODULE, "prepareMessages", InvalidRequestError(description=description))


def _unreplayable(name: str, id: str) -> PT.UnsupportedInput:
    return _invalid(f"Cannot replay provider-executed tool item '{name}' ('{id}') losslessly")


def _file(part: Pr.FilePart, index: int, prefixes: Sequence[str] | None) -> list[Item]:
    extra = _breakpoint(part.options)
    data = part.data
    if part.media_type.startswith("image/"):
        detail = P.or_default(openai_options(part.options).get("imageDetail"), "auto")
        if _is_file_id(data, prefixes):
            return [{"type": "input_image", "file_id": data, "detail": detail, **extra}]
        media_type = "image/jpeg" if part.media_type == "image/*" else part.media_type
        if isinstance(data, SplitResult):
            url = urlunsplit(data)
        elif isinstance(data, bytes):
            url = f"data:{media_type};base64,{_b64(data)}"
        else:
            url = data if _URL_OR_DATA.match(data) else f"data:{media_type};base64,{data}"
        return [{"type": "input_image", "image_url": url, "detail": detail, **extra}]
    if part.media_type == "application/pdf":
        if _is_file_id(data, prefixes):
            return [{"type": "input_file", "file_id": data, **extra}]
        if isinstance(data, SplitResult):
            return [{"type": "input_file", "file_url": urlunsplit(data), **extra}]
        if isinstance(data, bytes):
            name = P.or_default(part.file_name, f"part-{index}.pdf")
            file_data = f"data:application/pdf;base64,{_b64(data)}"
            return [{"type": "input_file", "filename": name, "file_data": file_data, **extra}]
        return []
    raise _invalid(f"Detected unsupported media type for file: '{part.media_type}'")


def _decode_params(tool: AnyProviderDefined, name: str, params: object) -> Any:
    try:
        return P.wire_parse_sync(tool.parameters_schema, object)(params)
    except S.SchemaError as error:
        raise PT.unsupported(
            MODULE,
            "prepareMessages",
            ToolParameterValidationError(tool_name=name, description=describe_schema_error(error)),
        ) from error


def _has(value: object, key: str) -> bool:
    return key in P.obj(value)


def _denied(result: object) -> bool:
    return P.obj(result).get("type") == "execution-denied"


@dataclass
class _Messages:
    """What ``prepare_messages`` builds, with what it reads throughout."""

    config: Mapping[str, Any]
    options: lm.ProviderOptions
    names: NameMapper
    reasoning_model: bool
    has_conversation: bool
    use_item_references: bool
    items: list[Item] = field(default_factory=list[Item])
    approvals: set[str] = field(default_factory=set[str])

    @property
    def replays_provider_items(self) -> bool:
        return self.config.get("store") is True or self.options.incremental_fallback is True

    def system(self, message: Pr.SystemMessage) -> None:
        text = {"type": "input_text", "text": message.content, **_breakpoint(message.options)}
        self.items.append(
            {"role": "developer" if self.reasoning_model else "system", "content": [text]}
        )

    def user(self, message: Pr.UserMessage) -> None:
        prefixes = self.config.get("file_id_prefixes")
        content: list[Item] = []
        for index, part in enumerate(message.content):
            if isinstance(part, Pr.TextPart):
                content.append(
                    {"type": "input_text", "text": part.text, **_breakpoint(part.options)}
                )
            else:
                content.extend(_file(part, index, prefixes))
        self.items.append({"role": "user", "content": content})

    def assistant(self, message: Pr.AssistantMessage) -> None:
        executed = [
            part
            for part in message.content
            if isinstance(part, Pr.ToolCallPart | Pr.ToolResultPart) and part.provider_executed
        ]
        reasoning: dict[str, Item] = {}
        for part in message.content:
            match part:
                case Pr.TextPart():
                    self._text(part)
                case Pr.ReasoningPart():
                    self._reasoning(part, reasoning)
                case Pr.ToolCallPart():
                    self._tool_call(part, executed)
                case Pr.ToolResultPart():
                    self._assistant_result(part, executed)
                case _:
                    pass

    def _skipped_or_referenced(self, id: object) -> bool:
        """A stored item is left out of a conversation, or referenced."""
        if id is None:
            return False
        if self.has_conversation:
            return True
        if self.use_item_references:
            self.items.append({"type": "item_reference", "id": id})
            return True
        return False

    def _text(self, part: Pr.TextPart) -> None:
        id = _item_id(part)
        if self._skipped_or_referenced(id):
            return
        options = openai_options(part.options)
        self.items.append(
            {
                "id": id,
                "type": "message",
                "role": "assistant",
                "status": P.or_default(options.get("status"), "completed"),
                "content": [
                    {
                        "type": "output_text",
                        "text": part.text,
                        "annotations": P.or_default(options.get("annotations"), list[Any]()),
                        "logprobs": [],
                    }
                ],
            }
        )

    def _reasoning(self, part: Pr.ReasoningPart, seen: dict[str, Item]) -> None:
        id = _item_id(part)
        if id is None or (self.has_conversation):
            return
        encrypted = openai_options(part.options).get("encryptedContent")
        known = seen.get(id)
        if self.use_item_references:
            # One reference for all the parts of a reasoning item.
            if known is None:
                self.items.append({"type": "item_reference", "id": id})
                seen[id] = {"type": "reasoning", "id": id, "summary": []}
            return
        summary = [{"type": "summary_text", "text": part.text}] if part.text else []
        if known is None:
            item: Item = {"type": "reasoning", "id": id, "summary": summary}
            if encrypted is not None:
                item["encrypted_content"] = encrypted
            seen[id] = item
            self.items.append(item)
            return
        known["summary"].extend(summary)
        # The last part with encrypted content sets it.
        if encrypted is not None:
            known["encrypted_content"] = encrypted

    def _tool_call(self, part: Pr.ToolCallPart, executed: list[Any]) -> None:
        id = _item_id(part)
        status = _status(part)
        if self._skipped_or_referenced(id):
            return
        if part.provider_executed:
            self._provider_call(part, executed)
            return
        name = self.names.get_provider_name(part.name)
        local_shell = provider_tool(self.options, "OpenAiLocalShell")
        if local_shell is not None and name == "local_shell":
            params = _decode_params(local_shell, "local_shell", part.params)
            self.items.append(
                {
                    "id": id,
                    "type": "local_shell_call",
                    "call_id": part.id,
                    "status": P.or_default(status, "completed"),
                    "action": params["action"],
                }
            )
            return
        shell = provider_tool(self.options, "OpenAiShell")
        if shell is not None and name == "shell":
            params = _decode_params(shell, "shell", part.params)
            self.items.append(
                {
                    "id": id,
                    "type": "shell_call",
                    "call_id": part.id,
                    "status": P.or_default(status, "completed"),
                    "action": params["action"],
                }
            )
            return
        item: Item = {
            "type": "function_call",
            "name": name,
            "call_id": part.id,
            "arguments": P.dumps(part.params),
        }
        if id is not None:
            item["id"] = id
        self.items.append(_with_status(item, status))

    def _provider_call(self, part: Pr.ToolCallPart, executed: list[Any]) -> None:
        if not self.replays_provider_items:
            return
        result = next(
            (
                c
                for c in executed
                if isinstance(c, Pr.ToolResultPart) and c.id == part.id and c.name == part.name
            ),
            None,
        )
        if result is None:
            raise _unreplayable(part.name, part.id)
        if _denied(result.result):
            return
        item_id = P.or_default(_item_id(part), P.or_default(_item_id(result), part.id))
        replay = _REPLAYS.get(part.name)
        item = None if replay is None else replay(item_id, part.params, result.result)
        if item is None:
            raise _unreplayable(part.name, part.id)
        self.items.append(item)

    def _assistant_result(self, part: Pr.ToolResultPart, executed: list[Any]) -> None:
        # Assistant tool results are always provider executed; denied ones
        # have no item in OpenAI's store.
        if _denied(part.result) or self.has_conversation:
            return
        if self.use_item_references:
            id = P.or_default(_item_id(part), part.id)
            self.items.append({"type": "item_reference", "id": id})
        elif part.provider_executed and self.replays_provider_items:
            call = next(
                (
                    c
                    for c in executed
                    if isinstance(c, Pr.ToolCallPart) and c.id == part.id and c.name == part.name
                ),
                None,
            )
            if call is None:
                raise _unreplayable(part.name, part.id)

    def tool(self, message: Pr.ToolMessage) -> None:
        for part in message.content:
            if isinstance(part, Pr.ToolApprovalResponsePart):
                self._approval(part)
            else:
                self._tool_result(part)

    def _approval(self, part: Pr.ToolApprovalResponsePart) -> None:
        if part.approval_id in self.approvals:
            return
        self.approvals.add(part.approval_id)
        if self.use_item_references:
            self.items.append({"type": "item_reference", "id": part.approval_id})
        self.items.append(
            {
                "type": "mcp_approval_response",
                "approval_request_id": part.approval_id,
                "approve": part.approved,
            }
        )

    def _tool_result(self, part: Pr.ToolResultPart) -> None:
        # A denied result with an approval id was answered by its approval
        # response.
        if _denied(part.result) and openai_options(part.options).get("approvalId") is not None:
            return
        id = P.or_default(_item_id(part), part.id)
        status = _status(part)
        name = self.names.get_provider_name(part.name)
        if provider_tool(self.options, "OpenAiApplyPatch") is not None and name == "apply_patch":
            result = P.obj(part.result)
            self.items.append(
                {"id": id, "type": "apply_patch_call_output", "call_id": part.id, **result}
            )
            return
        for tool_name, kind in (("OpenAiShell", "shell"), ("OpenAiLocalShell", "local_shell")):
            if provider_tool(self.options, tool_name) is not None and name == kind:
                item = {
                    "id": id,
                    "type": f"{kind}_call_output",
                    "call_id": part.id,
                    "output": part.result,
                }
                self.items.append(_with_status(item, status))
                return
        output = part.result if isinstance(part.result, str) else P.dumps(part.result)
        self.items.append(
            _with_status(
                {"type": "function_call_output", "call_id": part.id, "output": output}, status
            )
        )


def _web_search(id: object, _params: object, result: object) -> Item | None:
    if not _has(result, "status"):
        return None
    found = P.obj(result)
    item: Item = {"type": "web_search_call", "id": id}
    if "action" in found:
        item["action"] = found["action"]
    item["status"] = found["status"]
    return item


def _code_interpreter(id: object, params: object, result: object) -> Item | None:
    if not (
        _has(params, "code")
        and _has(params, "container_id")
        and _has(result, "status")
        and _has(result, "outputs")
    ):
        return None
    given, found = P.obj(params), P.obj(result)
    return {
        "type": "code_interpreter_call",
        "id": id,
        "code": given["code"],
        "container_id": given["container_id"],
        "status": found["status"],
        "outputs": found["outputs"],
    }


def _file_search(id: object, _params: object, result: object) -> Item | None:
    if not all(_has(result, key) for key in ("status", "queries", "results")):
        return None
    found = P.obj(result)
    return {
        "type": "file_search_call",
        "id": id,
        "status": found["status"],
        "queries": found["queries"],
        "results": found["results"],
    }


def _image_generation(id: object, _params: object, result: object) -> Item | None:
    if not _has(result, "result"):
        return None
    found = P.obj(result)
    return {
        "type": "image_generation_call",
        "id": id,
        "result": found["result"],
        "status": found.get("status", "completed"),
    }


_REPLAYS: dict[str, Callable[[object, object, object], Item | None]] = {
    "OpenAiWebSearch": _web_search,
    "OpenAiWebSearchPreview": _web_search,
    "OpenAiCodeInterpreter": _code_interpreter,
    "OpenAiFileSearch": _file_search,
    "OpenAiImageGeneration": _image_generation,
}
"""How a provider-executed call and its result are sent back as the item
OpenAI produced; ``None`` when the parts lack what the item needs."""


def _include(
    config: Mapping[str, Any],
    options: lm.ProviderOptions,
    include: dict[str, None],
    *,
    reasoning_model: bool,
    use_item_references: bool,
    web_socket_mode: bool,
) -> None:
    if config.get("top_logprobs") is not None:
        include["message.output_text.logprobs"] = None
    if (web_socket_mode or not use_item_references) and reasoning_model:
        include["reasoning.encrypted_content"] = None
    if provider_tool(options, "OpenAiCodeInterpreter") is not None:
        include["code_interpreter_call.outputs"] = None
    if provider_tool(options, "OpenAiWebSearch", "OpenAiWebSearchPreview") is not None:
        include["web_search_call.action.sources"] = None


def prepare_messages(
    config: Mapping[str, Any],
    options: lm.ProviderOptions,
    names: NameMapper,
    include: dict[str, None],
    *,
    web_socket_mode: bool,
) -> list[Item]:
    """The input items, adding what the request must ``include`` (an
    ordered set). Raises ``UnsupportedInput`` for input the API cannot
    take or a provider item that cannot be replayed."""
    reasoning_model = is_reasoning_model(config)
    use_item_references = (
        config.get("store") is True
        and config.get("use_item_references") is not False
        and options.incremental_fallback is not True
    )
    _include(
        config,
        options,
        include,
        reasoning_model=reasoning_model,
        use_item_references=use_item_references,
        web_socket_mode=web_socket_mode,
    )
    messages = _Messages(
        config,
        options,
        names,
        reasoning_model,
        config.get("conversation") is not None,
        use_item_references,
    )
    prompt = options.incremental_prompt or options.prompt
    for message in prompt.content:
        match message:
            case Pr.SystemMessage():
                messages.system(message)
            case Pr.UserMessage():
                messages.user(message)
            case Pr.AssistantMessage():
                messages.assistant(message)
            case Pr.ToolMessage():
                messages.tool(message)
    return messages.items


__all__ = ["KEY", "MODULE", "Item", "is_reasoning_model", "prepare_messages", "provider_tool"]
