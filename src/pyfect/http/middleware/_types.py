"""The type of a configured middleware (``cors(...)``, ``compression(...)``):
generic in the app it wraps, so the app's errors and requirements pass
through, with ``RM`` the requirements the middleware adds."""

from __future__ import annotations

from typing import Protocol

from pyfect._core import Effect
from pyfect.http.server_response import HttpServerResponse


class AppMiddleware[RM](Protocol):
    def __call__[E, R](
        self, app: Effect[HttpServerResponse, E, R], /
    ) -> Effect[HttpServerResponse, E, R | RM]: ...
