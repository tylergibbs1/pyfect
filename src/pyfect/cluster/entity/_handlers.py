"""An entity's handlers, built one RPC at a time, and the options it is
registered with."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, Never, Protocol, overload

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


class EntityHandlers[G, R = Never]:
    """The handlers of the entity ``G`` so far, needing ``R``. Immutable:
    ``handle`` gives a new one."""

    __slots__ = ("_by_tag", "entity")

    def __init__(self, entity: type[Entity], by_tag: Mapping[str, EntityHandlerFn]) -> None:
        self.entity = entity
        self._by_tag = dict(by_tag)

    @property
    def by_tag(self) -> Mapping[str, EntityHandlerFn]:
        return self._by_tag

    @overload
    def handle[P, S, E](
        self, rpc: Rpc[P, S, E, Never], /
    ) -> Bound[G, Request[P], S, E, Never, R]: ...
    @overload
    def handle[P, S, E, MP, ME, MT](
        self, rpc: Rpc[P, S, E, RpcMiddleware[MP, ME, Any], MT], /
    ) -> Bound[G, Request[P], S, E | ME, MP, R | MT]: ...
    @overload
    def handle[P, A, E](
        self, rpc: StreamRpc[P, A, E, Never], /
    ) -> StreamBound[G, Request[P], A, E, Never, R]: ...
    @overload
    def handle[P, A, E, MP, ME, MT](
        self, rpc: StreamRpc[P, A, E, RpcMiddleware[MP, ME, Any], MT], /
    ) -> StreamBound[G, Request[P], A, E | ME, MP, R | MT]: ...
    def handle(self, rpc: AnyRpc, /) -> Any:
        """The slot of ``rpc``'s handler: call it with the handler, which
        gets the entity ``Request`` and returns the effect to run (for a
        stream RPC, a stream or a scoped queue)."""
        if rpc.tag not in self.entity.rpcs:
            raise ValueError(f"{rpc.tag!r} is not an RPC of the entity {self.entity.type}")
        return _Slot(self, rpc.tag)

    def missing(self) -> list[str]:
        """The tags of the entity's RPCs without a handler."""
        return [tag for tag in self.entity.rpcs if tag not in self._by_tag]


class Bound[G, X, S, E, MP, RR](Protocol):
    """The handler slot of a unary RPC of the entity ``G``: request ``X``,
    success ``S``, errors ``E``; its middleware provides ``MP``; ``RR`` is
    what the handlers need so far."""

    @overload
    def __call__(
        self, handler: Callable[[X], Effect[S | Deferred[S, E], E, MP]], /
    ) -> EntityHandlers[G, RR]: ...
    @overload
    def __call__[R1](
        self, handler: Callable[[X], Effect[S | Deferred[S, E], E, R1 | MP]], /
    ) -> EntityHandlers[G, RR | R1]: ...


class StreamBound[G, X, A, E, MP, RR](Protocol):
    """The handler slot of a stream RPC of the entity ``G`` (see
    ``Bound``): the handler gives a stream, or a scoped queue that ends
    with ``Done``."""

    @overload
    def __call__(self, handler: Callable[[X], Stream[A, E, MP]], /) -> EntityHandlers[G, RR]: ...
    @overload
    def __call__[R1](
        self, handler: Callable[[X], Stream[A, E, R1 | MP]], /
    ) -> EntityHandlers[G, RR | R1]: ...
    @overload
    def __call__(
        self, handler: Callable[[X], Effect[Dequeue[A, E | Done], E, MP | Scope]], /
    ) -> EntityHandlers[G, RR]: ...
    @overload
    def __call__[R1](
        self, handler: Callable[[X], Effect[Dequeue[A, E | Done], E, R1 | MP | Scope]], /
    ) -> EntityHandlers[G, RR | R1]: ...


class _Slot:
    __slots__ = ("handlers", "tag")

    def __init__(self, handlers: EntityHandlers[Any, Any], tag: str) -> None:
        self.handlers = handlers
        self.tag = tag

    def __call__(self, handler: EntityHandlerFn, /) -> EntityHandlers[Any, Any]:
        handlers = self.handlers
        return EntityHandlers(handlers.entity, {**handlers.by_tag, self.tag: handler})


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
