"""A Responses API response as encoded response parts (Effect's
``makeResponse``), and what the streamed parts share with it: usage,
finish metadata, annotation sources and tool call parameters. Response
parts carry OpenAI metadata under ``metadata["openai"]`` in Effect's
spelling (``itemId``, ``encryptedContent``, ``annotations``,
``serviceTier``, ...)."""

from __future__ import annotations

from collections.abc import Callable, Generator
from datetime import UTC, datetime
from typing import Any

import pyfect as fx
from pyfect import date_time
from pyfect._core import Effect
from pyfect.ai import _provider as P
from pyfect.ai import _provider_tools as PT
from pyfect.ai import language_model as lm
from pyfect.ai import prompt as Pr
from pyfect.ai.ai_error import AiError, ToolParameterValidationError
from pyfect.ai.id_generator import IdGenerator
from pyfect.ai.id_generator import Service as IdService
from pyfect.ai.openai import _schema as W
from pyfect.ai.openai._errors import OPENAI
from pyfect.ai.openai._prompt import KEY, MODULE, openai_options, provider_tool
from pyfect.ai.openai_structured_output import to_codec_openai
from pyfect.ai.response import FinishReason
from pyfect.ai.tool import NameMapper, unsafe_secure_json_parse
from pyfect.http import url
from pyfect.http.response import HttpClientResponse

type Part = dict[str, Any]
type Gen[A] = Generator[Effect[Any, Any, Any], Any, A]

_FINISH_REASONS: dict[str, FinishReason] = {
    "content_filter": "content-filter",
    "function_call": "tool-calls",
    "length": "length",
    "max_output_tokens": "length",
    "stop": "stop",
    "tool_calls": "tool-calls",
}
_SERVICE_TIERS = frozenset({"default", "auto", "flex", "scale", "priority", "ultrafast"})


def resolve_finish_reason(reason: object, has_tool_calls: bool) -> FinishReason:
    if reason is None:
        return "tool-calls" if has_tool_calls else "stop"
    resolved = _FINISH_REASONS.get(str(reason))
    if resolved is None:
        return "tool-calls" if has_tool_calls else "unknown"
    return resolved


def escape_json_delta(delta: str) -> str:
    """``delta`` as the inside of a JSON string."""
    return P.dumps(delta)[1:-1]


def item_metadata(item_id: object) -> dict[str, Any]:
    return {} if item_id is None else {"itemId": item_id}


def encrypted_metadata(encrypted: object) -> dict[str, Any]:
    return {} if encrypted is None else {"encryptedContent": encrypted}


def timestamp(created_at: float) -> str:
    return date_time.format_iso(datetime.fromtimestamp(created_at, UTC))


def request_details(response: HttpClientResponse) -> Any:
    return P.request_details(response.request, secret_headers=OPENAI.secret_headers)


def _token_detail(details: object, key: str) -> int | float | None:
    value = P.obj(details).get(key)
    return value if isinstance(value, int | float) and not isinstance(value, bool) else None


def usage(raw: W.ResponseUsage | None) -> dict[str, Any]:
    if raw is None:
        return {"inputTokens": {}, "outputTokens": {}}
    input_tokens, output_tokens = raw["input_tokens"], raw["output_tokens"]
    cached = _token_detail(raw.get("input_tokens_details"), "cached_tokens") or 0
    cache_write = _token_detail(raw.get("input_tokens_details"), "cache_write_tokens")
    reasoning = _token_detail(raw.get("output_tokens_details"), "reasoning_tokens") or 0
    tokens: dict[str, Any] = {
        "uncached": input_tokens - cached,
        "total": input_tokens,
        "cacheRead": cached,
    }
    if cache_write is not None:
        tokens["cacheWrite"] = cache_write
    return {
        "inputTokens": tokens,
        "outputTokens": {
            "total": output_tokens,
            "text": output_tokens - reasoning,
            "reasoning": reasoning,
        },
    }


def finish_metadata(response: W.Response) -> dict[str, Any]:
    tier = response.get("service_tier")
    diagnostics = response.get("prompt_cache_diagnostics")
    metadata: dict[str, Any] = {}
    if tier in _SERVICE_TIERS:
        metadata["serviceTier"] = tier
    if diagnostics is not None:
        metadata["promptCacheDiagnostics"] = diagnostics
    return {"metadata": {KEY: metadata}} if metadata else {}


