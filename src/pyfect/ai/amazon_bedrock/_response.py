"""A Converse response, or a ConverseStream's events, as encoded response
parts (Effect's ``makeResponse`` and ``makeStreamResponse``)."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

import pyfect as fx
from pyfect import date_time
from pyfect import schema as S
from pyfect._core import Effect
from pyfect.ai import _provider as P
from pyfect.ai import language_model as lm
from pyfect.ai import telemetry as T
from pyfect.ai import tool as Tl
from pyfect.ai.ai_error import AiError, InvalidOutputError, InvalidResponseError
from pyfect.ai.amazon_bedrock import schema as W
from pyfect.ai.amazon_bedrock._prompt import PROVIDER, error
from pyfect.ai.anthropic_structured_output import to_codec_anthropic
from pyfect.ai.response import FinishReason
from pyfect.encoding import base64
from pyfect.result import Ok
from pyfect.stream import Stream
from pyfect.tracer import Span

type Part = dict[str, Any]

_FINISH_REASONS: dict[str, FinishReason] = {
    "end_turn": "stop",
    "stop_sequence": "stop",
    "tool_use": "tool-calls",
    "max_tokens": "length",
    "model_context_window_exceeded": "length",
    "guardrail_intervened": "content-filter",
    "content_filtered": "content-filter",
    "malformed_model_output": "error",
    "malformed_tool_use": "error",
}


def resolve_finish_reason(stop_reason: str, is_json_response: bool = False) -> FinishReason:
    """A stop reason as a finish reason (``other`` for one Bedrock adds
    later); calling the object tool of a JSON response is a ``stop``."""
    reason = _FINISH_REASONS.get(stop_reason, "other")
    return "stop" if is_json_response and reason == "tool-calls" else reason


def decode_tool_params(
    tools: Sequence[Tl.AnyTool], tool_name: str, params: object
) -> Effect[object]:
    """Bedrock is sent each tool's codec schema, which differs from the
    tool's own wherever the codec rewrites a parameter: parameters following
    the codec are re-encoded with the tool's schema for the toolkit to
    decode, others are kept for the toolkit to report."""
    tool = next((t for t in tools if t.name == tool_name), None)
    if tool is None or (isinstance(tool, Tl.Dynamic) and tool.json_schema is not None):
        return fx.succeed(params)
    schema = tool.parameters_schema
    try:
        codec = to_codec_anthropic(schema)[0]
    except Exception:
        return fx.succeed(params)
    decoded: Effect[object, Any, Any] = S.decode_unknown_effect(codec)(params).flat_map(
        S.encode_unknown_effect(schema)
    )
    return decoded.or_else_succeed(lambda _: params)


def _usage(usage: W.TokenUsage) -> dict[str, Any]:
    cache_read = usage.get("cacheReadInputTokens")
    cache_write = usage.get("cacheWriteInputTokens")
    input_tokens: dict[str, int] = {
        "uncached": usage["inputTokens"],
        "total": usage["inputTokens"] + (cache_read or 0) + (cache_write or 0),
    }
    if cache_read is not None:
        input_tokens["cacheRead"] = cache_read
    if cache_write is not None:
        input_tokens["cacheWrite"] = cache_write
    return {"inputTokens": input_tokens, "outputTokens": {"total": usage["outputTokens"]}}


def _finish(reason: FinishReason, stop_reason: str | None, usage: dict[str, Any]) -> Part:
    return {
        "type": "finish",
        "reason": reason,
        "usage": usage,
        "metadata": {PROVIDER: {"stopReason": stop_reason}},
    }


def _response_metadata(model_id: str) -> Effect[Part]:
    """Converse returns no response id."""
    return date_time.now().map(
        lambda now: {
            "type": "response-metadata",
            "modelId": model_id,
            "timestamp": date_time.format_iso(now),
        }
    )


def annotate_request(span: Span | None, request: W.ConverseRequest) -> None:
    if span is None:
        return
    inference = request.get("inferenceConfig", {})
    stops = inference.get("stopSequences")
    T.add_gen_ai_annotations(
        span,
        {
            "provider": {"name": "aws.bedrock"},
            "operation": {"name": "chat"},
            "request": {
                "model": request["modelId"],
                "max_tokens": inference.get("maxTokens"),
                "temperature": inference.get("temperature"),
                "top_p": inference.get("topP"),
                "stop_sequences": None if stops is None else list(stops),
            },
        },
    )


def _annotate_response(
    span: Span | None, model_id: str, stop_reason: str | None, usage: dict[str, Any]
) -> None:
    if span is None:
        return
    T.add_gen_ai_annotations(
        span,
        {
            "response": {
                "model": model_id,
                "finish_reasons": None if stop_reason is None else [stop_reason],
            },
            "usage": {
                "input_tokens": usage["inputTokens"]["total"],
                "output_tokens": usage["outputTokens"]["total"],
            },
        },
    )
    span.attribute("gen_ai.usage.cache_read.input_tokens", usage["inputTokens"].get("cacheRead", 0))
    span.attribute(
        "gen_ai.usage.cache_write.input_tokens", usage["inputTokens"].get("cacheWrite", 0)
    )


def _object_tool_name(request: W.ConverseRequest, options: lm.ProviderOptions) -> str | None:
    """Without native structured output the object is asked for through a
    tool named after it."""
    format = options.response_format
    if not isinstance(format, lm.JsonFormat) or "textFormat" in request.get("outputConfig", {}):
        return None
    return format.object_name


def make_response(
    request: W.ConverseRequest, response: W.ConverseResponse, options: lm.ProviderOptions
) -> Effect[list[Part], AiError]:
    content = response["output"]["message"]["content"]
    object_tool_name = _object_tool_name(request, options)
    # A model can call the object tool more than once; the first call is the
    # object (joining several inputs would not be JSON).
    object_tool_block = (
        None
        if object_tool_name is None
        else next(
            (b for b in content if "toolUse" in b and b["toolUse"]["name"] == object_tool_name),
            None,
        )
    )
    has_object_tool = object_tool_block is not None

    @fx.gen
    def run():
        parts: list[Part] = [(yield from _response_metadata(request["modelId"]))]
        for block in content:
            if "text" in block:
                # The native structured output arrives as text; prose next to
                # a called object tool is not part of the object.
                if not has_object_tool:
                    parts.append({"type": "text", "text": block["text"]})
            elif "toolUse" in block:
                tool_use = block["toolUse"]
                if tool_use["name"] == object_tool_name:
                    if block is object_tool_block:
                        parts.append({"type": "text", "text": P.dumps(tool_use.get("input"))})
                    continue
                params = yield from decode_tool_params(
                    options.tools, tool_use["name"], tool_use.get("input")
                )
                parts.append(
                    {
                        "type": "tool-call",
                        "id": tool_use["toolUseId"],
                        "name": tool_use["name"],
                        "params": params,
                        "providerExecuted": False,
                    }
                )
            elif "reasoningContent" in block:
                reasoning = block["reasoningContent"]
                if "reasoningText" in reasoning:
                    text = reasoning["reasoningText"]
                    info = {"signature": text["signature"]} if "signature" in text else {}
                    parts.append(
                        {"type": "reasoning", "text": text["text"], "metadata": {PROVIDER: info}}
                    )
                elif "redactedContent" in reasoning:
                    # No readable text: the encrypted payload rides along so
                    # the block can be sent back.
                    parts.append(
                        {
                            "type": "reasoning",
                            "text": "",
                            "metadata": {
                                PROVIDER: {"redactedContent": reasoning["redactedContent"]}
                            },
                        }
                    )
            # Blocks this provider does not model are ignored.
        usage = _usage(response["usage"])
        stop_reason = response["stopReason"]
        _annotate_response(options.span, request["modelId"], stop_reason, usage)
        parts.append(
            _finish(resolve_finish_reason(stop_reason, has_object_tool), stop_reason, usage)
        )
        return parts

    return run


def _truncate(text: str, max_length: int) -> str:
    return f"{text[:max_length]}..." if len(text) > max_length else text


@dataclass
class _ReasoningBlock:
    """Converse streams a reasoning block's signature after its text, and
    redacted reasoning as base64 chunks of one byte sequence, each encoded
    on its own, so they are joined before the block's metadata is sent."""

    signature: str | None = None
    redacted_chunks: list[bytes] = field(default_factory=list[bytes])

    def info(self) -> dict[str, str]:
        info: dict[str, str] = {}
        if self.signature is not None:
            info["signature"] = self.signature
        if self.redacted_chunks:
            info["redactedContent"] = base64.encode(b"".join(self.redacted_chunks))
        return info


