"""Message storage in memory (Effect's ``MessageStorage.MemoryDriver``):
one runner's journal of envelopes and their replies. It models claims
(ten minutes, as the SQL driver) but not transactions."""

from __future__ import annotations

from collections.abc import Callable, Generator, Sequence
from dataclasses import dataclass, field
from typing import Any

from pyfect import layer as layer_
from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect.clock import Clock, ClockService, now_millis_unsafe
from pyfect.cluster import reply as reply_
from pyfect.cluster import snowflake
from pyfect.cluster.cluster_error import PersistenceError
from pyfect.cluster.entity_address import EntityAddress
from pyfect.cluster.envelope import AddressEncoded
from pyfect.cluster.envelope import Encoded as EnvelopeEncoded
from pyfect.cluster.message_storage._encoded import (
    DuplicateEncoded,
    EncodedMessage,
    SaveResultEncoded,
    json_copy,
    make_encoded,
)
from pyfect.cluster.message_storage._service import (
    SAVE_SUCCESS,
    MessageStorage,
    MessageStorageService,
    TransactionNotifications,
)
from pyfect.cluster.snowflake import Snowflake
from pyfect.context import Reference, Tag
from pyfect.effect import gen, provide_service, succeed, sync

CLAIM_EXPIRATION_MILLIS = 10 * 60 * 1000
"""How long a returned message stays claimed (the SQL driver's
``last_read < ten minutes ago``)."""


@dataclass(eq=False, slots=True)
class MemoryEntry:
    """A stored request with its replies."""

    envelope: EnvelopeEncoded
    deliver_at: int | None
    replies: list[reply_.Encoded] = field(default_factory=list[reply_.Encoded])
    last_received_chunk: reply_.ChunkEncoded | None = None


class MemoryTransaction(Reference[bool], key="effect/cluster/MessageStorage/MemoryTransaction"):
    """Inside ``with_transaction`` of the memory driver."""

    @classmethod
    def default(cls) -> bool:
        return False


type _Address = AddressEncoded | EntityAddress


def _address_key(address: _Address) -> str:
    if isinstance(address, EntityAddress):
        shard_id = address.shard_id
        return f"{shard_id.group}/{shard_id.id}/{address.entity_type}/{address.entity_id}"
    shard = address["shardId"]
    return f"{shard['group']}/{shard['id']}/{address['entityType']}/{address['entityId']}"


def _same_entity(address: EntityAddress, encoded: AddressEncoded) -> bool:
    return address.entity_type == encoded["entityType"] and address.entity_id == encoded["entityId"]


def _shard_key(address: AddressEncoded) -> str:
    return f"{address['shardId']['group']}:{address['shardId']['id']}"