def finish(response: W.Response, http: HttpClientResponse, reason: FinishReason) -> Part:
    return {
        "type": "finish",
        "reason": reason,
        "usage": usage(response.get("usage")),
        "response": P.response_details(http),
        **finish_metadata(response),
    }


def _href(text: str) -> str:
    """``text`` as a WHATWG URL writes it (Effect decodes it with ``new
    URL``); an invalid one is left for the response decoder to reject."""
    try:
        return url.href(url.parse(text))
    except ValueError:
        return text


def source(annotation: dict[str, Any], id: str) -> Part | None:
    """The source part of a citation annotation."""
    match annotation["type"]:
        case "container_file_citation":
            return {
                "type": "source",
                "sourceType": "document",
                "id": id,
                "mediaType": "text/plain",
                "title": annotation["filename"],
                "fileName": annotation["filename"],
                "metadata": {
                    KEY: {
                        "type": annotation["type"],
                        "fileId": annotation["file_id"],
                        "containerId": annotation["container_id"],
                    }
                },
            }
        case "file_citation":
            return {
                "type": "source",
                "sourceType": "document",
                "id": id,
                "mediaType": "text/plain",
                "title": annotation["filename"],
                "fileName": annotation["filename"],
                "metadata": {
                    KEY: {
                        "type": annotation["type"],
                        "fileId": annotation["file_id"],
                        "index": annotation["index"],
                    }
                },
            }
        case "file_path":
            return {
                "type": "source",
                "sourceType": "document",
                "id": id,
                "mediaType": "application/octet-stream",
                "title": annotation["file_id"],
                "fileName": annotation["file_id"],
                "metadata": {
                    KEY: {
                        "type": annotation["type"],
                        "fileId": annotation["file_id"],
                        "index": annotation["index"],
                    }
                },
            }
        case "url_citation":
            return {
                "type": "source",
                "sourceType": "url",
                "id": id,
                "url": _href(annotation["url"]),
                "title": annotation["title"],
                "metadata": {
                    KEY: {
                        "type": annotation["type"],
                        "startIndex": annotation["start_index"],
                        "endIndex": annotation["end_index"],
                    }
                },
            }
        case _:
            return None


def sources(annotation: dict[str, Any], ids: IdService) -> Gen[list[Part]]:
    """The source part of ``annotation``, if it is a citation, with a new
    id."""
    if annotation["type"] not in (
        "container_file_citation",
        "file_citation",
        "file_path",
        "url_citation",
    ):
        return []
    id: str = yield from ids.generate_id()
    found = source(annotation, id)
    return [] if found is None else [found]


def parse_params(name: str, text: str, method: str) -> Effect[object, AiError]:
    try:
        return fx.succeed(unsafe_secure_json_parse(text))
    except ValueError as cause:
        return fx.fail(
            AiError(
                module=MODULE,
                method=method,
                reason=ToolParameterValidationError(
                    tool_name=name,
                    description=f"Failed to securely JSON parse tool parameters: {cause}",
                ),
            )
        )


def function_params(
    options: lm.ProviderOptions, name: str, arguments: str, method: str
) -> Gen[object]:
    raw = yield from parse_params(name, arguments, method)
    return (yield from PT.transform_params(MODULE, options, name, raw, transformer=to_codec_openai))


def mcp_call(names: NameMapper, arguments: object, method: str) -> Gen[tuple[str, object]]:
    """The MCP tool's name and the call's parameters (JSON text parsed)."""
    name = names.get_custom_name("mcp")
    if not isinstance(arguments, str):
        return name, arguments
    return name, (yield from parse_params(name, arguments, method))


def mcp_result(item: W.OutputItem) -> dict[str, Any]:
    result: dict[str, Any] = {
        "type": "mcp_call",
        "name": item["name"],
        "arguments": item["arguments"],
        "server_label": item["server_label"],
    }
    for key in ("output", "error"):
        if item.get(key) is not None:
            result[key] = item[key]
    return result


def approval_request_ids(prompt: Pr.Prompt) -> dict[str, str]:
    """The approval request ids the prompt's tool calls answer, to their
    call ids."""
    mapping: dict[str, str] = {}
    for message in prompt.content:
        if not isinstance(message, Pr.AssistantMessage):
            continue
        for part in message.content:
            if isinstance(part, Pr.ToolCallPart):
                request = openai_options(part.options).get("approvalRequestId")
                if request is not None:
                    mapping[str(request)] = part.id
    return mapping


def web_search_tool(options: lm.ProviderOptions) -> Any:
    return provider_tool(options, "OpenAiWebSearch", "OpenAiWebSearchPreview")


