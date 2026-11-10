"""What an entity manager's entities share: the manager's services and
settings, the resident and draining entities, and the helpers that write
requests to an entity's server."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Never

from pyfect._core import Effect, Restore, _Locally, _WithFiber, uninterruptible_mask
from pyfect._fiber import Fiber
from pyfect.clock import ClockService, now_millis_unsafe
from pyfect.cluster.cluster_schema import WithTransaction
from pyfect.cluster.entity._handlers import Concurrency
from pyfect.cluster.entity._request import Request as EntityRequest
from pyfect.cluster.entity_address import EntityAddress
from pyfect.cluster.entity_id import EntityId
from pyfect.cluster.message_storage import MessageStorageService
from pyfect.cluster.sharding_config import ShardingConfigService
from pyfect.cluster.snowflake import Snowflake, SnowflakeGenerator
from pyfect.context import Context
from pyfect.effect import interrupt, sync
from pyfect.exit import Exit
from pyfect.latch import Latch
from pyfect.rpc import AnyRpc
from pyfect.rpc import message as rpc_message
from pyfect.rpc.server._core import OnRequest
from pyfect.schedule import Decision
from pyfect.scope import CloseableScope

from ._state import EntityState, ManagerOptions, RequestEntry, RequestTransaction

if TYPE_CHECKING:
    from pyfect.cluster.entity import Entity, EntityHandlers


type RestartStep = Callable[[None], Effect[Decision[Any], Any, Any]]
"""Sleeps for an entity's next restart delay."""


@dataclass(eq=False, slots=True)
class CloseLatches:
    """Opened when an entity's scope has closed (``closed``), or to stop
    waiting for its handlers on a forced release (``force``)."""

    closed: Latch = field(default_factory=Latch)
    force: Latch = field(default_factory=Latch)
    closing: bool = False


@dataclass(eq=False, slots=True, kw_only=True)
class ManagerCore:
    entity: type[Entity]
    build: Effect[EntityHandlers[Any, Any], Never, Any]
    rpcs: dict[str, AnyRpc]
    options: ManagerOptions
    config: ShardingConfigService
    snowflakes: SnowflakeGenerator
    clock: ClockService
    context: Context[Any]
    manager_scope: CloseableScope
    storage_enabled: bool
    mailbox_capacity: Concurrency
    mailbox_metrics: bool
    defect_retry_policy: Any
    new_restart_step: Effect[RestartStep, Never, Any]
    """A fresh restart backoff, which each entity takes on its first defect."""
    active_servers: dict[EntityId, EntityState] = field(default_factory=dict[EntityId, EntityState])
    draining_servers: dict[EntityId, EntityState] = field(
        default_factory=dict[EntityId, EntityState]
    )
    resident_mailboxes: dict[int, dict[Snowflake, RequestEntry]] = field(
        default_factory=dict[int, dict[Snowflake, RequestEntry]]
    )
    """Mailboxes of every resident entity, draining ones too, by ``id``."""
    server_close_latches: dict[EntityAddress, CloseLatches] = field(
        default_factory=dict[EntityAddress, CloseLatches]
    )
    processed_request_ids: set[Snowflake] = field(default_factory=set[Snowflake])

    @property
    def storage(self) -> MessageStorageService:
        return self.options.storage

    def now_millis(self) -> int:
        return now_millis_unsafe(self.clock)

    def request_write_options(self, entry: RequestEntry) -> OnRequest | None:
        """Runs the request in a storage transaction (``WithTransaction``)
        and bound to its caller (``caller_scope``)."""
        on_transaction: OnRequest | None = None
        if entry.message.annotations.get(WithTransaction):
            storage = self.storage

            def transaction(effect: Effect[Any, Any, Any]) -> Effect[Any, Any, Any]:
                # Interrupts during commit must not hide the outcome from settle.
                def body(restore: Restore) -> Effect[Any, Any, Any]:
                    current = RequestTransaction()
                    entry.transaction = current

                    def settled(outcome: Exit[Any, Any]) -> Effect[None]:
                        if entry.transaction is current:
                            entry.transaction = None
                        settle = current.settle
                        return sync(lambda: None) if settle is None else settle(outcome)

                    return storage.with_transaction(restore(effect)).on_exit(settled)

                return uninterruptible_mask(body)

            on_transaction = transaction
        caller = entry.caller_scope
        if caller is None:
            return on_transaction
        on_caller = bind_to_caller(caller)
        if on_transaction is None:
            return on_caller
        inner = on_transaction
        return lambda effect: on_caller(inner(effect))


def bind_to_caller(caller_scope: CloseableScope) -> OnRequest:
    """Bind each handler fiber, replays too, to its caller's scope before
    its body runs."""

    def bind(effect: Effect[Any, Any, Any]) -> Effect[Any, Any, Any]:
        def body(fiber: Fiber[Any, Any]) -> Effect[Any, Any, Any]:
            if caller_scope.is_closed:
                return interrupt()
            key = object()

            def interrupt_handler(_: Exit[Any, Any]) -> Effect[None]:
                return sync(lambda: fiber.interrupt_as_unsafe(fiber.id))

            caller_scope._add(key, interrupt_handler)
            return effect.ensuring(sync(lambda: caller_scope._remove(key)))

        return _WithFiber(body)

    return bind


def request_envelope(entry: RequestEntry) -> rpc_message.Request:
    """The request as the entity's RPC server takes it, its payload the
    entity ``Request``."""
    envelope = entry.message.envelope
    payload = EntityRequest[Any](
        request_id=envelope.request_id,
        address=envelope.address,
        tag=envelope.tag,
        payload=envelope.payload,
        headers=envelope.headers,
        trace_id=envelope.trace_id,
        span_id=envelope.span_id,
        sampled=envelope.sampled,
        last_sent_chunk=entry.last_sent_chunk,
    )
    return rpc_message.Request(
        envelope.request_id,
        envelope.tag,
        payload,
        envelope.headers,
        envelope.trace_id,
        envelope.span_id,
        envelope.sampled,
    )


def set_context[A, E](effect: Effect[A, E, Any], services: Context[Any]) -> Effect[A, E]:
    """``effect`` run with exactly ``services`` (Effect's ``setContext``)."""
    located: Effect[A, E] = _Locally(effect, lambda _: services)
    return located


def retry_respond[A, E, R](times: int, effect: Effect[A, E, R]) -> Effect[A, E, R]:
    """``effect``, retried ``times`` times 200ms apart on a typed failure."""
    if times == 0:
        return effect
    return effect.catch_all(lambda _: retry_respond(times - 1, effect).delay("200 millis"))


__all__ = [
    "CloseLatches",
    "ManagerCore",
    "RestartStep",
    "bind_to_caller",
    "request_envelope",
    "retry_respond",
    "set_context",
]
