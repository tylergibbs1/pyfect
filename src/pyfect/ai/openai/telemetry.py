"""GenAI span attributes with OpenAI's own (Effect's ``OpenAiTelemetry``):
the shared ``gen_ai.*`` groups and ``openai.request.*`` /
``openai.response.*``. The same attributes as ``openai_compat``'s."""

from pyfect.ai.openai_compat.telemetry import (
    OpenAiAttributes,
    OpenAiTelemetryAttributeOptions,
    RequestAttributes,
    ResponseAttributes,
    add_gen_ai_annotations,
)

__all__ = [
    "OpenAiAttributes",
    "OpenAiTelemetryAttributeOptions",
    "RequestAttributes",
    "ResponseAttributes",
    "add_gen_ai_annotations",
]
