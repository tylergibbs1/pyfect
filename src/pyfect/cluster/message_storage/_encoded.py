"""``make_encoded``: a message storage on a driver that keeps Effect's
JSON (Effect's ``MessageStorage.makeEncoded``). The driver sees encoded
envelopes and replies only; this module encodes and decodes them."""

from __future__ import annotations

import json
from collections.abc import Generator, Iterable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

from pyfect import exit as exit_
from pyfect import schema as S
from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect.clock import Clock, ClockService
from pyfect.cluster import deliver_at, envelope
from pyfect.cluster import reply as reply_
from pyfect.cluster.cluster_error import MalformedMessage, PersistenceError
from pyfect.cluster.entity_address import EntityAddress
from pyfect.cluster.envelope import Encoded as EnvelopeEncoded
from pyfect.cluster.envelope import Request
from pyfect.cluster.message import (
    Incoming,
    IncomingEnvelope,
    IncomingRequest,
    OutgoingEnvelope,
    OutgoingRequest,
    codec_for_json,
    serialize_envelope,
)
from pyfect.cluster.message_storage._service import (
    MessageStorageService,
    SaveDuplicate,
    SaveResult,
    SaveSuccess,
    make,
)
from pyfect.cluster.reply import Reply, ReplyWithContext, WithExit
from pyfect.cluster.shard_id import ShardId
from pyfect.cluster.snowflake import Generator as SnowflakeGenerator
from pyfect.cluster.snowflake import Snowflake
from pyfect.cluster.snowflake import SnowflakeGenerator as Snowflakes
from pyfect.effect import gen, succeed, suspend, try_, void
from pyfect.result import Ok


@dataclass(frozen=True, slots=True, kw_only=True)
class DuplicateEncoded:
    original_id: Snowflake
    last_received_reply: reply_.Encoded | None


type SaveResultEncoded = SaveSuccess | DuplicateEncoded


@dataclass(frozen=True, slots=True)
class EncodedMessage:
    """An unprocessed envelope and the last reply sent for it."""

    envelope: EnvelopeEncoded
    last_sent_reply: reply_.Encoded | None


class EncodedStorage(Protocol):
    """What a message storage driver implements (Effect's
    ``MessageStorage.Encoded``). Lists it is given are never empty."""

    def save_envelope(
        self, envelope: EnvelopeEncoded, primary_key: str | None, deliver_at: int | None, /
    ) -> Effect[SaveResultEncoded, PersistenceError]: ...

    def save_reply(self, reply: reply_.Encoded, /) -> Effect[None, PersistenceError]: ...

    def clear_replies(
        self, request_id: Snowflake, /, *, expected_reply_id: Snowflake | None = None
    ) -> Effect[None, PersistenceError]: ...

    def request_id_for_primary_key(
        self, primary_key: str, /
    ) -> Effect[Snowflake | None, PersistenceError]: ...

    def replies_for(
        self, request_ids: Sequence[str], /
    ) -> Effect[list[reply_.Encoded], PersistenceError]: ...

    def replies_for_unfiltered(
        self, request_ids: Sequence[str], /
    ) -> Effect[list[reply_.Encoded], PersistenceError]: ...

    def unprocessed_messages(
        self,
        shard_ids: Sequence[str],
        now: int,
        /,
        *,
        limit: int | None = None,
        addresses: Sequence[EntityAddress] | None = None,
    ) -> Effect[list[EncodedMessage], PersistenceError]: ...

    def unprocessed_messages_by_id(
        self, message_ids: Sequence[Snowflake], now: int, /
    ) -> Effect[list[EncodedMessage], PersistenceError]: ...

    def reset_requests(
        self, request_ids: Sequence[Snowflake], /
    ) -> Effect[None, PersistenceError]: ...

    def reset_addresses(
        self, addresses: Sequence[EntityAddress], /
    ) -> Effect[None, PersistenceError]: ...

    def clear_address(self, address: EntityAddress, /) -> Effect[None, PersistenceError]: ...

    def reset_shards(self, shard_ids: Sequence[str], /) -> Effect[None, PersistenceError]: ...

    def with_transaction[A, E, R](self, effect: Effect[A, E, R], /) -> Effect[A, E, R]: ...


def now_millis(clock: ClockService) -> int:
    return clock.now_nanos_unsafe() // 1_000_000


def json_copy[T](value: T) -> T:
    """``value`` after a trip through JSON text, as stored."""
    return json.loads(json.dumps(value))


