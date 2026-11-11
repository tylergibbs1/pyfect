"""TLS connections a server closes without waiting for the client's ``close_notify``, as
Node's do (Effect's ``NodeHttpServer``) and as TLS 1.3 allows (RFC 8446 6.1).

asyncio otherwise keeps a closed TLS connection open until the client answers, up to 30
seconds, and a server waiting for its connections to close waits that long for an idle
keep-alive connection (dogfood turnstile #2).
"""

from __future__ import annotations

import contextlib
import ssl


class _OneWayShutdown(ssl.SSLObject):
    def unwrap(self) -> None:
        # Our close_notify is queued; the client's is not waited for.
        with contextlib.suppress(ssl.SSLWantReadError):
            super().unwrap()


def close_without_waiting(context: ssl.SSLContext) -> ssl.SSLContext:
    """``context``, whose connections close as soon as their ``close_notify`` is sent."""
    context.sslobject_class = _OneWayShutdown
    return context


__all__ = ["close_without_waiting"]
