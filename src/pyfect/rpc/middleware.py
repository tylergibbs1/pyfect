"""RPC middleware (Effect's ``RpcMiddleware``): a service wrapping the
handlers of the RPCs it is added to.

Declare one as a tag class over what it provides to the handlers, the
error it may fail with and the services it needs, and give the error's
schema::

    class Auth(RpcMiddleware[CurrentUser, Unauthorized], required_for_client=True):
        error = Unauthorized

    AuthLive = layer.succeed(Auth, lambda effect, options: effect.pipe(
        fx.provide_service(CurrentUser, user_of(options.headers))
    ))

Add it to an RPC with ``rpc.middleware(Auth)``. ``required_for_client``
makes a client of those RPCs run the middleware's client side, given with
``layer_client``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar, Generic, Never, TypeVar

from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect.context import Context, Tag
from pyfect.effect import context, provide_context, succeed
from pyfect.layer import Layer
from pyfect.layer import effect_context as layer_effect_context
from pyfect.schema import Codec, Top
from pyfect.scope import Scope

if TYPE_CHECKING:
    from pyfect.http.headers import Headers
    from pyfect.rpc._rpc import AnyRpc, ServerClient
    from pyfect.rpc.message import Request, RequestId

P_co = TypeVar("P_co", covariant=True, default=Never)
E_co = TypeVar("E_co", covariant=True, default=Never)
R_co = TypeVar("R_co", covariant=True, default=Never)


class SuccessValue:
    """What a handler's effect succeeds with, seen by a middleware: an
    opaque value it must pass on."""

    __slots__ = ()


class Unhandled(Exception):
    """The errors of a handler a middleware does not know (opaque)."""


@dataclass(frozen=True, slots=True)
class MiddlewareOptions:
    """The request a middleware runs for: the ``client``, ``request_id``,
    ``rpc``, decoded ``payload`` and ``headers``."""

    client: ServerClient
    request_id: RequestId
    rpc: AnyRpc
    payload: object
    headers: Headers


type MiddlewareFn[P, E, R] = Callable[
    [Effect[SuccessValue, Unhandled | E, P], MiddlewareOptions],
    Effect[SuccessValue, Unhandled | E, R | Scope],
]
"""A middleware: gets the handler's effect (which needs what the
middleware provides) and returns the effect to run instead."""


class RpcMiddleware(Tag[MiddlewareFn[P_co, E_co, R_co]], Generic[P_co, E_co, R_co]):
    """A middleware tag providing ``P`` to the handlers, failing with ``E``
    (encoded by ``error``) and needing ``R``. The class keyword
    ``required_for_client`` makes a client of its RPCs run its client
    side."""

    error: Codec[E_co, Any, Never, Never] | None = None
    required_for_client: ClassVar[bool] = False

    def __init_subclass__(cls, *, required_for_client: bool = False, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        if required_for_client:
            cls.required_for_client = True

    @classmethod
    def errors(cls) -> tuple[Top, ...]:
        """The error schema, as a tuple (empty without one)."""
        error = cls.error
        return () if error is None else (error.__codec__(),)


type AnyMiddleware = type[RpcMiddleware[Any, Any, Any]]


# --- client ------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ClientMiddlewareOptions:
    """A request a client is about to send for ``rpc``; ``next`` sends it on
    (to the next client middleware, then the protocol)."""

    rpc: AnyRpc
    request: Request
    next: Callable[[Request], Effect[SuccessValue, Unhandled]]


type ClientMiddlewareFn[E, R] = Callable[
    [ClientMiddlewareOptions], Effect[SuccessValue, Unhandled | E, R]
]


class ForClient[M]:
    """The client side of the middleware ``M`` (type-level marker)."""

    @property
    def middleware(self) -> M:
        raise TypeError("ForClient is a type-level marker")


_client_tags: dict[str, type[Tag[Any]]] = {}


def client_tag(middleware: AnyMiddleware) -> type[Tag[Any]]:
    """The tag holding ``middleware``'s client function, keyed
    ``<key>/Client`` as Effect keys it."""
    key = f"{middleware.key}/Client"
    found = _client_tags.get(key)
    if found is None:
        found = type(f"{middleware.__name__}Client", (Tag,), {}, key=key)
        _client_tags[key] = found
    return found


def layer_client[M: RpcMiddleware[Any, Any, Any], E, R](
    middleware: type[M], service: ClientMiddlewareFn[E, R]
) -> Layer[ForClient[M], Never, R]:
    """The client side of ``middleware``: runs around each request a client
    of its RPCs sends (Effect's ``RpcMiddleware.layerClient``)."""
    return layer_client_effect(middleware, succeed(service))


def layer_client_effect[M: RpcMiddleware[Any, Any, Any], E, R, EX, RX](
    middleware: type[M], made: Effect[ClientMiddlewareFn[E, R], EX, RX]
) -> Layer[ForClient[M], EX, R | RX]:
    """``layer_client`` with the client middleware made by an effect; it
    runs with the services of the layer's context."""
    require_effect(made, "made")

    def build(fn: ClientMiddlewareFn[E, R]) -> Effect[Context[Any], Never, Any]:
        def with_services(services: Context[Any]) -> Context[Any]:
            kept = Context({t: s for t, s in services.map_unsafe.items() if t is not Scope})

            def run(options: ClientMiddlewareOptions) -> Effect[SuccessValue, Any, Any]:
                return fn(options).pipe(provide_context(kept))

            return Context({client_tag(middleware): run})

        return context().map(with_services)

    return layer_effect_context(made.flat_map(build))


__all__ = [
    "AnyMiddleware",
    "ClientMiddlewareFn",
    "ClientMiddlewareOptions",
    "ForClient",
    "MiddlewareFn",
    "MiddlewareOptions",
    "RpcMiddleware",
    "SuccessValue",
    "Unhandled",
    "client_tag",
    "layer_client",
    "layer_client_effect",
]