class _EncodedBase:
    """The ``StorageBase`` of an encoded driver."""

    __slots__ = ("_clock", "_encoded", "_snowflakes", "storage")

    storage: MessageStorageService
    """The storage on this base, which answers decoded requests."""

    def __init__(
        self, encoded: EncodedStorage, snowflakes: Snowflakes, clock: ClockService
    ) -> None:
        self._encoded = encoded
        self._snowflakes = snowflakes
        self._clock = clock

    def save_request(
        self, message: OutgoingRequest, /
    ) -> Effect[SaveResult, PersistenceError | MalformedMessage]:
        def saved(result: SaveResultEncoded) -> Effect[SaveResult, MalformedMessage]:
            if isinstance(result, SaveSuccess):
                return succeed(result)
            original = result.original_id
            if result.last_received_reply is None:
                return succeed(SaveDuplicate(original_id=original, last_received_reply=None))
            decoded = reply_.decode(
                message.rpc, codec_for_json, result.last_received_reply, message.context
            )
            return MalformedMessage.refail(decoded).map(
                lambda r: SaveDuplicate(original_id=original, last_received_reply=r)
            )

        return (
            serialize_envelope(message)
            .flat_map(
                lambda encoded: self._encoded.save_envelope(
                    encoded,
                    envelope.primary_key(message.envelope),
                    deliver_at.to_millis(message.envelope.payload),
                )
            )
            .flat_map(saved)
        )

    def save_envelope(
        self, message: OutgoingEnvelope, /
    ) -> Effect[None, PersistenceError | MalformedMessage]:
        return (
            serialize_envelope(message)
            .flat_map(lambda encoded: self._encoded.save_envelope(encoded, None, None))
            .as_void()
        )

    def save_reply(
        self, reply: ReplyWithContext, /
    ) -> Effect[ReplyWithContext, PersistenceError | MalformedMessage]:
        def fallback(error: MalformedMessage) -> Effect[tuple[reply_.Encoded, ReplyWithContext]]:
            persisted = ReplyWithContext.from_defect(
                id=reply.reply.id, request_id=reply.reply.request_id, defect=error
            )
            return (
                reply_.serialize(persisted, codec_for_json).or_die().map(lambda e: (e, persisted))
            )

        encoded: Effect[tuple[reply_.Encoded, ReplyWithContext]] = (
            reply_.serialize(reply, codec_for_json)
            .flat_map(_json_checked)
            .map(lambda e: (e, reply))
            .catch_all(fallback)
        )
        return encoded.flat_map(lambda pair: self._encoded.save_reply(pair[0]).as_(pair[1]))

    def clear_replies(
        self, request_id: Snowflake, /, *, expected_reply_id: Snowflake | None = None
    ) -> Effect[None, PersistenceError]:
        return self._encoded.clear_replies(request_id, expected_reply_id=expected_reply_id)

    def replies_for(
        self, requests: Iterable[OutgoingRequest], /
    ) -> Effect[list[Reply], PersistenceError | MalformedMessage]:
        def run() -> Effect[list[Reply], PersistenceError]:
            by_id: dict[str, OutgoingRequest] = {}
            for message in requests:
                by_id[str(message.envelope.request_id)] = message
            if not by_id:
                return succeed([])
            return self._encoded.replies_for(list(by_id)).flat_map(
                lambda encoded: self._decode_replies(by_id, encoded)
            )

        return suspend(run)

    def replies_for_unfiltered(
        self, request_ids: Iterable[Snowflake], /
    ) -> Effect[list[Any], PersistenceError | MalformedMessage]:
        def run() -> Effect[list[Any], PersistenceError]:
            ids = [str(i) for i in request_ids]
            if not ids:
                return succeed([])
            return self._encoded.replies_for_unfiltered(ids).map(list[Any])

        return suspend(run)

    def request_id_for_primary_key(
        self, *, address: EntityAddress, tag: str, id: str
    ) -> Effect[Snowflake | None, PersistenceError]:
        key = envelope.primary_key_by_address(address=address, tag=tag, id=id)
        return self._encoded.request_id_for_primary_key(key)

    def unprocessed_messages(
        self,
        shard_ids: Iterable[ShardId],
        /,
        *,
        limit: int | None = None,
        addresses: Sequence[EntityAddress] | None = None,
    ) -> Effect[list[Incoming], PersistenceError]:
        shards = [str(s) for s in shard_ids]
        if not shards or (addresses is not None and len(addresses) == 0):
            return succeed([])
        return suspend(
            lambda: self._encoded.unprocessed_messages(
                shards, now_millis(self._clock), limit=limit, addresses=addresses
            )
        ).flat_map(self._decode_messages)

    def unprocessed_messages_by_id(
        self, message_ids: Iterable[Snowflake], /
    ) -> Effect[list[Incoming], PersistenceError]:
        ids = list(message_ids)
        if not ids:
            return succeed([])
        return suspend(
            lambda: self._encoded.unprocessed_messages_by_id(ids, now_millis(self._clock))
        ).flat_map(self._decode_messages)

    def reset_shards(self, shard_ids: Iterable[ShardId], /) -> Effect[None, PersistenceError]:
        shards = [str(s) for s in shard_ids]
        return void if not shards else self._encoded.reset_shards(shards)

    def reset_address(self, address: EntityAddress, /) -> Effect[None, PersistenceError]:
        return self._encoded.reset_addresses([address])

    def reset_requests(self, request_ids: Sequence[Snowflake], /) -> Effect[None, PersistenceError]:
        return void if not request_ids else self._encoded.reset_requests(request_ids)

    def reset_addresses(
        self, addresses: Sequence[EntityAddress], /
    ) -> Effect[None, PersistenceError]:
        return void if not addresses else self._encoded.reset_addresses(addresses)

    def clear_address(self, address: EntityAddress, /) -> Effect[None, PersistenceError]:
        return self._encoded.clear_address(address)

    def with_transaction[A, E, R](self, effect: Effect[A, E, R], /) -> Effect[A, E, R]:
        require_effect(effect, "effect")
        return self._encoded.with_transaction(effect)

    # --- decoding ---------------------------------------------------------------------

    def _decode_messages(self, encoded: list[EncodedMessage]) -> Effect[list[Incoming]]:
        """The messages that decode; a malformed request is answered with a
        defect (in the background) and left out."""
        storage = self.storage

        def body() -> Generator[Effect[Any, Any, Any], Any, list[Incoming]]:
            messages: list[Incoming] = []
            for item in encoded:
                try:
                    partial = envelope.decode(item.envelope)
                except S.SchemaError as error:
                    request_id = Snowflake(int(item.envelope["requestId"]))
                    defect = ReplyWithContext.from_defect(
                        id=self._snowflakes.next_unsafe(),
                        request_id=request_id,
                        defect=_envelope_defect(error),
                    )
                    yield from storage.save_reply(defect).ignore_cause().fork_daemon()
                    continue
                if isinstance(partial, Request):
                    messages.append(
                        IncomingRequest(
                            envelope=partial,
                            last_sent_reply=item.last_sent_reply,
                            respond=storage.save_reply,
                            codec_for=codec_for_json,
                        )
                    )
                else:
                    messages.append(IncomingEnvelope(envelope=partial))
            return messages

        return gen(body)

    def _decode_replies(
        self, by_id: dict[str, OutgoingRequest], encoded: list[reply_.Encoded]
    ) -> Effect[list[Reply]]:
        """The replies decoded by their requests' schemas; the first reply
        of a request that does not decode becomes a defect ending it, and
        its later replies are left out."""

        def body() -> Generator[Effect[Any, Any, Any], Any, list[Reply]]:
            replies: list[Reply] = []
            ignored: set[str] = set()
            for item in encoded:
                request_id = item["requestId"]
                message = by_id.get(request_id)
                if request_id in ignored or message is None:
                    continue
                # a defect while decoding stays one; only the failure ends the request
                decoded = yield from reply_.decode(
                    message.rpc, codec_for_json, item, message.context
                ).result()
                if isinstance(decoded, Ok):
                    replies.append(decoded.value)
                    continue
                ignored.add(request_id)
                replies.append(
                    WithExit(
                        id=self._snowflakes.next_unsafe(),
                        request_id=Snowflake(int(request_id)),
                        exit=exit_.die(decoded.error),
                    )
                )
            return replies

        return gen(body)


