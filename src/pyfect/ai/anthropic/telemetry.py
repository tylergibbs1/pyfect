"""GenAI span attributes with Anthropic's own (Effect's
``AnthropicTelemetry``): the shared ``gen_ai.*`` groups and
``gen_ai.anthropic.request.*`` / ``gen_ai.anthropic.response.*``."""

from __future__ import annotations

from typing import TypedDict

from pyfect.ai import telemetry as T
from pyfect.tracer import Span


class RequestAttributes(TypedDict, total=False):
    extended_thinking: bool | None
    thinking_budget_tokens: int | None


class ResponseAttributes(TypedDict, total=False):
    stop_reason: str | None


class AnthropicAttributes(TypedDict, total=False):
    request: RequestAttributes | None
    response: ResponseAttributes | None


class AnthropicTelemetryAttributeOptions(T.GenAIAttributeOptions, total=False):
    anthropic: AnthropicAttributes | None


def add_gen_ai_annotations(span: Span, options: AnthropicTelemetryAttributeOptions) -> None:
    """Write the shared groups, then Anthropic's."""
    T.add_gen_ai_annotations(span, options)
    anthropic = options.get("anthropic")
    if anthropic is None:
        return
    request = anthropic.get("request")
    if request is not None:
        T.add_span_attributes(span, "gen_ai.anthropic.request", request)
    response = anthropic.get("response")
    if response is not None:
        T.add_span_attributes(span, "gen_ai.anthropic.response", response)


__all__ = [
    "AnthropicAttributes",
    "AnthropicTelemetryAttributeOptions",
    "RequestAttributes",
    "ResponseAttributes",
    "add_gen_ai_annotations",
]
