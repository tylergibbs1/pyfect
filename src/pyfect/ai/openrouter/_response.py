"""An OpenRouter chat completion as encoded response parts (Effect's
``makeResponse`` in ``OpenRouterLanguageModel``), and what the streamed
response shares with it: finish reasons, usage, sources and the
provider metadata."""

from __future__ import annotations

from collections.abc import Generator, Mapping
from datetime import UTC, datetime
from typing import Any, Never

import pyfect as fx
from pyfect import date_time
from pyfect._core import Effect
from pyfect.ai import _provider as P
from pyfect.ai.ai_error import AiError, InvalidOutputError, ToolParameterValidationError
from pyfect.ai.id_generator import IdGenerator
from pyfect.ai.openrouter._prompt import KEY, MODULE, base64_from_data_url, media_type_of
from pyfect.ai.openrouter.generated import types as GT
from pyfect.ai.response import FinishReason
from pyfect.ai.tool import unsafe_secure_json_parse
from pyfect.http.response import HttpClientResponse

type Part = dict[str, Any]
type Gen[A] = Generator[Effect[Any, Any, Any], Any, A]

_FINISH_REASONS: Mapping[str, FinishReason] = {
    "content_filter": "content-filter",
    "error": "error",
    "function_call": "tool-calls",
    "length": "length",
    "tool_calls": "tool-calls",
    "stop": "stop",
}


def resolve_finish_reason(reason: str | None) -> FinishReason:
    if reason is None:
        return "other"
    return _FINISH_REASONS.get(reason, "unknown")


def usage(raw: GT.ChatUsage | None) -> dict[str, Any]:
    """Effect's ``getUsage``: a cached or reasoning count larger than its
    parent is read as separate from it (some providers report it so),
    else as part of it."""
    if raw is None:
        return {"inputTokens": {"total": 0}, "outputTokens": {"total": 0}}
    prompt = raw["prompt_tokens"]
    completion = raw["completion_tokens"]
    prompt_details = P.obj(raw.get("prompt_tokens_details"))
    cache_read = P.or_default(prompt_details.get("cached_tokens"), 0)
    cache_write = P.or_default(prompt_details.get("cache_write_tokens"), 0)
    reasoning = P.or_default(P.obj(raw.get("completion_tokens_details")).get("reasoning_tokens"), 0)
    input_total = prompt + cache_read if cache_read > prompt else prompt
    output_total = completion + reasoning if reasoning > completion else completion
    return {
        "inputTokens": {
            "uncached": input_total - cache_read,
            "total": input_total,
            "cacheRead": cache_read,
            "cacheWrite": cache_write,
        },
        "outputTokens": {
            "total": output_total,
            "text": output_total - reasoning,
            "reasoning": reasoning,
        },
    }


def timestamp(created: float) -> str:
    return date_time.format_iso(datetime.fromtimestamp(created, UTC))


def url_source(annotation: Mapping[str, Any]) -> Part:
    """The source of a ``url_citation`` annotation."""
    citation = annotation["url_citation"]
    metadata: dict[str, Any] = {}
    for source, target in (
        ("content", "content"),
        ("start_index", "startIndex"),
        ("end_index", "endIndex"),
    ):
        if source in citation:
            metadata[target] = citation[source]
    return {
        "type": "source",
        "sourceType": "url",
        "id": citation["url"],
        "url": citation["url"],
        "title": P.or_default(citation.get("title"), ""),
        "metadata": {KEY: metadata},
    }


def provider_of(raw: Mapping[str, Any]) -> dict[str, Any]:
    provider = raw.get("provider")
    return {"provider": provider} if isinstance(provider, str) else {}


def parse_params(name: str, text: str, method: str) -> Effect[object, AiError]:
    try:
        return fx.succeed(unsafe_secure_json_parse(text))
    except ValueError as cause:
        description = f"Failed to securely JSON parse tool parameters: {cause}"
        reason = ToolParameterValidationError(tool_name=name, description=description)
        return fx.fail(AiError(module=MODULE, method=method, reason=reason))


