"""Per-request changes to the TypeSafe client's HTTP client (Effect's
``TypeSafeConfig``)::

    program.pipe(config.with_client_transform(lambda client: client.retry_transient(times=2)))

A transform set here applies after the client's own ``transform_client``.
"""

from __future__ import annotations

from pyfect._core import Effect
from pyfect.ai import _provider as P
from pyfect.ai._provider import ClientTransform
from pyfect.context import Tag

Service = P.ClientConfig


class TypeSafeConfig(Tag[Service], key="@effect/ai-typesafe/TypeSafeConfig"):
    """Overrides for the requests made while it is provided."""


def get_or_none() -> Effect[Service | None]:
    """The provided ``TypeSafeConfig``, else ``None``."""
    return P.client_config(TypeSafeConfig)


def with_client_transform(transform: ClientTransform) -> P.WithClientTransform:
    """Run an effect with its requests sent through ``transform(client)``.
    Use with ``.pipe``."""
    return P.WithClientTransform(TypeSafeConfig, transform)


__all__ = ["ClientTransform", "Service", "TypeSafeConfig", "get_or_none", "with_client_transform"]