@dataclass
class _ToolBlock:
    id: str
    name: str
    params: str = ""


@dataclass
class _StreamState:
    request: W.ConverseRequest
    tools: Sequence[Tl.AnyTool]
    span: Span | None
    # Text and reasoning blocks have no `contentBlockStart`: they start on
    # their first delta.
    text_blocks: set[int] = field(default_factory=set[int])
    reasoning_blocks: dict[int, _ReasoningBlock] = field(default_factory=dict[int, _ReasoningBlock])
    # Bedrock streams tool input as partial JSON, parsed once the block stops.
    tool_blocks: dict[int, _ToolBlock] = field(default_factory=dict[int, _ToolBlock])
    # Captured at `messageStop`; the finish part is sent at `metadata`, which
    # follows it and carries the usage.
    stop_reason: str | None = None

    def delta(self, event: W.ContentBlockDeltaEvent) -> Effect[list[Part], AiError]:
        index = event["contentBlockIndex"]
        id = str(index)
        delta = event["delta"]
        parts: list[Part] = []
        if "toolUse" in delta:
            block = self.tool_blocks.get(index)
            # A tool delta without a `contentBlockStart` has no call id: dropped.
            if block is not None:
                block.params += delta["toolUse"]["input"]
                parts.append(
                    {
                        "type": "tool-params-delta",
                        "id": block.id,
                        "delta": delta["toolUse"]["input"],
                    }
                )
        elif "reasoningContent" in delta:
            reasoning = delta["reasoningContent"]
            found = self.reasoning_blocks.get(index)
            if found is None:
                found = self.reasoning_blocks[index] = _ReasoningBlock()
                parts.append({"type": "reasoning-start", "id": id})
            if "text" in reasoning:
                parts.append({"type": "reasoning-delta", "id": id, "delta": reasoning["text"]})
            if "signature" in reasoning:
                found.signature = reasoning["signature"]
            if "redactedContent" in reasoning:
                chunk = base64.decode(reasoning["redactedContent"])
                if not isinstance(chunk, Ok):
                    description = (
                        "Bedrock streamed redacted reasoning that is not base64: "
                        + _truncate(reasoning["redactedContent"], 100)
                    )
                    return fx.fail(
                        error("makeStreamResponse", InvalidResponseError(description=description))
                    )
                found.redacted_chunks.append(chunk.value)
        elif "text" in delta:
            if index not in self.text_blocks:
                self.text_blocks.add(index)
                parts.append({"type": "text-start", "id": id})
            parts.append({"type": "text-delta", "id": id, "delta": delta["text"]})
        # Deltas this provider does not model are skipped.
        return fx.succeed(parts)

    def stop(self, index: int) -> Effect[list[Part], AiError]:
        id = str(index)
        parts: list[Part] = []
        if index in self.text_blocks:
            self.text_blocks.discard(index)
            parts.append({"type": "text-end", "id": id})
        reasoning = self.reasoning_blocks.pop(index, None)
        if reasoning is not None:
            parts.append(
                {"type": "reasoning-end", "id": id, "metadata": {PROVIDER: reasoning.info()}}
            )
        block = self.tool_blocks.pop(index, None)
        if block is None:
            return fx.succeed(parts)
        try:
            # A tool taking no arguments streams no deltas at all.
            params = Tl.unsafe_secure_json_parse(block.params or "{}")
        except Exception:
            description = (
                f"Bedrock streamed input for the `{block.name}` tool that is not valid JSON: "
                + _truncate(block.params, 500)
            )
            return fx.fail(error("makeStreamResponse", InvalidOutputError(description=description)))
        parts.append({"type": "tool-params-end", "id": block.id})
        return decode_tool_params(self.tools, block.name, params).map(
            lambda decoded: [
                *parts,
                {
                    "type": "tool-call",
                    "id": block.id,
                    "name": block.name,
                    "params": decoded,
                    "providerExecuted": False,
                },
            ]
        )

    def event(self, event: W.ConverseStreamEvent) -> Effect[list[Part], AiError]:  # noqa: PLR0911
        model_id = self.request["modelId"]
        if not W.is_known_stream_event(event):
            # Events this provider does not model are ignored.
            return fx.succeed([])
        if "messageStart" in event:
            return _response_metadata(model_id).map(lambda part: [part])
        if "contentBlockStart" in event:
            start = event["contentBlockStart"]
            tool_use = start.get("start", {}).get("toolUse")
            if tool_use is None:
                return fx.succeed([])
            block = _ToolBlock(tool_use["toolUseId"], tool_use["name"])
            self.tool_blocks[start["contentBlockIndex"]] = block
            return fx.succeed([{"type": "tool-params-start", "id": block.id, "name": block.name}])
        if "contentBlockDelta" in event:
            return self.delta(event["contentBlockDelta"])
        if "contentBlockStop" in event:
            return self.stop(event["contentBlockStop"]["contentBlockIndex"])
        if "messageStop" in event:
            self.stop_reason = event["messageStop"]["stopReason"]
            return fx.succeed([])
        if "metadata" in event:
            usage = _usage(event["metadata"]["usage"])
            _annotate_response(self.span, model_id, self.stop_reason, usage)
            reason = (
                "unknown" if self.stop_reason is None else resolve_finish_reason(self.stop_reason)
            )
            return fx.succeed([_finish(reason, self.stop_reason, usage)])
        return fx.succeed([])


def make_stream_response(
    request: W.ConverseRequest,
    events: Stream[W.ConverseStreamEvent, AiError],
    options: lm.ProviderOptions,
) -> Stream[Part, AiError]:
    state = _StreamState(request, options.tools, options.span)
    return events.map_effect(state.event).flatten_iterable()
