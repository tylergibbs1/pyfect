"""Groups of RPCs (Effect's ``RpcGroup``) and their handlers.

A group is a class whose attributes are RPCs::

    class Users(RpcGroup):
        get_user = rpc.make("GetUser", payload=S.Struct(GetUser), success=User)

Its handlers are built one RPC at a time, then made into a layer the
server needs::

    UsersLive = Users.to_layer(
        Users.handlers()
        .handle(Users.get_user)(lambda request: find_user(request.payload["id"]))
    )

A client of the group is an instance of it (``RpcClient.make(Users)``),
on which each RPC attribute is the method calling it.
"""

from __future__ import annotations

import types
from collections.abc import Callable, Mapping
from typing import (
    Any,
    ClassVar,
    Generic,
    Never,
    Self,
    TypeVar,
    cast,
    get_args,
    get_origin,
    overload,
)

from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect.context import Context, ServiceMarker
from pyfect.deferred import Deferred
from pyfect.effect import context, die, provide_context, succeed
from pyfect.errors import Done
from pyfect.layer import Layer
from pyfect.layer import effect_context as layer_effect_context
from pyfect.queue import Dequeue
from pyfect.rpc._rpc import AnyRpc, HandlerEntry, Rpc, RpcRequest, StreamRpc, handler_tag
from pyfect.rpc._tags import Tags_contra, check_listed_tags
from pyfect.rpc.middleware import RpcMiddleware
from pyfect.scope import Scope
from pyfect.stream import Stream


class HandlersFor[G](ServiceMarker):
    """What a server of the group ``G`` needs: a handler for each of its
    RPCs (type-level marker; Effect's ``Rpc.ToHandler``)."""

    @property
    def group(self) -> G:
        raise TypeError("HandlersFor is a type-level marker")


type HandlerFn = Callable[[RpcRequest[Any]], Any]

G_co = TypeVar("G_co", covariant=True)
R_co = TypeVar("R_co", covariant=True, default=Never)
H = TypeVar("H", default=Never)
X_co = TypeVar("X_co", covariant=True)
S_contra = TypeVar("S_contra", contravariant=True)
A_contra = TypeVar("A_contra", contravariant=True)
E = TypeVar("E")
E_contra = TypeVar("E_contra", contravariant=True)
MP_contra = TypeVar("MP_contra", contravariant=True)
K = TypeVar("K")
RR_co = TypeVar("RR_co", covariant=True)
GM_co = TypeVar("GM_co", covariant=True)


class Handlers(Generic[G_co, R_co, H]):
    """The handlers of the group ``G`` so far, needing ``R``; ``H`` is the
    tags of the RPCs still without one, for a group that lists its tags
    (``Never`` once all have one, and for a group that does not). Immutable:
    ``handle`` gives a new one."""

    __slots__ = ("_by_tag", "group")

    def __init__(self, group: type[RpcGroup[Any]], by_tag: Mapping[str, HandlerFn]) -> None:
        self.group = group
        self._by_tag = dict(by_tag)

    @property
    def by_tag(self) -> Mapping[str, HandlerFn]:
        return self._by_tag

    @overload
    def handle[P, S, E1, T: str](
        self, rpc: Rpc[P, S, E1, Never, Never, T], /
    ) -> Bound[G_co, RpcRequest[P], S, E1, Never, R_co, T, H]: ...
    @overload
    def handle[P, S, E1, MP, ME, MT, T: str](
        self, rpc: Rpc[P, S, E1, RpcMiddleware[MP, ME, Any], MT, T], /
    ) -> Bound[G_co, RpcRequest[P], S, E1 | ME, MP, R_co | MT, T, H]: ...
    @overload
    def handle[P, A, E1, T: str](
        self, rpc: StreamRpc[P, A, E1, Never, Never, T], /
    ) -> StreamBound[G_co, RpcRequest[P], A, E1, Never, R_co, T, H]: ...
    @overload
    def handle[P, A, E1, MP, ME, MT, T: str](
        self, rpc: StreamRpc[P, A, E1, RpcMiddleware[MP, ME, Any], MT, T], /
    ) -> StreamBound[G_co, RpcRequest[P], A, E1 | ME, MP, R_co | MT, T, H]: ...
    def handle(self, rpc: AnyRpc, /) -> Any:
        """The slot of ``rpc``'s handler: call it with the handler, which
        gets the request (payload, headers, client, ...) and returns the
        effect to run (for a stream RPC, a stream or a scoped queue). The
        services ``rpc``'s middleware provides are removed from the
        handler's requirements, and the middleware is required instead.
        In a group that lists its tags, giving a handler to an RPC that
        already has one, or is not in the group, is a pyright error."""
        if self.group.rpcs.get(rpc.tag) is not rpc:
            raise ValueError(f"{rpc.tag!r} is not an RPC of {self.group.__name__}")
        slot: type[_Slot] = StreamBound if rpc.is_stream else Bound
        return cast("Any", slot(self, rpc))

    def _register(self, rpc: AnyRpc, handler: HandlerFn) -> Handlers[Any, Any, Any]:
        return Handlers(self.group, {**self._by_tag, rpc.tag: handler})


