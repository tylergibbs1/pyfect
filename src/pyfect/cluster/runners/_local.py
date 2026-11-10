"""``Runners.make``: a transport completed with local delivery. Persisted
messages are saved first; a duplicate request resumes from its stored
replies; replies a request cannot get from a local handler are read back
from storage, on notification or every ``entity_reply_poll_interval``."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import Any, Never, cast

from pyfect import exit as Exit
from pyfect._core import Effect, Restore, uninterruptible_mask
from pyfect._fiber import Fiber
from pyfect.cause import Cause
from pyfect.cluster.cluster_error import (
    EntityNotAssignedToRunner,
    MalformedMessage,
    PersistenceError,
)
from pyfect.cluster.cluster_schema import Persisted
from pyfect.cluster.message import (
    Outgoing,
    OutgoingEnvelope,
    OutgoingRequest,
    deserialize_local,
    incoming_local_from_outgoing,
    serialize,
)
from pyfect.cluster.message_storage import (
    NOOP,
    MessageStorage,
    MessageStorageService,
    SaveResult,
    SaveSuccess,
    TransactionNotifications,
)
from pyfect.cluster.message_storage._service import Notification
from pyfect.cluster.reply import Reply, WithExit
from pyfect.cluster.runner_address import RunnerAddress
from pyfect.cluster.runners._service import (
    LocalSendError,
    NotifyLocalFn,
    RunnersService,
    RunnersTransport,
    SendError,
    SendLocalFn,
)
from pyfect.cluster.sharding_config import ShardingConfig
from pyfect.cluster.snowflake import Generator, Snowflake, SnowflakeGenerator
from pyfect.duration import Duration
from pyfect.effect import catch_tag, die, gen, never, succeed, suspend, sync
from pyfect.latch import Latch
from pyfect.logger import log_debug
from pyfect.scope import CloseableScope, Scope, fork_in, fork_scoped, scoped

_VOID: Effect[None] = succeed(None)

type _AfterPersist[E] = Callable[[Outgoing, bool], Effect[None, E]]


@dataclass(slots=True, eq=False)
class _StorageRequest:
    """The callers waiting for a request's replies from storage, and the
    replies read for them. ``messages`` keeps insertion order."""

    latch: Latch
    messages: dict[int, OutgoingRequest] = field(default_factory=dict[int, OutgoingRequest])
    replies: list[Reply] = field(default_factory=list[Reply])
    pump: Fiber[None, Never] | None = None


def _die_malformed(error: MalformedMessage) -> Effect[Never]:
    return die(error)


def _is_persisted(message: Outgoing) -> bool:
    return message.rpc.annotations.get(Persisted)


def _notify_after_commit[E](message: Outgoing, notify: Effect[None, E]) -> Effect[None, E]:
    """A message saved in a transaction is invisible to readers until the
    commit, so its wake-up waits for the commit. A failure then can no
    longer be returned and is dropped; the next storage poll delivers the
    message."""
    if not _is_persisted(message):
        return notify

    def defer(notifications: list[Notification] | None) -> Effect[None, E]:
        if notifications is None:
            return notify
        return sync(lambda: notifications.append(notify.ignore()))

    return TransactionNotifications().flat_map(defer)


class _LocalRunners:
    __slots__ = (
        "_codec_for",
        "_rewrites",
        "_scope",
        "_snowflakes",
        "_storage",
        "_storage_latch",
        "_storage_requests",
        "_transport",
        "_waiting",
    )

    def __init__(
        self,
        transport: RunnersTransport,
        storage: MessageStorageService,
        scope: CloseableScope,
        snowflakes: SnowflakeGenerator,
    ) -> None:
        self._transport = transport
        self._codec_for = transport.codec_for
        self._storage = storage
        self._scope = scope
        self._snowflakes = snowflakes
        self._rewrites: dict[Snowflake, Snowflake] = {}
        self._storage_requests: dict[Snowflake, _StorageRequest] = {}
        self._waiting: dict[Snowflake, OutgoingRequest] = {}
        self._storage_latch = Latch(False)

    # --- the remote half ---------------------------------------------------------------

    def ping(self, address: RunnerAddress, /) -> Effect[None, Any]:
        return self._transport.ping(address)

    def send(self, address: RunnerAddress, message: Outgoing, /) -> Effect[None, SendError]:
        return self._transport.send(address, message)

    def on_runner_unavailable(self, address: RunnerAddress, /) -> Effect[None]:
        return self._transport.on_runner_unavailable(address)

    # --- persisting ------------------------------------------------------------------------

    def _notify_with[E](
        self, message: Outgoing, after_persist: _AfterPersist[E]
    ) -> Effect[None, E | PersistenceError]:
        """Save a persisted message, then ``after_persist(message,
        is_duplicate)``; a duplicate request is resumed under its original
        id, or answered at once with its stored exit."""
        if not _is_persisted(message):
            return after_persist(message, False)
        storage = self._storage
        if isinstance(message, OutgoingEnvelope):
            rewrite = self._rewrites.get(message.envelope.request_id)
            entry = self._storage_requests.get(
                message.envelope.request_id if rewrite is None else rewrite
            )
            if rewrite is not None:
                message = replace(message, envelope=message.envelope.with_request_id(rewrite))
            after = after_persist(message, False)
            if entry is not None:
                after = entry.latch.open().and_then(after)
            saved = storage.save_envelope(message).pipe(catch_tag(MalformedMessage, _die_malformed))
            return saved.and_then(after)
        request = message

        def on_saved(result: SaveResult) -> Effect[None, E]:
            if isinstance(result, SaveSuccess):
                return after_persist(request, False)
            last = result.last_received_reply
            request_id = request.envelope.request_id
            if isinstance(last, WithExit):
                return request.respond(last.with_request_id(request_id))
            self._rewrites[request_id] = result.original_id

            def respond(reply: Reply) -> Effect[None]:
                if isinstance(reply, WithExit):
                    self._rewrites.pop(request_id, None)
                return request.respond(reply.with_request_id(request_id))

            original = replace(
                request,
                last_received_reply=last,
                envelope=request.envelope.with_request_id(result.original_id),
                respond=respond,
                encoded_cache=None,
            )
            return after_persist(original, True)

        saved = storage.save_request(request).pipe(catch_tag(MalformedMessage, _die_malformed))
        return saved.flat_map(on_saved)

    # --- replies from storage -------------------------------------------------------------

    def _remove_storage_request(self, request_id: Snowflake, entry: _StorageRequest) -> None:
        # A reset request can register a replacement entry under the same id.
        if self._storage_requests.get(request_id) is not entry:
            return
        del self._storage_requests[request_id]
        self._waiting.pop(request_id, None)

    def _pump_replies(self, request_id: Snowflake, entry: _StorageRequest) -> Effect[None]:
        """Sends the replies the storage loop reads to every waiting
        caller, waiting for the ack of each chunk; owned by the entry, so
        one caller can leave without stopping the others."""

        @gen
        def pump():
            while True:
                yield from entry.latch.wait()
                index = 0
                while index < len(entry.replies):
                    reply = entry.replies[index]
                    if isinstance(reply, WithExit):
                        self._remove_storage_request(request_id, entry)
                        for message in list(entry.messages.values()):
                            yield from message.respond(reply)
                        return
                    entry.latch.close_unsafe()
                    for message in list(entry.messages.values()):
                        yield from message.respond(reply)
                    yield from entry.latch.wait()
                    index += 1
                entry.replies = []
                entry.latch.close_unsafe()
                first = next(iter(entry.messages.values()), None)
                if first is None:
                    return
                self._waiting[request_id] = first
                self._storage_latch.open_unsafe()

        return pump

    def _reply_from_storage(self, message: OutgoingRequest) -> Effect[None]:
        def body(restore: Restore) -> Effect[None]:
            @gen
            def run():
                request_id = message.envelope.request_id
                entry = self._storage_requests.get(request_id)
                if entry is None:
                    entry = _StorageRequest(Latch(False))
                    entry.pump = yield from fork_in(
                        self._pump_replies(request_id, entry), self._scope
                    )
                    self._storage_requests[request_id] = entry
                    self._waiting[request_id] = message
                current = entry
                pump = cast("Fiber[None, Never]", current.pump)
                current.messages[id(message)] = message
                # A waiter joining an existing entry (a duplicate) reads now.
                self._storage_latch.open_unsafe()

                def leave() -> Effect[None]:
                    current.messages.pop(id(message), None)
                    if not current.messages:
                        self._remove_storage_request(request_id, current)
                        return pump.interrupt()
                    # The storage loop decodes replies with the waiting message.
                    if self._waiting.get(request_id) is message:
                        self._waiting[request_id] = next(iter(current.messages.values()))
                    return _VOID

                return (yield from restore(pump.join()).ensuring(suspend(leave)))

            return run

        return uninterruptible_mask(body)

    def _reply_from_storage_with_wake(self, message: OutgoingRequest) -> Effect[None]:
        """Read the replies back from storage; a local reply handler wakes
        the storage loop, so streams need not wait for the next poll."""
        latch = self._storage_latch

        def wake(_: Reply) -> Effect[None]:
            return latch.open().as_void()

        wakeup = (
            self._storage.register_reply_handler(replace(message, respond=wake))
            .ignore()
            .and_then(never)
        )
        return self._reply_from_storage(message).race_first(wakeup)

    def _can_reply_locally(self, message: OutgoingRequest) -> bool:
        # Stream replies stay on the storage loop, which keeps their order
        # and waits for their acks.
        return self._storage is not NOOP and _is_persisted(message) and not message.rpc.is_stream

    def _notify_local_request(
        self, message: OutgoingRequest, notify_entity: Callable[[Outgoing], Effect[None]]
    ) -> Effect[None, PersistenceError]:
        """Register the reply handler before saving, so a fresh request is
        answered by it without reading storage."""

        @gen
        def run():
            handler = yield from fork_scoped(
                self._storage.register_reply_handler(message), start_immediately=True
            )

            def after(saved: Outgoing, duplicate: bool) -> Effect[None]:
                outgoing = cast("OutgoingRequest", saved)
                if duplicate:
                    return (
                        handler.interrupt()
                        .and_then(notify_entity(saved))
                        .and_then(self._reply_from_storage_with_wake(outgoing))
                    )
                # The handler can be dropped (its shard moved, a commit
                # error hid the notification): the reply is then in storage.
                return (
                    notify_entity(saved)
                    .and_then(handler.join())
                    .pipe(
                        catch_tag(
                            EntityNotAssignedToRunner,
                            lambda _: self._reply_from_storage(outgoing),
                        )
                    )
                )

            yield from self._notify_with(message, after)

        return scoped(run)

    def _read_replies_loop(self) -> Effect[Never]:
        storage = self._storage

        def logged(cause: Cause[Any]) -> Effect[list[Reply]]:
            return (
                log_debug(cause)
                .annotate_logs(
                    {
                        "package": "@effect/cluster",
                        "module": "Runners",
                        "fiber": "Read replies loop",
                    }
                )
                .as_([])
            )

        @gen
        def loop():
            found: dict[int, _StorageRequest] = {}
            while True:
                yield from self._storage_latch.wait()
                self._storage_latch.close_unsafe()
                replies = yield from storage.replies_for(list(self._waiting.values())).catch_cause(
                    logged
                )
                for reply in replies:
                    entry = self._storage_requests.get(reply.request_id)
                    if entry is None:
                        continue
                    entry.replies.append(reply)
                    self._waiting.pop(reply.request_id, None)
                    found[id(entry)] = entry
                for entry in found.values():
                    entry.latch.open_unsafe()
                found.clear()

        return loop

    def _poll(self) -> Effect[None]:
        def body() -> Effect[None]:
            if not self._waiting:
                return self._storage_latch.wait()
            return self._storage_latch.open().as_void()

        return suspend(body)

    # --- the service --------------------------------------------------------------------

    def send_local(
        self, message: Outgoing, /, *, send: SendLocalFn, simulate_remote_serialization: bool
    ) -> Effect[None, LocalSendError | PersistenceError]:
        if not simulate_remote_serialization:
            return send(incoming_local_from_outgoing(message))
        codec_for = self._codec_for

        def malformed(error: MalformedMessage) -> Effect[None]:
            if isinstance(message, OutgoingEnvelope):
                return die(error)
            return message.respond(
                WithExit(
                    id=self._snowflakes.next_unsafe(),
                    request_id=message.envelope.request_id,
                    exit=Exit.die(error),
                )
            )

        return (
            serialize(message, codec_for)
            .flat_map(lambda encoded: deserialize_local(message, encoded, codec_for))
            .flat_map(send)
            .pipe(catch_tag(MalformedMessage, malformed))
        )

    def notify(
        self, address: RunnerAddress | None, message: Outgoing, /, *, discard: bool
    ) -> Effect[None, SendError]:
        transport = self._transport

        def after(saved: Outgoing, duplicate: bool) -> Effect[None, SendError]:
            if discard or isinstance(saved, OutgoingEnvelope):
                return _notify_after_commit(saved, transport.notify(address, message, discard))
            if not duplicate and address is not None:
                return transport.send(address, saved).catch_all(
                    lambda _: self._reply_from_storage(saved)
                )
            return transport.notify(address, message, discard).and_then(
                self._reply_from_storage(saved)
            )

        return self._notify_with(message, after)

    def notify_local(
        self,
        message: Outgoing,
        /,
        *,
        notify: NotifyLocalFn,
        discard: bool,
        storage_only: bool = False,
    ) -> Effect[None, PersistenceError]:
        def notify_entity(outgoing: Outgoing) -> Effect[None]:
            return notify(incoming_local_from_outgoing(outgoing)).pipe(
                catch_tag(EntityNotAssignedToRunner, lambda _: _VOID)
            )

        if (
            isinstance(message, OutgoingRequest)
            and not discard
            and not storage_only
            and self._can_reply_locally(message)
        ):
            return self._notify_local_request(message, notify_entity)

        def after(saved: Outgoing, _duplicate: bool) -> Effect[None]:
            if discard or isinstance(saved, OutgoingEnvelope):
                return _notify_after_commit(saved, notify_entity(saved))
            reply = (
                self._reply_from_storage(saved)
                if storage_only
                else self._reply_from_storage_with_wake(saved)
            )
            return notify_entity(saved).and_then(reply)

        return self._notify_with(message, after)

    def _start(self, poll_interval: Duration) -> Effect[None]:
        if self._storage is NOOP:
            return _VOID

        @gen
        def start():
            yield from fork_in(self._read_replies_loop(), self._scope)
            yield from fork_in(self._poll().delay(poll_interval).forever(), self._scope)

        return start


def make(
    transport: RunnersTransport,
) -> Effect[RunnersService, Never, MessageStorage | Generator | ShardingConfig | Scope]:
    """A ``Runners`` service sending remotely through ``transport`` and
    delivering locally through storage (Effect's ``Runners.make``)."""

    @gen
    def run():
        storage = yield from MessageStorage()
        scope = yield from Scope()
        snowflakes = yield from Generator()
        config = yield from ShardingConfig()
        runners = _LocalRunners(transport, storage, scope, snowflakes)
        yield from runners._start(config.entity_reply_poll_interval)
        return cast("RunnersService", runners)

    return run


__all__ = ["make"]
