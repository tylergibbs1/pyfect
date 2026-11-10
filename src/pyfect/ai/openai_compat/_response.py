"""A chat completion, or its streamed chunks, as encoded response parts
(Effect's ``makeResponse`` and ``makeStreamResponse`` in
``@effect/ai-openai-compat``)."""

from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pyfect as fx
from pyfect import date_time
from pyfect._core import Effect
from pyfect.ai import _provider as P
from pyfect.ai import _provider_tools as PT
from pyfect.ai import language_model as lm
from pyfect.ai import tool as T
from pyfect.ai.ai_error import AiError, ToolParameterValidationError
from pyfect.ai.openai_compat import _schema as W
from pyfect.ai.openai_compat._prompt import KEY, MODULE
from pyfect.ai.response import FinishReason
from pyfect.ai.tool import NameMapper, unsafe_secure_json_parse
from pyfect.http.response import HttpClientResponse
from pyfect.stream import Stream

type Part = dict[str, Any]
type Gen[A] = Generator[Effect[Any, Any, Any], Any, A]

_FINISH_REASONS: dict[str, FinishReason] = {
    "content_filter": "content-filter",
    "function_call": "tool-calls",
    "length": "length",
    "stop": "stop",
    "tool_calls": "tool-calls",
}
_SERVICE_TIERS = frozenset({"default", "auto", "flex", "scale", "priority"})


def resolve_finish_reason(reason: str | None, has_tool_calls: bool) -> FinishReason:
    if reason is None:
        return "tool-calls" if has_tool_calls else "stop"
    resolved = _FINISH_REASONS.get(reason)
    if resolved is None:
        return "tool-calls" if has_tool_calls else "unknown"
    return resolved


def _timestamp(created: int) -> str:
    return date_time.format_iso(datetime.fromtimestamp(created, UTC))


def _service_tier(tier: str | None) -> str | None:
    return tier if tier in _SERVICE_TIERS else None


def _finish_metadata(tier: str | None) -> dict[str, Any]:
    if tier is None:
        return {}
    return {"metadata": {KEY: {"serviceTier": _service_tier(tier)}}}


def usage(raw: W.Usage | None) -> dict[str, Any]:
    if raw is None:
        return {"inputTokens": {}, "outputTokens": {}}
    details: dict[str, Any] = {**raw}
    cached = P.obj(details.get("prompt_tokens_details")).get("cached_tokens")
    reasoning = P.obj(details.get("completion_tokens_details")).get("reasoning_tokens")
    cached = cached if isinstance(cached, int | float) else 0
    reasoning = reasoning if isinstance(reasoning, int | float) else 0
    prompt, completion = raw["prompt_tokens"], raw["completion_tokens"]
    return {
        "inputTokens": {"uncached": prompt - cached, "total": prompt, "cacheRead": cached},
        "outputTokens": {
            "total": completion,
            "text": completion - reasoning,
            "reasoning": reasoning,
        },
    }


def _reasoning_field(message: W.Message) -> str | None:
    if message.get("reasoning") is not None:
        return "reasoning"
    if message.get("reasoning_content") is not None:
        return "reasoning_content"
    return None


def _parse_params(name: str, text: str, method: str) -> Effect[object, AiError]:
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


def _call_metadata(item_id: str | None, extra: object) -> dict[str, Any]:
    metadata: dict[str, Any] = {}
    if item_id is not None:
        metadata["itemId"] = item_id
    if extra is not None:
        metadata["extraContent"] = extra
    return {KEY: metadata}


def _tool_call(
    options: lm.ProviderOptions,
    names: NameMapper,
    completion: W.ChatCompletion,
    index: int,
    call: W.ToolCall,
    *,
    codecs: T.CodecTransformer,
) -> Gen[Part]:
    function = call.get("function") or {}
    name = names.get_custom_name(P.or_default(function.get("name"), "unknown_tool"))
    raw = yield from _parse_params(
        name, P.or_default(function.get("arguments"), "{}"), "makeResponse"
    )
    params = yield from PT.transform_params(MODULE, options, name, raw, transformer=codecs)
    return {
        "type": "tool-call",
        "id": P.or_default(call.get("id"), f"{completion['id']}_tool_{index}"),
        "name": name,
        "params": params,
        "metadata": _call_metadata(call.get("id"), call.get("extra_content")),
    }


