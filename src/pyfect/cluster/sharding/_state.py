"""The state one ``Sharding`` instance shares between its loops: the shard
assignments and locks, the entity managers, the client requests, and the
latches that wake each loop."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from pyfect._core import Effect, _Locally
from pyfect._fiber import Fiber
from pyfect.clock import ClockService, now_millis_unsafe
from pyfect.cluster import cluster_metrics
from pyfect.cluster._entity_manager import EntityManager
from pyfect.cluster._entity_reaper import EntityReaperService
from pyfect.cluster._hash import shard_number
from pyfect.cluster._shard_lock import effective_interval
from pyfect.cluster.cluster_error import EntityNotAssignedToRunner
from pyfect.cluster.entity_address import EntityAddress
from pyfect.cluster.entity_id import EntityId
from pyfect.cluster.message import IncomingRequest, OutgoingRequest
from pyfect.cluster.message_storage import MessageStorageService
from pyfect.cluster.runner import Runner
from pyfect.cluster.runner_address import RunnerAddress
from pyfect.cluster.runner_health import RunnerHealthService
from pyfect.cluster.runner_storage import RunnerStorageService
from pyfect.cluster.runners import RunnersService
from pyfect.cluster.shard_id import ShardId
from pyfect.cluster.sharding_config import ShardGroups, ShardingConfigService
from pyfect.cluster.sharding_registration_event import ShardingRegistrationEvent
from pyfect.cluster.snowflake import Snowflake, SnowflakeGenerator
from pyfect.context import Context
from pyfect.duration import Seconds, to_millis
from pyfect.effect import die, succeed, suspend
from pyfect.latch import Latch
from pyfect.pubsub import PubSub
from pyfect.rpc import AnyRpc
from pyfect.scope import CloseableScope
from pyfect.semaphore import Semaphore

if TYPE_CHECKING:
    from pyfect.cluster.entity import Entity
    from pyfect.cluster.sharding._singletons import Singletons

type ManagerStatus = Literal["alive", "closing", "closed"]


@dataclass(eq=False, slots=True)
class EntityManagerState:
    entity: type[Entity]
    manager: EntityManager
    status: ManagerStatus = "alive"


@dataclass(eq=False, slots=True)
class PendingNotification:
    """A persisted request whose sender waits until the storage loop has
    read it (``notify(..., wait_until_read=True)``)."""

    resume: Callable[[Effect[None, EntityNotAssignedToRunner]], None]
    message: IncomingRequest


@dataclass(eq=False, slots=True)
class ClientRequestEntry:
    """A request a client of this runner waits on; ``runner`` is the one
    a volatile request was last sent to."""

    rpc: AnyRpc
    context: Context[Any]
    message: OutgoingRequest
    last_chunk_id: Snowflake | None = None
    runner: RunnerAddress | None = None


@dataclass(eq=False, slots=True)
class ResumptionState:
    """An entity resuming its unprocessed messages from storage after its
    mailbox was full."""

    unprocessed: dict[Snowflake, None]
    interrupts: dict[Snowflake, Any] = field(default_factory=dict[Snowflake, Any])


class Residency:
    """The runner-wide count of resident entities, capped by
    ``max_resident_entities``; a freed slot wakes the storage loop."""

    __slots__ = ("_count", "_max", "_wake")

    def __init__(self, maximum: int | Literal["unbounded"], wake: Latch) -> None:
        self._max = maximum
        self._count = 0
        self._wake = wake

    def at_capacity_unsafe(self) -> bool:
        return isinstance(self._max, int) and self._count >= self._max

    def admit_unsafe(self) -> bool:
        if self.at_capacity_unsafe():
            return False
        self._count += 1
        return True

    def release_unsafe(self) -> None:
        self._count -= 1
        # A slot has freed up, so the storage loop can admit messages for
        # entities it had to skip.
        if self._max != "unbounded":
            self._wake.open_unsafe()


@dataclass(eq=False, slots=True, kw_only=True)
class ShardingState:
    config: ShardingConfigService
    shard_groups: ShardGroups
    clock: ClockService
    runners: RunnersService
    runner_health: RunnerHealthService
    snowflakes: SnowflakeGenerator
    sharding_scope: CloseableScope
    services: Context[Any]
    storage: MessageStorageService
    storage_enabled: bool
    runner_storage: RunnerStorageService
    events: PubSub[ShardingRegistrationEvent]
    reaper: EntityReaperService
    active_shards_latch: Latch
    storage_read_latch: Latch
    self_runner: Runner | None
    residency: Residency
    is_shutdown: bool = False
    entity_managers: dict[str, EntityManagerState] = field(
        default_factory=dict[str, EntityManagerState]
    )
    entity_manager_latches: dict[str, Latch] = field(default_factory=dict[str, Latch])
    registration_start_millis: int | None = None
    registration_fallback_start_millis: int | None = None
    shard_assignments: dict[ShardId, RunnerAddress] = field(
        default_factory=dict[ShardId, RunnerAddress]
    )
    self_shards: set[ShardId] = field(default_factory=set[ShardId])
    acquired_shards: set[ShardId] = field(default_factory=set[ShardId])
    """The shards whose lock this runner holds."""
    releasing_shards: set[ShardId] = field(default_factory=set[ShardId])
    """Shards still held while their entities stop and their locks are
    released."""
    force_releasing_shards: set[ShardId] = field(default_factory=set[ShardId])
    """Shards whose entities are force interrupted and locks fully
    released before normal reacquisition."""
    shard_locks_healthy_latch: Latch = field(default_factory=lambda: Latch(True))
    handoff_latch: Latch = field(default_factory=Latch)
    """Open once shutdown hands every shard off."""
    handed_off_latch: Latch = field(default_factory=Latch)
    """Open once the handoff has released every shard lock."""
    singletons_ready: Latch = field(default_factory=Latch)
    shard_locks_changed: Latch = field(default_factory=Latch)
    registration_lock: Semaphore = field(default_factory=lambda: Semaphore(1))
    """Serializes runner registration with unregistration, so a
    registration in flight cannot advertise a runner shutting down."""
    storage_read_lock: Semaphore = field(default_factory=lambda: Semaphore(1))
    pending_notifications: dict[Snowflake, PendingNotification] = field(
        default_factory=dict[Snowflake, PendingNotification]
    )
    entity_resumption: dict[EntityAddress, ResumptionState] = field(
        default_factory=dict[EntityAddress, ResumptionState]
    )
    client_requests: dict[Snowflake, ClientRequestEntry] = field(
        default_factory=dict[Snowflake, ClientRequestEntry]
    )
    all_runners: dict[Runner, bool] = field(default_factory=dict[Runner, bool])
    healthy_runner_count: int = 0
    handoff: Effect[None] | None = None
    singletons: Singletons | None = None

    # --- addressing -----------------------------------------------------------------------

    @property
    def runner_address(self) -> RunnerAddress | None:
        return self.config.runner_address

    @property
    def shard_lock_interval(self) -> Seconds:
        return effective_interval(self.config)

    def get_shard_id(self, entity_id: EntityId, group: str) -> ShardId:
        return ShardId(group=group, id=shard_number(entity_id, self.config.shards_per_group))

    def is_local_runner(self, address: RunnerAddress) -> bool:
        local = self.config.runner_address
        return local is not None and address == local

    def is_entity_on_local_shards(self, address: EntityAddress) -> bool:
        return address.shard_id in self.acquired_shards

    def now_millis(self) -> int:
        return now_millis_unsafe(self.clock)

    def residency_at_capacity(self) -> bool:
        return self.residency.at_capacity_unsafe()

    # --- shard locks ----------------------------------------------------------------------

    def is_awaiting_shard_lock(self, shard_id: ShardId) -> bool:
        return (
            not self.is_shutdown
            and shard_id in self.self_shards
            and shard_id not in self.acquired_shards
        )

    def notify_shard_lock_waiters(self) -> Effect[None]:
        """Open the current latch and replace it, so a waiter that checked
        its shard before this cannot miss it."""

        def run() -> Effect[None]:
            latch = self.shard_locks_changed
            self.shard_locks_changed = Latch()
            return latch.open().as_void()

        return suspend(run)

    def await_shard_lock(self, shard_id: ShardId) -> Effect[None]:
        """Requests for a shard assigned to this runner wait for its lock,
        at most ``shard_lock_expiration``, instead of bouncing while the
        previous owner drains."""

        def loop() -> Effect[None]:
            if not self.is_awaiting_shard_lock(shard_id):
                return _VOID
            return self.shard_locks_changed.wait().and_then(suspend(loop))

        def start() -> Effect[None]:
            if not self.is_awaiting_shard_lock(shard_id):
                return _VOID
            return suspend(loop).timeout_option(self.config.shard_lock_expiration).as_void()

        return suspend(start)

    # --- gauges ---------------------------------------------------------------------------

    def update_releasing_gauge(self) -> None:
        # The releasing gauge reports to the registry and attributes the
        # layer was built with.
        cluster_metrics.shards_releasing.update_unsafe(len(self.releasing_shards), self.services)

    def update_shard_gauges(self) -> None:
        cluster_metrics.shards.update_unsafe(len(self.acquired_shards), Context.empty())
        self.update_releasing_gauge()

    # --- entity registration --------------------------------------------------------------

    def registration_time_remaining(self) -> int:
        """Milliseconds left before a missing entity type is a defect. The
        first missing entity seen starts a fallback window of two
        timeouts, shared by the storage loop and local sends."""
        now = self.now_millis()
        timeout = int(to_millis(self.config.entity_registration_timeout))
        started = self.registration_start_millis
        if started is None:
            if self.registration_fallback_start_millis is None:
                self.registration_fallback_start_millis = now
            started = self.registration_fallback_start_millis
            timeout *= 2
        return max(0, timeout - (now - started))

    # --- forking --------------------------------------------------------------------------

    def run_fork(self, effect: Effect[Any, Any, Any]) -> Fiber[Any, Any]:
        """Fork ``effect`` with the layer's services into the sharding
        scope (Effect's ``runFork``)."""
        parent = Fiber.get_current()
        assert parent is not None, "sharding runs on a fiber"
        fiber = parent._fork(
            _Locally(effect, lambda _: self.services), daemon=True, start_immediately=True
        )
        return fiber.run_in(self.sharding_scope)


def entity_not_registered(entity_type: str) -> Effect[Any]:
    return die(RuntimeError(f"Entity type '{entity_type}' not registered"))


_VOID: Effect[None] = succeed(None)

__all__ = [
    "ClientRequestEntry",
    "EntityManagerState",
    "ManagerStatus",
    "PendingNotification",
    "Residency",
    "ResumptionState",
    "ShardingState",
    "entity_not_registered",
]
