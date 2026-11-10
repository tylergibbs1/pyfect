"""Streamed message events as encoded stream parts (Effect's
``makeStreamResponse``)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

import pyfect as fx
from pyfect._core import Effect
from pyfect.ai import _provider as P
from pyfect.ai import language_model as lm
from pyfect.ai.ai_error import AiError, ToolParameterValidationError
from pyfect.ai.anthropic import _schema as W
from pyfect.ai.anthropic._response import (
    Gen,
    Part,
    ServerResults,
    caller_metadata,
    citable_documents,
    citation_source,
    now_iso,
    resolve_finish_reason,
    transform_params,
    usage_part,
)
from pyfect.ai.response import FinishReason
from pyfect.ai.tool import NameMapper, unsafe_secure_json_parse
from pyfect.http.response import HttpClientResponse
from pyfect.stream import Stream

_SERVER_CALLS = frozenset(
    {
        "code_execution",
        "bash_code_execution",
        "text_editor_code_execution",
        "web_fetch",
        "web_search",
    }
)
_SEARCH_CALLS = frozenset({"tool_search_tool_bm25", "tool_search_tool_regex"})


@dataclass
class _ToolBlock:
    id: str
    name: str
    params: P.TextBuffer
    first_delta: bool
    provider_name: str | None = None
    provider_executed: bool | None = None
    caller: dict[str, Any] | None = None


@dataclass
class _Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read: int = 0
    cache_write: int = 0


@dataclass
class _State:
    options: lm.ProviderOptions
    response: HttpClientResponse
    results: ServerResults
    max_chars: int
    container: Any = None
    context_management: Any = None
    finish_reason: FinishReason = "unknown"
    stop_sequence: str | None = None
    raw_usage: dict[str, Any] | None = None
    usage: _Usage = field(default_factory=_Usage)
    blocks: dict[int, str | _ToolBlock] = field(default_factory=dict[int, "str | _ToolBlock"])
    block_type: str | None = None

    @property
    def names(self) -> NameMapper:
        return self.results.names

    # message events ---------------------------------------------------------------------

    def message_start(self, event: W.MessageStartEvent) -> Gen[list[Part]]:
        message = event["message"]
        usage = message["usage"]
        self.raw_usage = dict(usage)
        self.usage.input_tokens = usage["input_tokens"]
        self.usage.cache_read = usage.get("cache_read_input_tokens") or 0
        self.usage.cache_write = usage.get("cache_creation_input_tokens") or 0
        if message.get("container") is not None:
            self.container = message.get("container")
        if message["stop_sequence"] is not None:
            self.stop_sequence = message["stop_sequence"]
        if message["stop_reason"] is not None:
            self.finish_reason = resolve_finish_reason(message["stop_reason"])
        timestamp = yield from now_iso()
        parts: list[Part] = [
            {
                "type": "response-metadata",
                "id": message["id"],
                "modelId": message["model"],
                "timestamp": timestamp,
            }
        ]
        for block in message["content"]:
            if block["type"] == "tool_use":
                parts.extend((yield from self._prepopulated_tool_use(block)))
        return parts

    def _prepopulated_tool_use(self, block: W.ContentBlock) -> Gen[list[Part]]:
        name = self.names.get_custom_name(block["name"])
        params = yield from transform_params(self.options, name, block.get("input"))
        call: Part = {"type": "tool-call", "id": block["id"], "name": name, "params": params}
        caller = caller_metadata(block)
        if caller is not None:
            call["metadata"] = {"anthropic": {"caller": caller}}
        return [
            {"type": "tool-params-start", "id": block["id"], "name": name},
            {
                "type": "tool-params-delta",
                "id": block["id"],
                "delta": P.dumps(P.obj(block.get("input"))),
            },
            {"type": "tool-params-end", "id": block["id"]},
            call,
        ]

    def message_delta(self, event: W.MessageDeltaEvent) -> list[Part]:
        usage = event["usage"]
        self.raw_usage = {**(self.raw_usage or {}), **usage}
        if usage.get("input_tokens") is not None:
            self.usage.input_tokens = cast("int", usage.get("input_tokens"))
        self.usage.output_tokens = usage["output_tokens"]
        if usage.get("cache_read_input_tokens") is not None:
            self.usage.cache_read = cast("int", usage.get("cache_read_input_tokens"))
        if usage.get("cache_creation_input_tokens") is not None:
            self.usage.cache_write = cast("int", usage.get("cache_creation_input_tokens"))
        delta = event["delta"]
        if delta.get("container") is not None:
            self.container = delta.get("container")
        if event.get("context_management") is not None:
            self.context_management = event.get("context_management")
        if delta["stop_reason"] is not None:
            self.finish_reason = resolve_finish_reason(delta["stop_reason"])
        if delta["stop_sequence"] is not None:
            self.stop_sequence = delta["stop_sequence"]
        return []

    def message_stop(self) -> list[Part]:
        usage = self.usage
        return [
            {
                "type": "finish",
                "reason": self.finish_reason,
                "usage": usage_part(
                    usage.input_tokens, usage.output_tokens, usage.cache_read, usage.cache_write
                ),
                "response": P.response_details(self.response),
                "metadata": {
                    "anthropic": {
                        "container": self.container,
                        "contextManagement": self.context_management,
                        "stopSequence": self.stop_sequence,
                        "usage": self.raw_usage,
                    }
                },
            }
        ]

    # content blocks ---------------------------------------------------------------------

    def _tool_use_start(self, index: int, block: W.ContentBlock) -> list[Part]:
        input = P.obj(block.get("input"))
        initial = P.dumps(input) if input else ""
        name = self.names.get_custom_name(block["name"])
        self.blocks[index] = _ToolBlock(
            block["id"],
            name,
            P.TextBuffer(initial, self.max_chars),
            len(initial) > 0,
            caller=caller_metadata(block),
        )
        return [{"type": "tool-params-start", "id": block["id"], "name": name}]

    def _server_tool_use_start(self, index: int, block: W.ContentBlock) -> list[Part]:
        provider = block["name"]
        if provider in _SERVER_CALLS:
            custom = "code_execution" if provider.endswith("_code_execution") else provider
        elif provider in _SEARCH_CALLS:
            self.results.search_calls[block["id"]] = provider
            custom = provider
        else:
            return []
        name = self.names.get_custom_name(custom)
        self.blocks[index] = _ToolBlock(
            block["id"], name, P.TextBuffer("", self.max_chars), True, provider, True
        )
        return [
            {"type": "tool-params-start", "id": block["id"], "name": name, "providerExecuted": True}
        ]

    def content_block_start(  # noqa: PLR0911
        self, event: W.ContentBlockStartEvent
    ) -> Gen[list[Part]]:
        block = event["content_block"]
        index = event["index"]
        kind = block["type"]
        self.block_type = kind
        match kind:
            case "text":
                self.blocks[index] = "text"
                return [{"type": "text-start", "id": str(index)}]
            case "thinking":
                self.blocks[index] = "reasoning"
                return [{"type": "reasoning-start", "id": str(index)}]
            case "redacted_thinking":
                self.blocks[index] = "reasoning"
                info = {"type": "redacted_thinking", "redactedData": block.get("data")}
                return [
                    {
                        "type": "reasoning-start",
                        "id": str(index),
                        "metadata": {"anthropic": {"info": info}},
                    }
                ]
            case "tool_use":
                return self._tool_use_start(index, block)
            case "server_tool_use":
                return self._server_tool_use_start(index, block)
            case "mcp_tool_use":
                return [self.results.mcp_call(block)]
            case "fallback":
                timestamp = yield from now_iso()
                return [
                    {
                        "type": "response-metadata",
                        "modelId": block["to"]["model"],
                        "timestamp": timestamp,
                        "metadata": {"anthropic": {"fallback": block}},
                    }
                ]
            case _:
                parts = yield from self.results.result_parts(block)
                return parts or []

    def _input_json_delta(self, index: int, delta: str) -> Gen[list[Part]]:
        block = self.blocks.get(index)
        if not delta or not isinstance(block, _ToolBlock):
            return []
        if block.first_delta and block.provider_name in (
            "bash_code_execution",
            "text_editor_code_execution",
        ):
            delta = f'{{"type":{P.dumps(block.provider_name)},{delta[1:]}'
        if not block.params.add(delta):
            error = P.too_large("AnthropicLanguageModel", "makeStreamResponse", self.max_chars)
            return (yield from fx.fail(error))
        block.first_delta = False
        return [{"type": "tool-params-delta", "id": block.id, "delta": delta}]

    def content_block_delta(self, event: W.ContentBlockDeltaEvent) -> Gen[list[Part]]:
        delta = event["delta"]
        index = event["index"]
        match delta.get("type"):
            case "text_delta":
                return [{"type": "text-delta", "id": str(index), "delta": delta.get("text", "")}]
            case "thinking_delta":
                return [
                    {
                        "type": "reasoning-delta",
                        "id": str(index),
                        "delta": delta.get("thinking", ""),
                    }
                ]
            case "signature_delta" if self.block_type == "thinking":
                info = {"type": "thinking", "signature": delta.get("signature")}
                return [
                    {
                        "type": "reasoning-delta",
                        "id": str(index),
                        "delta": "",
                        "metadata": {"anthropic": {"info": info}},
                    }
                ]
            case "input_json_delta":
                return (yield from self._input_json_delta(index, delta.get("partial_json", "")))
            case "citations_delta":
                source = yield from citation_source(delta["citation"], self.results.documents)
                return [] if source is None else [source]
            case _:
                return []

    def _tool_call(self, block: _ToolBlock) -> Gen[Part]:
        text = block.params.text() or "{}"
        if block.provider_name == "code_execution":
            try:
                parsed = P.obj(unsafe_secure_json_parse(text))
                if "code" in parsed and "type" not in parsed:
                    text = P.dumps({"type": "programmatic-tool-call", **parsed})
            except ValueError:
                pass
        try:
            params = unsafe_secure_json_parse(text)
        except ValueError as cause:
            error = AiError(
                module="AnthropicLanguageModel",
                method="makeStreamResponse",
                reason=ToolParameterValidationError(
                    tool_name=block.name,
                    description=f"Failed to securely JSON parse tool parameters: {cause}",
                ),
            )
            return (yield from fx.fail(error))
        if block.provider_executed is not True:
            params = yield from transform_params(self.options, block.name, params)
        part: Part = {"type": "tool-call", "id": block.id, "name": block.name, "params": params}
        if block.provider_executed is not None:
            part["providerExecuted"] = block.provider_executed
        if block.caller is not None:
            part["metadata"] = {"anthropic": {"caller": block.caller}}
        return part

    def content_block_stop(self, event: W.ContentBlockStopEvent) -> Gen[list[Part]]:
        index = event["index"]
        block = self.blocks.pop(index, None)
        self.block_type = None
        if block == "text":
            return [{"type": "text-end", "id": str(index)}]
        if block == "reasoning":
            return [{"type": "reasoning-end", "id": str(index)}]
        if isinstance(block, _ToolBlock):
            end: Part = {"type": "tool-params-end", "id": block.id}
            return [end, (yield from self._tool_call(block))]
        return []

    def event(self, event: W.MessageStreamEvent) -> Gen[list[Part]]:  # noqa: PLR0911
        match event["type"]:
            case "message_start":
                return (yield from self.message_start(event))
            case "message_delta":
                return self.message_delta(event)
            case "message_stop":
                return self.message_stop()
            case "content_block_start":
                return (yield from self.content_block_start(event))
            case "content_block_delta":
                return (yield from self.content_block_delta(event))
            case "content_block_stop":
                return (yield from self.content_block_stop(event))
            case "error":
                return [
                    {
                        "type": "error",
                        "error": event["error"],
                        "metadata": {"anthropic": {"requestId": event["request_id"]}},
                    }
                ]


def make_stream_response(
    options: lm.ProviderOptions,
    events: Stream[W.MessageStreamEvent, AiError],
    response: HttpClientResponse,
    names: NameMapper,
    max_chars: int,
) -> Stream[Part, AiError, Any]:
    """``max_chars`` bounds each tool call's streamed parameters."""
    results = ServerResults(names, citable_documents(options.prompt))
    state = _State(options, response, results, max_chars)

    def convert(event: W.MessageStreamEvent) -> Effect[list[Part], AiError, Any]:
        return fx.gen(lambda: state.event(event))

    return events.map_effect(convert).flatten_iterable()