class _Slot:
    """Registers the handler it is called with (``Bound`` / ``StreamBound``)."""

    __slots__ = ("_handlers", "_rpc")

    def __init__(self, handlers: Handlers[Any, Any, Any], rpc: AnyRpc) -> None:
        self._handlers = handlers
        self._rpc = rpc

    def __call__(self, handler: HandlerFn, /) -> Any:
        return self._handlers._register(self._rpc, handler)  # pyright: ignore[reportPrivateUsage]


# Each slot's overloads come in three pairs, by the tags ``H`` still without a
# handler: ``K`` alone (the last), ``K`` among others (pyright solves ``Rest``
# as the others), or ``Never`` (all handled, or a group not listing its tags).
# An RPC already handled matches none. In each pair the first solves a handler
# needing only ``MP``; the second alone would leave ``R1`` Unknown.


class Bound(_Slot, Generic[G_co, X_co, S_contra, E, MP_contra, RR_co, K, H]):
    """The handler slot of a unary RPC: request ``X``, success ``S``,
    errors ``E``; its middleware provides ``MP``; ``R`` is what the
    handlers need so far; ``K`` is the RPC's tag and ``H`` the tags still
    without a handler. They are fixed by ``handle``, before the handler is
    seen (in one call ``MP`` would be solved from the handler too)."""

    __slots__ = ()

    @overload
    def __call__(
        self: Bound[G_co, X_co, S_contra, E, MP_contra, RR_co, K, K],
        handler: Callable[[X_co], Effect[S_contra | Deferred[S_contra, E], E, MP_contra]],
        /,
    ) -> Handlers[G_co, RR_co]: ...
    @overload
    def __call__[R1](
        self: Bound[G_co, X_co, S_contra, E, MP_contra, RR_co, K, K],
        handler: Callable[[X_co], Effect[S_contra | Deferred[S_contra, E], E, R1 | MP_contra]],
        /,
    ) -> Handlers[G_co, RR_co | R1]: ...
    @overload
    def __call__[Rest](
        self: Bound[G_co, X_co, S_contra, E, MP_contra, RR_co, K, K | Rest],
        handler: Callable[[X_co], Effect[S_contra | Deferred[S_contra, E], E, MP_contra]],
        /,
    ) -> Handlers[G_co, RR_co, Rest]: ...
    @overload
    def __call__[R1, Rest](
        self: Bound[G_co, X_co, S_contra, E, MP_contra, RR_co, K, K | Rest],
        handler: Callable[[X_co], Effect[S_contra | Deferred[S_contra, E], E, R1 | MP_contra]],
        /,
    ) -> Handlers[G_co, RR_co | R1, Rest]: ...
    @overload
    def __call__(
        self: Bound[G_co, X_co, S_contra, E, MP_contra, RR_co, K, Never],
        handler: Callable[[X_co], Effect[S_contra | Deferred[S_contra, E], E, MP_contra]],
        /,
    ) -> Handlers[G_co, RR_co]: ...
    @overload
    def __call__[R1](
        self: Bound[G_co, X_co, S_contra, E, MP_contra, RR_co, K, Never],
        handler: Callable[[X_co], Effect[S_contra | Deferred[S_contra, E], E, R1 | MP_contra]],
        /,
    ) -> Handlers[G_co, RR_co | R1]: ...
    def __call__(self: Bound[Any, Any, Any, Any, Any, Any, Any, Any], handler: Any, /) -> Any:
        return _Slot.__call__(self, handler)


