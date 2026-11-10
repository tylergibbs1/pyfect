"""An entity type's manager (Effect's ``internal/entityManager``): starts
its entities on demand, delivers requests and envelopes to them, keeps
them alive, and stops those of a shard."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Any, Never

from pyfect import exit as Exit
from pyfect import schema as S
from pyfect._core import Effect, _Locally
from pyfect._fiber import Fiber
from pyfect.clock import Clock
from pyfect.cluster import cluster_metrics
from pyfect.cluster._entity_reaper import EntityReaper
from pyfect.cluster._resource_map import ResourceMap
from pyfect.cluster.cluster_error import (
    AlreadyProcessingMessage,
    EntityNotAssignedToRunner,
    MailboxFull,
    MalformedMessage,
)
from pyfect.cluster.cluster_schema import Persisted, Uninterruptible
from pyfect.cluster.entity._keep_alive import KeepAliveRpc
from pyfect.cluster.entity_address import EntityAddress
from pyfect.cluster.envelope import AckChunk
from pyfect.cluster.message import (
    Incoming,
    IncomingEnvelope,
    IncomingLocal,
    IncomingRequest,
    IncomingRequestLocal,
    dynamic_annotations,
)
from pyfect.cluster.message_storage import NOOP
from pyfect.cluster.reply import Chunk, Reply, ReplyWithContext, WithExit
from pyfect.cluster.shard_id import ShardId
from pyfect.cluster.sharding_config import ShardingConfig
from pyfect.cluster.snowflake import Generator
from pyfect.context import Context
from pyfect.duration import to_millis
from pyfect.effect import context, die, fail, gen, succeed, suspend, sync
from pyfect.exit import Exit as ExitT
from pyfect.logger import CurrentLogAnnotations
from pyfect.metric import register_unsafe
from pyfect.metric._state import GaugeState
from pyfect.rpc import message as rpc_message
from pyfect.schedule import exponential, spaced, to_step_with_sleep
from pyfect.schedule import min as schedule_min
from pyfect.scope import Scope, acquire_release, fork_in

from ._activation import make_entity
from ._core import ManagerCore, request_envelope, retry_respond
from ._decode import DecodedRequest, decode_message
from ._state import EntityState, ManagerOptions, RequestEntry

if TYPE_CHECKING:
    from pyfect.cluster.entity import Entity, EntityHandlers

type LocalSendError = EntityNotAssignedToRunner | MailboxFull | AlreadyProcessingMessage

_VOID: Effect[None] = succeed(None)

DEFAULT_RETRY_POLICY = schedule_min(exponential("500 millis", 1.5), spaced("10 seconds"))
"""Restarts after a defect wait 500ms, growing by 1.5, at most 10s."""


def _run_fork(services: Context[Any], effect: Effect[Any, Any, Any]) -> Fiber[Any, Any]:
    """Effect's ``runForkWith(services)``: a detached fiber, started now."""
    parent = Fiber.get_current()
    assert parent is not None, "an entity manager runs on a fiber"
    return parent._fork(_Locally(effect, lambda _: services), daemon=True, start_immediately=True)


