"""Responses API stream events as encoded stream parts (Effect's
``makeStreamResponse``).

Function calls stream their arguments as parameter deltas; apply patch
and code interpreter calls stream the JSON of their parameters, built
around the diff or code deltas. A reasoning item's summary parts end once
the next one starts or the item is done, so the last one can carry the
encrypted content; over HTTP with stored item references each ends at
once."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Literal

import pyfect as fx
from pyfect._core import Effect
from pyfect.ai import _provider as P
from pyfect.ai import language_model as lm
from pyfect.ai.ai_error import AiError
from pyfect.ai.id_generator import Service as IdService
from pyfect.ai.openai import _schema as W
from pyfect.ai.openai._prompt import KEY
from pyfect.ai.openai._response import (
    Gen,
    Part,
    approval_request_ids,
    encrypted_metadata,
    escape_json_delta,
    finish,
    function_params,
    item_metadata,
    mcp_call,
    mcp_result,
    request_details,
    resolve_finish_reason,
    sources,
    timestamp,
    web_search_tool,
)
from pyfect.ai.tool import NameMapper
from pyfect.http.response import HttpClientResponse
from pyfect.stream import Stream

type _SummaryStatus = Literal["active", "can-conclude", "concluded"]


@dataclass
class _Reasoning:
    encrypted_content: str | None
    summary_parts: dict[int, _SummaryStatus] = field(default_factory=dict[int, _SummaryStatus])


@dataclass
class _ApplyPatch:
    has_diff: bool
    end_emitted: bool


@dataclass
class _CodeInterpreter:
    container_id: str
    has_code: bool = False
    streamed_code: str = ""


@dataclass
class _ToolCall:
    id: str
    name: str
    function_emitted: bool | None = None
    apply_patch: _ApplyPatch | None = None
    code_interpreter: _CodeInterpreter | None = None


def _reasoning_end(item_id: str, index: int, encrypted: str | None) -> Part:
    return {
        "type": "reasoning-end",
        "id": f"{item_id}:{index}",
        "metadata": {KEY: {**item_metadata(item_id), **encrypted_metadata(encrypted)}},
    }


@dataclass
class _Stream:
    options: lm.ProviderOptions
    response: HttpClientResponse
    names: NameMapper
    ids: IdService
    concludes_summaries: bool
    """Whether summary parts end at once (stored item references over HTTP
    need no encrypted content)."""
    approvals: dict[str, str] = field(default_factory=dict[str, str])
    stream_approvals: dict[str, str] = field(default_factory=dict[str, str])
    has_tool_calls: bool = False
    annotations: list[Any] = field(default_factory=list[Any])
    reasoning: dict[str, _Reasoning] = field(default_factory=dict[str, _Reasoning])
    tool_calls: dict[int, _ToolCall] = field(default_factory=dict[int, _ToolCall])
    web_search: Any = None

    def __post_init__(self) -> None:
        self.approvals = approval_request_ids(self.options.prompt)
        self.web_search = web_search_tool(self.options)

    def reasoning_part(self, item_id: str, encrypted: str | None = None) -> _Reasoning:
        active = self.reasoning.get(item_id)
        if active is None:
            active = _Reasoning(encrypted)
            self.reasoning[item_id] = active
        elif encrypted is not None:
            active.encrypted_content = encrypted
        return active

    def finish_code(self, output_index: int, code: str | None, parts: list[Part]) -> None:
        call = self.tool_calls.get(output_index)
        if call is None or call.code_interpreter is None:
            return
        code_call = call.code_interpreter
        delta = '"}' if code_call.has_code else f"{P.dumps(code)}}}"
        parts.append({"type": "tool-params-delta", "id": call.id, "delta": delta})
        parts.append({"type": "tool-params-end", "id": call.id})
        parts.append(
            {
                "type": "tool-call",
                "id": call.id,
                "name": call.name,
                "params": {
                    "code": code_call.streamed_code if code_call.has_code else code,
                    "container_id": code_call.container_id,
                },
                "providerExecuted": True,
            }
        )
        del self.tool_calls[output_index]

    # Events -------------------------------------------------------------------------

    def event(self, event: W.ResponseStreamEvent) -> Effect[list[Part], AiError, Any]:
        handler = _EVENTS.get(event["type"])
        if handler is None:
            return fx.succeed([])
        return fx.gen(lambda: handler(self, event))

    def created(self, event: Any) -> Gen[list[Part]]:
        yield from ()
        response = event["response"]
        return [
            {
                "type": "response-metadata",
                "id": response["id"],
                "modelId": response["model"],
                "timestamp": timestamp(response["created_at"]),
                "request": request_details(self.response),
            }
        ]

    def error(self, event: Any) -> Gen[list[Part]]:
        yield from ()
        return [{"type": "error", "error": event}]

    def completed(self, event: Any) -> Gen[list[Part]]:
        yield from ()
        response = event["response"]
        reason = P.obj(response.get("incomplete_details")).get("reason")
        return [finish(response, self.response, resolve_finish_reason(reason, self.has_tool_calls))]

    def failed(self, event: Any) -> Gen[list[Part]]:
        yield from ()
        response = event["response"]
        parts: list[Part] = []
        if response.get("error"):
            parts.append({"type": "error", "error": response["error"]})
        parts.append(finish(response, self.response, "error"))
        return parts

    def item_added(self, event: Any) -> Gen[list[Part]]:
        yield from ()
        return _ADDED.get(event["item"]["type"], _nothing)(
            self, event["output_index"], event["item"]
        )

    def item_done(self, event: Any) -> Gen[list[Part]]:
        handler = _DONE.get(event["item"]["type"])
        if handler is None:
            return []
        return (yield from handler(self, event["output_index"], event["item"]))

    def text_delta(self, event: Any) -> Gen[list[Part]]:
        yield from ()
        return [{"type": "text-delta", "id": event["item_id"], "delta": event["delta"]}]

    def annotation_added(self, event: Any) -> Gen[list[Part]]:
        annotation = event["annotation"]
        self.annotations.append(annotation)
        return (yield from sources(annotation, self.ids))

    def arguments_delta(self, event: Any) -> Gen[list[Part]]:
        yield from ()
        call = self.tool_calls.get(event["output_index"])
        if call is None:
            return []
        return [{"type": "tool-params-delta", "id": call.id, "delta": event["delta"]}]

    def arguments_done(self, event: Any) -> Gen[list[Part]]:
        call = self.tool_calls.get(event["output_index"])
        if call is None or call.function_emitted is not False:
            return []
        self.has_tool_calls = True
        params = yield from function_params(
            self.options, call.name, event["arguments"], "makeStreamResponse"
        )
        call.function_emitted = True
        return [
            {"type": "tool-params-end", "id": call.id},
            {
                "type": "tool-call",
                "id": call.id,
                "name": call.name,
                "params": params,
                "metadata": {KEY: item_metadata(event.get("item_id"))},
            },
        ]

    def diff_delta(self, event: Any) -> Gen[list[Part]]:
        yield from ()
        call = self.tool_calls.get(event["output_index"])
        if call is None or call.apply_patch is None:
            return []
        call.apply_patch.has_diff = True
        return [
            {"type": "tool-params-delta", "id": call.id, "delta": escape_json_delta(event["delta"])}
        ]

    def diff_done(self, event: Any) -> Gen[list[Part]]:
        yield from ()
        call = self.tool_calls.get(event["output_index"])
        if call is None or call.apply_patch is None or call.apply_patch.end_emitted:
            return []
        parts: list[Part] = []
        delta = event.get("delta")
        if not call.apply_patch.has_diff and delta is not None:
            parts.append(
                {"type": "tool-params-delta", "id": call.id, "delta": escape_json_delta(delta)}
            )
            call.apply_patch.has_diff = True
        parts.append({"type": "tool-params-delta", "id": call.id, "delta": '"}}'})
        parts.append({"type": "tool-params-end", "id": call.id})
        call.apply_patch.end_emitted = True
        return parts

    def code_delta(self, event: Any) -> Gen[list[Part]]:
        yield from ()
        call = self.tool_calls.get(event["output_index"])
        if call is None or call.code_interpreter is None:
            return []
        code = call.code_interpreter
        delta = ("" if code.has_code else '"') + escape_json_delta(event["delta"])
        code.has_code = True
        code.streamed_code += event["delta"]
        return [{"type": "tool-params-delta", "id": call.id, "delta": delta}]

    def code_done(self, event: Any) -> Gen[list[Part]]:
        yield from ()
        parts: list[Part] = []
        self.finish_code(event["output_index"], event["code"], parts)
        return parts

    def partial_image(self, event: Any) -> Gen[list[Part]]:
        yield from ()
        return [
            {
                "type": "tool-result",
                "id": event["item_id"],
                "name": self.names.get_custom_name("image_generation"),
                "isFailure": False,
                "providerExecuted": False,
                "result": {"result": event["partial_image_b64"]},
                "preliminary": True,
            }
        ]

    def summary_added(self, event: Any) -> Gen[list[Part]]:
        yield from ()
        item_id, index = event["item_id"], event["summary_index"]
        reasoning = self.reasoning_part(item_id)
        parts: list[Part] = []
        if index > 0:
            # The parts that could end end before a new one starts.
            for summary, status in sorted(reasoning.summary_parts.items()):
                if status == "can-conclude":
                    parts.append(_reasoning_end(item_id, summary, reasoning.encrypted_content))
                    reasoning.summary_parts[summary] = "concluded"
        if index not in reasoning.summary_parts:
            reasoning.summary_parts[index] = "active"
            parts.append(
                {
                    "type": "reasoning-start",
                    "id": f"{item_id}:{index}",
                    "metadata": {
                        KEY: {
                            **item_metadata(item_id),
                            **encrypted_metadata(reasoning.encrypted_content),
                        }
                    },
                }
            )
        return parts

    def summary_delta(self, event: Any) -> Gen[list[Part]]:
        yield from ()
        item_id = event["item_id"]
        return [
            {
                "type": "reasoning-delta",
                "id": f"{item_id}:{event['summary_index']}",
                "delta": event["delta"],
                "metadata": {KEY: item_metadata(item_id)},
            }
        ]

    def summary_done(self, event: Any) -> Gen[list[Part]]:
        yield from ()
        item_id, index = event["item_id"], event["summary_index"]
        reasoning = self.reasoning_part(item_id)
        if self.concludes_summaries:
            reasoning.summary_parts[index] = "concluded"
            return [
                {
                    "type": "reasoning-end",
                    "id": f"{item_id}:{index}",
                    "metadata": {KEY: item_metadata(item_id)},
                }
            ]
        # A last summary part with the encrypted content may follow.
        reasoning.summary_parts[index] = "can-conclude"
        return []


def _nothing(_state: _Stream, _index: int, _item: Any) -> list[Part]:
    return []


# Items added ----------------------------------------------------------------------------


def _added_apply_patch(state: _Stream, index: int, item: Any) -> list[Part]:
    id = item["call_id"]
    name = state.names.get_custom_name("apply_patch")
    operation = item["operation"]
    deleting = operation["type"] == "delete_file"
    state.tool_calls[index] = _ToolCall(id, name, apply_patch=_ApplyPatch(not deleting, deleting))
    parts: list[Part] = [{"type": "tool-params-start", "id": id, "name": name}]
    if deleting:
        delta = P.dumps({"call_id": id, "operation": operation})
        parts.append({"type": "tool-params-delta", "id": id, "delta": delta})
        parts.append({"type": "tool-params-end", "id": id})
    else:
        delta = (
            f'{{"call_id":"{escape_json_delta(id)}",'
            f'"operation":{{"type":"{escape_json_delta(operation["type"])}",'
            f'"path":"{escape_json_delta(operation["path"])}","diff":"'
        )
        parts.append({"type": "tool-params-delta", "id": id, "delta": delta})
    return parts


def _added_code_interpreter(state: _Stream, index: int, item: Any) -> list[Part]:
    name = state.names.get_custom_name("code_interpreter")
    id = item["id"]
    state.tool_calls[index] = _ToolCall(
        id, name, code_interpreter=_CodeInterpreter(item["container_id"])
    )
    return [
        {"type": "tool-params-start", "id": id, "name": name, "providerExecuted": True},
        {
            "type": "tool-params-delta",
            "id": id,
            "delta": f'{{"container_id":{P.dumps(item["container_id"])},"code":',
        },
    ]


def _added_computer(state: _Stream, index: int, item: Any) -> list[Part]:
    name = state.names.get_custom_name("computer_use")
    state.tool_calls[index] = _ToolCall(item["id"], name)
    return [{"type": "tool-params-start", "id": item["id"], "name": name, "providerExecuted": True}]


def _added_executed(provider_name: str) -> Callable[[_Stream, int, Any], list[Part]]:
    def added(state: _Stream, _index: int, item: Any) -> list[Part]:
        return [
            {
                "type": "tool-call",
                "id": item["id"],
                "name": state.names.get_custom_name(provider_name),
                "params": {},
                "providerExecuted": True,
            }
        ]

    return added


def _added_function(state: _Stream, index: int, item: Any) -> list[Part]:
    state.tool_calls[index] = _ToolCall(item["call_id"], item["name"], function_emitted=False)
    return [{"type": "tool-params-start", "id": item["call_id"], "name": item["name"]}]


def _added_message(state: _Stream, _index: int, item: Any) -> list[Part]:
    state.annotations.clear()
    return [{"type": "text-start", "id": item["id"], "metadata": {KEY: item_metadata(item["id"])}}]


def _added_reasoning(state: _Stream, _index: int, item: Any) -> list[Part]:
    reasoning = state.reasoning_part(item["id"], item.get("encrypted_content"))
    if 0 in reasoning.summary_parts:
        return []
    reasoning.summary_parts[0] = "active"
    return [
        {
            "type": "reasoning-start",
            "id": f"{item['id']}:0",
            "metadata": {
                KEY: {
                    **item_metadata(item["id"]),
                    **encrypted_metadata(reasoning.encrypted_content),
                }
            },
        }
    ]


def _added_shell(state: _Stream, index: int, item: Any) -> list[Part]:
    id = P.or_default(item.get("id"), item["call_id"])
    state.tool_calls[index] = _ToolCall(id, state.names.get_custom_name("shell"))
    return []


def _added_web_search(state: _Stream, index: int, item: Any) -> list[Part]:
    tool = state.web_search
    name = state.names.get_custom_name("web_search" if tool is None else tool.provider_name)
    id = item["id"]
    state.tool_calls[index] = _ToolCall(id, name)
    if tool is not None and tool.name == "OpenAiWebSearch":
        return []
    return [
        {
            "type": "tool-params-start",
            "id": id,
            "name": "OpenAiWebSearch" if tool is None else tool.name,
            "providerExecuted": True,
        },
        {"type": "tool-params-end", "id": id},
        {"type": "tool-call", "id": id, "name": name, "params": {}, "providerExecuted": True},
    ]


_ADDED: dict[str, Callable[[_Stream, int, Any], list[Part]]] = {
    "apply_patch_call": _added_apply_patch,
    "code_interpreter_call": _added_code_interpreter,
    "computer_call": _added_computer,
    "file_search_call": _added_executed("file_search"),
    "function_call": _added_function,
    "image_generation_call": _added_executed("image_generation"),
    "message": _added_message,
    "reasoning": _added_reasoning,
    "shell_call": _added_shell,
    "web_search_call": _added_web_search,
}
"""The parts of an item that starts. MCP items have theirs when done, so
a call can take the id of the approval it answers."""


# Items done -----------------------------------------------------------------------------


def _done_apply_patch(state: _Stream, index: int, item: Any) -> Gen[list[Part]]:
    yield from ()
    call = state.tool_calls.get(index)
    parts: list[Part] = []
    operation = item["operation"]
    if (
        call is not None
        and call.apply_patch is not None
        and not call.apply_patch.end_emitted
        and operation["type"] != "delete_file"
    ):
        if not call.apply_patch.has_diff:
            delta = escape_json_delta(P.or_default(operation.get("diff"), ""))
            parts.append({"type": "tool-params-delta", "id": call.id, "delta": delta})
        parts.append({"type": "tool-params-delta", "id": call.id, "delta": '"}}'})
        parts.append({"type": "tool-params-end", "id": call.id})
        call.apply_patch.end_emitted = True
    # The call is complete only once its status is.
    if call is not None and item["status"] == "completed":
        parts.append(
            {
                "type": "tool-call",
                "id": call.id,
                "name": state.names.get_custom_name("apply_patch"),
                "params": {"call_id": item["call_id"], "operation": operation},
                "metadata": {KEY: item_metadata(item.get("id"))},
            }
        )
    state.tool_calls.pop(index, None)
    return parts


def _done_code_interpreter(state: _Stream, index: int, item: Any) -> Gen[list[Part]]:
    yield from ()
    parts: list[Part] = []
    state.finish_code(index, item.get("code"), parts)
    status = P.or_default(item.get("status"), "completed")
    parts.append(
        {
            "type": "tool-result",
            "id": item["id"],
            "name": state.names.get_custom_name("code_interpreter"),
            "isFailure": status != "completed",
            "result": {"status": status, "outputs": item.get("outputs")},
            "providerExecuted": True,
        }
    )
    return parts


def _done_computer(state: _Stream, index: int, item: Any) -> Gen[list[Part]]:
    yield from ()
    state.tool_calls.pop(index, None)
    name = state.names.get_custom_name("computer_use")
    return [
        {"type": "tool-params-end", "id": item["id"]},
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
            "isFailure": False,
            "result": {"status": P.or_default(item.get("status"), "completed")},
        },
    ]


def _done_file_search(state: _Stream, index: int, item: Any) -> Gen[list[Part]]:
    yield from ()
    state.tool_calls.pop(index, None)
    return [
        {
            "type": "tool-result",
            "id": item["id"],
            "name": state.names.get_custom_name("file_search"),
            "isFailure": item["status"] != "completed",
            "result": {
                "status": item["status"],
                "queries": item["queries"],
                "results": item.get("results"),
            },
            "providerExecuted": True,
        }
    ]


def _done_function(state: _Stream, index: int, item: Any) -> Gen[list[Part]]:
    call = state.tool_calls.pop(index, None)
    if call is not None and call.function_emitted:
        return []
    state.has_tool_calls = True
    name = item["name"]
    params = yield from function_params(
        state.options, name, item["arguments"], "makeStreamResponse"
    )
    return [
        {"type": "tool-params-end", "id": item["call_id"]},
        {
            "type": "tool-call",
            "id": item["call_id"],
            "name": name,
            "params": params,
            "metadata": {KEY: item_metadata(item.get("id"))},
        },
    ]


def _done_image_generation(state: _Stream, _index: int, item: Any) -> Gen[list[Part]]:
    yield from ()
    status = P.or_default(item.get("status"), "completed")
    result = item.get("result")
    return [
        {
            "type": "tool-result",
            "id": item["id"],
            "name": state.names.get_custom_name("image_generation"),
            "isFailure": status != "completed",
            "result": {"result": result}
            if status == "completed"
            else {"status": status, "result": result},
            "providerExecuted": True,
        }
    ]


def _done_local_shell(state: _Stream, _index: int, item: Any) -> Gen[list[Part]]:
    yield from ()
    return [
        {
            "type": "tool-call",
            "id": item["call_id"],
            "name": state.names.get_custom_name("local_shell"),
            "params": {"action": item["action"]},
            "metadata": {KEY: item_metadata(item.get("id"))},
        }
    ]


def _done_mcp_call(state: _Stream, _index: int, item: Any) -> Gen[list[Part]]:
    request = item.get("approval_request_id")
    id = item["id"]
    if request is not None:
        id = state.stream_approvals.get(request, state.approvals.get(request, id))
    name, params = yield from mcp_call(state.names, item["arguments"], "makeStreamResponse")
    return [
        {"type": "tool-call", "id": id, "name": name, "params": params, "providerExecuted": True},
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


def _done_mcp_approval(state: _Stream, _index: int, item: Any) -> Gen[list[Part]]:
    id: str = yield from state.ids.generate_id()
    approval = P.or_default(item.get("approval_request_id"), item["id"])
    state.stream_approvals[approval] = id
    name, params = yield from mcp_call(state.names, item["arguments"], "makeStreamResponse")
    return [
        {"type": "tool-call", "id": id, "name": name, "params": params, "providerExecuted": True},
        {"type": "tool-approval-request", "approvalId": approval, "toolCallId": id},
    ]


def _done_message(state: _Stream, _index: int, item: Any) -> Gen[list[Part]]:
    yield from ()
    metadata: dict[str, Any] = {}
    if state.annotations:
        metadata["annotations"] = list(state.annotations)
    metadata.update(item_metadata(item["id"]))
    return [{"type": "text-end", "id": item["id"], "metadata": {KEY: metadata}}]


def _done_reasoning(state: _Stream, _index: int, item: Any) -> Gen[list[Part]]:
    yield from ()
    item_id = item["id"]
    reasoning = state.reasoning_part(item_id, item.get("encrypted_content"))
    parts = [
        _reasoning_end(item_id, index, reasoning.encrypted_content)
        for index, status in sorted(reasoning.summary_parts.items())
        if status in ("active", "can-conclude")
    ]
    state.reasoning.pop(item_id, None)
    return parts


def _done_shell(state: _Stream, index: int, item: Any) -> Gen[list[Part]]:
    yield from ()
    state.tool_calls.pop(index, None)
    return [
        {
            "type": "tool-call",
            "id": P.or_default(item.get("id"), item["call_id"]),
            "name": state.names.get_custom_name("shell"),
            "params": {"action": item["action"]},
            "metadata": {KEY: item_metadata(item.get("id"))},
        }
    ]


def _done_web_search(state: _Stream, index: int, item: Any) -> Gen[list[Part]]:
    yield from ()
    state.tool_calls.pop(index, None)
    tool = state.web_search
    name = state.names.get_custom_name("web_search" if tool is None else tool.name)
    action: dict[str, Any] = {"action": item["action"]} if "action" in item else {}
    parts: list[Part] = []
    if tool is not None and tool.name == "OpenAiWebSearch":
        parts.append(
            {
                "type": "tool-call",
                "id": item["id"],
                "name": name,
                "params": action,
                "providerExecuted": True,
            }
        )
    result: dict[str, Any] = {**action}
    result["status"] = item["status"]
    parts.append(
        {
            "type": "tool-result",
            "id": item["id"],
            "name": name,
            "isFailure": item["status"] != "completed",
            "result": result,
            "providerExecuted": True,
        }
    )
    return parts


_DONE: dict[str, Callable[[_Stream, int, Any], Gen[list[Part]]]] = {
    "apply_patch_call": _done_apply_patch,
    "code_interpreter_call": _done_code_interpreter,
    "computer_call": _done_computer,
    "file_search_call": _done_file_search,
    "function_call": _done_function,
    "image_generation_call": _done_image_generation,
    "local_shell_call": _done_local_shell,
    "mcp_call": _done_mcp_call,
    "mcp_approval_request": _done_mcp_approval,
    "message": _done_message,
    "reasoning": _done_reasoning,
    "shell_call": _done_shell,
    "web_search_call": _done_web_search,
}

_EVENTS: dict[str, Callable[[_Stream, Any], Gen[list[Part]]]] = {
    "response.created": _Stream.created,
    "error": _Stream.error,
    "response.completed": _Stream.completed,
    "response.incomplete": _Stream.completed,
    "response.failed": _Stream.failed,
    "response.output_item.added": _Stream.item_added,
    "response.output_item.done": _Stream.item_done,
    "response.output_text.delta": _Stream.text_delta,
    "response.output_text.annotation.added": _Stream.annotation_added,
    "response.reasoning_summary_part.added": _Stream.summary_added,
    "response.reasoning_summary_part.done": _Stream.summary_done,
    "response.reasoning_summary_text.delta": _Stream.summary_delta,
    "response.function_call_arguments.delta": _Stream.arguments_delta,
    "response.function_call_arguments.done": _Stream.arguments_done,
    "response.code_interpreter_call_code.delta": _Stream.code_delta,
    "response.code_interpreter_call_code.done": _Stream.code_done,
    "response.apply_patch_call_operation_diff.delta": _Stream.diff_delta,
    "response.apply_patch_call_operation_diff.done": _Stream.diff_done,
    "response.image_generation_call.partial_image": _Stream.partial_image,
}
"""The events this library reads; others have no parts."""


def make_stream_response(
    options: lm.ProviderOptions,
    events: Stream[W.ResponseStreamEvent, AiError],
    response: HttpClientResponse,
    names: NameMapper,
    ids: IdService,
    *,
    concludes_summaries: bool,
) -> Stream[Part, AiError, Any]:
    state = _Stream(options, response, names, ids, concludes_summaries)
    return events.map_effect(state.event).flatten_iterable()