def _web_search_result(item: W.OutputItem) -> dict[str, Any]:
    result: dict[str, Any] = {}
    if "action" in item:
        result["action"] = item["action"]
    result["status"] = item["status"]
    return result


class _Output:
    """The parts of each output item."""

    def __init__(self, options: lm.ProviderOptions, names: NameMapper, ids: IdService) -> None:
        self.options = options
        self.names = names
        self.ids = ids
        self.approvals = approval_request_ids(options.prompt)
        self.has_tool_calls = False

    def item(self, item: W.OutputItem) -> Gen[list[Part]]:
        handler = _OUTPUT.get(item["type"])
        if handler is None:
            return []
        return (yield from handler(self, item))

    def apply_patch_call(self, item: W.OutputItem) -> Gen[list[Part]]:
        yield from ()
        return [
            {
                "type": "tool-call",
                "id": item["call_id"],
                "name": self.names.get_custom_name("apply_patch"),
                "params": {"call_id": item["call_id"], "operation": item["operation"]},
                "metadata": {KEY: item_metadata(item.get("id"))},
            }
        ]

    def code_interpreter_call(self, item: W.OutputItem) -> Gen[list[Part]]:
        yield from ()
        name = self.names.get_custom_name("code_interpreter")
        status = P.or_default(item.get("status"), "completed")
        return [
            {
                "type": "tool-call",
                "id": item["id"],
                "name": name,
                "params": {"code": item.get("code"), "container_id": item["container_id"]},
                "providerExecuted": True,
            },
            {
                "type": "tool-result",
                "id": item["id"],
                "name": name,
                "isFailure": status != "completed",
                "result": {"status": status, "outputs": item.get("outputs")},
                "providerExecuted": True,
            },
        ]

    def file_search_call(self, item: W.OutputItem) -> Gen[list[Part]]:
        yield from ()
        name = self.names.get_custom_name("file_search")
        return [
            {
                "type": "tool-call",
                "id": item["id"],
                "name": name,
                "params": {},
                "providerExecuted": True,
            },
            {
                "type": "tool-result",
                "id": item["id"],
                "name": name,
                "isFailure": item["status"] != "completed",
                "result": {
                    "status": item["status"],
                    "queries": item["queries"],
                    "results": item.get("results"),
                },
                "providerExecuted": True,
            },
        ]

    def function_call(self, item: W.OutputItem) -> Gen[list[Part]]:
        self.has_tool_calls = True
        name = item["name"]
        params = yield from function_params(self.options, name, item["arguments"], "makeResponse")
        return [
            {
                "type": "tool-call",
                "id": item["call_id"],
                "name": name,
                "params": params,
                "metadata": {KEY: item_metadata(item.get("id"))},
            }
        ]

    def image_generation_call(self, item: W.OutputItem) -> Gen[list[Part]]:
        yield from ()
        name = self.names.get_custom_name("image_generation")
        status = P.or_default(item.get("status"), "completed")
        result = item.get("result")
        return [
            {
                "type": "tool-call",
                "id": item["id"],
                "name": name,
                "params": {},
                "providerExecuted": True,
            },
            {
                "type": "tool-result",
                "id": item["id"],
                "name": name,
                "isFailure": status != "completed",
                "result": {"result": result}
                if status == "completed"
                else {"status": status, "result": result},
            },
        ]

    def local_shell_call(self, item: W.OutputItem) -> Gen[list[Part]]:
        yield from ()
        return [
            {
                "type": "tool-call",
                "id": item["call_id"],
                "name": self.names.get_custom_name("local_shell"),
                "params": {"action": item["action"]},
                "metadata": {KEY: item_metadata(item.get("id"))},
            }
        ]

    def mcp_call(self, item: W.OutputItem) -> Gen[list[Part]]:
        request = item.get("approval_request_id")
        id = item["id"] if request is None else self.approvals.get(request, item["id"])
        name, params = yield from mcp_call(self.names, item["arguments"], "makeResponse")
        return [
            {
                "type": "tool-call",
                "id": id,
                "name": name,
                "params": params,
                "providerExecuted": True,
            },
            {
                "type": "tool-result",
                "id": id,
                "name": name,
                "isFailure": item.get("error") is not None,
                "providerExecuted": True,
                "result": mcp_result(item),
                "metadata": {KEY: item_metadata(item.get("id"))},
            },
        ]

    def mcp_approval_request(self, item: W.OutputItem) -> Gen[list[Part]]:
        approval = P.or_default(item.get("approval_request_id"), item["id"])
        id: str = yield from self.ids.generate_id()
        name, params = yield from mcp_call(self.names, item["arguments"], "makeResponse")
        return [
            {
                "type": "tool-call",
                "id": id,
                "name": name,
                "params": params,
                "providerExecuted": True,
            },
            {"type": "tool-approval-request", "toolCallId": id, "approvalId": approval},
        ]

    def message(self, item: W.OutputItem) -> Gen[list[Part]]:
        parts: list[Part] = []
        for content in item["content"]:
            if content["type"] == "output_text":
                annotations = content["annotations"]
                metadata = item_metadata(item.get("id"))
                if annotations:
                    metadata["annotations"] = list(annotations)
                parts.append({"type": "text", "text": content["text"], "metadata": {KEY: metadata}})
                for annotation in annotations:
                    parts.extend((yield from sources(annotation, self.ids)))
            elif content["type"] == "refusal":
                parts.append(
                    {"type": "text", "text": "", "metadata": {KEY: {"refusal": content["refusal"]}}}
                )
        return parts

    def reasoning(self, item: W.OutputItem) -> Gen[list[Part]]:
        yield from ()
        metadata = {
            KEY: {
                **item_metadata(item.get("id")),
                **encrypted_metadata(item.get("encrypted_content")),
            }
        }
        # An empty part carries the item's id and encrypted content when
        # there is no summary.
        summary = item["summary"] or [{"text": ""}]
        return [{"type": "reasoning", "text": s["text"], "metadata": metadata} for s in summary]

    def shell_call(self, item: W.OutputItem) -> Gen[list[Part]]:
        yield from ()
        return [
            {
                "type": "tool-call",
                "id": item["call_id"],
                "name": self.names.get_custom_name("shell"),
                "params": {"action": item["action"]},
                "metadata": {KEY: item_metadata(item.get("id"))},
            }
        ]

    def web_search_call(self, item: W.OutputItem) -> Gen[list[Part]]:
        yield from ()
        tool = web_search_tool(self.options)
        name = self.names.get_custom_name("web_search" if tool is None else tool.name)
        preview = tool is not None and tool.name == "OpenAiWebSearchPreview"
        return [
            {
                "type": "tool-call",
                "id": item["id"],
                "name": name,
                "params": {} if preview or "action" not in item else {"action": item["action"]},
                "providerExecuted": True,
            },
            {
                "type": "tool-result",
                "id": item["id"],
                "name": name,
                "isFailure": item["status"] != "completed",
                "result": _web_search_result(item),
                "providerExecuted": True,
            },
        ]


