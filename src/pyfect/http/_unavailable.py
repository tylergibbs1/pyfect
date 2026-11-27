"""The answer to a request that arrives while no app is served: ``503``,
``service unavailable``, as Effect's ``NodeHttpServer`` gives since 4.1.5
(Effect #10786). ``live_server`` and the ASGI servers both send it."""

from __future__ import annotations

from pyfect.http.server_response import raw

UNAVAILABLE = raw(
    "service unavailable",
    status=503,
    headers={"cache-control": "no-store", "retry-after": "1"},
)

__all__ = ["UNAVAILABLE"]