class StreamBound(_Slot, Generic[G_co, X_co, A_contra, E_contra, MP_contra, RR_co, K, H]):
    """The handler slot of a stream RPC (see ``Bound``): the handler gives
    a stream, or a scoped queue that ends with ``Done``."""

    __slots__ = ()

    @overload
    def __call__(
        self: StreamBound[G_co, X_co, A_contra, E_contra, MP_contra, RR_co, K, K],
        handler: Callable[[X_co], Stream[A_contra, E_contra, MP_contra]],
        /,
    ) -> Handlers[G_co, RR_co]: ...
    @overload
    def __call__[R1](
        self: StreamBound[G_co, X_co, A_contra, E_contra, MP_contra, RR_co, K, K],
        handler: Callable[[X_co], Stream[A_contra, E_contra, R1 | MP_contra]],
        /,
    ) -> Handlers[G_co, RR_co | R1]: ...
    @overload
    def __call__(
        self: StreamBound[G_co, X_co, A_contra, E_contra, MP_contra, RR_co, K, K],
        handler: Callable[
            [X_co], Effect[Dequeue[A_contra, E_contra | Done], E_contra, MP_contra | Scope]
        ],
        /,
    ) -> Handlers[G_co, RR_co]: ...
    @overload
    def __call__[R1](
        self: StreamBound[G_co, X_co, A_contra, E_contra, MP_contra, RR_co, K, K],
        handler: Callable[
            [X_co], Effect[Dequeue[A_contra, E_contra | Done], E_contra, R1 | MP_contra | Scope]
        ],
        /,
    ) -> Handlers[G_co, RR_co | R1]: ...
    @overload
    def __call__[Rest](
        self: StreamBound[G_co, X_co, A_contra, E_contra, MP_contra, RR_co, K, K | Rest],
        handler: Callable[[X_co], Stream[A_contra, E_contra, MP_contra]],
        /,
    ) -> Handlers[G_co, RR_co, Rest]: ...
    @overload
    def __call__[R1, Rest](
        self: StreamBound[G_co, X_co, A_contra, E_contra, MP_contra, RR_co, K, K | Rest],
        handler: Callable[[X_co], Stream[A_contra, E_contra, R1 | MP_contra]],
        /,
    ) -> Handlers[G_co, RR_co | R1, Rest]: ...
    @overload
    def __call__[Rest](
        self: StreamBound[G_co, X_co, A_contra, E_contra, MP_contra, RR_co, K, K | Rest],
        handler: Callable[
            [X_co], Effect[Dequeue[A_contra, E_contra | Done], E_contra, MP_contra | Scope]
        ],
        /,
    ) -> Handlers[G_co, RR_co, Rest]: ...
    @overload
    def __call__[R1, Rest](
        self: StreamBound[G_co, X_co, A_contra, E_contra, MP_contra, RR_co, K, K | Rest],
        handler: Callable[
            [X_co], Effect[Dequeue[A_contra, E_contra | Done], E_contra, R1 | MP_contra | Scope]
        ],
        /,
    ) -> Handlers[G_co, RR_co | R1, Rest]: ...
    @overload
    def __call__(
        self: StreamBound[G_co, X_co, A_contra, E_contra, MP_contra, RR_co, K, Never],
        handler: Callable[[X_co], Stream[A_contra, E_contra, MP_contra]],
        /,
    ) -> Handlers[G_co, RR_co]: ...
    @overload
    def __call__[R1](
        self: StreamBound[G_co, X_co, A_contra, E_contra, MP_contra, RR_co, K, Never],
        handler: Callable[[X_co], Stream[A_contra, E_contra, R1 | MP_contra]],
        /,
    ) -> Handlers[G_co, RR_co | R1]: ...
    @overload
    def __call__(
        self: StreamBound[G_co, X_co, A_contra, E_contra, MP_contra, RR_co, K, Never],
        handler: Callable[
            [X_co], Effect[Dequeue[A_contra, E_contra | Done], E_contra, MP_contra | Scope]
        ],
        /,
    ) -> Handlers[G_co, RR_co]: ...
    @overload
    def __call__[R1](
        self: StreamBound[G_co, X_co, A_contra, E_contra, MP_contra, RR_co, K, Never],
        handler: Callable[
            [X_co], Effect[Dequeue[A_contra, E_contra | Done], E_contra, R1 | MP_contra | Scope]
        ],
        /,
    ) -> Handlers[G_co, RR_co | R1]: ...
    def __call__(self: StreamBound[Any, Any, Any, Any, Any, Any, Any, Any], handler: Any, /) -> Any:
        return _Slot.__call__(self, handler)


