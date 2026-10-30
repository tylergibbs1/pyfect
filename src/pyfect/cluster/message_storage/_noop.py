"""A message storage that keeps nothing (Effect's ``MessageStorage.noop``):
every request is new and no message is ever unprocessed."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from typing import Any

from pyfect import layer as layer_
from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect.cluster.cluster_error import MalformedMessage, PersistenceError
from pyfect.cluster.entity_address import EntityAddress
from pyfect.cluster.message import Incoming, OutgoingEnvelope, OutgoingRequest
from pyfect.cluster.message_storage._service import (
    SAVE_SUCCESS,
    MessageStorage,
    MessageStorageService,
    SaveResult,
)
from pyfect.cluster.reply import Reply, ReplyWithContext
from pyfect.cluster.shard_id import ShardId
from pyfect.cluster.snowflake import Snowflake
from pyfect.effect import succeed, void


class _NoopBase:
    __slots__ = ()

    def save_request(
        self, message: OutgoingRequest, /
    ) -> Effect[SaveResult, PersistenceError | MalformedMessage]:
        return succeed(SAVE_SUCCESS)

    def save_envelope(
        self, message: OutgoingEnvelope, /
    ) -> Effect[None, PersistenceError | MalformedMessage]:
        return void

    def save_reply(
        self, reply: ReplyWithContext, /
    ) -> Effect[ReplyWithContext, PersistenceError | MalformedMessage]:
        return succeed(reply)

    def clear_replies(
        self, request_id: Snowflake, /, *, expected_reply_id: Snowflake | None = None
    ) -> Effect[None, PersistenceError]:
        return void

    def replies_for(
        self, requests: Iterable[OutgoingRequest], /
    ) -> Effect[list[Reply], PersistenceError | MalformedMessage]:
        return succeed([])

    def replies_for_unfiltered(
        self, request_ids: Iterable[Snowflake], /
    ) -> Effect[list[Any], PersistenceError | MalformedMessage]:
        return succeed([])

    def request_id_for_primary_key(
        self, *, address: EntityAddress, tag: str, id: str
    ) -> Effect[Snowflake | None, PersistenceError]:
        return succeed(None)

    def unprocessed_messages(
        self,
        shard_ids: Iterable[ShardId],
        /,
        *,
        limit: int | None = None,
        addresses: Sequence[EntityAddress] | None = None,
    ) -> Effect[list[Incoming], PersistenceError]:
        return succeed([])

    def unprocessed_messages_by_id(
        self, message_ids: Iterable[Snowflake], /
    ) -> Effect[list[Incoming], PersistenceError]:
        return succeed([])

    def reset_shards(self, shard_ids: Iterable[ShardId], /) -> Effect[None, PersistenceError]:
        return void

    def reset_address(self, address: EntityAddress, /) -> Effect[None, PersistenceError]:
        return void

    def reset_requests(self, request_ids: Sequence[Snowflake], /) -> Effect[None, PersistenceError]:
        return void

    def reset_addresses(
        self, addresses: Sequence[EntityAddress], /
    ) -> Effect[None, PersistenceError]:
        return void

    def clear_address(self, address: EntityAddress, /) -> Effect[None, PersistenceError]:
        return void

    def with_transaction[A, E, R](self, effect: Effect[A, E, R], /) -> Effect[A, E, R]:
        require_effect(effect, "effect")
        return effect


NOOP: MessageStorageService = MessageStorageService(_NoopBase())
"""The storage that keeps nothing; runners compare against it to skip
reading replies back."""

layer_noop: layer_.Layer[MessageStorage] = layer_.succeed(MessageStorage, NOOP)

__all__ = ["NOOP", "layer_noop"]