class MemoryEncoded:
    """The memory driver's ``EncodedStorage``. Envelopes are kept by
    identity: the journal, the unprocessed set and the claims hold the same
    dictionaries."""

    def __init__(self, clock: ClockService) -> None:
        self._clock = clock
        self.requests: dict[str, MemoryEntry] = {}
        self.requests_by_primary_key: dict[str, MemoryEntry] = {}
        self.unprocessed: dict[int, EnvelopeEncoded] = {}
        self.reply_ids: set[str] = set()
        self.last_read: dict[int, int] = {}
        self.journal: list[EnvelopeEncoded] = []

    def save_envelope(
        self, envelope: EnvelopeEncoded, primary_key: str | None, deliver_at: int | None, /
    ) -> Effect[SaveResultEncoded, PersistenceError]:
        def run() -> SaveResultEncoded:
            stored = json_copy(envelope)
            if primary_key:
                existing = self.requests_by_primary_key.get(primary_key)
            elif stored["_tag"] == "Request":
                existing = self.requests.get(stored["requestId"])
            else:
                existing = None
            if existing is not None:
                replies = existing.replies
                last = (
                    replies[0]
                    if len(replies) == 1 and replies[0]["_tag"] == "WithExit"
                    else existing.last_received_chunk
                )
                return DuplicateEncoded(
                    original_id=Snowflake(int(existing.envelope["requestId"])),
                    last_received_reply=last,
                )
            if stored["_tag"] == "Request":
                entry = MemoryEntry(stored, deliver_at)
                self.requests[stored["requestId"]] = entry
                if primary_key:
                    self.requests_by_primary_key[primary_key] = entry
            elif stored["_tag"] == "AckChunk":
                entry = self.requests.get(stored["requestId"])
                if entry is not None:
                    reply_id = stored["replyId"]
                    for r in entry.replies:
                        if r["_tag"] == "Chunk" and r["id"] == reply_id:
                            entry.last_received_chunk = r
                            break
            self.unprocessed[id(stored)] = stored
            self.journal.append(stored)
            return SAVE_SUCCESS

        return sync(run)

    def save_reply(self, reply: reply_.Encoded, /) -> Effect[None, PersistenceError]:
        def run() -> None:
            stored = json_copy(reply)
            entry = self.requests.get(stored["requestId"])
            if entry is None or stored["id"] in self.reply_ids:
                return
            if stored["_tag"] == "WithExit":
                self.unprocessed.pop(id(entry.envelope), None)
                self.last_read.pop(id(entry.envelope), None)
            entry.replies.append(stored)
            self.reply_ids.add(stored["id"])

        save = sync(run)

        # Memory has no transaction isolation: an exit is published at the
        # outer commit, before its queued handler notifications, so readers
        # cannot see a success that may still be rolled back.
        def deferred(notifications: Any) -> Effect[None]:
            if reply["_tag"] == "WithExit" and notifications is not None:
                pending: list[Any] = notifications
                return sync(lambda: pending.append(save))
            return save

        return TransactionNotifications().flat_map(deferred)

    def clear_replies(
        self, request_id: Snowflake, /, *, expected_reply_id: Snowflake | None = None
    ) -> Effect[None, PersistenceError]:
        def run() -> None:
            entry = self.requests.get(str(request_id))
            if entry is None:
                return
            if expected_reply_id is not None and (
                not entry.replies or entry.replies[-1]["id"] != str(expected_reply_id)
            ):
                return
            entry.replies = []
            entry.last_received_chunk = None
            self.unprocessed[id(entry.envelope)] = entry.envelope
            self.last_read.pop(id(entry.envelope), None)

        return sync(run)

    def request_id_for_primary_key(
        self, primary_key: str, /
    ) -> Effect[Snowflake | None, PersistenceError]:
        def run() -> Snowflake | None:
            entry = self.requests_by_primary_key.get(primary_key)
            return None if entry is None else Snowflake(int(entry.envelope["requestId"]))

        return sync(run)

    def replies_for(
        self, request_ids: Sequence[str], /
    ) -> Effect[list[reply_.Encoded], PersistenceError]:
        def run() -> list[reply_.Encoded]:
            replies: list[reply_.Encoded] = []
            for request_id in request_ids:
                entry = self.requests.get(request_id)
                if entry is None:
                    continue
                chunk = entry.last_received_chunk
                if chunk is None:
                    replies.extend(entry.replies)
                    continue
                for r in entry.replies:
                    if r["_tag"] == "Chunk" and r["sequence"] <= chunk["sequence"]:
                        continue
                    replies.append(r)
            return replies

        return sync(run)

    def replies_for_unfiltered(
        self, request_ids: Sequence[str], /
    ) -> Effect[list[reply_.Encoded], PersistenceError]:
        def run() -> list[reply_.Encoded]:
            replies: list[reply_.Encoded] = []
            for request_id in request_ids:
                entry = self.requests.get(request_id)
                if entry is not None:
                    replies.extend(entry.replies)
            return replies

        return sync(run)

    def unprocessed_messages(
        self,
        shard_ids: Sequence[str],
        now: int,
        /,
        *,
        limit: int | None = None,
        addresses: Sequence[EntityAddress] | None = None,
    ) -> Effect[list[EncodedMessage], PersistenceError]:
        if addresses is not None and len(addresses) == 0:
            return succeed([])

        def run() -> list[EncodedMessage]:
            if not self.unprocessed:
                return []
            address_filter = None if addresses is None else {_address_key(a) for a in addresses}
            shards = set(shard_ids)
            messages: list[EncodedMessage] = []
            for envelope in list(self.journal):
                if limit is not None and len(messages) >= limit:
                    break
                key = id(envelope)
                if key not in self.unprocessed or _shard_key(envelope["address"]) not in shards:
                    continue
                if (
                    address_filter is not None
                    and _address_key(envelope["address"]) not in address_filter
                ):
                    continue
                if envelope["_tag"] == "Request":
                    entry = self.requests[envelope["requestId"]]
                    if entry.deliver_at and entry.deliver_at > now:
                        continue
                    claimed_at = self.last_read.get(key)
                    if claimed_at is not None and claimed_at > now - CLAIM_EXPIRATION_MILLIS:
                        continue
                    last = entry.replies[-1] if entry.replies else None
                    messages.append(EncodedMessage(envelope, last))
                    self.last_read[key] = now
                else:
                    messages.append(EncodedMessage(envelope, None))
                    del self.unprocessed[key]
            return messages

        return sync(run)

    def _unprocessed_with(self, keep: Callable[[EnvelopeEncoded], bool]) -> list[EncodedMessage]:
        messages: list[EncodedMessage] = []
        now = now_millis_unsafe(self._clock)
        for envelope in self.unprocessed.values():
            if not keep(envelope):
                continue
            if envelope["_tag"] == "Request":
                entry = self.requests.get(envelope["requestId"])
                if entry is not None and entry.deliver_at and entry.deliver_at > now:
                    continue
                last = entry.replies[-1] if entry is not None and entry.replies else None
                messages.append(EncodedMessage(envelope, last))
            else:
                messages.append(EncodedMessage(envelope, None))
        return messages

    def unprocessed_messages_by_id(
        self, message_ids: Sequence[Snowflake], now: int, /
    ) -> Effect[list[EncodedMessage], PersistenceError]:
        ids = {str(i) for i in message_ids}
        return sync(lambda: self._unprocessed_with(lambda e: e["requestId"] in ids))

    def reset_requests(self, request_ids: Sequence[Snowflake], /) -> Effect[None, PersistenceError]:
        def run() -> None:
            for request_id in request_ids:
                entry = self.requests.get(str(request_id))
                if entry is not None:
                    self.last_read.pop(id(entry.envelope), None)

        return sync(run)

    def reset_addresses(
        self, addresses: Sequence[EntityAddress], /
    ) -> Effect[None, PersistenceError]:
        if not addresses:
            return succeed(None)

        def run() -> None:
            keys = {_address_key(a) for a in addresses}
            for envelope in self.journal:
                if _address_key(envelope["address"]) in keys:
                    self.last_read.pop(id(envelope), None)

        return sync(run)

    def clear_address(self, address: EntityAddress, /) -> Effect[None, PersistenceError]:
        def run() -> None:
            for primary_key, entry in list(self.requests_by_primary_key.items()):
                if _same_entity(address, entry.envelope["address"]):
                    del self.requests_by_primary_key[primary_key]
            kept: list[EnvelopeEncoded] = []
            for envelope in self.journal:
                if not _same_entity(address, envelope["address"]):
                    kept.append(envelope)
                    continue
                self.unprocessed.pop(id(envelope), None)
                self.last_read.pop(id(envelope), None)
                if envelope["_tag"] == "Request":
                    self.requests.pop(envelope["requestId"], None)
            self.journal[:] = kept

        return sync(run)

    def reset_shards(self, shard_ids: Sequence[str], /) -> Effect[None, PersistenceError]:
        def run() -> None:
            shards = set(shard_ids)
            for envelope in self.journal:
                if _shard_key(envelope["address"]) in shards:
                    self.last_read.pop(id(envelope), None)

        return sync(run)

    def with_transaction[A, E, R](self, effect: Effect[A, E, R], /) -> Effect[A, E, R]:
        require_effect(effect, "effect")
        return effect.pipe(provide_service(MemoryTransaction, True))