class RpcGroup(Generic[Tags_contra]):
    """A group of RPCs: subclass it with the RPCs as attributes. A group
    listing its RPCs' tags, ``class Users(RpcGroup[Literal["GetUser",
    "Users"]])``, has its handlers checked by pyright: ``to_layer`` rejects
    them while an RPC has none (Effect's ``toLayer``). The class is checked
    against the list when it is defined."""

    rpcs: ClassVar[Mapping[str, AnyRpc]] = {}
    _wraps_rpcs: ClassVar[bool] = False
    _rpc_methods: dict[str, Any]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        for base in types.get_original_bases(cls):
            origin = get_origin(base)
            if isinstance(origin, type) and issubclass(origin, RpcGroup) and origin._wraps_rpcs:
                _add_middleware(cls, get_args(base)[0])
        found: dict[str, AnyRpc] = {}
        for klass in reversed(cls.__mro__):
            for value in vars(klass).values():
                if isinstance(value, AnyRpc):
                    found[value.tag] = value
        cls.rpcs = found
        check_listed_tags(cls, RpcGroup, found)

    @classmethod
    def handlers(cls) -> Handlers[Self, Never, Tags_contra]:
        """No handlers yet: add one per RPC with ``handle``."""
        return Handlers(cls, {})

    @classmethod
    def to_layer[R](
        cls, handlers: Handlers[Self, R, Never], /
    ) -> Layer[HandlersFor[Self], Never, R]:
        """The layer of the group's handlers (Effect's ``toLayer``). Each
        handler runs with the services of the layer's context. An RPC left
        without a handler is a pyright error when the group lists its tags
        (``RpcGroup[Literal[...]]``), and a ``ValueError`` here either way."""
        message = cls._missing_handlers(handlers)
        if message is not None:
            raise ValueError(message)
        return cls.to_layer_effect(succeed(handlers))

    @classmethod
    def _missing_handlers(cls, handlers: Handlers[Any, Any]) -> str | None:
        missing = [
            f"{tag} ({cls.__name__}.{_attribute_of(cls, rpc)})"
            for tag, rpc in cls.rpcs.items()
            if tag not in handlers.by_tag
        ]
        if not missing:
            return None
        return f"{cls.__name__} has no handler for {', '.join(missing)}"

    @classmethod
    def to_layer_effect[EX, RR = Never](
        cls, handlers: Effect[Handlers[Self, RR, Never], EX, RR], /
    ) -> Layer[HandlersFor[Self], EX, RR]:
        """``to_layer`` with the handlers made by an effect."""
        require_effect(handlers, "handlers")
        return layer_effect_context(handlers.flat_map(cls._handler_context))

    @classmethod
    def _handler_context(cls, handlers: Handlers[Any, Any]) -> Effect[Context[Any]]:
        message = cls._missing_handlers(handlers)
        if message is not None:
            return die(ValueError(message))

        def entries(services: Context[Any]) -> Context[Any]:
            kept = Context({t: s for t, s in services.map_unsafe.items() if t is not Scope})
            return Context(
                {
                    handler_tag(rpc): HandlerEntry(rpc.tag, handlers.by_tag[rpc.tag], kept)
                    for rpc in cls.rpcs.values()
                }
            )

        return context().map(entries)