class EntityManager:
    """The entities of one entity type on this runner."""

    __slots__ = ("_core", "_entities")

    def __init__(
        self, core: ManagerCore, entities: ResourceMap[EntityAddress, EntityState, Any]
    ) -> None:
        self._core = core
        self._entities = entities

    # --- delivery -----------------------------------------------------------------------

    def _send_envelope(self, server: EntityState, message: IncomingEnvelope) -> Effect[None]:
        envelope = message.envelope
        entry = server.active_requests.get(envelope.request_id)
        if entry is None:
            return _VOID
        if isinstance(envelope, AckChunk):
            last = entry.last_sent_chunk
            if last is not None and envelope.reply_id != last.id:
                return _VOID
            return server.write(0, rpc_message.Ack(envelope.request_id), None)
        return server.write(0, rpc_message.Interrupt(envelope.request_id), None)

    def _keep_alive(self, server: EntityState, message: IncomingRequestLocal) -> Effect[None]:
        core = self._core

        def respond() -> Effect[None]:
            reply = WithExit(
                request_id=message.envelope.request_id,
                id=core.snowflakes.next_unsafe(),
                exit=Exit.succeed(None),
            )
            return retry_respond(4, message.respond(reply)).or_die()

        reply = suspend(respond)
        if server.keep_alive_enabled:
            return reply
        server.keep_alive_enabled = True

        def disabled() -> Effect[None]:
            server.keep_alive_enabled = False
            return reply

        waiting = server.keep_alive_latch.when_open(suspend(disabled))
        return fork_in(waiting, server.scope, start_immediately=True).as_void()

    def _send_request(
        self, server: EntityState, message: IncomingRequestLocal
    ) -> Effect[None, LocalSendError]:
        core = self._core
        request_id = message.envelope.request_id
        address = message.envelope.address
        # A request already running may have more than one sender; the
        # others resume from storage only.
        if request_id in server.active_requests or request_id in core.processed_request_ids:
            return fail(AlreadyProcessingMessage(envelope_id=request_id, address=address))
        rpc = core.rpcs[message.envelope.tag]
        if not core.storage_enabled and message.annotations.get(Persisted):
            return die(
                RuntimeError(
                    "EntityManager.sendLocal: Cannot process a persisted message without "
                    "MessageStorage"
                )
            )
        if rpc.tag == KeepAliveRpc.tag:
            return self._keep_alive(server, message)
        capacity = core.mailbox_capacity
        if capacity != "unbounded" and len(server.active_requests) >= capacity:
            return fail(MailboxFull(address=address))
        caller_scope = (
            message.caller_scope
            if message.caller_scope is not None
            and not message.annotations.get(Persisted)
            and message.annotations.get(Uninterruptible) is False
            else None
        )
        if caller_scope is not None and caller_scope.is_closed:
            return _VOID
        last = message.last_sent_reply
        entry = RequestEntry(
            rpc=rpc,
            message=message,
            last_sent_chunk=last if isinstance(last, Chunk) else None,
            sequence=last.sequence + 1 if isinstance(last, Chunk) else 0,
            caller_scope=caller_scope,
        )
        server.active_requests[request_id] = entry
        if caller_scope is not None:
            # Register cleanup atomically with admission, including requests
            # awaiting delivery.
            def forget(_: ExitT[Any, Any]) -> Effect[None]:
                def run() -> None:
                    if server.active_requests.pop(request_id, None) is not None and (
                        not server.active_requests
                    ):
                        server.last_active_check = core.now_millis()

                return sync(run)

            caller_scope._add(object(), forget)
        return server.write(0, request_envelope(entry), core.request_write_options(entry))

    def send_local(self, message: IncomingLocal) -> Effect[None, LocalSendError]:
        """Deliver a decoded message to its entity, starting it if needed."""
        core = self._core
        if isinstance(message, IncomingEnvelope):
            draining = core.draining_servers.get(message.envelope.address.entity_id)
            if draining is not None and message.envelope.request_id in draining.active_requests:
                return self._send_envelope(draining, message)

        def deliver(server: EntityState) -> Effect[None, LocalSendError]:
            if isinstance(message, IncomingRequestLocal):
                return self._send_request(server, message)
            return self._send_envelope(server, message)

        return (
            self._entities.get(message.envelope.address)
            .flat_map(deliver)
            .pipe(_without_log_annotations)
        )

    def send(self, message: Incoming) -> Effect[None, LocalSendError]:
        """Decode a message read from storage or another runner, then
        deliver it; a request that does not decode is answered with a
        ``MalformedMessage`` defect."""
        core = self._core

        def malformed(error: S.SchemaError) -> Effect[None, LocalSendError]:
            if isinstance(message, IncomingEnvelope):
                return die(MalformedMessage(cause=error))
            rpc = core.rpcs.get(message.envelope.tag)
            reply = WithExit(
                id=core.snowflakes.next_unsafe(),
                request_id=message.envelope.request_id,
                exit=Exit.die(MalformedMessage(cause=error)),
            )
            replied = (
                ReplyWithContext(reply=reply, context=core.context)
                if rpc is None
                else ReplyWithContext(reply=reply, rpc=rpc, context=core.context)
            )
            return message.respond(replied).or_die()

        def decoded(
            result: DecodedRequest | IncomingEnvelope,
        ) -> Effect[None, LocalSendError]:
            if isinstance(result, IncomingEnvelope):
                return self.send_local(result)
            request = message
            assert isinstance(request, IncomingRequest)
            rpc = core.rpcs[result.envelope.tag]

            def respond(reply: Reply) -> Effect[None, Any]:
                return request.respond(ReplyWithContext(reply=reply, rpc=rpc, context=core.context))

            return self.send_local(
                IncomingRequestLocal(
                    annotations=dynamic_annotations(rpc, result.envelope),
                    envelope=result.envelope,
                    last_sent_reply=result.last_sent_reply,
                    caller_scope=request.caller_scope,
                    respond=respond,
                )
            )

        return (
            decode_message(core.rpcs, message)
            .match_effect(on_failure=malformed, on_success=decoded)
            .pipe(_provide(core.context))
        )

    # --- state ----------------------------------------------------------------------------

    def is_processing_for(
        self, message: Incoming, *, exclude_replies: bool = False, exclude_completed: bool = False
    ) -> bool:
        core = self._core
        request_id = message.envelope.request_id
        if (
            not exclude_replies
            and not exclude_completed
            and request_id in core.processed_request_ids
        ):
            return True
        state = core.active_servers.get(message.envelope.address.entity_id)
        if state is None:
            return False
        request = state.active_requests.get(request_id)
        if request is None:
            return False
        if exclude_replies and request.sent_reply:
            return False
        return not (exclude_completed and request.sent_exit)

    def clear_processed(self) -> None:
        self._core.processed_request_ids.clear()

    def has_servers_unsafe(self, shard_id: ShardId) -> bool:
        """Whether any entity of the shard is still open, those
        ``interrupt_shard`` waits on too."""
        return any(address.shard_id == shard_id for address in self._core.server_close_latches)

    def is_resident_unsafe(self, address: EntityAddress) -> bool:
        return self._entities.has_unsafe(address)

    def resident_addresses_unsafe(self) -> list[EntityAddress]:
        return self._entities.keys_unsafe()

    @property
    def active_entity_count(self) -> Effect[int]:
        return sync(lambda: len(self._core.active_servers))

    def interrupt_shard(self, shard_id: ShardId, *, force: bool = False) -> Effect[None]:
        """Stop every entity of ``shard_id`` and wait until each has closed;
        with ``force``, without waiting for their handlers."""
        core = self._core
        entities = self._entities

        def loop() -> Effect[None]:
            latches = [
                (address, found)
                for address, found in list(core.server_close_latches.items())
                if address.shard_id == shard_id
            ]
            if force:
                for _, found in latches:
                    found.force.open_unsafe()
            # Look entities up by address: ``active_servers`` is keyed by
            # entity id, so an entity with the same id on another shard
            # can hide this one.
            fibers: list[Fiber[Any, Any]] = []
            for address, found in latches:
                if not found.closing:
                    fibers.append(_run_fork(core.context, entities.remove_ignore(address)))
                fibers.append(_run_fork(core.context, found.closed.wait()))
            if not fibers:
                return _VOID
            return Fiber.join_all(fibers).flat_map(lambda _: suspend(loop))

        return suspend(loop)


