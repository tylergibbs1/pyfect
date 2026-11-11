"""An entity's handlers, built one RPC at a time, and the options it is
registered with."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Generic, Literal, Never, TypeVar, cast, overload

from pyfect._core import Effect
from pyfect.cluster.entity._request import Request
from pyfect.deferred import Deferred
from pyfect.duration import Duration, from_input_unsafe
from pyfect.duration import Input as DurationInput
from pyfect.errors import Done
from pyfect.queue import Dequeue
from pyfect.rpc._rpc import AnyRpc, Rpc, StreamRpc
from pyfect.rpc.middleware import RpcMiddleware
from pyfect.schedule import Schedule
from pyfect.scope import Scope
from pyfect.stream import Stream

if TYPE_CHECKING:
    from pyfect.cluster.entity._entity import Entity

type Concurrency = int | Literal["unbounded"]
type EntityHandlerFn = Callable[[Request[Any]], Any]


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


class EntityHandlers(Generic[G_co, R_co, H]):
    """The handlers of the entity ``G`` so far, needing ``R``; ``H`` is the
    tags of the RPCs still without one, for an entity that lists its tags
    (``Never`` once all have one, and for an entity that does not).
    Immutable: ``handle`` gives a new one."""

    __slots__ = ("_by_tag", "entity")

    def __init__(self, entity: type[Entity[Any]], by_tag: Mapping[str, EntityHandlerFn]) -> None:
        self.entity = entity
        self._by_tag = dict(by_tag)

    @property
    def by_tag(self) -> Mapping[str, EntityHandlerFn]:
        return self._by_tag

    @overload
    def handle[P, S, E1, T: str](
        self, rpc: Rpc[P, S, E1, Never, Never, T], /
    ) -> Bound[G_co, Request[P], S, E1, Never, R_co, T, H]: ...
    @overload
    def handle[P, S, E1, MP, ME, MT, T: str](
        self, rpc: Rpc[P, S, E1, RpcMiddleware[MP, ME, Any], MT, T], /
    ) -> Bound[G_co, Request[P], S, E1 | ME, MP, R_co | MT, T, H]: ...
    @overload
    def handle[P, A, E1, T: str](
        self, rpc: StreamRpc[P, A, E1, Never, Never, T], /
    ) -> StreamBound[G_co, Request[P], A, E1, Never, R_co, T, H]: ...
    @overload
    def handle[P, A, E1, MP, ME, MT, T: str](
        self, rpc: StreamRpc[P, A, E1, RpcMiddleware[MP, ME, Any], MT, T], /
    ) -> StreamBound[G_co, Request[P], A, E1 | ME, MP, R_co | MT, T, H]: ...
    def handle(self, rpc: AnyRpc, /) -> Any:
        """The slot of ``rpc``'s handler: call it with the handler, which
        gets the entity ``Request`` and returns the effect to run (for a
        stream RPC, a stream or a scoped queue). In an entity that lists its
        tags, giving a handler to an RPC that already has one, or is not the
        entity's, is a pyright error."""
        if rpc.tag not in self.entity.rpcs:
            raise ValueError(f"{rpc.tag!r} is not an RPC of the entity {self.entity.type}")
        slot: type[_Slot] = StreamBound if rpc.is_stream else Bound
        return cast("Any", slot(self, rpc.tag))

    def missing(self) -> list[str]:
        """The tags of the entity's RPCs without a handler."""
        return [tag for tag in self.entity.rpcs if tag not in self._by_tag]


class _Slot:
    """Registers the handler it is called with (``Bound`` / ``StreamBound``)."""

    __slots__ = ("_handlers", "_tag")

    def __init__(self, handlers: EntityHandlers[Any, Any, Any], tag: str) -> None:
        self._handlers = handlers
        self._tag = tag

    def __call__(self, handler: EntityHandlerFn, /) -> Any:
        handlers = self._handlers
        return EntityHandlers[Any, Any, Any](
            handlers.entity, {**handlers.by_tag, self._tag: handler}
        )


# Each slot's overloads come in three pairs, by the tags ``H`` still without a
# handler: ``K`` alone (the last), ``K`` among others (pyright solves ``Rest``
# as the others), or ``Never`` (all handled, or a group not listing its tags).
# An RPC already handled matches none. In each pair the first solves a handler
# needing only ``MP``; the second alone would leave ``R1`` Unknown.


