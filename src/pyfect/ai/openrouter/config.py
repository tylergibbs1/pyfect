"""Per-request changes to the OpenRouter client's HTTP client (Effect's
``OpenRouterConfig``)::

    program.pipe(config.with_client_transform(lambda client: client.retry_transient(times=2)))

The transform applies to the generated client's operations and to
decisions requests, not to streamed chat completions; it replaces any
transform set around it (compose them by hand to apply both).
"""

from __future__ import annotations

from pyfect._core import Effect
from pyfect.ai import _provider as P
from pyfect.ai._provider import ClientTransform
from pyfect.context import Tag

Service = P.ClientConfig


class OpenRouterConfig(Tag[Service], key="@effect/ai-openrouter/OpenRouterConfig"):
    """Overrides for the requests made while it is provided."""


def get_or_none() -> Effect[Service | None]:
    """The provided ``OpenRouterConfig``, else ``None``."""
    return P.client_config(OpenRouterConfig)


def with_client_transform(transform: ClientTransform) -> P.WithClientTransform:
    """Run an effect with its requests sent through ``transform(client)``.
    Use with ``.pipe``."""
    return P.WithClientTransform(OpenRouterConfig, transform)


__all__ = ["ClientTransform", "OpenRouterConfig", "Service", "get_or_none", "with_client_transform"]
