"""Anthropic's Messages API for ``pyfect.ai`` (Effect's
``@effect/ai-anthropic``): the ``client``, its per-call ``config``, the
``language_model``, the provider-defined ``tool`` constructors, the error
``metadata`` an ``AiError`` carries and the GenAI ``telemetry``
attributes. Requests go over the ``HttpClient`` service with Anthropic's
JSON wire format; streams are read as Server-Sent Events::

    from pyfect.ai.anthropic import client, language_model

    program.pipe(fx.provide(language_model.model("claude-sonnet-5-5").layer)).pipe(
        fx.provide(client.layer_config(api_key=config.redacted("ANTHROPIC_API_KEY")))
    )
"""

from pyfect.ai.anthropic import client, config, error, language_model, telemetry, tool
from pyfect.ai.anthropic.client import AnthropicClient
from pyfect.ai.anthropic.config import AnthropicConfig

__all__ = [
    "AnthropicClient",
    "AnthropicConfig",
    "client",
    "config",
    "error",
    "language_model",
    "telemetry",
    "tool",
]
