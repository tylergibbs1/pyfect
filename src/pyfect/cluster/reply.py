"""What an entity answers (Effect's ``Reply``): ``WithExit``, the end of a
request with its exit, or ``Chunk``, a part of a streamed reply.

``reply_schema(rpc, codec_for)`` reads and writes the replies of ``rpc``
(Effect's ``Reply.Reply``); encoded, they are Effect's JSON shapes
``WithExitEncoded`` and ``ChunkEncoded``.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from typing import Any, Literal, TypedDict, TypeIs

from pyfect import exit as exit_
from pyfect import schema as S
from pyfect._core import Effect
from pyfect._wire_codec import Const, key, wire_codec
from pyfect.cluster.cluster_error import MalformedMessage
from pyfect.cluster.snowflake import Snowflake, SnowflakeFromBigInt
from pyfect.context import Context
from pyfect.effect import provide_context, succeed
from pyfect.exit import Exit
from pyfect.rpc import AnyRpc
from pyfect.rpc import make as make_rpc
from pyfect.rpc._rpc import exit_schema
from pyfect.rpc.schema import get_stream_schemas
from pyfect.rpc.serialization import CodecFor


@dataclass(frozen=True, slots=True, kw_only=True)
class WithExit[A = Any, E = Any]:
    """The last reply of ``request_id``."""

    request_id: Snowflake
    id: Snowflake
    exit: Exit[A, E]

    def with_request_id(self, request_id: Snowflake) -> WithExit[A, E]:
        return replace(self, request_id=request_id)


@dataclass(frozen=True, slots=True, kw_only=True)
class Chunk[A = Any]:
    """Items ``values`` of the streamed reply to ``request_id``, the
    ``sequence``-th chunk."""

    request_id: Snowflake
    id: Snowflake
    sequence: int
    values: tuple[A, ...]

    @staticmethod
    def empty_from(request_id: Snowflake) -> Chunk[None]:
        return Chunk(request_id=request_id, id=Snowflake(0), sequence=0, values=(None,))

    def with_request_id(self, request_id: Snowflake) -> Chunk[A]:
        return replace(self, request_id=request_id)


type Reply[A = Any, E = Any] = WithExit[A, E] | Chunk[A]


def is_reply(u: object) -> TypeIs[Reply]:
    return isinstance(u, WithExit | Chunk)


class WithExitEncoded(TypedDict):
    _tag: Literal["WithExit"]
    requestId: str
    id: str
    exit: object


class ChunkEncoded(TypedDict):
    _tag: Literal["Chunk"]
    requestId: str
    id: str
    sequence: int
    values: Sequence[object]


type Encoded = WithExitEncoded | ChunkEncoded

type OnWire = Encoded | bytes
"""A reply as a serialization's ``codec_for`` writes it: a frame under
``SchemaBinary``, so only JSON storage may read its fields."""

_never_rpc = make_rpc("Never", success=S.Never)


@dataclass(frozen=True, slots=True)
class ReplyWithContext[A = Any, E = Any]:
    """A reply with the services its schemas need and its RPC."""

    reply: Reply[A, E]
    context: Context[Any] = field(default_factory=Context.empty)
    rpc: AnyRpc = _never_rpc

    @staticmethod
    def from_defect(
        *, id: Snowflake, request_id: Snowflake, defect: BaseException | str
    ) -> ReplyWithContext:
        """A reply ending ``request_id`` with ``defect``, kept as what a
        defect schema reads back, so it always encodes. A ``str`` is stored
        as a JSON string, as Effect stores a string defect."""
        return ReplyWithContext(
            WithExit(request_id=request_id, id=id, exit=exit_.die(_portable_defect(defect))),
        )

    @staticmethod
    def interrupt(*, id: Snowflake, request_id: Snowflake) -> ReplyWithContext:
        return ReplyWithContext(
            WithExit(request_id=request_id, id=id, exit=exit_.interrupt(None)),
        )


_defect = S.Defect()
_encode_defect = S.encode_unknown_sync(_defect)
_decode_defect = S.decode_unknown_sync(_defect)


def _portable_defect(defect: object) -> object:
    return _decode_defect(_encode_defect(defect))


def with_exit_schema(exit: S.Top) -> S.Bottom[WithExit, Mapping[str, object]]:
    return wire_codec(
        WithExit,
        [
            Const("_tag", "WithExit"),
            key("requestId", "request_id", SnowflakeFromBigInt),
            key("id", "id", SnowflakeFromBigInt),
            key("exit", "exit", exit),
        ],
        identifier="Reply.WithExit",
    )


def chunk_schema(success: S.Top) -> S.Bottom[Chunk, Mapping[str, object]]:
    return wire_codec(
        Chunk,
        [
            Const("_tag", "Chunk"),
            key("requestId", "request_id", SnowflakeFromBigInt),
            key("id", "id", SnowflakeFromBigInt),
            key("sequence", "sequence", S.Int),
            key("values", "values", S.NonEmptyArray(success)),
        ],
        identifier="Reply.Chunk",
    )


_schemas: dict[tuple[int, int], tuple[CodecFor, AnyRpc, S.Codec[Any, Any, Any, Any]]] = {}


def reply_schema(rpc: AnyRpc, codec_for: CodecFor) -> S.Codec[Reply, Any, Any, Any]:
    """The replies of ``rpc``: ``WithExit`` with its exit, and ``Chunk`` of
    its stream items when it streams (Effect's ``Reply.Reply``)."""
    cached = _schemas.get((id(codec_for), id(rpc)))
    if cached is not None and cached[0] is codec_for and cached[1] is rpc:
        return cached[2]
    streams = get_stream_schemas(rpc.success_schema)
    members: list[S.Top] = [with_exit_schema(exit_schema(rpc))]
    if streams is not None:
        members.append(chunk_schema(streams.success))
    schema = codec_for(S.Union(*members))
    _schemas[(id(codec_for), id(rpc))] = (codec_for, rpc, schema)
    return schema


def _encode(
    schema: S.Codec[Reply, Any, Any, Any], reply: Reply, context: Context[Any]
) -> Effect[Encoded, MalformedMessage]:
    return MalformedMessage.refail(S.encode_effect(schema)(reply).pipe(provide_context(context)))


def serialize(self: ReplyWithContext, codec_for: CodecFor) -> Effect[OnWire, MalformedMessage]:
    """The reply encoded by its RPC's schema."""
    return _encode(reply_schema(self.rpc, codec_for), self.reply, self.context)


def serialize_or_defect(self: ReplyWithContext, codec_for: CodecFor) -> Effect[OnWire]:
    """The reply encoded, or a defect ending its request when it cannot be."""

    def defect(error: MalformedMessage) -> Effect[OnWire]:
        fallback = ReplyWithContext.from_defect(
            id=self.reply.id, request_id=self.reply.request_id, defect=error
        )
        return serialize(fallback, codec_for).or_die()

    return serialize(self, codec_for).catch_all(defect)


def decode(
    rpc: AnyRpc, codec_for: CodecFor, encoded: object, context: Context[Any]
) -> Effect[Reply, S.SchemaError]:
    """A reply of ``rpc`` from its encoded form."""
    return S.decode_unknown_effect(reply_schema(rpc, codec_for))(encoded).pipe(
        provide_context(context)
    )


def serialize_last_received(
    rpc: AnyRpc, last_received: Reply | None, context: Context[Any], codec_for: CodecFor
) -> Effect[Encoded | None, MalformedMessage]:
    """The last reply a sender got, encoded."""
    if last_received is None:
        return succeed(None)
    return _encode(reply_schema(rpc, codec_for), last_received, context)


def encoded_request_id(encoded: Encoded) -> str:
    return encoded["requestId"]


__all__ = [
    "Chunk",
    "ChunkEncoded",
    "Encoded",
    "MalformedMessage",
    "OnWire",
    "Reply",
    "ReplyWithContext",
    "WithExit",
    "WithExitEncoded",
    "chunk_schema",
    "decode",
    "encoded_request_id",
    "is_reply",
    "reply_schema",
    "serialize",
    "serialize_last_received",
    "serialize_or_defect",
    "with_exit_schema",
]