def generate_id() -> Effect[str, Never, IdGenerator]:
    return IdGenerator().flat_map(lambda ids: ids.generate_id())


def _reasoning(details: GT.ChatReasoningDetails) -> tuple[list[Part], bool]:
    parts: list[Part] = []
    encrypted = False
    for detail in details:
        metadata = {KEY: {"reasoningDetails": [detail]}}
        match detail["type"]:
            case "reasoning.text":
                text = detail.get("text")
                if text:
                    parts.append({"type": "reasoning", "text": text, "metadata": metadata})
            case "reasoning.summary":
                if detail["summary"]:
                    parts.append(
                        {"type": "reasoning", "text": detail["summary"], "metadata": metadata}
                    )
            case "reasoning.encrypted":
                if detail["data"]:
                    encrypted = True
                    parts.append({"type": "reasoning", "text": "[REDACTED]", "metadata": metadata})
            case _:
                pass
    return parts, encrypted


def _texts(content: object) -> list[Part]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}] if content else []
    items: list[Any] = list(content) if isinstance(content, list) else []  # pyright: ignore[reportUnknownArgumentType]
    return [{"type": "text", "text": i["text"]} for i in items if i["type"] == "text"]


def _image(url: str) -> Gen[Part]:
    if url.startswith("data:"):
        media_type = media_type_of(url, "image/jpeg")
        return {"type": "file", "mediaType": media_type, "data": base64_from_data_url(url)}
    id = yield from generate_id()
    return {"type": "source", "sourceType": "url", "id": id, "url": url, "title": ""}


def _make_response(raw: GT.ChatResult, response: HttpClientResponse) -> Gen[list[Part]]:
    parts: list[Part] = [
        {
            "type": "response-metadata",
            "id": raw["id"],
            "modelId": raw["model"],
            "timestamp": timestamp(raw["created"]),
        }
    ]
    if not raw["choices"]:
        reason = InvalidOutputError(description="Received response with empty choices")
        return (yield from fx.fail(AiError(module=MODULE, method="makeResponse", reason=reason)))
    choice = raw["choices"][0]
    message = choice["message"]
    finish_reason = choice["finish_reason"]
    details = message.get("reasoning_details")
    encrypted = False
    if details:
        reasoning_parts, encrypted = _reasoning(details)
        parts.extend(reasoning_parts)
    elif message.get("reasoning"):
        parts.append({"type": "reasoning", "text": message.get("reasoning")})
    parts.extend(_texts(message.get("content")))
    calls = message.get("tool_calls") or []
    for index, call in enumerate(calls):
        name = call["function"]["name"]
        params = yield from parse_params(
            name, P.or_default(call["function"].get("arguments"), "{}"), "makeResponse"
        )
        part: Part = {"type": "tool-call", "id": call["id"], "name": name, "params": params}
        if index == 0 and details:
            part["metadata"] = {KEY: {"reasoningDetails": details}}
        parts.append(part)
    for image in message.get("images") or []:
        image_part = yield from _image(image["image_url"]["url"])
        parts.append(image_part)
    annotations = message.get("annotations")
    parts.extend(url_source(a) for a in annotations or [] if a["type"] == "url_citation")
    files = [annotation for annotation in annotations or [] if annotation["type"] == "file"]
    if encrypted and calls and finish_reason == "stop":
        # Gemini 3 answers `stop` after a tool call with a thought signature,
        # though it expects the call's result.
        finish_reason = "tool_calls"
    metadata: dict[str, Any] = {
        "systemFingerprint": raw.get("system_fingerprint"),
        "usage": raw.get("usage"),
    }
    if files:
        metadata["annotations"] = files
    metadata.update(provider_of(raw))
    parts.append(
        {
            "type": "finish",
            "reason": resolve_finish_reason(finish_reason),
            "usage": usage(raw.get("usage")),
            "response": P.response_details(response),
            "metadata": {KEY: metadata},
        }
    )
    return parts


def make_response(
    raw: GT.ChatResult, response: HttpClientResponse
) -> Effect[list[Part], AiError, IdGenerator]:
    return fx.gen(lambda: _make_response(raw, response))