def _make_response(
    options: lm.ProviderOptions,
    completion: W.ChatCompletion,
    response: HttpClientResponse,
    names: NameMapper,
    codecs: T.CodecTransformer,
) -> Gen[list[Part]]:
    parts: list[Part] = [
        {
            "type": "response-metadata",
            "id": completion["id"],
            "modelId": completion["model"],
            "timestamp": _timestamp(completion["created"]),
        }
    ]
    choice = completion["choices"][0] if completion["choices"] else None
    message = None if choice is None else choice.get("message")
    has_tool_calls = False
    if message is not None:
        field_name = _reasoning_field(message)
        reasoning = None if field_name is None else message.get(field_name)
        if isinstance(reasoning, str) and reasoning:
            parts.append(
                {
                    "type": "reasoning",
                    "text": reasoning,
                    "metadata": {KEY: {"reasoningField": field_name}},
                }
            )
        content = message.get("content")
        if content:
            parts.append({"type": "text", "text": content})
        for index, call in enumerate(message.get("tool_calls") or []):
            parts.append(
                (yield from _tool_call(options, names, completion, index, call, codecs=codecs))
            )
            has_tool_calls = True
    reason = None if choice is None else choice.get("finish_reason")
    parts.append(
        {
            "type": "finish",
            "reason": resolve_finish_reason(reason, has_tool_calls),
            "usage": usage(completion.get("usage")),
            "response": P.response_details(response),
            **_finish_metadata(completion.get("service_tier")),
        }
    )
    return parts


def make_response(
    options: lm.ProviderOptions,
    completion: W.ChatCompletion,
    response: HttpClientResponse,
    names: NameMapper,
    codecs: T.CodecTransformer,
) -> Effect[list[Part], AiError, Any]:
    """``codecs`` makes the codecs decoding the tool calls' parameters."""
    return fx.gen(lambda: _make_response(options, completion, response, names, codecs))


@dataclass
class _ToolCall:
    id: str
    name: str
    arguments: P.TextBuffer
    extra_content: object


def _record_order[A](items: dict[int, A]) -> list[A]:
    """The values in JavaScript's ``Object.values`` order: non-negative
    integer keys ascending, then the rest as inserted."""
    indexes = sorted(k for k in items if k >= 0)
    return [items[k] for k in indexes] + [v for k, v in items.items() if k < 0]