def _envelope_defect(error: S.SchemaError) -> str:
    """Effect's stored defect for an envelope that does not decode: the
    ``String`` of its ``SchemaError``, the path under the ``envelope`` key
    of the row it decodes."""
    issue = S.issue.format_issue(S.issue.Pointer(("envelope",), error.issue))
    return f"SchemaError({issue})"


def _json_checked(encoded: reply_.Encoded) -> Effect[reply_.Encoded, MalformedMessage]:
    """``encoded`` if it is JSON (a reply a driver can store)."""

    def check() -> reply_.Encoded:
        json.dumps(encoded)
        return encoded

    return MalformedMessage.refail(try_(check))


def make_encoded(encoded: EncodedStorage) -> Effect[MessageStorageService, Any, SnowflakeGenerator]:
    """A message storage on the driver ``encoded``."""

    def body() -> Generator[Effect[Any, Any, Any], Any, MessageStorageService]:
        snowflakes = yield from SnowflakeGenerator()
        clock = yield from Clock()
        base = _EncodedBase(encoded, snowflakes, clock)
        storage = yield from make(base)
        base.storage = storage
        return storage

    return gen(body)


__all__ = [
    "DuplicateEncoded",
    "EncodedMessage",
    "EncodedStorage",
    "SaveResultEncoded",
    "json_copy",
    "make_encoded",
    "now_millis",
]
