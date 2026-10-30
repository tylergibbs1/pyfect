"""HTTP API middleware (Effect's ``HttpApiMiddleware``): a service that
wraps the handlers of the endpoints it is added to.

Declare one as a tag class over what it provides, the errors it may fail
with and the services it needs, and give the error schemas::

    class Authorization(
        HttpApiMiddleware[CurrentUser, Unauthorized], security={"bearer": security.bearer}
    ):
        error = Unauthorized

    AuthorizationLive = layer.succeed(Authorization, {"bearer": check_token})

Without ``security`` the service is a ``MiddlewareFn``: it gets the
handler's effect, which needs what the middleware provides. With it, the
service maps each security name to a ``SecurityMiddlewareFn``, which also
gets the decoded credential; they are tried in order. Add a middleware to
an endpoint with ``endpoint.middleware(Authorization)`` or to a whole group
with ``class Users(HttpApiGroup[Authorization], ...)``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, ClassVar, Generic, Never, TypeVar

from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect.context import Context, Tag
from pyfect.effect import context, fail, provide_context, succeed
from pyfect.http.error import HttpClientError
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse
from pyfect.http.router import Provided, Unhandled
from pyfect.http.server_response import HttpServerResponse
from pyfect.http_api.error import HttpApiSchemaError
from pyfect.http_api.security import Credential, HttpApiSecurity
from pyfect.layer import Layer
from pyfect.layer import effect_context as layer_effect_context
from pyfect.layer import succeed as layer_succeed
from pyfect.schema import Codec, Top

if TYPE_CHECKING:
    from pyfect.http_api.endpoint import AnyEndpoint
    from pyfect.http_api.group import AnyGroup

P_co = TypeVar("P_co", covariant=True, default=Never)
E_co = TypeVar("E_co", covariant=True, default=Never)
R_co = TypeVar("R_co", covariant=True, default=Never)


@dataclass(frozen=True, slots=True)
class MiddlewareOptions:
    """The endpoint and group a middleware runs for."""

    endpoint: AnyEndpoint
    group: AnyGroup


@dataclass(frozen=True, slots=True)
class SecurityOptions:
    """``MiddlewareOptions`` with the credential the security decoded."""

    credential: Credential
    endpoint: AnyEndpoint
    group: AnyGroup


type MiddlewareFn[P, E, R] = Callable[
    [Effect[HttpServerResponse, Unhandled, P], MiddlewareOptions],
    Effect[HttpServerResponse, Unhandled | E, R | Provided],
]
type SecurityMiddlewareFn[P, E, R] = Callable[
    [Effect[HttpServerResponse, Unhandled, P], SecurityOptions],
    Effect[HttpServerResponse, Unhandled | E, R | Provided],
]
type MiddlewareService[P, E, R] = (
    MiddlewareFn[P, E, R] | Mapping[str, SecurityMiddlewareFn[P, E, R]]
)


class HttpApiMiddleware(Tag[MiddlewareService[P_co, E_co, R_co]], Generic[P_co, E_co, R_co]):
    """A middleware tag providing ``P`` to the handlers, failing with ``E``
    (encoded by ``error``) and needing ``R``. The class keyword
    ``security`` makes it a security middleware; ``required_for_client``
    makes a client of its endpoints use its client layer
    (``layer_client``)."""

    error: Codec[E_co, Any, Never, Never] | tuple[Codec[E_co, Any, Never, Never], ...] = ()
    security: ClassVar[Mapping[str, HttpApiSecurity] | None] = None
    required_for_client: ClassVar[bool] = False

    def __init_subclass__(
        cls,
        *,
        security: Mapping[str, HttpApiSecurity] | None = None,
        required_for_client: bool = False,
        **kwargs: Any,
    ) -> None:
        super().__init_subclass__(**kwargs)
        if security is not None:
            if not security:
                raise ValueError("HttpApiMiddleware: security must not be empty")
            cls.security = MappingProxyType(dict(security))
        if required_for_client:
            cls.required_for_client = True

    @classmethod
    def errors(cls) -> tuple[Top, ...]:
        """The error schemas, as a tuple."""
        error = cls.error
        return error if isinstance(error, tuple) else (error,)


type AnyMiddleware = type[HttpApiMiddleware[Any, Any, Any]]


def layer_schema_error_transform[E, R](
    middleware: type[HttpApiMiddleware[Never, E, R]],
    transform: Callable[
        [HttpApiSchemaError, MiddlewareOptions],
        Effect[HttpServerResponse, E | HttpApiSchemaError, R | Provided],
    ],
) -> Layer[HttpApiMiddleware[Never, E, R]]:
    """A layer of ``middleware`` answering the schema errors of requests
    with ``transform`` (a 422 instead of the 400, say)."""

    def service(
        effect: Effect[HttpServerResponse, Unhandled, Never], options: MiddlewareOptions
    ) -> Effect[HttpServerResponse, Any, Any]:
        def on_error(error: object) -> Effect[HttpServerResponse, Any, Any]:
            if isinstance(error, HttpApiSchemaError):
                return transform(error, options)
            return fail(error)

        return effect.catch_all(on_error)

    return layer_succeed(middleware, service)


# --- client ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ClientMiddlewareOptions:
    """A client request about to be sent for ``endpoint``; ``next`` sends
    it on (to the next client middleware, then the HTTP client)."""

    endpoint: AnyEndpoint
    group: AnyGroup
    request: HttpClientRequest
    next: Callable[[HttpClientRequest], Effect[HttpClientResponse, HttpClientError]]


type ClientMiddlewareFn[E, R] = Callable[
    [ClientMiddlewareOptions], Effect[HttpClientResponse, E | HttpClientError, R]
]


class ForClient[M]:
    """The client layer of the middleware ``M`` (type-level marker)."""

    @property
    def middleware(self) -> M:
        raise TypeError("ForClient is a type-level marker")


def client_key(middleware: AnyMiddleware) -> str:
    return f"{middleware.key}/Client"


def layer_client[M: HttpApiMiddleware[Any, Any, Any], E, R](
    middleware: type[M], service: ClientMiddlewareFn[E, R]
) -> Layer[ForClient[M], Never, R]:
    """The client side of ``middleware``: runs around each request a
    client of its endpoints sends (Effect's ``layerClient``)."""
    return layer_client_effect(middleware, succeed(service))


def layer_client_effect[M: HttpApiMiddleware[Any, Any, Any], E, R, EX, RX](
    middleware: type[M], made: Effect[ClientMiddlewareFn[E, R], EX, RX]
) -> Layer[ForClient[M], EX, R | RX]:
    """``layer_client`` with the client middleware made by an effect."""
    require_effect(made, "made")

    def build(fn: ClientMiddlewareFn[E, R]) -> Effect[Context[Any], Never, Any]:
        def with_services(services: Context[Any]) -> Context[Any]:
            def run(options: ClientMiddlewareOptions) -> Effect[HttpClientResponse, Any, Any]:
                return fn(options).pipe(provide_context(services))

            return Context({client_tag(middleware): run})

        return context().map(with_services)

    return layer_effect_context(made.flat_map(build))


_client_tags: dict[str, type[Tag[Any]]] = {}


def client_tag(middleware: AnyMiddleware) -> type[Tag[Any]]:
    """The tag holding ``middleware``'s client function: one per middleware,
    keyed ``<key>/Client`` (Effect's ``ForClient`` key)."""
    key = client_key(middleware)
    found = _client_tags.get(key)
    if found is None:
        found = type(f"{middleware.__name__}Client", (Tag,), {}, key=key)
        _client_tags[key] = found
    return found


__all__ = [
    "AnyMiddleware",
    "ClientMiddlewareFn",
    "ClientMiddlewareOptions",
    "ForClient",
    "HttpApiMiddleware",
    "MiddlewareFn",
    "MiddlewareOptions",
    "MiddlewareService",
    "SecurityMiddlewareFn",
    "SecurityOptions",
    "client_key",
    "client_tag",
    "layer_client",
    "layer_client_effect",
    "layer_schema_error_transform",
]
