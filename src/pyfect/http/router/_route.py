"""Routes: a method, a path and a handler, maybe under a prefix."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Any, Generic, Literal, Never, Self, TypeVar, cast, overload

from pyfect._core import Effect
from pyfect._pipe import pipe_one
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
    from the request URL before the handler runs. ``redacted_params`` are the
    path params (``"*"`` for the wildcard) recorded as ``REDACTED`` in the
    server span and request log when the route matches."""

    method: Method
    path: str
    handler: Effect[HttpServerResponse, E_co, R_co]
    uninterruptible: bool = False
    prefix: str | None = None
    redacted_params: tuple[str, ...] = ()

    def pipe[B](self, f: Callable[[Self], B], /, *more: Never) -> B:
        return pipe_one(self, f, more)


type Handler[E, R] = (
    HttpServerResponse
    | Effect[HttpServerResponse, E, R]
    | Callable[[ServerRequest], Effect[HttpServerResponse, E, R]]
)


def redacted_param_names(names: Sequence[str]) -> tuple[str, ...]:
    """``names`` as a tuple; a lone string is a mistake for a list of one name."""
    if isinstance(names, str):
        raise TypeError(f"redacted_params takes a sequence of names, not the string {names!r}")
    return tuple(names)


def to_effect(handler: Handler[Any, Any]) -> Effect[HttpServerResponse, Any, Any]:
    if isinstance(handler, HttpServerResponse):
        return succeed(handler)
    if isinstance(handler, Effect):
        return cast("Effect[HttpServerResponse, Any, Any]", handler)
    return HttpServerRequest().flat_map(handler)


@overload
def route(
    method: Method,
    path: str,
    handler: HttpServerResponse,
    *,
    uninterruptible: bool = False,
    redacted_params: Sequence[str] = (),
) -> Route: ...
@overload
def route[E](
    method: Method,
    path: str,
    handler: Effect[HttpServerResponse, E, Provided]
    | Callable[[ServerRequest], Effect[HttpServerResponse, E, Provided]],
    *,
    uninterruptible: bool = False,
    redacted_params: Sequence[str] = (),
) -> Route[E]: ...
@overload
def route[E, R](
    method: Method,
    path: str,
    handler: Effect[HttpServerResponse, E, R | Provided]
    | Callable[[ServerRequest], Effect[HttpServerResponse, E, R | Provided]],
    *,
    uninterruptible: bool = False,
    redacted_params: Sequence[str] = (),
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
    redacted_params: Sequence[str] = (),
) -> Route[Any, Any]:
    """A route for ``add_all``. ``handler`` is a response, an effect, or a
    function of the request. Handlers run interruptibly unless
    ``uninterruptible``. The values of ``redacted_params`` (``"*"`` for the
    wildcard) are recorded as ``REDACTED`` in the server span and request log;
    the handler sees the path as sent."""
    return Route(
        method,
        path,
        to_effect(handler),
        uninterruptible,
        redacted_params=redacted_param_names(redacted_params),
    )


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
