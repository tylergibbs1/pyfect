"""OpenAI-compatible providers over Chat Completions (Effect's
``@effect/ai-openai-compat``): ``client``, ``config``, ``error``,
``language_model``, ``embedding_model`` and ``telemetry``."""

from pyfect.ai.openai_compat import (
    client,
    config,
    embedding_model,
    error,
    language_model,
    telemetry,
)
from pyfect.ai.openai_compat.client import OpenAiClient
from pyfect.ai.openai_compat.config import OpenAiConfig

__all__ = [
    "OpenAiClient",
    "OpenAiConfig",
    "client",
    "config",
    "embedding_model",
    "error",
    "language_model",
    "telemetry",
]
