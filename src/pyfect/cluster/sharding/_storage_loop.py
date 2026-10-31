"""The storage inbox: reads unprocessed messages from storage and hands
them to the entity managers, in order, a batch at a time. It shuts down
before shard acquisition, so no message is processed once the shards are
released, and after the entity managers, so interrupts and acks still
reach them. Entities whose mailbox filled up resume from storage on
their own fiber."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from typing import Any, Never

from pyfect import cause as Cause
from pyfect._core import Effect
from pyfect.clock import sleep
from pyfect.cluster.cluster_error import (
    AlreadyProcessingMessage,
    EntityNotAssignedToRunner,
    MailboxFull,
    PersistenceError,
)
from pyfect.cluster.entity_address import EntityAddress
from pyfect.cluster.envelope import Interrupt
from pyfect.cluster.message import Incoming, IncomingEnvelope, IncomingRequest
from pyfect.cluster.reply import ReplyWithContext
from pyfect.cluster.runner_address import RunnerAddress
from pyfect.cluster.snowflake import Snowflake
from pyfect.effect import catch_tag, fail, gen, succeed, suspend, sync
from pyfect.logger import log_debug, log_warning
from pyfect.schedule import spaced
from pyfect.scope import add_finalizer, fork_in, scoped

from ._state import PendingNotification, ResumptionState, ShardingState, entity_not_registered

_VOID: Effect[None] = succeed(None)


class _Read:
    """The state of one pass of the storage loop."""

    __slots__ = (
        "capped",
        "delivered",
        "index",
        "messages",
        "removable",
        "reset_addresses",
        "reset_request_ids",
    )

    def __init__(self) -> None:
        self.index = 0
        self.messages: list[Incoming] = []
        self.delivered = False
        self.removable: dict[int, PendingNotification] = {}
        self.reset_addresses: dict[EntityAddress, None] = {}
        self.reset_request_ids: list[Snowflake] = []
        self.capped: dict[EntityAddress, None] = {}


class StorageInbox:
    __slots__ = ("_self_address", "_state")

    def __init__(self, state: ShardingState, self_address: RunnerAddress) -> None:
        self._state = state
        self._self_address = self_address

    # --- one message ----------------------------------------------------------------------

    def _release_completed_claim(self, read: _Read, message: Incoming) -> None:
        """A completed request may stay deduplicated after storage claims
        its reset: release the claim so the reset is redelivered at once."""
        found = self._state.entity_managers.get(message.envelope.address.entity_type)
        if found is None or not found.manager.is_processing_for(message, exclude_completed=True):
            read.reset_request_ids.append(message.envelope.request_id)

    def _send(self, read: _Read) -> Effect[None]:
        state = self._state

        def mark_delivered(_: None) -> None:
            read.delivered = True

        def body() -> Effect[None, Any]:  # noqa: PLR0911
            message = read.messages[read.index]
            address = message.envelope.address
            if address.shard_id not in state.acquired_shards:
                return _VOID
            found = state.entity_managers.get(address.entity_type)
            if found is None:
                if state.registration_time_remaining() > 0:
                    # Reset the address in case the entity is slow to register.
                    read.reset_addresses[address] = None
                    return _VOID
                # The entity did not register in time: save a defect reply.
                return entity_not_registered(address.entity_type)
            if found.status == "closed":
                return _VOID
            manager = found.manager
            processing = manager.is_processing_for(message)
            if isinstance(message, IncomingEnvelope) and processing:
                # The message may affect a request being processed.
                return manager.send(message).map(mark_delivered)
            if processing or found.status == "closing":
                # Already processing, or the entity is closing: skip it.
                if processing:
                    self._release_completed_claim(read, message)
                return _VOID
            if isinstance(message, IncomingRequest):
                pending = state.pending_notifications.pop(message.envelope.request_id, None)
                if pending is not None:
                    read.removable.pop(id(pending), None)
                    pending.resume(_VOID)
            # At entity capacity, messages for entities not yet resident are
            # skipped; their claims are released after the read.
            if state.residency_at_capacity() and not manager.is_resident_unsafe(address):
                read.capped[address] = None
                return _VOID
            # An entity resuming on another fiber takes the message id.
            resuming = state.entity_resumption.get(address)
            if resuming is not None:
                resuming.unprocessed[message.envelope.request_id] = None
                if isinstance(message, IncomingEnvelope) and isinstance(
                    message.envelope, Interrupt
                ):
                    resuming.interrupts[message.envelope.request_id] = message
                return _VOID
            return manager.send(message).map(mark_delivered)

        def failed(cause: Cause.Cause[Any]) -> Effect[None]:
            message = read.messages[read.index]
            found = cause.find_recoverable_error()
            if not isinstance(found, Cause.Fail):
                if cause.has_interrupts:
                    return _VOID
                defect = ReplyWithContext.from_defect(
                    id=state.snowflakes.next_unsafe(),
                    request_id=message.envelope.request_id,
                    defect=cause.squash(),
                )
                return state.storage.save_reply(defect).ignore()
            error = found.error
            if isinstance(error, AlreadyProcessingMessage):
                # Completion raced with decoding.
                self._release_completed_claim(read, message)
                return _VOID
            if isinstance(error, MailboxFull):
                address = message.envelope.address
                manager = state.entity_managers.get(address.entity_type)
                # A resident entity has a full mailbox; its messages resume
                # from storage once there is room.
                if (
                    isinstance(message, IncomingRequest)
                    and manager is not None
                    and manager.manager.is_resident_unsafe(address)
                ):
                    return self.resume_from_storage(message)
                # Otherwise the runner ran out of entity slots meanwhile.
                read.capped[address] = None
            return _VOID

        return suspend(body).catch_cause(failed)

    # --- one pass -------------------------------------------------------------------------

    def _read_and_process(
        self,
        read: _Read,
        *,
        limit: int | None = None,
        addresses: list[EntityAddress] | None = None,
    ) -> Effect[int, Any]:
        state = self._state

        @gen
        def run():
            read.messages = yield from state.storage.unprocessed_messages(
                list(state.acquired_shards), limit=limit, addresses=addresses
            )
            read.index = 0
            while read.index < len(read.messages):
                yield from self._send(read)
                read.index += 1
            return len(read.messages)

        return run

    def _pass(self, read: _Read, batch_size: int) -> Effect[None, Any]:
        state = self._state

        @gen
        def run():  # noqa: PLR0912
            # Wait for the next poll interval, or a notification.
            yield from state.storage_read_latch.wait()
            # A notification from now on starts the next read at once.
            state.storage_read_latch.close_unsafe()
            # While the lock is held, resuming entities know no more ids are
            # added to their unprocessed set.
            yield from state.storage_read_lock.take(1)
            for found in list(state.entity_managers.values()):
                found.manager.clear_processed()
            for pending in state.pending_notifications.values():
                read.removable[id(pending)] = pending

            read.delivered = False
            read_count = 0
            full_batch = False
            exhaustive = False

            # First deliver to resident entities, so they keep making
            # progress at the entity cap.
            if state.residency_at_capacity():
                resident: list[EntityAddress] = []
                for found in list(state.entity_managers.values()):
                    if found.status == "closed":
                        continue
                    resident.extend(found.manager.resident_addresses_unsafe())
                if resident:
                    read_count = yield from self._read_and_process(
                        read, limit=batch_size, addresses=resident
                    )
                    full_batch = read_count >= batch_size

            # Then the rest, spawning entities while slots are left.
            if not state.residency_at_capacity() and read_count < batch_size:
                limit = batch_size - read_count
                count = yield from self._read_and_process(read, limit=limit)
                if count >= limit:
                    full_batch = True
                elif not read.capped:
                    exhaustive = True

            if read.removable:
                # On an exhaustive read, a message not seen is no longer
                # processable here. At the cap, the messages are persisted
                # and delivered once a slot frees up, so senders succeed.
                # Otherwise the read was cut by the batch size and the
                # notifications stay for the next read.
                capped = bool(read.capped) or state.residency_at_capacity()
                if exhaustive or capped:
                    for pending in list(read.removable.values()):
                        state.pending_notifications.pop(pending.message.envelope.request_id, None)
                        pending.resume(
                            fail(
                                EntityNotAssignedToRunner(address=pending.message.envelope.address)
                            )
                            if exhaustive
                            else _VOID
                        )
                read.removable.clear()
            for address in list(read.reset_addresses):
                yield from log_warning(
                    "Could not find entity manager for address, retrying"
                ).annotate_logs("address", address)
            # Claims for unregistered entity types, and those skipped at the
            # entity cap, are reset in one storage call after the lock is
            # released and before the next read.
            to_reset: list[EntityAddress] | None = None
            if read.reset_addresses or read.capped:
                to_reset = [*read.reset_addresses, *read.capped]
                read.reset_addresses.clear()
                read.capped.clear()

            # Let the resuming entities check whether they are done.
            yield from state.storage_read_lock.release(1)

            if read.reset_request_ids:
                yield from state.storage.reset_requests(list(read.reset_request_ids)).ignore()
                read.reset_request_ids.clear()
            if to_reset is not None:
                yield from state.storage.reset_addresses(to_reset).ignore()

            # A full batch means more could be waiting: read again at once,
            # if this read made progress (a full batch of skipped messages
            # must not spin the loop).
            if full_batch and read.delivered:
                state.storage_read_latch.open_unsafe()

        return run

    def loop(self) -> Effect[Never]:
        state = self._state
        batch_size = max(1, state.config.unprocessed_message_batch_size)

        @gen
        def run():
            yield from log_debug("Starting")
            yield from add_finalizer(lambda _: log_debug("Shutting down"))
            read = _Read()
            while True:
                yield from self._pass(read, batch_size)

        def failed(cause: Cause.Cause[Any]) -> Effect[None]:
            return log_warning("Could not read messages from storage", cause)

        return (
            scoped(run)
            .ensuring(state.storage_read_lock.release_all().as_void())
            .catch_cause(failed)
            .forever()
            .annotate_logs(
                {
                    "module": "effect/cluster/Sharding",
                    "fiber": "Storage read loop",
                    "runner": self._self_address,
                }
            )
        )

    # --- resuming from storage ------------------------------------------------------------

    def resume_from_storage(self, last_received: IncomingRequest) -> Effect[None]:
        """Resume the unprocessed messages of an entity whose mailbox was
        full."""
        state = self._state
        address = last_received.envelope.address
        found = state.entity_resumption.get(address)
        if found is not None:
            found.unprocessed[last_received.envelope.request_id] = None
            return _VOID
        state.entity_resumption[address] = ResumptionState(
            {last_received.envelope.request_id: None}
        )
        return fork_in(self._resume(address), state.sharding_scope).as_void()

    def _resume(self, address: EntityAddress) -> Effect[None]:
        state = self._state

        @gen
        def run():
            found = state.entity_managers.get(address.entity_type)
            if found is None:
                state.entity_resumption.pop(address, None)
                return
            manager = found.manager
            resumption = state.entity_resumption[address]
            done = False
            while not done:
                # The shard moved away: stop.
                if address.shard_id not in state.acquired_shards:
                    return
                ids = list(resumption.unprocessed)[:1024]
                messages = yield from state.storage.unprocessed_messages_by_id(ids)
                # Should not happen, but handled just in case.
                if not messages:
                    yield from sleep(state.config.entity_message_poll_interval)
                    continue
                for message in messages:
                    yield from self._send_with_retry(manager, resumption, address, message)
                for request_id in ids:
                    resumption.unprocessed.pop(request_id, None)
                if resumption.unprocessed:
                    continue

                # Caught up with the storage loop: let it take over.
                def finish() -> bool:
                    if resumption.unprocessed:
                        return False
                    state.entity_resumption.pop(address, None)
                    return True

                done = yield from state.storage_read_lock.with_permits(sync(finish))

        def failed(cause: Cause.Cause[Any]) -> Effect[None]:
            return log_debug("Could not resume unprocessed messages", cause)

        def forget() -> None:
            state.entity_resumption.pop(address, None)

        return (
            run.retry(
                while_=lambda error: isinstance(error, PersistenceError),
                schedule=spaced(state.config.entity_message_poll_interval),
            )
            .catch_cause(failed)
            .annotate_logs(
                {
                    "module": "effect/cluster/Sharding",
                    "fiber": "Resuming unprocessed messages",
                    "runner": self._self_address,
                    "entity": address,
                }
            )
            .ensuring(sync(forget))
        )

    def _send_with_retry(
        self, manager: Any, resumption: ResumptionState, address: EntityAddress, message: Incoming
    ) -> Effect[None, EntityNotAssignedToRunner]:
        state = self._state

        def attempt() -> Effect[None, Any]:
            if address.shard_id not in state.acquired_shards:
                return fail(EntityNotAssignedToRunner(address=address))
            # A request that was interrupted gets its interrupt after it.
            interrupt = (
                resumption.interrupts.get(message.envelope.request_id)
                if isinstance(message, IncomingRequest)
                else None
            )
            if interrupt is None:
                return manager.send(message)

            def then(_: None) -> Effect[None, Any]:
                resumption.interrupts.pop(message.envelope.request_id, None)
                return manager.send(interrupt)

            return manager.send(message).flat_map(then)

        def retry(_: MailboxFull) -> Effect[None, EntityNotAssignedToRunner]:
            return self._send_with_retry(manager, resumption, address, message).delay(
                state.config.send_retry_interval
            )

        return (
            suspend(attempt)
            .pipe(catch_tag(MailboxFull, retry))
            .pipe(catch_tag(AlreadyProcessingMessage, lambda _: _VOID))
        )


__all__ = ["StorageInbox"]