@dataclass(frozen=True, slots=True)
class MemoryDriverService:
    """The memory storage and its driver, for tests to look inside."""

    storage: MessageStorageService
    encoded: MemoryEncoded


def make_memory_driver() -> Effect[MemoryDriverService, Any, snowflake.Generator]:
    def body() -> Generator[Effect[Any, Any, Any], Any, MemoryDriverService]:
        clock = yield from Clock()
        encoded = MemoryEncoded(clock)
        storage = yield from make_encoded(encoded)
        return MemoryDriverService(storage, encoded)

    return gen(body)


class MemoryDriver(Tag[MemoryDriverService], key="effect/cluster/MessageStorage/MemoryDriver"):
    """The memory driver of ``layer_memory``."""


memory_driver_layer: layer_.Layer[MemoryDriver] = layer_.effect(
    MemoryDriver, make_memory_driver()
).pipe(layer_.provide(snowflake.layer_generator))
"""Effect's ``MemoryDriver.layer``."""

layer_memory: layer_.Layer[MessageStorage | MemoryDriver] = layer_.effect(
    MessageStorage, MemoryDriver().map(lambda driver: driver.storage)
).pipe(layer_.provide_merge(memory_driver_layer))
"""Message storage in memory, with its driver."""

__all__ = [
    "CLAIM_EXPIRATION_MILLIS",
    "MemoryDriver",
    "MemoryDriverService",
    "MemoryEncoded",
    "MemoryEntry",
    "MemoryTransaction",
    "layer_memory",
    "make_memory_driver",
    "memory_driver_layer",
]
