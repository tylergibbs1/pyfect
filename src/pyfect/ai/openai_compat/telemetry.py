"""GenAI span attributes with OpenAI's own (Effect's ``OpenAiTelemetry``):
the shared ``gen_ai.*`` groups and ``openai.request.*`` /
``openai.response.*``."""

from __future__ import annotations

from typing import TypedDict

from pyfect.ai import telemetry as T
from pyfect.tracer import Span


class RequestAttributes(TypedDict, total=False):
    """OpenAI request span attributes: the service tier asked for."""

    service_tier: str | None


class ResponseAttributes(TypedDict, total=False):
    """OpenAI response span attributes: the service tier used and system fingerprint."""

    service_tier: str | None
    system_fingerprint: str | None


class OpenAiAttributes(TypedDict, total=False):
    """The ``openai.*`` span attributes of a request and its response."""

    request: RequestAttributes | None
    response: ResponseAttributes | None


class OpenAiTelemetryAttributeOptions(T.GenAIAttributeOptions, total=False):
    """GenAI span attributes with OpenAI's own added."""

    openai: OpenAiAttributes | None


def add_gen_ai_annotations(span: Span, options: OpenAiTelemetryAttributeOptions) -> None:
    """Write the shared groups, then OpenAI's."""
    T.add_gen_ai_annotations(span, options)
    openai = options.get("openai")
    if openai is None:
        return
    request = openai.get("request")
    if request is not None:
        T.add_span_attributes(span, "openai.request", request)
    response = openai.get("response")
    if response is not None:
        T.add_span_attributes(span, "openai.response", response)


__all__ = [
    "OpenAiAttributes",
    "OpenAiTelemetryAttributeOptions",
    "RequestAttributes",
    "ResponseAttributes",
    "add_gen_ai_annotations",
]
