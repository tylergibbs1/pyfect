"""Entities (Effect's ``Entity``): a type name and the RPCs its instances
answer, addressed by id across a cluster.

An entity is a class whose attributes are its RPCs::

    class Counter(Entity, type="Counter"):
        increment = rpc.make("Increment", payload=S.Int, success=S.Int)

A client of the entity (``Counter.client()``, an effect needing
``Sharding``) gives, per entity id, an instance of the class on which each
RPC attribute is the method calling it; its calls fail with the RPC's
errors or the cluster's ``MailboxFull``, ``AlreadyProcessingMessage``,
``PersistenceError`` and ``EntityNotAssignedToRunner``.
"""

from __future__ import annotations

import builtins
import types
from collections.abc import Callable, Mapping
from dataclasses import replace
from typing import Any, ClassVar, Never, Self, cast

from pyfect import layer as layer_
from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect.cluster.cluster_error import (
    AlreadyProcessingMessage,
    EntityNotAssignedToRunner,
    MailboxFull,
    PersistenceError,
)
from pyfect.cluster.cluster_schema import ShardGroup
from pyfect.cluster.entity._handlers import (
    Concurrency,
    EntityHandlers,
    EntityOptions,
    parse_options,
)
from pyfect.cluster.entity._queue import Behaviour, queue_handlers
from pyfect.cluster.entity._services import CurrentAddress, CurrentRunnerAddress
from pyfect.cluster.entity_id import EntityId
from pyfect.cluster.entity_type import EntityType
from pyfect.cluster.shard_id import ShardId
from pyfect.cluster.sharding import Sharding
from pyfect.context import Context, TagLike
from pyfect.duration import Duration
from pyfect.effect import context, die, gen, succeed
from pyfect.layer import Layer
from pyfect.rpc._rpc import AnyRpc, ClientErrors, HandlerEntry, RpcRequest, handler_tag
from pyfect.rpc.group import RpcGroup
from pyfect.schedule import Schedule
from pyfect.scope import Scope

type ClusterClientError = (
    MailboxFull | AlreadyProcessingMessage | PersistenceError | EntityNotAssignedToRunner
)
"""What an entity client's calls fail with besides the RPC's own errors."""

type _Activation = Scope | CurrentAddress | CurrentRunnerAddress


def _rpc_attributes(cls: builtins.type[Any]) -> dict[str, AnyRpc]:
    """The class's RPC attributes by name, the most derived winning."""
    return {
        name: value
        for klass in reversed(cls.__mro__)
        for name, value in vars(klass).items()
        if isinstance(value, AnyRpc)
    }


