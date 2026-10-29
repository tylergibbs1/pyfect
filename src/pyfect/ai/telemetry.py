"""GenAI span attributes (Effect's ``Telemetry``): the OpenTelemetry
semantic conventions for generative AI, written onto a span::

    telemetry.add_gen_ai_annotations(
        span,
        {"provider": {"name": "openai"}, "usage": {"input_tokens": 10}},
    )

Each group's keys are written under its prefix (``gen_ai.usage.input_tokens``);
``None`` values are skipped. Effect spells the keys in camelCase and
converts them; the Python keys are already the attribute names.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Literal, TypedDict, cast

from pyfect.tracer import Span

type WellKnownOperationName = Literal["chat", "embeddings", "text_completion"]
type WellKnownOutputType = Literal["text", "json", "image", "speech"]
type WellKnownProviderName = Literal[
    "anthropic",
    "aws.bedrock",
    "azure.ai.inference",
    "azure.ai.openai",
    "cohere",
    "deepseek",
    "gcp.gemini",
    "gcp.gen_ai",
    "gcp.vertex_ai",
    "groq",
    "ibm.watsonx.ai",
    "mistral_ai",
    "moonshot_ai",
    "openai",
    "perplexity",
    "x_ai",
]


class ProviderAttributes(TypedDict, total=False):
    name: str | None


class OperationAttributes(TypedDict, total=False):
    name: str | None


class OutputAttributes(TypedDict, total=False):
    type: str | None


class UsageAttributes(TypedDict, total=False):
    input_tokens: int | float | None
    output_tokens: int | float | None


class RequestAttributes(TypedDict, total=False):
    model: str | None
    temperature: float | None
    top_k: float | None
    top_p: float | None
    max_tokens: int | None
    encoding_formats: Sequence[str] | None
    stop_sequences: Sequence[str] | None
    frequency_penalty: float | None
    presence_penalty: float | None
    seed: int | None


class ResponseAttributes(TypedDict, total=False):
    id: str | None
    model: str | None
    finish_reasons: Sequence[str] | None


class GenAIAttributeOptions(TypedDict, total=False):
    """The groups ``add_gen_ai_annotations`` writes."""

    provider: ProviderAttributes | None
    operation: OperationAttributes | None
    output: OutputAttributes | None
    request: RequestAttributes | None
    response: ResponseAttributes | None
    usage: UsageAttributes | None


def _attribute_value(value: object) -> object:
    return list(cast("tuple[object, ...]", value)) if isinstance(value, tuple) else value


def add_span_attributes(span: Span, prefix: str, attributes: Mapping[str, object]) -> None:
    """Each value of ``attributes`` that is not ``None`` as
    ``"{prefix}.{key}"`` (Effect's ``addSpanAttributes``)."""
    for key, value in attributes.items():
        if value is not None:
            span.attribute(f"{prefix}.{key}", _attribute_value(value))


_GROUPS = ("provider", "operation", "output", "request", "response", "usage")


def add_gen_ai_annotations(span: Span, options: GenAIAttributeOptions) -> None:
    """Write each group of ``options`` under ``gen_ai.<group>``."""
    for group in _GROUPS:
        attributes = options.get(group)
        if attributes is not None:
            add_span_attributes(span, f"gen_ai.{group}", attributes)


__all__ = [
    "GenAIAttributeOptions",
    "OperationAttributes",
    "OutputAttributes",
    "ProviderAttributes",
    "RequestAttributes",
    "ResponseAttributes",
    "UsageAttributes",
    "WellKnownOperationName",
    "WellKnownOutputType",
    "WellKnownProviderName",
    "add_gen_ai_annotations",
    "add_span_attributes",
]
