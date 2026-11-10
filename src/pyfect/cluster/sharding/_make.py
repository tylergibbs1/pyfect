"""``Sharding.make`` and ``layer``: wires the loops together in the order
Effect does, so the scope's finalizers run in its shutdown order (hand
the shards off first, then the singletons, clients, runner sync, storage
inbox and shard acquisition, and release every lock last)."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Never

from pyfect import layer as layer_
from pyfect._core import Effect, _Locally
from pyfect.clock import Clock
from pyfect.cluster import _entity_manager, _entity_reaper, cluster_metrics, snowflake
from pyfect.cluster._entity_reaper import EntityReaper
from pyfect.cluster._interruptors import around_entity_type
from pyfect.cluster.cluster_error import (
    AlreadyProcessingMessage,
    EntityNotAssignedToRunner,
    MailboxFull,
    PersistenceError,
)
from pyfect.cluster.entity_id import EntityId
from pyfect.cluster.message import Incoming, Outgoing
from pyfect.cluster.message_storage import NOOP, MessageStorage
from pyfect.cluster.runner import Runner
from pyfect.cluster.runner_health import RunnerHealth
from pyfect.cluster.runner_storage import RunnerStorage
from pyfect.cluster.runners import Runners
from pyfect.cluster.shard_id import ShardId
from pyfect.cluster.sharding_config import ShardingConfig, shard_group_config
from pyfect.cluster.sharding_registration_event import EntityRegistered, ShardingRegistrationEvent
from pyfect.cluster.snowflake import Generator, Snowflake
from pyfect.context import Context
from pyfect.effect import context, gen, succeed, suspend, sync
from pyfect.exit import Exit, Failure
from pyfect.fiber_map import FiberMap
from pyfect.latch import Latch
from pyfect.layer import Layer
from pyfect.logger import log_debug
from pyfect.pubsub import PubSub
from pyfect.scope import Scope, fork_in
from pyfect.stream import Stream, from_pubsub

from ._acquisition import ShardAcquisition
from ._clients import Clients
from ._routing import Routing
from ._runners_sync import health_check, sync_loop
from ._service import Sharding, ShardingService
from ._shard_fence import ShardFence
from ._singletons import Singletons
from ._state import EntityManagerState, Residency, ShardingState
from ._storage_loop import StorageInbox

if TYPE_CHECKING:
    from pyfect.cluster.entity import Entity, EntityHandlers, EntityOptions

_VOID: Effect[None] = succeed(None)


class _Sharding:
    """The ``Sharding`` service of one runner."""

    __slots__ = ("_clients", "_fence", "_routing", "_shutdown", "_singletons", "_state")

    def __init__(
        self,
        state: ShardingState,
        routing: Routing,
        clients: Clients,
        singletons: Singletons,
        shutdown: Callable[[Exit[Any, Any] | None], Effect[None]],
    ) -> None:
        self._state = state
        self._routing = routing
        self._clients = clients
        self._singletons = singletons
        self._shutdown = shutdown
        self._fence = ShardFence(state)

    @property
    def get_registration_events(self) -> Stream[ShardingRegistrationEvent]:
        return from_pubsub(self._state.events)

    def get_shard_id(self, entity_id: EntityId, group: str, /) -> ShardId:
        return self._state.get_shard_id(entity_id, group)

    def has_shard_id(self, shard_id: ShardId, /) -> bool:
        state = self._state
        return not state.is_shutdown and shard_id in state.acquired_shards

    @property
    def get_snowflake(self) -> Effect[Snowflake]:
        return sync(self._state.snowflakes.next_unsafe)

    @property
    def is_shutdown(self) -> Effect[bool]:
        return sync(lambda: self._state.is_shutdown)

    def make_client[T: Entity](self, entity: type[T], /) -> Effect[Callable[[str], T]]:
        return self._clients.get(entity)

    def register_entity(
        self,
        entity: type[Entity],
        build: Effect[EntityHandlers[Any, Any], Never, Any],
        options: EntityOptions,
        /,
    ) -> Effect[None, Never, Any]:
        return _register_entity(self, entity, build, options)

    def register_singleton(
        self, name: str, run: Effect[None, Any, Any], shard_group: str | None, /
    ) -> Effect[None, Never, Any]:
        return self._singletons.register(name, run, shard_group)

    def send(
        self, message: Incoming, /
    ) -> Effect[None, EntityNotAssignedToRunner | MailboxFull | AlreadyProcessingMessage]:
        return self._routing.send_local(message)

    def send_outgoing(
        self, message: Outgoing, discard: bool, /
    ) -> Effect[
        None,
        MailboxFull | AlreadyProcessingMessage | PersistenceError | EntityNotAssignedToRunner,
    ]:
        return self._routing.send_outgoing(message, discard)

    def notify(
        self, message: Incoming, /, *, wait_until_read: bool = False
    ) -> Effect[None, EntityNotAssignedToRunner | AlreadyProcessingMessage]:
        return self._routing.notify_local(message, False, wait_until_read=wait_until_read)

    def reset(
        self, request_id: Snowflake, /, *, expected_reply_id: Snowflake | None = None
    ) -> Effect[bool]:
        return self._routing.reset(request_id, expected_reply_id)

    @property
    def poll_storage(self) -> Effect[None]:
        return self._state.storage_read_latch.open().as_void()

    @property
    def active_entity_count(self) -> Effect[int]:
        def count() -> int:
            return sum(
                len(m.manager._core.active_servers) for m in self._state.entity_managers.values()
            )

        return sync(count)


def _register_entity(
    sharding: _Sharding,
    entity: type[Entity],
    build: Effect[EntityHandlers[Any, Any], Never, Any],
    options: EntityOptions,
) -> Effect[None, Never, Any]:
    state = sharding._state

    @gen
    def run():
        runner_address = state.runner_address
        if runner_address is None or entity.type in state.entity_managers:
            return
        scope = yield from Scope()
        registration = yield from context()
        holder: list[EntityManagerState] = []

        def closed(_: Exit[Any, Any]) -> Effect[None]:
            def mark() -> None:
                if holder:
                    holder[0].status = "closed"

            return sync(mark)

        yield from scope.add_finalizer(closed)
        residency = state.residency
        manager_options = _entity_manager.ManagerOptions(
            sharding=sharding,
            storage=state.storage,
            runner_address=runner_address,
            residency=residency,
            abandon_undelivered=sharding._clients.abandon_undelivered,
            is_shard_owned=lambda shard_id: sharding._fence.is_shard_owned(
                runner_address, shard_id
            ),
            max_idle_time=options.max_idle_time,
            concurrency=options.concurrency,
            mailbox_capacity=options.mailbox_capacity,
            mailbox_metrics=options.mailbox_metrics,
            disable_fatal_defects=options.disable_fatal_defects,
            defect_retry_policy=options.defect_retry_policy,
            span_attributes=options.span_attributes,
        )
        # Registration overrides the construction fallbacks, except for the
        # services the runner owns.
        manager_context = (
            state.services.merge(registration)
            .add(ShardingConfig, state.config)
            .add(Clock, state.clock)
            .add(EntityReaper, state.reaper)
            .add(Scope, scope)
            .add(Generator, state.snowflakes)
        )
        manager = yield from _Locally(
            _entity_manager.make(entity, build, manager_options), lambda _: manager_context
        )
        entry = EntityManagerState(entity, manager)
        holder.append(entry)

        def closing(_: Exit[Any, Any]) -> Effect[None]:
            def run_closing() -> Effect[None]:
                entry.status = "closing"
                stop = sharding._shutdown(None) if state.config.preemptive_shutdown else _VOID
                return around_entity_type(entity.type, stop)

            return suspend(run_closing)

        yield from scope.add_finalizer(closing)

        # Register while storage is idle, so message order is kept.
        def register_now() -> None:
            if state.registration_start_millis is None:
                state.registration_start_millis = state.now_millis()
            state.entity_managers[entity.type] = entry
            # Persisted messages read before this registration were reset:
            # read storage again instead of waiting for the next poll.
            state.storage_read_latch.open_unsafe()
            latch = state.entity_manager_latches.pop(entity.type, None)
            if latch is not None:
                latch.open_unsafe()

        yield from state.storage_read_lock.with_permits(sync(register_now))
        yield from state.events.publish(EntityRegistered(entity))

    return run


@gen
def _make():  # noqa: PLR0915
    config = yield from ShardingConfig()
    clock = yield from Clock()
    runners = yield from Runners()
    runner_health = yield from RunnerHealth()
    snowflakes = yield from Generator()
    sharding_scope = yield from Scope()
    services = yield from context()
    services = Context({t: s for t, s in services.map_unsafe.items() if t is not Scope})
    storage = yield from MessageStorage()
    runner_storage = yield from RunnerStorage()
    events = yield from PubSub[ShardingRegistrationEvent].unbounded()
    shard_groups = shard_group_config(config)
    initial_address = config.runner_address
    self_runner = (
        None
        if initial_address is None
        else Runner(
            address=initial_address,
            groups=shard_groups.assigned,
            weight=config.runner_shard_weight,
        )
    )
    active_shards_latch = Latch()
    storage_read_latch = Latch(True)
    reaper = yield from EntityReaper()
    state = ShardingState(
        config=config,
        shard_groups=shard_groups,
        clock=clock,
        runners=runners,
        runner_health=runner_health,
        snowflakes=snowflakes,
        sharding_scope=sharding_scope,
        services=services,
        storage=storage,
        storage_enabled=storage is not NOOP,
        runner_storage=runner_storage,
        events=events,
        reaper=reaper,
        active_shards_latch=active_shards_latch,
        storage_read_latch=storage_read_latch,
        self_runner=self_runner,
        residency=Residency(config.max_resident_entities, storage_read_latch),
    )

    yield from sharding_scope.add_finalizer(
        lambda _: log_debug("Shutdown complete").annotate_logs("module", "effect/cluster/Sharding")
    )

    # --- shard acquisition ---
    if initial_address is not None:
        self_address = initial_address
        state.update_releasing_gauge()
        # The locks expire over time, so a failure here is ignored.
        yield from sharding_scope.add_finalizer(
            lambda _: state.runner_storage.release_all(self_address).ignore()
        )
        # Shard releases fork into a child scope closed after the shutdown
        # handoff, as forks into the closing sharding scope never run.
        release_scope = yield from sharding_scope.fork()
        release_map = yield from FiberMap[ShardId, Any, Any].make()
        acquisition = ShardAcquisition(state, self_address, release_scope, release_map)
        yield from fork_in(acquisition.acquisition_loop(), sharding_scope)
        yield from fork_in(acquisition.refresh_loop(), sharding_scope)
        # Open the shard latch every poll interval.
        yield from fork_in(
            state.active_shards_latch.open().delay(config.entity_message_poll_interval).forever(),
            sharding_scope,
        )
        state.handoff = acquisition.make_handoff()

    # --- storage inbox ---
    if state.storage_enabled and initial_address is not None:
        inbox = StorageInbox(state, initial_address)
        yield from fork_in(
            state.storage_read_latch.open().delay(config.entity_message_poll_interval).forever(),
            sharding_scope,
        )
        # Forked once the state the loop reads is ready.
        yield from fork_in(inbox.loop(), sharding_scope)

    routing = Routing(state)

    # --- runner storage sync ---
    if self_runner is not None:
        cluster_metrics.runners.update_unsafe(1, Context.empty())
        cluster_metrics.runners_healthy.update_unsafe(1, Context.empty())
    yield from fork_in(sync_loop(state), sharding_scope)

    # --- clients ---
    clients = yield from Clients.make(state, routing)

    # --- singletons ---
    singleton_fibers = yield from FiberMap[Any, Any, Any].make()
    singletons = Singletons(state, singleton_fibers)
    state.singletons = singletons
    state.singletons_ready.open_unsafe()

    def shutdown(exit: Exit[Any, Any] | None) -> Effect[None]:
        @gen
        def run():
            if exit is not None:
                yield from log_debug(
                    "Shutting down", exit.cause if isinstance(exit, Failure) else {}
                ).annotate_logs("module", "effect/cluster/Sharding")
            if state.is_shutdown:
                return
            state.is_shutdown = True
            yield from state.notify_shard_lock_waiters()
            if self_runner is not None:
                yield from state.registration_lock.with_permits(
                    state.runner_storage.unregister(self_runner.address)
                ).ignore()

        return run

    sharding = _Sharding(state, routing, clients, singletons, shutdown)

    # --- runner health checks ---
    if self_runner is not None:
        yield from singletons.register(
            "effect/cluster/Sharding/RunnerHealth", health_check(state), None
        )

    # --- finalization ---
    # Hand the shards off before the loops stop.
    def finalize(exit: Exit[Any, Any]) -> Effect[None]:
        handoff = state.handoff
        return shutdown(exit).and_then(_VOID if handoff is None else handoff)

    yield from sharding_scope.add_finalizer(finalize)
    service: ShardingService = sharding
    return service


make: Effect[ShardingService, Never, Any] = _make
"""The ``Sharding`` service (Effect's ``Sharding.make``)."""

layer: Layer[
    Sharding,
    Never,
    ShardingConfig | Runners | MessageStorage | RunnerStorage | RunnerHealth,
] = layer_.effect(Sharding, make).pipe(
    layer_.provide(layer_.merge(snowflake.layer_generator, _entity_reaper.layer))
)
"""The ``Sharding`` service, with its own snowflake generator and entity
reaper (Effect's ``Sharding.layer``). ``MessageStorage.layer_noop`` makes
persisted sends defect."""

__all__ = ["layer", "make"]