class Bound(_Slot, Generic[G_co, X_co, S_contra, E, MP_contra, RR_co, K, H]):
    """The handler slot of a unary RPC of the entity ``G``: request ``X``,
    success ``S``, errors ``E``; its middleware provides ``MP``; ``R`` is
    what the handlers need so far; ``K`` is the RPC's tag and ``H`` the tags
    still without a handler."""

    __slots__ = ()

    @overload
    def __call__(
        self: Bound[G_co, X_co, S_contra, E, MP_contra, RR_co, K, K],
        handler: Callable[[X_co], Effect[S_contra | Deferred[S_contra, E], E, MP_contra]],
        /,
    ) -> EntityHandlers[G_co, RR_co]: ...
    @overload
    def __call__[R1](
        self: Bound[G_co, X_co, S_contra, E, MP_contra, RR_co, K, K],
        handler: Callable[[X_co], Effect[S_contra | Deferred[S_contra, E], E, R1 | MP_contra]],
        /,
    ) -> EntityHandlers[G_co, RR_co | R1]: ...
    @overload
    def __call__[Rest](
        self: Bound[G_co, X_co, S_contra, E, MP_contra, RR_co, K, K | Rest],
        handler: Callable[[X_co], Effect[S_contra | Deferred[S_contra, E], E, MP_contra]],
        /,
    ) -> EntityHandlers[G_co, RR_co, Rest]: ...
    @overload
    def __call__[R1, Rest](
        self: Bound[G_co, X_co, S_contra, E, MP_contra, RR_co, K, K | Rest],
        handler: Callable[[X_co], Effect[S_contra | Deferred[S_contra, E], E, R1 | MP_contra]],
        /,
    ) -> EntityHandlers[G_co, RR_co | R1, Rest]: ...
    @overload
    def __call__(
        self: Bound[G_co, X_co, S_contra, E, MP_contra, RR_co, K, Never],
        handler: Callable[[X_co], Effect[S_contra | Deferred[S_contra, E], E, MP_contra]],
        /,
    ) -> EntityHandlers[G_co, RR_co]: ...
    @overload
    def __call__[R1](
        self: Bound[G_co, X_co, S_contra, E, MP_contra, RR_co, K, Never],
        handler: Callable[[X_co], Effect[S_contra | Deferred[S_contra, E], E, R1 | MP_contra]],
        /,
    ) -> EntityHandlers[G_co, RR_co | R1]: ...
    def __call__(self: Bound[Any, Any, Any, Any, Any, Any, Any, Any], handler: Any, /) -> Any:
        return _Slot.__call__(self, handler)