_OUTPUT: dict[str, Callable[[_Output, W.OutputItem], Gen[list[Part]]]] = {
    "apply_patch_call": _Output.apply_patch_call,
    "code_interpreter_call": _Output.code_interpreter_call,
    "file_search_call": _Output.file_search_call,
    "function_call": _Output.function_call,
    "image_generation_call": _Output.image_generation_call,
    "local_shell_call": _Output.local_shell_call,
    "mcp_call": _Output.mcp_call,
    "mcp_approval_request": _Output.mcp_approval_request,
    "message": _Output.message,
    "reasoning": _Output.reasoning,
    "shell_call": _Output.shell_call,
    "web_search_call": _Output.web_search_call,
}
"""The parts of each output item type; others (``mcp_list_tools``) have
none."""


def _make_response(
    options: lm.ProviderOptions,
    raw: W.Response,
    response: HttpClientResponse,
    names: NameMapper,
) -> Gen[list[Part]]:
    ids: IdService = yield from IdGenerator()
    output = _Output(options, names, ids)
    parts: list[Part] = [
        {
            "type": "response-metadata",
            "id": raw["id"],
            "modelId": raw["model"],
            "timestamp": timestamp(raw["created_at"]),
            "request": request_details(response),
        }
    ]
    for item in raw["output"]:
        parts.extend((yield from output.item(item)))
    reason = P.obj(raw.get("incomplete_details")).get("reason")
    parts.append(finish(raw, response, resolve_finish_reason(reason, output.has_tool_calls)))
    return parts


def make_response(
    options: lm.ProviderOptions,
    raw: W.Response,
    response: HttpClientResponse,
    names: NameMapper,
) -> Effect[list[Part], AiError, Any]:
    return fx.gen(lambda: _make_response(options, raw, response, names))
