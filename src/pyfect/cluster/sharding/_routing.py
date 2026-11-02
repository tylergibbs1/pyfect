"""Sending messages: to a local entity, through storage, or to the runner
that owns the shard, retrying while shards move and abandoning messages
the runner can no longer route once it shuts down."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pyfect._core import Effect
from pyfect.clock import sleep
from pyfect.cluster import _cluster_abandon, deliver_at
from pyfect.cluster.cluster_error import (
    AlreadyProcessingMessage,
    EntityNotAssignedToRunner,
    MailboxFull,
    MalformedMessage,
    PersistenceError,
    RunnerUnavailable,
)
from pyfect.cluster.cluster_schema import Persisted
from pyfect.cluster.envelope import AckChunk, Request
from pyfect.cluster.message import (
    Incoming,
    IncomingEnvelope,
    IncomingLocal,
    IncomingRequest,
    Outgoing,
    OutgoingRequest,
)
from pyfect.cluster.runner_address import RunnerAddress
from pyfect.duration import Seconds
from pyfect.effect import callback, catch_tag, die, fail, succeed, suspend
from pyfect.latch import Latch
from pyfect.logger import log_debug, log_warning

from ._state import PendingNotification, ShardingState, entity_not_registered

_VOID: Effect[None] = succeed(None)

type SendError = EntityNotAssignedToRunner | MailboxFull | AlreadyProcessingMessage
type OutgoingError = (
    MailboxFull | AlreadyProcessingMessage | PersistenceError | EntityNotAssignedToRunner
)


class Routing:
    __slots__ = ("_state",)

    def __init__(self, state: ShardingState) -> None:
        self._state = state

    # --- waiting for an entity type -------------------------------------------------------

    def _await_registration_deadline(self, entity_type: str) -> Effect[Any]:
        """Sleep until the registration deadline shared with the storage
        loop, checking again in case registration started meanwhile."""

        def run() -> Effect[Any]:
            remaining = self._state.registration_time_remaining()
            if remaining > 0:
                return sleep(Seconds(remaining / 1000)).and_then(
                    self._await_registration_deadline(entity_type)
                )
            return entity_not_registered(entity_type)

        return suspend(run)

    def wait_for_entity_manager(self, entity_type: str) -> Effect[None]:
        state = self._state
        latch = state.entity_manager_latches.get(entity_type)
        if latch is None:
            latch = Latch()
            state.entity_manager_latches[entity_type] = latch
        return latch.wait().race_first(self._await_registration_deadline(entity_type))

    # --- local delivery -------------------------------------------------------------------

    def send_local(self, message: Outgoing | Incoming) -> Effect[None, Any]:
        state = self._state
        address = message.envelope.address
        is_request = isinstance(message, IncomingRequest | OutgoingRequest)

        def loop() -> Effect[None, Any]:
            # Entities draining from a released shard still take interrupts
            # and acks.
            if not state.is_entity_on_local_shards(address) and (
                is_request or address.shard_id not in state.releasing_shards
            ):
                return fail(EntityNotAssignedToRunner(address=address))
            found = state.entity_managers.get(address.entity_type)
            if found is None:
                return self.wait_for_entity_manager(address.entity_type).and_then(suspend(loop))
            if found.status == "closed" or (
                found.status == "closing" and isinstance(message, IncomingRequest)
            ):
                # Shutting down: no new requests.
                return fail(EntityNotAssignedToRunner(address=address))
            if isinstance(message, IncomingRequest | IncomingEnvelope):
                return found.manager.send(message)
            return state.runners.send_local(
                message,
                send=found.manager.send_local,
                simulate_remote_serialization=state.config.simulate_remote_serialization,
            )

        send = suspend(loop)
        return state.await_shard_lock(address.shard_id).and_then(send) if is_request else send

    def notify_local(
        self, message: Outgoing | Incoming, discard: bool, *, wait_until_read: bool = False
    ) -> Effect[None, Any]:
        state = self._state

        def notify_now() -> Effect[None, EntityNotAssignedToRunner]:
            if not state.storage_enabled:
                return die(RuntimeError("Sharding.notifyLocal: storage is disabled"))
            _read_when_due(state, message)
            return state.storage_read_latch.open().as_void()

        def notify_storage(_: IncomingLocal) -> Effect[None, EntityNotAssignedToRunner]:
            return notify_now()

        def loop() -> Effect[None, Any]:  # noqa: PLR0911
            address = message.envelope.address
            found = state.entity_managers.get(address.entity_type)
            if found is None:
                return self.wait_for_entity_manager(address.entity_type).and_then(suspend(loop))
            if found.status == "closed":
                return fail(EntityNotAssignedToRunner(address=address))
            is_local = state.is_entity_on_local_shards(address)
            if isinstance(message, IncomingRequest | IncomingEnvelope):
                if not is_local:
                    return fail(EntityNotAssignedToRunner(address=address))
                if isinstance(message, IncomingRequest) and found.manager.is_processing_for(
                    message, exclude_replies=True
                ):
                    return fail(
                        AlreadyProcessingMessage(
                            address=address, envelope_id=message.envelope.request_id
                        )
                    )
                if isinstance(message, IncomingRequest) and wait_until_read:
                    if not state.storage_enabled:
                        return notify_now()
                    request = message
                    return callback(lambda resume: self._park(request, resume))
                return notify_now()
            return state.runners.notify_local(
                message, notify=notify_storage, discard=discard, storage_only=not is_local
            )

        return suspend(loop)

    def _park(
        self,
        message: IncomingRequest,
        resume: Callable[[Effect[None, EntityNotAssignedToRunner]], None],
    ) -> None:
        state = self._state
        request_id = message.envelope.request_id
        entry = state.pending_notifications.get(request_id)
        if entry is not None:
            previous = entry.resume

            def both(effect: Effect[None, EntityNotAssignedToRunner]) -> None:
                previous(effect)
                resume(effect)

            entry.resume = both
            return
        state.pending_notifications[request_id] = PendingNotification(resume, message)
        state.storage_read_latch.open_unsafe()

    # --- outgoing messages ----------------------------------------------------------------

    def send_outgoing(
        self,
        message: Outgoing,
        discard: bool,
        retries: int | None = None,
        runner: RunnerAddress | None = None,
    ) -> Effect[None, OutgoingError]:
        """Route ``message``; ``runner`` is the runner serving the request,
        for its interrupts and acks (later attempts use the current shard
        assignment)."""
        state = self._state
        annotations = (
            message.annotations if isinstance(message, OutgoingRequest) else message.rpc.annotations
        )
        persisted = annotations.get(Persisted)
        should_fail = not discard and (
            isinstance(message, OutgoingRequest) or isinstance(message.envelope, AckChunk)
        )

        def abandon(error: EntityNotAssignedToRunner) -> Effect[None, OutgoingError]:
            if not persisted:
                if should_fail:
                    return fail(error)
                return log_debug(
                    "Abandoning outgoing message during shutdown", message.envelope.address
                )
            persist: Effect[Any, Any] = (
                state.storage.save_request(message)
                if isinstance(message, OutgoingRequest)
                else state.storage.save_envelope(message)
            )
            then: Effect[None, Any]
            if should_fail:
                # The message is durable, so a transient routing state is
                # never an error for the caller; the runner can no longer
                # observe the reply, so the caller is interrupted and the
                # request is served under the next owner.
                then = (
                    _cluster_abandon.interrupt
                    if isinstance(message, OutgoingRequest)
                    else fail(error)
                )
            else:
                then = log_warning(
                    "Persisting outgoing message abandoned during shutdown",
                    message.envelope.address,
                )
            return persist.pipe(catch_tag(MalformedMessage, _die)).and_then(then)

        def attempt() -> Effect[None, Any]:  # noqa: PLR0911
            address = message.envelope.address
            if persisted and not state.storage_enabled:
                return die(
                    RuntimeError("Sharding.sendOutgoing: Persisted messages require MessageStorage")
                )
            if should_fail and state.is_shutdown:
                return fail(EntityNotAssignedToRunner(address=address))
            target = runner if runner is not None else state.shard_assignments.get(address.shard_id)
            is_local = target is not None and state.is_local_runner(target)
            if persisted:
                if is_local:
                    return self.notify_local(message, discard)
                return state.runners.notify(target, message, discard=discard)
            if target is None:
                return fail(EntityNotAssignedToRunner(address=address))
            if isinstance(message, OutgoingRequest):
                entry = state.client_requests.get(message.envelope.request_id)
                if entry is not None:
                    entry.runner = target
            if is_local:
                return self.send_local(message)
            if discard:
                return state.runners.notify(target, message, discard=discard)
            return state.runners.send(target, message)

        def recover(error: Any) -> Effect[None, OutgoingError]:
            if not isinstance(error, EntityNotAssignedToRunner | RunnerUnavailable):
                return fail(error)
            # Abandon the message during teardown: retrying would loop
            # forever once the runner is shutting down.
            if isinstance(error, EntityNotAssignedToRunner):
                target = state.entity_managers.get(message.envelope.address.entity_type)
                cannot_recover = state.is_shutdown or (
                    target is not None and target.status != "alive"
                )
                if cannot_recover:
                    return abandon(error)
            if retries == 0:
                return die(error)
            return self.send_outgoing(
                message, discard, None if retries is None else retries - 1
            ).delay(state.config.send_retry_interval)

        return suspend(attempt).catch_all(recover)

    def reset(self, request_id: Any, expected_reply_id: Any | None) -> Effect[bool]:
        return self._state.storage.clear_replies(
            request_id, expected_reply_id=expected_reply_id
        ).match_cause(on_failure=lambda _: False, on_success=lambda _: True)


def _read_when_due(state: ShardingState, message: Outgoing | Incoming) -> None:
    """For a request due later (``DeliverAt``, such as a durable clock's
    wake-up), also read storage when it falls due, on the ``Clock``: the
    storage poll alone finds it up to ``entity_message_poll_interval`` late
    (pyfect-only; the poll stays the fallback for another runner's messages)."""
    request = message.envelope
    if not isinstance(request, Request):
        return
    due = deliver_at.to_millis(request.payload)
    wait = None if due is None else due - state.now_millis()
    if wait is not None and wait > 0:
        state.run_fork(sleep(Seconds(wait / 1000)).and_then(state.storage_read_latch.open()))


def _die(error: MalformedMessage) -> Effect[Any]:
    return die(error)


__all__ = ["Routing"]