def _without_log_annotations[A, E, R](effect: Effect[A, E, R]) -> Effect[A, E, R]:
    return _Locally(effect, lambda current: current.add(CurrentLogAnnotations, {}))


def _provide(services: Context[Any]) -> Any:
    def apply[A, E](effect: Effect[A, E, Any]) -> Effect[A, E]:
        return _Locally(effect, lambda current: current.merge(services))

    return apply


def make(
    entity: type[Entity],
    build: Effect[EntityHandlers[Any, Any], Never, Any],
    options: ManagerOptions,
) -> Effect[EntityManager, Never, Any]:
    """The manager of ``entity``'s entities on this runner, closed with
    the current scope."""

    @gen
    def run():
        config = yield from ShardingConfig()
        snowflakes = yield from Generator()
        manager_scope = yield from Scope()
        clock = yield from Clock()
        services = yield from context()
        policy = (
            DEFAULT_RETRY_POLICY
            if options.defect_retry_policy is None
            else options.defect_retry_policy.concat(DEFAULT_RETRY_POLICY)
        )
        rpcs = dict(entity.rpcs)
        rpcs[KeepAliveRpc.tag] = KeepAliveRpc
        core = ManagerCore(
            entity=entity,
            build=build,
            rpcs=rpcs,
            options=options,
            config=config,
            snowflakes=snowflakes,
            clock=clock,
            context=services,
            manager_scope=manager_scope,
            storage_enabled=options.storage is not NOOP,
            mailbox_capacity=(
                config.entity_mailbox_capacity
                if options.mailbox_capacity is None
                else options.mailbox_capacity
            ),
            mailbox_metrics=(
                config.entity_mailbox_metrics
                if options.mailbox_metrics is None
                else options.mailbox_metrics
            ),
            defect_retry_policy=policy,
            new_restart_step=to_step_with_sleep(policy),
        )

        # Registered before the entities resource map, so the series is
        # removed only after every entity has drained on shutdown.
        def largest(_: Any) -> GaugeState[int]:
            return GaugeState(max((len(m) for m in core.resident_mailboxes.values()), default=0))

        yield from acquire_release(
            sync(
                lambda: register_unsafe(
                    cluster_metrics.entity_mailbox_size_max.with_attributes({"type": entity.type}),
                    services,
                    largest,
                )
            ),
            lambda registration, _: sync(registration.remove),
        )

        def lookup(address: EntityAddress) -> Effect[EntityState, Any, Scope]:
            return make_entity(core, address).pipe(_without_log_annotations)

        entities = yield from ResourceMap.make(lookup)
        reaper = yield from EntityReaper()
        max_idle = (
            config.entity_max_idle_time if options.max_idle_time is None else options.max_idle_time
        )
        if math.isfinite(max_idle):
            yield from reaper.register(
                max_idle_millis=to_millis(max_idle),
                servers=core.active_servers,
                entities=entities,
            )

        def count(_: Any) -> GaugeState[int]:
            return GaugeState(len(core.active_servers))

        series = register_unsafe(
            cluster_metrics.entities.with_attributes({"type": entity.type}), services, count
        )
        yield from manager_scope.add_finalizer(lambda _: sync(series.remove))
        return EntityManager(core, entities)

    return run


__all__ = ["DEFAULT_RETRY_POLICY", "EntityManager", "make"]