class Entity(ClientErrors[ClusterClientError]):
    """An entity type: subclass it with the RPCs as attributes and
    ``type=`` its name (the class name when left out)."""

    type: ClassVar[EntityType]
    rpcs: ClassVar[Mapping[str, AnyRpc]] = {}
    annotations: ClassVar[Context[Any]] = Context.empty()
    protocol: ClassVar[builtins.type[RpcGroup]]
    _rpc_methods: dict[str, Any]

    def __init_subclass__(
        cls,
        *,
        type: str | None = None,
        annotations: Context[Any] | None = None,
        rpc_annotations: Context[Any] | None = None,
        **kwargs: Any,
    ) -> None:
        """``annotations`` annotate the entity (``ShardGroup``, ...);
        ``rpc_annotations`` annotate each of its RPCs, unless the RPC has
        its own value (Effect's ``annotateRpcs``)."""
        super().__init_subclass__(**kwargs)
        if type is not None:
            cls.type = EntityType(type)
        elif "type" not in {k for klass in cls.__mro__[1:] for k in vars(klass)}:
            cls.type = EntityType(cls.__name__)
        if annotations is not None:
            cls.annotations = cls.annotations.merge(annotations)
        attributes = _rpc_attributes(cls)
        if rpc_annotations is not None:
            for name, rpc in attributes.items():
                annotated = replace(rpc, annotations=rpc_annotations.merge(rpc.annotations))
                setattr(cls, name, annotated)
                attributes[name] = annotated
        cls.rpcs = {rpc.tag: rpc for rpc in attributes.values()}
        cls.protocol = builtins.type(
            f"{cls.__name__}Protocol", (RpcGroup,), {rpc.tag: rpc for rpc in attributes.values()}
        )

    # --- annotations --------------------------------------------------------------------

    @classmethod
    def _derive(cls, **kwargs: Context[Any]) -> builtins.type[Self]:
        derived = types.new_class(cls.__name__, (cls,), dict(kwargs))
        derived.__module__ = cls.__module__
        derived.__qualname__ = cls.__qualname__
        return derived

    @classmethod
    def annotate[A, T](cls, tag: TagLike[A, T], value: A) -> builtins.type[Self]:
        """This entity with ``value`` for ``tag`` in its annotations."""
        return cls._derive(annotations=Context.make(tag, value))

    @classmethod
    def annotate_merge(cls, annotations: Context[Any]) -> builtins.type[Self]:
        return cls._derive(annotations=annotations)

    @classmethod
    def annotate_rpcs[A, T](cls, tag: TagLike[A, T], value: A) -> builtins.type[Self]:
        """This entity with ``value`` for ``tag`` on each RPC that has no
        value of its own."""
        return cls._derive(rpc_annotations=Context.make(tag, value))

    @classmethod
    def annotate_rpcs_merge(cls, annotations: Context[Any]) -> builtins.type[Self]:
        return cls._derive(rpc_annotations=annotations)

    # --- addressing ---------------------------------------------------------------------

    @classmethod
    def get_shard_group(cls, entity_id: EntityId) -> str:
        """The shard group of ``entity_id`` (``ShardGroup``, ``"default"``
        unless annotated)."""
        return cls.annotations.get(ShardGroup)(entity_id)

    @classmethod
    def get_shard_id(cls, entity_id: EntityId) -> Effect[ShardId, Never, Sharding]:
        return Sharding().map(
            lambda sharding: sharding.get_shard_id(entity_id, cls.get_shard_group(entity_id))
        )

    @classmethod
    def client(cls) -> Effect[Callable[[str], Self], Never, Sharding]:
        """A function giving the client of an entity id."""
        return Sharding().flat_map(lambda sharding: sharding.make_client(cls))

    # --- handlers -----------------------------------------------------------------------

    @classmethod
    def handlers(cls) -> EntityHandlers[Self]:
        """No handlers yet: add one per RPC with ``handle``."""
        return EntityHandlers(cls, {})

    @classmethod
    def _missing_message(cls, handlers: EntityHandlers[Any, Any]) -> str | None:
        missing = handlers.missing()
        if not missing:
            return None
        return f"the entity {cls.type} has no handler for {', '.join(missing)}"

    @classmethod
    def to_handlers(
        cls, build: Effect[EntityHandlers[Any, Any], Never, Any]
    ) -> Effect[Context[Any], Never, Any]:
        """The handler services of the entity's ``protocol`` (Effect's
        ``RpcGroup.toHandlers``): each handler gets the entity ``Request``
        (the RPC request's payload) and runs with the services of the
        caller of this effect."""
        require_effect(build, "build")

        @gen
        def make():
            services = yield from context()
            handlers = yield from build
            message = cls._missing_message(handlers)
            if message is not None:
                return (yield from die(ValueError(message)))
            kept = Context({t: s for t, s in services.map_unsafe.items() if t is not Scope})
            entries: dict[Any, Any] = {}
            for tag, rpc in cls.rpcs.items():
                handler = handlers.by_tag[tag]
                entries[handler_tag(rpc)] = HandlerEntry(tag, _payload_handler(handler), kept)
            return Context(entries)

        return make

    # --- layers ------------------------------------------------------------------------

    @classmethod
    def to_layer[R](
        cls,
        handlers: EntityHandlers[Self, R],
        /,
        *,
        max_idle_time: Duration | None = None,
        concurrency: Concurrency = 1,
        mailbox_capacity: Concurrency | None = None,
        mailbox_metrics: bool | None = None,
        disable_fatal_defects: bool = False,
        defect_retry_policy: Schedule[Any, Any, Any, Any] | None = None,
        span_attributes: Mapping[str, str] | None = None,
    ) -> Layer[Never, Never, R | Sharding]:
        """Register the entity's ``handlers`` with ``Sharding`` (Effect's
        ``toLayer``). An RPC without a handler is a ``ValueError``."""
        message = cls._missing_message(handlers)
        if message is not None:
            raise ValueError(message)
        options = parse_options(
            max_idle_time=max_idle_time,
            concurrency=concurrency,
            mailbox_capacity=mailbox_capacity,
            mailbox_metrics=mailbox_metrics,
            disable_fatal_defects=disable_fatal_defects,
            defect_retry_policy=defect_retry_policy,
            span_attributes=span_attributes,
        )
        return cls._register(succeed(handlers), options)

    @classmethod
    def to_layer_effect[RR, RX](
        cls,
        build: Effect[EntityHandlers[Self, RR], Never, RX | _Activation],
        /,
        *,
        max_idle_time: Duration | None = None,
        concurrency: Concurrency = 1,
        mailbox_capacity: Concurrency | None = None,
        mailbox_metrics: bool | None = None,
        disable_fatal_defects: bool = False,
        defect_retry_policy: Schedule[Any, Any, Any, Any] | None = None,
        span_attributes: Mapping[str, str] | None = None,
    ) -> Layer[Never, Never, RR | RX | Sharding]:
        """``to_layer`` with the handlers made by ``build``, which runs each
        time an entity starts, with its ``CurrentAddress``,
        ``CurrentRunnerAddress`` and activation ``Scope``."""
        require_effect(build, "build")
        options = parse_options(
            max_idle_time=max_idle_time,
            concurrency=concurrency,
            mailbox_capacity=mailbox_capacity,
            mailbox_metrics=mailbox_metrics,
            disable_fatal_defects=disable_fatal_defects,
            defect_retry_policy=defect_retry_policy,
            span_attributes=span_attributes,
        )
        return cls._register(cast("Effect[EntityHandlers[Any, Any], Never, Any]", build), options)

    @classmethod
    def to_layer_queue[R](
        cls,
        behaviour: Behaviour[R],
        /,
        *,
        max_idle_time: Duration | None = None,
        mailbox_capacity: Concurrency | None = None,
        mailbox_metrics: bool | None = None,
        disable_fatal_defects: bool = False,
        defect_retry_policy: Schedule[Any, Any, Any, Any] | None = None,
        span_attributes: Mapping[str, str] | None = None,
    ) -> Layer[Never, Never, R | Sharding]:
        """Register the entity served by ``behaviour``, which takes each
        request from a mailbox queue and answers it with a ``Replier``
        (Effect's ``toLayerQueue``). It is forked when an entity starts,
        and requests run concurrently."""
        options = parse_options(
            max_idle_time=max_idle_time,
            concurrency="unbounded",
            mailbox_capacity=mailbox_capacity,
            mailbox_metrics=mailbox_metrics,
            disable_fatal_defects=disable_fatal_defects,
            defect_retry_policy=defect_retry_policy,
            span_attributes=span_attributes,
        )
        return cls._register(queue_handlers(cls, behaviour), options)

    @classmethod
    def to_layer_queue_effect[R, RX](
        cls,
        build: Effect[Behaviour[R], Never, RX | _Activation],
        /,
        *,
        max_idle_time: Duration | None = None,
        mailbox_capacity: Concurrency | None = None,
        mailbox_metrics: bool | None = None,
        disable_fatal_defects: bool = False,
        defect_retry_policy: Schedule[Any, Any, Any, Any] | None = None,
        span_attributes: Mapping[str, str] | None = None,
    ) -> Layer[Never, Never, R | RX | Sharding]:
        """``to_layer_queue`` with the behaviour made by ``build`` when an
        entity starts."""
        require_effect(build, "build")
        options = parse_options(
            max_idle_time=max_idle_time,
            concurrency="unbounded",
            mailbox_capacity=mailbox_capacity,
            mailbox_metrics=mailbox_metrics,
            disable_fatal_defects=disable_fatal_defects,
            defect_retry_policy=defect_retry_policy,
            span_attributes=span_attributes,
        )
        handlers = build.flat_map(lambda behaviour: queue_handlers(cls, behaviour))
        return cls._register(handlers, options)

    @classmethod
    def _register(
        cls, build: Effect[EntityHandlers[Any, Any], Never, Any], options: EntityOptions
    ) -> Layer[Never, Never, Any]:
        return layer_.effect_discard(
            Sharding().flat_map(lambda sharding: sharding.register_entity(cls, build, options))
        )


def _payload_handler(handler: Callable[[Any], Any]) -> Callable[[RpcRequest[Any]], Any]:
    def run(request: RpcRequest[Any]) -> Any:
        return handler(request.payload)

    return run


__all__ = ["ClusterClientError", "Entity"]