def _attribute_of(group: type, rpc: AnyRpc) -> str:
    """The attribute name ``rpc`` has on ``group`` (its tag if none)."""
    for klass in group.__mro__:
        for name, value in vars(klass).items():
            if value is rpc:
                return name
    return rpc.tag


class HandlerOf[T](ServiceMarker):
    """A handler of the RPC ``T`` in the context (type-level marker)."""

    @property
    def rpc(self) -> T:
        raise TypeError("HandlerOf is a type-level marker")


def to_layer_handler[P, S, E, R2](
    rpc: Rpc[P, S, E, Never],
    handler: Callable[[RpcRequest[P]], Effect[S | Deferred[S, E], E, R2]],
) -> Layer[HandlerOf[Rpc[P, S, E]], Never, R2]:
    """The layer of one RPC's handler (Effect's ``toLayerHandler``); it
    runs with the services of the layer's context."""

    def entry(services: Context[Any]) -> Context[Any]:
        kept = Context({t: s for t, s in services.map_unsafe.items() if t is not Scope})
        return Context({handler_tag(rpc): HandlerEntry(rpc.tag, handler, kept)})

    return layer_effect_context(context().map(entry))


def access_handler[P, S, E](
    rpc: Rpc[P, S, E, Never],
) -> Effect[Callable[[RpcRequest[P]], Effect[S, E]], Never, HandlerOf[Rpc[P, S, E]]]:
    """The handler of ``rpc`` from the context, running with its layer's
    services (Effect's ``accessHandler``)."""

    def found(services: Context[Any]) -> Callable[[RpcRequest[P]], Effect[S, E]]:
        entry: HandlerEntry = services.get_unsafe(handler_tag(rpc))

        def run(request: RpcRequest[P]) -> Effect[S, E]:
            return cast("Effect[S, E]", entry.handler(request)).pipe(provide_context(entry.context))

        return run

    return cast(
        "Effect[Callable[[RpcRequest[P]], Effect[S, E]], Never, HandlerOf[Rpc[P, S, E]]]",
        context().map(found),
    )


def _add_middleware(group: type[RpcGroup], middleware: Any) -> None:
    for name, value in list(vars(group).items()):
        if isinstance(value, AnyRpc):
            setattr(group, name, value.with_middleware(middleware))


class RpcGroupWith(RpcGroup[Tags_contra], Generic[GM_co, Tags_contra]):
    """A group whose RPCs are all wrapped by ``GM`` (Effect's
    ``RpcGroup.middleware``)::

        class Users(RpcGroupWith[Auth]):
            get = rpc.make("Users.get", ...)
    """

    _wraps_rpcs: ClassVar[bool] = True


__all__ = [
    "Bound",
    "HandlerFn",
    "HandlerOf",
    "Handlers",
    "HandlersFor",
    "RpcGroup",
    "RpcGroupWith",
    "StreamBound",
    "access_handler",
    "to_layer_handler",
]
