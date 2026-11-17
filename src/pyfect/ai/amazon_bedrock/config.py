"""Per-request changes to the HTTP client of an Amazon Bedrock client
(Effect's ``AmazonBedrockConfig``)::

    program.pipe(config.with_client_transform(lambda client: client.retry_transient(times=2)))
"""

from __future__ import annotations

from pyfect._core import Effect
from pyfect.ai import _provider as P
from pyfect.ai._provider import ClientTransform
from pyfect.context import Tag

Service = P.ClientConfig


class AmazonBedrockConfig(Tag[Service], key="@effect/ai-amazon-bedrock/AmazonBedrockConfig"):
    """Overrides for the requests made while it is provided."""


def get_or_none() -> Effect[Service | None]:
    """The provided ``AmazonBedrockConfig``, else ``None``."""
    return P.client_config(AmazonBedrockConfig)


def with_client_transform(transform: ClientTransform) -> P.WithClientTransform:
    """Run an effect with its requests sent through ``transform(client)``.
    Use with ``.pipe``."""
    return P.WithClientTransform(AmazonBedrockConfig, transform)


__all__ = [
    "AmazonBedrockConfig",
    "ClientTransform",
    "Service",
    "get_or_none",
    "with_client_transform",
]
