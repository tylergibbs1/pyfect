"""Streamed OpenRouter chat completion chunks as encoded response parts
(Effect's ``makeStreamResponse`` in ``OpenRouterLanguageModel``).

Reasoning and text deltas open their part on first use; a tool call
ends as soon as its streamed arguments parse as JSON. The chunk carrying
``usage`` (the last) flushes the rest: with a ``tool-calls`` finish the
unfinished calls are sent (unparseable arguments as ``{}``), then the open
reasoning and text parts end and the finish part follows. Reasoning
details are accumulated (consecutive text details merged) and replayed on
the reasoning end and the first tool call."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

import pyfect as fx
from pyfect import date_time
from pyfect._core import Effect
from pyfect.ai import _provider as P
from pyfect.ai.ai_error import AiError, InvalidOutputError
from pyfect.ai.openrouter import _response as Rs
from pyfect.ai.openrouter._prompt import KEY, MODULE, base64_from_data_url, media_type_of
from pyfect.ai.openrouter.generated import types as GT
from pyfect.ai.response import FinishReason
from pyfect.ai.tool import unsafe_secure_json_parse
from pyfect.http.response import HttpClientResponse
from pyfect.stream import Stream

type Part = Rs.Part
type Detail = dict[str, Any]


@dataclass
class _ToolCall:
    id: str
    name: str
    params: P.TextBuffer


def _invalid(description: str) -> AiError:
    reason = InvalidOutputError(description=description)
    return AiError(module=MODULE, method="makeStreamResponse", reason=reason)


def _parsed(text: str) -> tuple[bool, object]:
    try:
        return True, unsafe_secure_json_parse(text)
    except ValueError:
        return False, None


@dataclass
class _Stream:
    response: HttpClientResponse
    max_chars: int
    text_started: bool = False
    reasoning_started: bool = False
    metadata_emitted: bool = False
    details_attached: bool = False
    finish_reason: FinishReason = "other"
    reasoning_id: str = ""
    text_id: str = ""
    total_tool_calls: int = 0
    tool_calls: dict[int, _ToolCall] = field(default_factory=dict[int, _ToolCall])
    details: list[Detail] = field(default_factory=list[Detail])
    file_annotations: list[Any] = field(default_factory=list[Any])
    usage: dict[str, Any] = field(default_factory=lambda: {"inputTokens": {}, "outputTokens": {}})

    def _accumulated(self) -> list[Detail]:
        return [dict(detail) for detail in self.details]

    def _details_metadata(self) -> dict[str, Any] | None:
        return {KEY: {"reasoningDetails": self._accumulated()}} if self.details else None

    def _call_metadata(self) -> dict[str, Any] | None:
        if self.details_attached:
            return None
        self.details_attached = True
        return {KEY: {"reasoningDetails": self._accumulated()}}

    def _reasoning(self, delta: str, metadata: object) -> Rs.Gen[list[Part]]:
        parts: list[Part] = []
        if not self.reasoning_started:
            self.reasoning_id = yield from Rs.generate_id()
            parts.append({"type": "reasoning-start", "id": self.reasoning_id, "metadata": metadata})
            self.reasoning_started = True
        parts.append(
            {
                "type": "reasoning-delta",
                "id": self.reasoning_id,
                "delta": delta,
                "metadata": metadata,
            }
        )
        return parts

    def _accumulate(self, details: GT.ChatStreamReasoningDetails) -> None:
        for detail in details:
            last = self.details[-1] if self.details else None
            if (
                detail["type"] == "reasoning.text"
                and last is not None
                and last["type"] == detail["type"]
            ):
                last["text"] = P.or_default(last.get("text"), "") + P.or_default(
                    detail.get("text"), ""
                )
                for key in ("signature", "format"):
                    value = last.get(key)
                    last[key] = value if value is not None else detail.get(key)
            else:
                self.details.append(dict(detail))

    def _reasoning_deltas(self, delta: GT.ChatStreamDelta) -> Rs.Gen[list[Part]]:
        parts: list[Part] = []
        details = delta.get("reasoning_details")
        if details:
            self._accumulate(details)
            metadata = {KEY: {"reasoningDetails": [dict(detail) for detail in details]}}
            for detail in details:
                match detail["type"]:
                    case "reasoning.text":
                        text = detail.get("text")
                        if text is not None:
                            parts.extend((yield from self._reasoning(text, metadata)))
                    case "reasoning.summary":
                        parts.extend((yield from self._reasoning(detail["summary"], metadata)))
                    case "reasoning.encrypted":
                        parts.extend((yield from self._reasoning("[REDACTED]", metadata)))
                    case _:
                        pass
        elif delta.get("reasoning") is not None:
            parts.extend((yield from self._reasoning(str(delta.get("reasoning")), None)))
        return parts

    def _text(self, content: str) -> Rs.Gen[list[Part]]:
        parts: list[Part] = []
        if self.reasoning_started and not self.text_started:
            parts.append(
                {
                    "type": "reasoning-end",
                    "id": self.reasoning_id,
                    "metadata": self._details_metadata(),
                }
            )
            self.reasoning_started = False
        if not self.text_started:
            self.text_id = yield from Rs.generate_id()
            parts.append({"type": "text-start", "id": self.text_id})
            self.text_started = True
        parts.append({"type": "text-delta", "id": self.text_id, "delta": content})
        return parts

    def _tool_deltas(self, calls: Sequence[GT.ChatStreamToolCall]) -> Rs.Gen[list[Part]]:
        parts: list[Part] = []
        for call in calls:
            index = int(call["index"])
            active = self.tool_calls.get(index)
            function = call.get("function") or {}
            delta = P.or_default(function.get("arguments"), "")
            if active is None:
                if call.get("type") != "function":
                    message = "Received tool call delta that was not of type: 'function'"
                    return (yield from fx.fail(_invalid(message)))
                id = call.get("id")
                if id is None:
                    message = "Received tool call delta without a tool call identifier"
                    return (yield from fx.fail(_invalid(message)))
                name = function.get("name")
                if name is None:
                    message = "Received tool call delta without a tool call name"
                    return (yield from fx.fail(_invalid(message)))
                active = _ToolCall(id, name, P.TextBuffer("", self.max_chars))
                self.tool_calls[index] = active
                parts.append({"type": "tool-params-start", "id": id, "name": name})
            if not active.params.add(delta):
                return (
                    yield from fx.fail(P.too_large(MODULE, "makeStreamResponse", self.max_chars))
                )
            if delta:
                parts.append({"type": "tool-params-delta", "id": active.id, "delta": delta})
            ok, params = _parsed(active.params.text())
            if not ok:
                continue
            parts.append({"type": "tool-params-end", "id": active.id})
            parts.append(
                {
                    "type": "tool-call",
                    "id": active.id,
                    "name": active.name,
                    "params": params,
                    "metadata": self._call_metadata(),
                }
            )
            self.total_tool_calls += 1
            del self.tool_calls[index]
        return parts

    def _flush(self, chunk: GT.ChatStreamChunk) -> list[Part]:
        parts: list[Part] = []
        encrypted = any(
            detail["type"] == "reasoning.encrypted" and detail.get("data")
            for detail in self.details
        )
        if self.total_tool_calls > 0 and encrypted and self.finish_reason == "stop":
            # Gemini 3 answers `stop` after a tool call with a thought
            # signature, though it expects the call's result.
            self.finish_reason = "tool-calls"
        if self.finish_reason == "tool-calls":
            for index in sorted(self.tool_calls):
                call = self.tool_calls[index]
                ok, params = _parsed(call.params.text())
                parts.append(
                    {
                        "type": "tool-call",
                        "id": call.id,
                        "name": call.name,
                        "params": params if ok else {},
                        "metadata": self._call_metadata(),
                    }
                )
        if self.reasoning_started:
            parts.append(
                {
                    "type": "reasoning-end",
                    "id": self.reasoning_id,
                    "metadata": self._details_metadata(),
                }
            )
        if self.text_started:
            parts.append({"type": "text-end", "id": self.text_id})
        metadata: dict[str, Any] = {}
        if chunk.get("system_fingerprint") is not None:
            metadata["systemFingerprint"] = chunk.get("system_fingerprint")
        metadata["usage"] = chunk.get("usage")
        metadata.update(Rs.provider_of(chunk))
        if self.file_annotations:
            metadata["annotations"] = list(self.file_annotations)
        parts.append(
            {
                "type": "finish",
                "reason": self.finish_reason,
                "usage": {key: dict(value) for key, value in self.usage.items()},
                "response": P.response_details(self.response),
                "metadata": {KEY: metadata},
            }
        )
        return parts

    def _choice(self, choice: GT.ChatStreamChoice) -> Rs.Gen[list[Part]]:
        reason = choice.get("finish_reason")
        if reason is not None:
            self.finish_reason = Rs.resolve_finish_reason(reason)
        delta = choice["delta"]
        parts = yield from self._reasoning_deltas(delta)
        content = delta.get("content")
        if content is not None:
            parts.extend((yield from self._text(content)))
        for annotation in delta.get("annotations") or []:
            if annotation["type"] == "url_citation":
                parts.append(Rs.url_source(annotation))
            elif annotation["type"] == "file":
                self.file_annotations.append(annotation)
        calls = delta.get("tool_calls")
        if calls is not None:
            parts.extend((yield from self._tool_deltas(calls)))
        for image in delta.get("images") or []:
            url = image["image_url"]["url"]
            parts.append(
                {
                    "type": "file",
                    "mediaType": media_type_of(url, "image/jpeg"),
                    "data": base64_from_data_url(url),
                }
            )
        return parts

    def _chunk(self, chunk: GT.ChatStreamChunk) -> Rs.Gen[list[Part]]:
        parts: list[Part] = []
        if "error" in chunk:
            self.finish_reason = "error"
            parts.append({"type": "error", "error": chunk["error"]})
        if not self.metadata_emitted:
            now = yield from date_time.now()
            parts.append(
                {
                    "type": "response-metadata",
                    "id": chunk["id"],
                    "modelId": chunk["model"],
                    "timestamp": date_time.format_iso(now),
                }
            )
            self.metadata_emitted = True
        raw_usage = chunk.get("usage")
        if raw_usage is not None:
            self.usage = Rs.usage(raw_usage)
        if chunk["choices"]:
            parts.extend((yield from self._choice(chunk["choices"][0])))
        if raw_usage is not None:
            parts.extend(self._flush(chunk))
        return parts

    def event(self, chunk: GT.ChatStreamChunk) -> Effect[list[Part], AiError, Any]:
        return fx.gen(lambda: self._chunk(chunk))


def _without_none(part: Mapping[str, Any]) -> Part:
    """A part with an absent ``metadata`` left out (Effect's ``undefined``)."""
    return {key: value for key, value in part.items() if not (key == "metadata" and value is None)}


def make_stream_response(
    chunks: Stream[GT.ChatStreamChunk, AiError], response: HttpClientResponse, max_chars: int
) -> Stream[Part, AiError, Any]:
    """``max_chars`` bounds each tool call's streamed arguments."""
    state = _Stream(response, max_chars)
    return chunks.map_effect(state.event).flatten_iterable().map(_without_none)