@dataclass
class _Stream:
    options: lm.ProviderOptions
    response: HttpClientResponse
    names: NameMapper
    codecs: T.CodecTransformer
    max_chars: int
    too_large: bool = False
    service_tier: str | None = None
    usage: W.Usage | None = None
    finish_reason: str | None = None
    metadata_emitted: bool = False
    text_started: bool = False
    text_id: str = ""
    reasoning_started: bool = False
    reasoning_id: str = ""
    has_tool_calls: bool = False
    tool_calls: dict[int, _ToolCall] = field(default_factory=dict[int, _ToolCall])

    def _item(self, id: str) -> dict[str, Any]:
        return {KEY: {"itemId": id}}

    def done(self) -> Gen[list[Part]]:
        parts: list[Part] = []
        if self.reasoning_started:
            parts.append(
                {
                    "type": "reasoning-end",
                    "id": self.reasoning_id,
                    "metadata": self._item(self.reasoning_id),
                }
            )
        if self.text_started:
            parts.append(
                {"type": "text-end", "id": self.text_id, "metadata": self._item(self.text_id)}
            )
        for call in _record_order(self.tool_calls):
            raw = yield from _parse_params(
                call.name, call.arguments.text() or "{}", "makeStreamResponse"
            )
            params = yield from PT.transform_params(
                MODULE, self.options, call.name, raw, transformer=self.codecs
            )
            parts.append({"type": "tool-params-end", "id": call.id})
            parts.append(
                {
                    "type": "tool-call",
                    "id": call.id,
                    "name": call.name,
                    "params": params,
                    "metadata": _call_metadata(call.id, call.extra_content),
                }
            )
            self.has_tool_calls = True
        parts.append(
            {
                "type": "finish",
                "reason": resolve_finish_reason(self.finish_reason, self.has_tool_calls),
                "usage": usage(self.usage),
                "response": P.response_details(self.response),
                **_finish_metadata(self.service_tier),
            }
        )
        return parts

    def _reasoning(self, field_name: str, delta: str) -> list[Part]:
        parts: list[Part] = []
        if not self.reasoning_started:
            self.reasoning_started = True
            metadata = {KEY: {"itemId": self.reasoning_id, "reasoningField": field_name}}
            parts.append({"type": "reasoning-start", "id": self.reasoning_id, "metadata": metadata})
        parts.append({"type": "reasoning-delta", "id": self.reasoning_id, "delta": delta})
        return parts

    def _text(self, delta: str) -> list[Part]:
        parts: list[Part] = []
        if self.reasoning_started:
            self.reasoning_started = False
            parts.append(
                {
                    "type": "reasoning-end",
                    "id": self.reasoning_id,
                    "metadata": self._item(self.reasoning_id),
                }
            )
        if not self.text_started:
            self.text_started = True
            parts.append(
                {"type": "text-start", "id": self.text_id, "metadata": self._item(self.text_id)}
            )
        parts.append({"type": "text-delta", "id": self.text_id, "delta": delta})
        return parts

    def _tool_deltas(self, chunk_id: str, deltas: list[W.ToolCall]) -> list[Part]:
        parts: list[Part] = []
        self.has_tool_calls = self.has_tool_calls or len(deltas) > 0
        for position, delta in enumerate(deltas):
            index = delta.get("index")
            if index is None:
                index = position
            active = self.tool_calls.get(index)
            function = delta.get("function") or {}
            id = active.id if active is not None else delta.get("id")
            if id is None:
                id = f"{chunk_id}_tool_{index}"
            provider_name = function.get("name")
            if provider_name is not None:
                name = self.names.get_custom_name(provider_name)
            elif active is not None:
                name = active.name
            else:
                name = self.names.get_custom_name("unknown_tool")
            arguments = function.get("arguments") or ""
            if active is None:
                buffer = P.TextBuffer("", self.max_chars)
                self.too_large = self.too_large or not buffer.add(arguments)
                self.tool_calls[index] = _ToolCall(id, name, buffer, delta.get("extra_content"))
                parts.append({"type": "tool-params-start", "id": id, "name": name})
            else:
                active.name = name
                self.too_large = self.too_large or not active.arguments.add(arguments)
                if delta.get("extra_content") is not None:
                    active.extra_content = delta.get("extra_content")
            if arguments:
                parts.append({"type": "tool-params-delta", "id": id, "delta": arguments})
        return parts

    def chunk(self, chunk: W.ChatCompletion) -> list[Part]:
        parts: list[Part] = []
        if "service_tier" in chunk:
            self.service_tier = chunk["service_tier"]
        if chunk.get("usage") is not None:
            self.usage = chunk.get("usage")
        if not self.metadata_emitted:
            self.metadata_emitted = True
            self.text_id = f"{chunk['id']}_message"
            self.reasoning_id = f"{chunk['id']}_reasoning"
            parts.append(
                {
                    "type": "response-metadata",
                    "id": chunk["id"],
                    "modelId": chunk["model"],
                    "timestamp": _timestamp(chunk["created"]),
                }
            )
        if not chunk["choices"]:
            return parts
        choice = chunk["choices"][0]
        delta = choice.get("delta")
        if delta is not None:
            field_name = _reasoning_field(delta)
            reasoning = None if field_name is None else delta.get(field_name)
            if field_name is not None and isinstance(reasoning, str) and reasoning:
                parts.extend(self._reasoning(field_name, reasoning))
            content = delta.get("content")
            if content:
                parts.extend(self._text(content))
            calls = delta.get("tool_calls")
            if calls is not None:
                parts.extend(self._tool_deltas(chunk["id"], calls))
        if choice.get("finish_reason") is not None:
            self.finish_reason = choice.get("finish_reason")
        return parts

    def event(self, event: W.StreamEvent) -> Effect[list[Part], AiError, Any]:
        if event == "[DONE]":
            return fx.gen(self.done)
        if isinstance(event, W.UnknownEvent):
            return fx.succeed([])
        parts = self.chunk(event)
        if self.too_large:
            return fx.fail(P.too_large(MODULE, "makeStreamResponse", self.max_chars))
        return fx.succeed(parts)


def make_stream_response(
    options: lm.ProviderOptions,
    events: Stream[W.StreamEvent, AiError],
    response: HttpClientResponse,
    names: NameMapper,
    max_chars: int,
    *,
    codecs: T.CodecTransformer,
) -> Stream[Part, AiError, Any]:
    """``max_chars`` bounds each tool call's streamed parameters; ``codecs``
    makes the codecs decoding them."""
    state = _Stream(options, response, names, codecs, max_chars)
    return events.map_effect(state.event).flatten_iterable()
