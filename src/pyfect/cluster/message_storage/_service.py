"""The ``MessageStorage`` service and ``make``, which adds the reply
handlers (in memory, per runner) to a storage that persists."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from typing import Any, Never, Protocol

from pyfect._concurrency import for_each
from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect._fiber import Fiber
from pyfect.cluster.cluster_error import (
    EntityNotAssignedToRunner,
    MalformedMessage,
    PersistenceError,
)
from pyfect.cluster.cluster_schema import ABANDON_ANNOTATION
from pyfect.cluster.entity_address import EntityAddress
from pyfect.cluster.message import (
    Incoming,
    IncomingRequest,
    OutgoingEnvelope,
    OutgoingRequest,
)
from pyfect.cluster.reply import Reply, ReplyWithContext, WithExit
from pyfect.cluster.shard_id import ShardId
from pyfect.cluster.snowflake import Snowflake
from pyfect.context import Reference, Tag
from pyfect.effect import (
    callback,
    current_fiber,
    fail,
    provide_service,
    suspend,
    sync,
    void,
)


@dataclass(frozen=True, slots=True)
class SaveSuccess:
    """The message was saved."""


SAVE_SUCCESS = SaveSuccess()


@dataclass(frozen=True, slots=True, kw_only=True)
class SaveDuplicate:
    """A request with the same primary key was saved before, as
    ``original_id``; ``last_received_reply`` is its exit or its last
    acknowledged chunk."""

    original_id: Snowflake
    last_received_reply: Reply | None


type SaveResult = SaveSuccess | SaveDuplicate


class StorageBase(Protocol):
    """What a storage implements; ``make`` adds the reply handlers. Its
    ``save_reply`` gives back the reply it persisted (a defect in place of
    one that could not be encoded)."""

    def save_request(
        self, message: OutgoingRequest, /
    ) -> Effect[SaveResult, PersistenceError | MalformedMessage]: ...

    def save_envelope(
        self, message: OutgoingEnvelope, /
    ) -> Effect[None, PersistenceError | MalformedMessage]: ...

    def save_reply(
        self, reply: ReplyWithContext, /
    ) -> Effect[ReplyWithContext, PersistenceError | MalformedMessage]: ...

    def clear_replies(
        self, request_id: Snowflake, /, *, expected_reply_id: Snowflake | None = None
    ) -> Effect[None, PersistenceError]: ...

    def replies_for(
        self, requests: Iterable[OutgoingRequest], /
    ) -> Effect[list[Reply], PersistenceError | MalformedMessage]: ...

    def replies_for_unfiltered(
        self, request_ids: Iterable[Snowflake], /
    ) -> Effect[list[Any], PersistenceError | MalformedMessage]: ...

    def request_id_for_primary_key(
        self, *, address: EntityAddress, tag: str, id: str
    ) -> Effect[Snowflake | None, PersistenceError]: ...

    def unprocessed_messages(
        self,
        shard_ids: Iterable[ShardId],
        /,
        *,
        responder: MessageStorageService,
        limit: int | None = None,
        addresses: Sequence[EntityAddress] | None = None,
    ) -> Effect[list[Incoming], PersistenceError]:
        """The unprocessed messages; ``responder`` (the storage reading
        them, Effect's ``this``) saves their replies and the defects of
        malformed ones."""
        ...

    def unprocessed_messages_by_id(
        self, message_ids: Iterable[Snowflake], /, *, responder: MessageStorageService
    ) -> Effect[list[Incoming], PersistenceError]: ...

    def reset_shards(self, shard_ids: Iterable[ShardId], /) -> Effect[None, PersistenceError]: ...

    def reset_address(self, address: EntityAddress, /) -> Effect[None, PersistenceError]: ...

    def reset_requests(
        self, request_ids: Sequence[Snowflake], /
    ) -> Effect[None, PersistenceError]: ...

    def reset_addresses(
        self, addresses: Sequence[EntityAddress], /
    ) -> Effect[None, PersistenceError]: ...

    def clear_address(self, address: EntityAddress, /) -> Effect[None, PersistenceError]: ...

    def with_transaction[A, E, R](self, effect: Effect[A, E, R], /) -> Effect[A, E, R]: ...


type Notification = Effect[None, PersistenceError | MalformedMessage]


class TransactionNotifications(
    Reference[list[Notification] | None],
    key="effect/cluster/MessageStorage/TransactionNotifications",
):
    """Inside ``with_transaction``: the reply notifications that wait for
    the outermost commit."""

    @classmethod
    def default(cls) -> list[Notification] | None:
        return None


type _Resume = Callable[[Effect[None, EntityNotAssignedToRunner]], None]


@dataclass(eq=False, slots=True)
class _ReplyHandler:
    message: OutgoingRequest | IncomingRequest
    shard_set: set[_ReplyHandler]
    resume: _Resume

    def respond(self, reply: ReplyWithContext) -> Notification:
        message = self.message
        if isinstance(message, IncomingRequest):
            return message.respond(reply)
        return message.respond(reply.reply)


def _abandon(fiber: Fiber[Any, Any]) -> Effect[Never]:
    def register(_resume: Callable[[Effect[Never]], None]) -> None:
        fiber.interrupt_as_unsafe(fiber.id, ABANDON_ANNOTATION)

    return callback(register).interruptible()


@dataclass(eq=False, slots=True)
class MessageStorageService:
    """Where messages to entities and their replies are kept (Effect's
    ``MessageStorage``), with the reply handlers of this runner.

    ``unprocessed_messages`` claims the messages it returns for ten
    minutes; ``reset_*`` release claims early."""

    base: StorageBase
    _handlers: dict[Snowflake, list[_ReplyHandler]] = field(
        default_factory=dict[Snowflake, list[_ReplyHandler]]
    )
    _handlers_by_shard: dict[str, set[_ReplyHandler]] = field(
        default_factory=dict[str, set[_ReplyHandler]]
    )

    def save_request(
        self, message: OutgoingRequest, /
    ) -> Effect[SaveResult, PersistenceError | MalformedMessage]:
        """Saves the request ``message``, or gives ``SaveDuplicate`` (with
        the original's id and its last reply) when a request of the same
        primary key is already stored. Fails with ``PersistenceError``
        when the storage cannot be written, ``MalformedMessage`` when the
        message (or the stored reply) does not encode (or decode)."""
        return self.base.save_request(message)

    def save_envelope(
        self, message: OutgoingEnvelope, /
    ) -> Effect[None, PersistenceError | MalformedMessage]:
        """Saves the envelope ``message`` (an ``AckChunk`` or an
        ``Interrupt``). Fails with ``PersistenceError`` when the storage
        cannot be written, ``MalformedMessage`` when it does not encode."""
        return self.base.save_envelope(message)

    def clear_replies(
        self, request_id: Snowflake, /, *, expected_reply_id: Snowflake | None = None
    ) -> Effect[None, PersistenceError]:
        """Deletes the replies of ``request_id``; with
        ``expected_reply_id``, only while that is still its latest reply
        (so a stale resume cannot clear a newer one). Fails with
        ``PersistenceError`` when the storage cannot be written."""
        return self.base.clear_replies(request_id, expected_reply_id=expected_reply_id)

    def replies_for(
        self, requests: Iterable[OutgoingRequest], /
    ) -> Effect[list[Reply], PersistenceError | MalformedMessage]:
        """The stored replies of ``requests`` that are still to be
        delivered: their unacknowledged chunks and their ``WithExit``.
        Fails with ``PersistenceError`` when the storage cannot be read,
        ``MalformedMessage`` when a reply does not decode."""
        return self.base.replies_for(requests)

    def replies_for_unfiltered(
        self, request_ids: Iterable[Snowflake], /
    ) -> Effect[list[Any], PersistenceError | MalformedMessage]:
        """Every stored reply of ``request_ids``, encoded. Fails with
        ``PersistenceError`` when the storage cannot be read."""
        return self.base.replies_for_unfiltered(request_ids)

    def request_id_for_primary_key(
        self, *, address: EntityAddress, tag: str, id: str
    ) -> Effect[Snowflake | None, PersistenceError]:
        """The id of the stored request to ``address`` with RPC ``tag``
        and primary key ``id``, ``None`` when there is none. Fails with
        ``PersistenceError`` when the storage cannot be read."""
        return self.base.request_id_for_primary_key(address=address, tag=tag, id=id)

    def unprocessed_messages(
        self,
        shard_ids: Iterable[ShardId],
        /,
        *,
        limit: int | None = None,
        addresses: Sequence[EntityAddress] | None = None,
    ) -> Effect[list[Incoming], PersistenceError]:
        """Claims, for ten minutes, the unprocessed messages of
        ``shard_ids`` and gives them: requests without a ``WithExit`` or
        with unacknowledged chunks, the latest ``AckChunk`` and the
        ``Interrupt`` envelopes of unprocessed requests. ``limit`` bounds
        how many one read gives, ``addresses`` restricts it to those
        entities. A message that does not decode gets a defect reply
        instead. Fails with ``PersistenceError`` when the storage cannot
        be read."""
        return self.base.unprocessed_messages(
            shard_ids, responder=self, limit=limit, addresses=addresses
        )

    def unprocessed_messages_by_id(
        self, message_ids: Iterable[Snowflake], /
    ) -> Effect[list[Incoming], PersistenceError]:
        """The unprocessed messages among ``message_ids``, claimed as
        ``unprocessed_messages`` claims them. Fails with
        ``PersistenceError`` when the storage cannot be read."""
        return self.base.unprocessed_messages_by_id(message_ids, responder=self)

    def reset_shards(self, shard_ids: Iterable[ShardId], /) -> Effect[None, PersistenceError]:
        """Releases the claims on the messages of ``shard_ids``, so the
        next read gives them again. Fails with ``PersistenceError`` when
        the storage cannot be written."""
        return self.base.reset_shards(shard_ids)

    def reset_address(self, address: EntityAddress, /) -> Effect[None, PersistenceError]:
        """Releases the claims on the messages to ``address``. Fails with
        ``PersistenceError`` when the storage cannot be written."""
        return self.base.reset_address(address)

    def reset_requests(self, request_ids: Sequence[Snowflake], /) -> Effect[None, PersistenceError]:
        """Releases the claims on ``request_ids``, leaving their replies
        and processed state as they are. Fails with ``PersistenceError``
        when the storage cannot be written."""
        return self.base.reset_requests(request_ids)

    def reset_addresses(
        self, addresses: Sequence[EntityAddress], /
    ) -> Effect[None, PersistenceError]:
        """Releases the claims on the messages to ``addresses``. Fails
        with ``PersistenceError`` when the storage cannot be written."""
        return self.base.reset_addresses(addresses)

    def clear_address(self, address: EntityAddress, /) -> Effect[None, PersistenceError]:
        """Deletes every message to ``address`` and their replies. Fails
        with ``PersistenceError`` when the storage cannot be written."""
        return self.base.clear_address(address)

    def with_transaction[A, E, R](self, effect: Effect[A, E, R], /) -> Effect[A, E, R]:
        """``effect`` in one storage transaction; reply notifications wait
        for the outermost commit."""
        require_effect(effect, "effect")

        def run(outer: list[Notification] | None) -> Effect[A, E, R]:
            notifications: list[Notification] = []

            def committed(_: A) -> Effect[None]:
                if outer is not None:
                    pending = outer
                    return sync(lambda: pending.extend(notifications))
                return for_each(notifications, lambda n: n).as_void().or_die()

            inner = effect.pipe(provide_service(TransactionNotifications, notifications))
            return self.base.with_transaction(inner).tap(committed)

        return TransactionNotifications().flat_map(run)

    def register_reply_handler(
        self, message: OutgoingRequest | IncomingRequest, /
    ) -> Effect[None, EntityNotAssignedToRunner]:
        """Wait for the exit of ``message``'s request, sending every reply
        saved meanwhile to it. Fails with ``EntityNotAssignedToRunner``
        when its shard's handlers are dropped."""
        request_id = message.envelope.request_id
        handlers_by_id = self._handlers
        by_shard = self._handlers_by_shard

        def register(resume: _Resume) -> Effect[None]:
            shard = str(message.envelope.address.shard_id)
            handlers = handlers_by_id.setdefault(request_id, [])
            shard_set = by_shard.setdefault(shard, set())
            entry = _ReplyHandler(message, shard_set, resume)
            handlers.append(entry)
            shard_set.add(entry)

            def unregister() -> None:
                if entry in handlers:
                    handlers.remove(entry)
                shard_set.discard(entry)

            return sync(unregister)

        return callback(register)

    def _resume_unregistered(self, handler: _ReplyHandler, interrupt: bool) -> None:
        if interrupt:
            handler.resume(_current_abandon())
        else:
            address = handler.message.envelope.address
            handler.resume(fail(EntityNotAssignedToRunner(address=address)))

    def unregister_reply_handler(
        self, request_id: Snowflake, /, *, interrupt: bool = False
    ) -> Effect[None]:
        """Drop the handlers of ``request_id``: they fail with
        ``EntityNotAssignedToRunner``, or are interrupted as abandoned."""

        def run() -> None:
            handlers = self._handlers.pop(request_id, None)
            for handler in handlers or ():
                handler.shard_set.discard(handler)
                self._resume_unregistered(handler, interrupt)

        return sync(run)

    def unregister_shard_reply_handlers(
        self, shard_id: ShardId, /, *, interrupt: bool = False
    ) -> Effect[None]:
        """Drop the handlers of every request to ``shard_id``."""

        def run() -> None:
            shard_set = self._handlers_by_shard.pop(str(shard_id), None)
            for handler in list(shard_set or ()):
                self._handlers.pop(handler.message.envelope.request_id, None)
                self._resume_unregistered(handler, interrupt)

        return sync(run)

    def save_reply(
        self, reply: ReplyWithContext, /
    ) -> Effect[None, PersistenceError | MalformedMessage]:
        """Persist ``reply`` and send it to the request's handlers; an exit
        resumes them (after the outermost commit, in a transaction)."""
        request_id = reply.reply.request_id

        def persisted(saved: ReplyWithContext) -> Effect[None, PersistenceError | MalformedMessage]:
            def notify_now() -> Notification:
                handlers = self._handlers.get(request_id)
                if handlers is None:
                    return void
                if isinstance(saved.reply, WithExit):
                    del self._handlers[request_id]
                    for handler in handlers:
                        handler.shard_set.discard(handler)
                        handler.resume(void)
                if len(handlers) == 1:
                    return handlers[0].respond(saved)
                return for_each(list(handlers), lambda h: h.respond(saved)).as_void()

            notify = suspend(notify_now)
            if not isinstance(saved.reply, WithExit):
                return notify

            def defer(notifications: list[Notification] | None) -> Notification:
                if notifications is None:
                    return notify
                return sync(lambda: notifications.append(notify))

            return TransactionNotifications().flat_map(defer)

        return self.base.save_reply(reply).flat_map(persisted)


def _current_abandon() -> Effect[None]:
    return current_fiber().flat_map(_abandon)


def make(base: StorageBase) -> Effect[MessageStorageService]:
    """A message storage on ``base`` (Effect's ``MessageStorage.make``)."""
    return sync(lambda: MessageStorageService(base))


class MessageStorage(Tag[MessageStorageService], key="effect/cluster/MessageStorage"):
    """The message storage of this runner."""


__all__ = [
    "SAVE_SUCCESS",
    "MessageStorage",
    "MessageStorageService",
    "Notification",
    "SaveDuplicate",
    "SaveResult",
    "SaveSuccess",
    "StorageBase",
    "TransactionNotifications",
    "make",
]
