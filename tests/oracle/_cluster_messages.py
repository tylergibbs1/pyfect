"""Requests and replies for the message storage ports, after the helpers
of Effect's ``test/cluster/MessageStorage.test.ts`` (``makeRequest``,
``makeReply``, ``makeChunkReply``, ``makeAckChunk``)."""

from __future__ import annotations

from typing import Any, Never, TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect.cluster import entity_address, envelope, shard_id
from pyfect.cluster.entity_id import EntityId
from pyfect.cluster.entity_type import EntityType
from pyfect.cluster.envelope import AckChunk
from pyfect.cluster.message import OutgoingEnvelope, OutgoingRequest
from pyfect.cluster.reply import Chunk, ReplyWithContext, WithExit
from pyfect.cluster.snowflake import Generator
from pyfect.context import Context
from pyfect.http.headers import EMPTY
from pyfect.rpc import AnyRpc
from pyfect.rpc import make as make_rpc


class IdPayload(TypedDict):
    id: int


GetUserRpc = make_rpc("GetUser", payload=S.Struct(IdPayload))

UnknownSuccessRpc = make_rpc("UnknownSuccess", payload=S.Struct(IdPayload), success=S.Unknown)


class PrimaryKeyPayload(S.Class):
    id: int

    def primary_key(self) -> str:
        return str(self.id)


PrimaryKeyTest = make_rpc("PrimaryKeyTest", payload=PrimaryKeyPayload)


class LongKeyPayload(S.Class):
    id: str

    def primary_key(self) -> str:
        return self.id


LongKeyRpc = make_rpc("LongKeyRpc", payload=LongKeyPayload)

StreamRpc = make_rpc("StreamTest", payload=PrimaryKeyPayload, success=S.Null, stream=True)


def make_request(
    *,
    rpc: AnyRpc = GetUserRpc,
    payload: Any = None,
    entity_id: str = "1",
    shard: shard_id.ShardId | None = None,
) -> fx.Effect[OutgoingRequest, Never, Generator]:
    def build(snowflakes: Any) -> OutgoingRequest:
        return OutgoingRequest(
            envelope=envelope.make_request(
                request_id=snowflakes.unsafe_next(),
                address=entity_address.make(
                    shard_id=shard_id.make("default", 1) if shard is None else shard,
                    entity_type=EntityType("test"),
                    entity_id=EntityId(entity_id),
                ),
                tag=rpc.tag,
                payload={"id": 123} if payload is None else payload,
                trace_id="noop",
                span_id="noop",
                sampled=False,
                headers=EMPTY,
            ),
            annotations=rpc.annotations,
            context=Context.empty(),
            rpc=rpc,
            last_received_reply=None,
            respond=lambda _reply: fx.void,
        )

    return Generator().map(build)


def make_reply(request: OutgoingRequest) -> fx.Effect[ReplyWithContext, Never, Generator]:
    return Generator().map(
        lambda snowflakes: ReplyWithContext(
            WithExit(
                id=snowflakes.unsafe_next(),
                request_id=request.envelope.request_id,
                exit=fx.exit.succeed(None),
            ),
            request.context,
            request.rpc,
        )
    )


def make_chunk_reply(
    request: OutgoingRequest, sequence: int = 0
) -> fx.Effect[ReplyWithContext, Never, Generator]:
    return Generator().map(
        lambda snowflakes: ReplyWithContext(
            Chunk(
                id=snowflakes.unsafe_next(),
                request_id=request.envelope.request_id,
                sequence=sequence,
                values=(None,),
            ),
            request.context,
            request.rpc,
        )
    )


def make_ack_chunk(
    request: OutgoingRequest, chunk: ReplyWithContext
) -> fx.Effect[OutgoingEnvelope, Never, Generator]:
    return Generator().map(
        lambda snowflakes: OutgoingEnvelope(
            envelope=AckChunk(
                id=snowflakes.unsafe_next(),
                address=request.envelope.address,
                request_id=chunk.reply.request_id,
                reply_id=chunk.reply.id,
            ),
            rpc=request.rpc,
        )
    )


def make_empty_reply(request: OutgoingRequest) -> ReplyWithContext:
    return ReplyWithContext(
        Chunk.empty_from(request.envelope.request_id), request.context, request.rpc
    )
