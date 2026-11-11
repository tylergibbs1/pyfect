"""Routes: a method, a path and a handler, maybe under a prefix."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Generic, Literal, Never, Self, TypeVar, cast, overload

from pyfect._core import Effect
from pyfect.effect import succeed
from pyfect.http.router._provided import Provided
from pyfect.http.server_request import HttpServerRequest, ServerRequest
from pyfect.http.server_response import HttpServerResponse

type Method = Literal["*", "GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "QUERY", "HEAD"]


# Declared covariant: pyright infers a frozen dataclass's type parameters as
# invariant on 3.13+ (its synthesized ``__replace__`` takes the fields), which
# made ``add_all([a_route, a_failing_route])`` match no overload.
E_co = TypeVar("E_co", covariant=True, default=Never)
R_co = TypeVar("R_co", covariant=True, default=Never)


@dataclass(frozen=True, slots=True)
class Route(Generic[E_co, R_co]):
    """``method`` ``"*"`` matches every method, and a ``path`` ending in
    ``/*`` matches its prefix too. ``prefix`` is the mount point removed
    from the request URL before the handler runs."""

    method: Method
    path: str
    handler: Effect[HttpServerResponse, E_co, R_co]
    uninterruptible: bool = False
    prefix: str | None = None

    def pipe[B](self, f: Callable[[Self], B], /) -> B:
        return f(self)


type Handler[E, R] = (
    HttpServerResponse
    | Effect[HttpServerResponse, E, R]
    | Callable[[ServerRequest], Effect[HttpServerResponse, E, R]]
)


def to_effect(handler: Handler[Any, Any]) -> Effect[HttpServerResponse, Any, Any]:
    if isinstance(handler, HttpServerResponse):
        return succeed(handler)
    if isinstance(handler, Effect):
        return cast("Effect[HttpServerResponse, Any, Any]", handler)
    return HttpServerRequest().flat_map(handler)


@overload
def route(
    method: Method, path: str, handler: HttpServerResponse, *, uninterruptible: bool = False
) -> Route: ...
@overload
def route[E](
    method: Method,
    path: str,
    handler: Effect[HttpServerResponse, E, Provided]
    | Callable[[ServerRequest], Effect[HttpServerResponse, E, Provided]],
    *,
    uninterruptible: bool = False,
) -> Route[E]: ...
@overload
def route[E, R](
    method: Method,
    path: str,
    handler: Effect[HttpServerResponse, E, R | Provided]
    | Callable[[ServerRequest], Effect[HttpServerResponse, E, R | Provided]],
    *,
    uninterruptible: bool = False,
) -> Route[E, R]: ...
def route(
    method: Method,
    path: str,
    # Spelled out (not ``Handler``): a function is a valid handler.
    handler: HttpServerResponse
    | Effect[HttpServerResponse, Any, Any]
    | Callable[[ServerRequest], Effect[HttpServerResponse, Any, Any]],
    *,
    uninterruptible: bool = False,
) -> Route[Any, Any]:
    """A route for ``add_all``. ``handler`` is a response, an effect, or a
    function of the request. Handlers run interruptibly unless
    ``uninterruptible``."""
    return Route(method, path, to_effect(handler), uninterruptible)


def remove_trailing_slash(path: str) -> str:
    return path.removesuffix("/")


def prefix_path(path: str, prefix: str) -> str:
    """``path`` under ``prefix``: ``"*"`` becomes ``prefix + "/*"`` and
    ``"/"`` the prefix itself."""
    prefix = remove_trailing_slash(prefix)
    if path == "*":
        return f"{prefix}/*"
    if path == "/":
        return prefix
    return prefix + path


def prefix_route[E, R](prefix: str) -> Callable[[Route[E, R]], Route[E, R]]:
    """Mount a route under ``prefix``. Use with ``.pipe``."""

    def apply(self: Route[E, R]) -> Route[E, R]:
        return replace(
            self,
            path=prefix_path(self.path, prefix),
            prefix=remove_trailing_slash(prefix)
            if self.prefix is None
            else prefix_path(self.prefix, prefix),
        )

    return apply
