"""The state an entity manager keeps per entity and per request."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

from pyfect._core import Effect
from pyfect.cluster.entity._handlers import Concurrency
from pyfect.cluster.entity_address import EntityAddress
from pyfect.cluster.message import IncomingRequestLocal
from pyfect.cluster.reply import Chunk
from pyfect.cluster.runner_address import RunnerAddress
from pyfect.cluster.shard_id import ShardId
from pyfect.cluster.snowflake import Snowflake
from pyfect.duration import Seconds
from pyfect.exit import Exit
from pyfect.latch import Latch
from pyfect.rpc import AnyRpc
from pyfect.rpc.message import FromClient
from pyfect.rpc.server._core import OnRequest
from pyfect.schedule import Schedule
from pyfect.scope import CloseableScope

if TYPE_CHECKING:
    from pyfect.cluster.message_storage import MessageStorageService
    from pyfect.cluster.sharding import ShardingService

type WriteFn = Callable[[int, FromClient, OnRequest | None], Effect[None]]
"""Hands the entity's RPC server a message (``RpcServer.write``)."""


@dataclass(eq=False, slots=True)
class RequestTransaction:
    """Settles a ``WithTransaction`` request once its transaction ends."""

    settle: Callable[[Exit[Any, Any]], Effect[None]] | None = None


@dataclass(eq=False, slots=True, kw_only=True)
class RequestEntry:
    """A request in an entity's mailbox. ``delivered`` excludes requests
        awaiting their first dispatch from replay; ``terminating`` treats an
        early termination interrupt as a shutdown one; an ``interrupted`` request
    is never run again; a request with a
        ``caller_scope`` does not outlive its caller."""

    rpc: AnyRpc
    message: IncomingRequestLocal
    sent_reply: bool = False
    delivered: bool = False
    sent_exit: bool = False
    terminating: bool = False
    last_sent_chunk: Chunk[Any] | None = None
    sequence: int = 0
    caller_scope: CloseableScope | None = None
    transaction: RequestTransaction | None = None
    interrupted: bool = False
    """An interrupt arrived while no handlers were ready; it is sent to each
    later handler generation instead of the request."""
    interrupt_sent_to: WriteFn | None = None
    """The handler generation the remembered interrupt was last sent to."""


@dataclass(eq=False, slots=True, kw_only=True)
class EntityState:
    """A resident entity: its mailbox (``active_requests``), when it was
    last active (clock milliseconds) and how to write to its server."""

    address: EntityAddress
    scope: CloseableScope
    active_requests: dict[Snowflake, RequestEntry]
    write: WriteFn
    keep_alive_latch: Latch
    last_active_check: int
    keep_alive_enabled: bool = False


class Residency(Protocol):
    """The runner-wide cap on resident entities: ``admit_unsafe`` takes a
    slot (``False`` at capacity), ``release_unsafe`` gives it back."""

    def admit_unsafe(self) -> bool: ...

    def release_unsafe(self) -> None: ...


type AbandonUndelivered = Callable[[EntityAddress, Callable[[Snowflake], bool]], Effect[None]]
"""Called once a retiring entity stops taking requests, so callers waiting
on requests it never started can be released."""


@dataclass(frozen=True, slots=True, kw_only=True)
class ManagerOptions:
    """How ``make`` runs an entity type's entities."""

    sharding: ShardingService
    storage: MessageStorageService
    runner_address: RunnerAddress
    residency: Residency
    abandon_undelivered: AbandonUndelivered
    is_shard_owned: Callable[[ShardId], Effect[bool]]
    """Whether this runner still owns the shard, checked before storing the
    final reply of a persisted request."""
    max_idle_time: Seconds | None = None
    concurrency: Concurrency = 1
    mailbox_capacity: Concurrency | None = None
    mailbox_metrics: bool | None = None
    disable_fatal_defects: bool = False
    defect_retry_policy: Schedule[Any, Any, Any, Any] | None = None
    span_attributes: Mapping[str, str] = field(default_factory=dict[str, str])


__all__ = [
    "AbandonUndelivered",
    "EntityState",
    "ManagerOptions",
    "RequestEntry",
    "RequestTransaction",
    "Residency",
    "WriteFn",
]
