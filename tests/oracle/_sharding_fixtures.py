"""The sharding layers and storage variants Effect's ``Sharding.test.ts``
builds its cases on (``TestSharding``, ``CappedSharding``,
``UnregisteredSharding``, ``Layer.updateService`` over the storage), shared
by the ``test_sharding*`` modules."""

from __future__ import annotations

import copy
from collections.abc import Callable
from dataclasses import replace
from typing import Any, Never

import pyfect as fx
from pyfect import metric
from pyfect.cluster import (
    message_storage,
    runner_health,
    runner_storage,
    runners,
    sharding,
    sharding_config,
)
from pyfect.cluster.entity_address import EntityAddress
from pyfect.cluster.entity_id import EntityId
from pyfect.cluster.envelope import make_request
from pyfect.cluster.message import OutgoingRequest
from pyfect.cluster.message_storage import MessageStorage, MessageStorageService
from pyfect.cluster.sharding_config import ShardingConfig
from pyfect.context import Context
from pyfect.duration import millis

from ._cluster_entities import TestEntity, test_entity_no_state, test_entity_state_layer

test_config = sharding_config.layer(
    replace(
        sharding_config.DEFAULTS,
        entity_mailbox_capacity=10,
        entity_termination_timeout=millis(0),
        entity_message_poll_interval=millis(5000),
        send_retry_interval=millis(100),
        refresh_assignments_interval=millis(0),
    )
)

test_sharding_without_state = (
    test_entity_no_state.pipe(fx.layer.provide_merge(sharding.layer))
    .pipe(fx.layer.provide(runner_health.layer_noop))
    .pipe(fx.layer.provide(runner_storage.layer_memory))
)

test_sharding_without_runners = test_sharding_without_state.pipe(
    fx.layer.provide_merge(test_entity_state_layer)
)

test_sharding_without_storage = test_sharding_without_runners.pipe(
    fx.layer.provide(runners.layer_noop)
).pipe(fx.layer.provide(test_config))

restart_env = test_sharding_without_state.pipe(fx.layer.provide(runners.layer_noop)).pipe(
    fx.layer.provide(test_config)
)
"""A runner over storage and entity state that outlive it."""

restart_storage = fx.layer.merge(
    message_storage.layer_memory.pipe(fx.layer.provide(test_config)), test_entity_state_layer
)

test_sharding = test_sharding_without_storage.pipe(
    fx.layer.provide_merge(message_storage.layer_memory)
).pipe(fx.layer.provide(test_config))


# --- storage and config variants -------------------------------------------------------------


def make_config(**changes: Any) -> fx.Layer[ShardingConfig]:
    defaults: dict[str, Any] = {
        "entity_mailbox_capacity": 10,
        "entity_termination_timeout": millis(0),
        "entity_message_poll_interval": millis(5000),
        "send_retry_interval": millis(100),
        "refresh_assignments_interval": millis(0),
    }
    return sharding_config.layer(replace(sharding_config.DEFAULTS, **(defaults | changes)))


def patched[S](service: S, **methods: Callable[..., Any]) -> S:
    """``service`` with ``methods`` replaced, sharing its state (Effect's
    ``{ ...storage, method }``)."""
    patched: Any = copy.copy(service)
    namespace: dict[str, Any] = {"__slots__": ()}
    for name, method in methods.items():
        namespace[name] = _delegate(method)
    patched.__class__ = type("Patched", (type(service),), namespace)
    return patched


def _delegate(method: Callable[..., Any]) -> Callable[..., Any]:
    def call(_self: object, *args: Any, **kwargs: Any) -> Any:
        return method(*args, **kwargs)

    return call


def update_storage(
    transform: Callable[[MessageStorageService], MessageStorageService],
) -> fx.Layer[MessageStorage, Never, MessageStorage]:
    """Effect's ``Layer.updateService(MessageStorage, transform)``."""
    return fx.layer.effect(MessageStorage, MessageStorage().map(transform))


def capped(
    transform: Callable[[MessageStorageService], MessageStorageService] | None = None,
    **changes: Any,
) -> fx.Layer[Any, Never, Never]:
    config = make_config(**changes)
    built = test_sharding_without_runners.pipe(fx.layer.provide(runners.layer_noop)).pipe(
        fx.layer.provide(config)
    )
    if transform is not None:
        built = built.pipe(fx.layer.provide(update_storage(transform)))
    return built.pipe(fx.layer.provide_merge(message_storage.layer_memory)).pipe(
        fx.layer.provide(config)
    )


def unregistered(**changes: Any) -> fx.Layer[Any, Never, Never]:
    config = make_config(**changes)
    return (
        sharding.layer.pipe(fx.layer.provide(runner_storage.layer_memory))
        .pipe(fx.layer.provide(runner_health.layer_noop))
        .pipe(fx.layer.provide(runners.layer_noop))
        .pipe(fx.layer.provide_merge(message_storage.layer_memory))
        .pipe(fx.layer.provide(config))
    )


def without_storage_updated(
    transform: Callable[[MessageStorageService], MessageStorageService],
) -> fx.Layer[Any, Never, Never]:
    return (
        test_sharding_without_storage.pipe(fx.layer.provide(update_storage(transform)))
        .pipe(fx.layer.provide_merge(message_storage.layer_memory))
        .pipe(fx.layer.provide(test_config))
    )


def series(registry: dict[Any, Any], metric_id: str) -> list[tuple[Any, Any]]:
    """``(attributes, state)`` of every series of ``metric_id``, sorted by
    attributes, as Effect's tests read ``Metric.snapshotUnsafe``."""
    snapshots = metric.snapshot_unsafe(Context.make(metric.MetricRegistry, registry))
    found = [(dict(s.attributes or {}), s.state) for s in snapshots if s.id == metric_id]
    return sorted(found, key=lambda pair: sorted(pair[0].items()))


@fx.fn
def save_get_user_request(entity_id: str, id: int):
    """Saves a persisted ``GetUser`` request straight to storage, bypassing
    the client, so the storage loop learns about it only from its next
    poll."""
    storage = yield from MessageStorage()
    service = yield from sharding.Sharding()
    rpc = TestEntity.rpcs["GetUser"]
    entity = EntityId(entity_id)
    request_id = yield from service.get_snowflake
    yield from storage.save_request(
        OutgoingRequest(
            envelope=make_request(
                request_id=request_id,
                address=EntityAddress(
                    shard_id=service.get_shard_id(entity, "default"),
                    entity_type=TestEntity.type,
                    entity_id=entity,
                ),
                tag="GetUser",
                payload={"id": id},
            ),
            annotations=rpc.annotations,
            context=Context.empty(),
            rpc=rpc,
            last_received_reply=None,
            respond=lambda _: fx.void,
        )
    )
