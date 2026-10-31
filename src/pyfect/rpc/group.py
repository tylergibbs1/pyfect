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

from collections.abc import Callable, Mapping
from typing import Any, ClassVar, Never, Protocol, Self, cast, overload

from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect.context import Context
from pyfect.deferred import Deferred
from pyfect.effect import context, die, provide_context, succeed
from pyfect.errors import Done
from pyfect.layer import Layer
from pyfect.layer import effect_context as layer_effect_context
from pyfect.queue import Dequeue
from pyfect.rpc._rpc import AnyRpc, HandlerEntry, Rpc, RpcRequest, StreamRpc, handler_tag
from pyfect.rpc.middleware import RpcMiddleware
from pyfect.scope import Scope
from pyfect.stream import Stream


class HandlersFor[G]:
    """What a server of the group ``G`` needs: a handler for each of its
    RPCs (type-level marker; Effect's ``Rpc.ToHandler``)."""

    @property
    def group(self) -> G:
        raise TypeError("HandlersFor is a type-level marker")


type HandlerFn = Callable[[RpcRequest[Any]], Any]


class Handlers[G, R = Never]:
    """The handlers of the group ``G`` so far, needing ``R``. Immutable:
    ``handle`` gives a new one."""

    __slots__ = ("_by_tag", "group")

    def __init__(self, group: type[RpcGroup], by_tag: Mapping[str, HandlerFn]) -> None:
        self.group = group
        self._by_tag = dict(by_tag)

    @property
    def by_tag(self) -> Mapping[str, HandlerFn]:
        return self._by_tag

    @overload
    def handle[P, S, E](
        self, rpc: Rpc[P, S, E, Never], /
    ) -> Bound[G, RpcRequest[P], S, E, Never, R]: ...
    @overload
    def handle[P, S, E, MP, ME, MT](
        self, rpc: Rpc[P, S, E, RpcMiddleware[MP, ME, Any], MT], /
    ) -> Bound[G, RpcRequest[P], S, E | ME, MP, R | MT]: ...
    @overload
    def handle[P, A, E](
        self, rpc: StreamRpc[P, A, E, Never], /
    ) -> StreamBound[G, RpcRequest[P], A, E, Never, R]: ...
    @overload
    def handle[P, A, E, MP, ME, MT](
        self, rpc: StreamRpc[P, A, E, RpcMiddleware[MP, ME, Any], MT], /
    ) -> StreamBound[G, RpcRequest[P], A, E | ME, MP, R | MT]: ...
    def handle(self, rpc: AnyRpc, /) -> Any:
        """The slot of ``rpc``'s handler: call it with the handler, which
        gets the request (payload, headers, client, ...) and returns the
        effect to run (for a stream RPC, a stream or a scoped queue). The
        services ``rpc``'s middleware provides are removed from the
        handler's requirements, and the middleware is required instead."""
        if self.group.rpcs.get(rpc.tag) is not rpc:
            raise ValueError(f"{rpc.tag!r} is not an RPC of {self.group.__name__}")
        return _Slot(self, rpc)

    def _register(self, rpc: AnyRpc, handler: HandlerFn) -> Handlers[Any, Any]:
        return Handlers(self.group, {**self._by_tag, rpc.tag: handler})


class _Slot:
    __slots__ = ("handlers", "rpc")

    def __init__(self, handlers: Handlers[Any, Any], rpc: AnyRpc) -> None:
        self.handlers = handlers
        self.rpc = rpc

    def __call__(self, handler: HandlerFn, /) -> Handlers[Any, Any]:
        return self.handlers._register(self.rpc, handler)  # pyright: ignore[reportPrivateUsage]


class Bound[G, X, S, E, MP, RR](Protocol):
    """The handler slot of a unary RPC: request ``X``, success ``S``,
    errors ``E``; its middleware provides ``MP``; ``RR`` is what the
    handlers need so far. They are fixed by ``handle``, before the handler
    is seen (in one call ``MP`` would be solved from the handler too)."""

    @overload
    def __call__(
        self, handler: Callable[[X], Effect[S | Deferred[S, E], E, MP]], /
    ) -> Handlers[G, RR]: ...
    @overload
    def __call__[R1](
        self, handler: Callable[[X], Effect[S | Deferred[S, E], E, R1 | MP]], /
    ) -> Handlers[G, RR | R1]: ...


class StreamBound[G, X, A, E, MP, RR](Protocol):
    """The handler slot of a stream RPC (see ``Bound``): the handler gives
    a stream, or a scoped queue that ends with ``Done``."""

    @overload
    def __call__(self, handler: Callable[[X], Stream[A, E, MP]], /) -> Handlers[G, RR]: ...
    @overload
    def __call__[R1](
        self, handler: Callable[[X], Stream[A, E, R1 | MP]], /
    ) -> Handlers[G, RR | R1]: ...
    @overload
    def __call__(
        self, handler: Callable[[X], Effect[Dequeue[A, E | Done], E, MP | Scope]], /
    ) -> Handlers[G, RR]: ...
    @overload
    def __call__[R1](
        self, handler: Callable[[X], Effect[Dequeue[A, E | Done], E, R1 | MP | Scope]], /
    ) -> Handlers[G, RR | R1]: ...


class RpcGroup:
    """A group of RPCs: subclass it with the RPCs as attributes."""

    rpcs: ClassVar[Mapping[str, AnyRpc]] = {}
    _rpc_methods: dict[str, Any]

    def __init_subclass__(cls, **kwargs: Any) -> None:
        super().__init_subclass__(**kwargs)
        found: dict[str, AnyRpc] = {}
        for klass in reversed(cls.__mro__):
            for value in vars(klass).values():
                if isinstance(value, AnyRpc):
                    found[value.tag] = value
        cls.rpcs = found

    @classmethod
    def handlers(cls) -> Handlers[Self]:
        """No handlers yet: add one per RPC with ``handle``."""
        return Handlers(cls, {})

    @classmethod
    def to_layer[R](cls, handlers: Handlers[Self, R], /) -> Layer[HandlersFor[Self], Never, R]:
        """The layer of the group's handlers (Effect's ``toLayer``). Each
        handler runs with the services of the layer's context. An RPC left
        without a handler is a ``ValueError`` here (Effect rejects it at
        compile time; pyright cannot name the RPCs not yet handled)."""
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
        cls, handlers: Effect[Handlers[Self, RR], EX, RR], /
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


class HandlerOf[T]:
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


__all__ = [
    "Bound",
    "HandlerFn",
    "HandlerOf",
    "Handlers",
    "HandlersFor",
    "RpcGroup",
    "StreamBound",
    "access_handler",
    "to_layer_handler",
]