class StreamBound(_Slot, Generic[G_co, X_co, A_contra, E_contra, MP_contra, RR_co, K, H]):
    """The handler slot of a stream RPC of the entity ``G`` (see
    ``Bound``): the handler gives a stream, or a scoped queue that ends
    with ``Done``."""

    __slots__ = ()

    @overload
    def __call__(
        self: StreamBound[G_co, X_co, A_contra, E_contra, MP_contra, RR_co, K, K],
        handler: Callable[[X_co], Stream[A_contra, E_contra, MP_contra]],
        /,
    ) -> EntityHandlers[G_co, RR_co]: ...
    @overload
    def __call__[R1](
        self: StreamBound[G_co, X_co, A_contra, E_contra, MP_contra, RR_co, K, K],
        handler: Callable[[X_co], Stream[A_contra, E_contra, R1 | MP_contra]],
        /,
    ) -> EntityHandlers[G_co, RR_co | R1]: ...
    @overload
    def __call__(
        self: StreamBound[G_co, X_co, A_contra, E_contra, MP_contra, RR_co, K, K],
        handler: Callable[
            [X_co], Effect[Dequeue[A_contra, E_contra | Done], E_contra, MP_contra | Scope]
        ],
        /,
    ) -> EntityHandlers[G_co, RR_co]: ...
    @overload
    def __call__[R1](
        self: StreamBound[G_co, X_co, A_contra, E_contra, MP_contra, RR_co, K, K],
        handler: Callable[
            [X_co], Effect[Dequeue[A_contra, E_contra | Done], E_contra, R1 | MP_contra | Scope]
        ],
        /,
    ) -> EntityHandlers[G_co, RR_co | R1]: ...
    @overload
    def __call__[Rest](
        self: StreamBound[G_co, X_co, A_contra, E_contra, MP_contra, RR_co, K, K | Rest],
        handler: Callable[[X_co], Stream[A_contra, E_contra, MP_contra]],
        /,
    ) -> EntityHandlers[G_co, RR_co, Rest]: ...
    @overload
    def __call__[R1, Rest](
        self: StreamBound[G_co, X_co, A_contra, E_contra, MP_contra, RR_co, K, K | Rest],
        handler: Callable[[X_co], Stream[A_contra, E_contra, R1 | MP_contra]],
        /,
    ) -> EntityHandlers[G_co, RR_co | R1, Rest]: ...
    @overload
    def __call__[Rest](
        self: StreamBound[G_co, X_co, A_contra, E_contra, MP_contra, RR_co, K, K | Rest],
        handler: Callable[
            [X_co], Effect[Dequeue[A_contra, E_contra | Done], E_contra, MP_contra | Scope]
        ],
        /,
    ) -> EntityHandlers[G_co, RR_co, Rest]: ...
    @overload
    def __call__[R1, Rest](
        self: StreamBound[G_co, X_co, A_contra, E_contra, MP_contra, RR_co, K, K | Rest],
        handler: Callable[
            [X_co], Effect[Dequeue[A_contra, E_contra | Done], E_contra, R1 | MP_contra | Scope]
        ],
        /,
    ) -> EntityHandlers[G_co, RR_co | R1, Rest]: ...
    @overload
    def __call__(
        self: StreamBound[G_co, X_co, A_contra, E_contra, MP_contra, RR_co, K, Never],
        handler: Callable[[X_co], Stream[A_contra, E_contra, MP_contra]],
        /,
    ) -> EntityHandlers[G_co, RR_co]: ...
    @overload
    def __call__[R1](
        self: StreamBound[G_co, X_co, A_contra, E_contra, MP_contra, RR_co, K, Never],
        handler: Callable[[X_co], Stream[A_contra, E_contra, R1 | MP_contra]],
        /,
    ) -> EntityHandlers[G_co, RR_co | R1]: ...
    @overload
    def __call__(
        self: StreamBound[G_co, X_co, A_contra, E_contra, MP_contra, RR_co, K, Never],
        handler: Callable[
            [X_co], Effect[Dequeue[A_contra, E_contra | Done], E_contra, MP_contra | Scope]
        ],
        /,
    ) -> EntityHandlers[G_co, RR_co]: ...
    @overload
    def __call__[R1](
        self: StreamBound[G_co, X_co, A_contra, E_contra, MP_contra, RR_co, K, Never],
        handler: Callable[
            [X_co], Effect[Dequeue[A_contra, E_contra | Done], E_contra, R1 | MP_contra | Scope]
        ],
        /,
    ) -> EntityHandlers[G_co, RR_co | R1]: ...
    def __call__(self: StreamBound[Any, Any, Any, Any, Any, Any, Any, Any], handler: Any, /) -> Any:
        return _Slot.__call__(self, handler)


@dataclass(frozen=True, slots=True, kw_only=True)
class EntityOptions:
    """How an entity runs: an idle entity stops after ``max_idle_time``
    (the sharding default when ``None``), at most ``concurrency`` requests
    at once, ``mailbox_capacity`` requests waiting (the sharding default
    when ``None``); a defect ends every request of the entity unless
    ``disable_fatal_defects``, and the entity restarts on the
    ``defect_retry_policy``."""

    max_idle_time: Duration | None = None
    concurrency: Concurrency = 1
    mailbox_capacity: Concurrency | None = None
    mailbox_metrics: bool | None = None
    disable_fatal_defects: bool = False
    defect_retry_policy: Schedule[Any, Any, Any, Any] | None = None
    span_attributes: Mapping[str, str] = field(default_factory=dict[str, str])


def parse_options(
    *,
    max_idle_time: DurationInput | None,
    concurrency: Concurrency,
    mailbox_capacity: Concurrency | None,
    mailbox_metrics: bool | None,
    disable_fatal_defects: bool,
    defect_retry_policy: Schedule[Any, Any, Any, Any] | None,
    span_attributes: Mapping[str, str] | None,
) -> EntityOptions:
    """The options of ``to_layer``, checked and parsed once."""
    return EntityOptions(
        max_idle_time=None if max_idle_time is None else from_input_unsafe(max_idle_time),
        concurrency=concurrency,
        mailbox_capacity=mailbox_capacity,
        mailbox_metrics=mailbox_metrics,
        disable_fatal_defects=disable_fatal_defects,
        defect_retry_policy=defect_retry_policy,
        span_attributes=dict(span_attributes or {}),
    )


__all__ = [
    "Bound",
    "Concurrency",
    "EntityHandlerFn",
    "EntityHandlers",
    "EntityOptions",
    "StreamBound",
    "parse_options",
]
