"""What is sent to an entity (Effect's ``Envelope``): a ``Request`` of one
of its RPCs, an ``AckChunk`` acknowledging a streamed reply, or an
``Interrupt`` cancelling a request.

A request whose payload is already encoded is a *partial* request; it
crosses runners and is written to message storage. ``PartialSchema``
reads and writes partial envelopes as Effect's JSON (camelCase keys,
snowflakes as decimal strings), the ``Encoded`` shapes below.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Literal, NotRequired, TypedDict, TypeIs, cast

from pyfect import primary_key as primary_key_
from pyfect import schema as S
from pyfect._wire_codec import Const, key, wire_codec
from pyfect.cluster.entity_address import EntityAddress
from pyfect.cluster.shard_id import ShardId
from pyfect.cluster.snowflake import Snowflake, SnowflakeFromBigInt
from pyfect.encoding.schema_binary._undefined import Undefined
from pyfect.http.headers import EMPTY, Headers
from pyfect.schema import ast
from pyfect.schema import transformation as T


@dataclass(frozen=True, slots=True, kw_only=True)
class Request[P]:
    """A call of the entity RPC ``tag`` with ``payload`` (decoded, or
    encoded for a partial request)."""

    request_id: Snowflake
    address: EntityAddress
    tag: str
    payload: P
    headers: Headers = field(default=EMPTY)
    trace_id: str | None = None
    span_id: str | None = None
    sampled: bool | None = None

    def with_request_id(self, request_id: Snowflake) -> Request[P]:
        return replace(self, request_id=request_id)


type PartialRequest = Request[object]
"""A request whose payload is encoded."""


@dataclass(frozen=True, slots=True, kw_only=True)
class AckChunk:
    """The sender took the streamed reply ``reply_id`` of ``request_id``."""

    id: Snowflake
    address: EntityAddress
    request_id: Snowflake
    reply_id: Snowflake

    def with_request_id(self, request_id: Snowflake) -> AckChunk:
        return replace(self, request_id=request_id)


@dataclass(frozen=True, slots=True, kw_only=True)
class Interrupt:
    """The sender cancelled ``request_id``."""

    id: Snowflake
    address: EntityAddress
    request_id: Snowflake

    def with_request_id(self, request_id: Snowflake) -> Interrupt:
        return replace(self, request_id=request_id)


type Envelope[P] = Request[P] | AckChunk | Interrupt
type Partial = PartialRequest | AckChunk | Interrupt


def is_envelope(u: object) -> TypeIs[Envelope[Any]]:
    return isinstance(u, Request | AckChunk | Interrupt)


def make_request[P](
    *,
    request_id: Snowflake,
    address: EntityAddress,
    tag: str,
    payload: P,
    headers: Headers = EMPTY,
    trace_id: str | None = None,
    span_id: str | None = None,
    sampled: bool | None = None,
) -> Request[P]:
    """A request; the span ids are kept only with a ``trace_id``."""
    if trace_id is None:
        return Request(
            request_id=request_id, address=address, tag=tag, payload=payload, headers=headers
        )
    return Request(
        request_id=request_id,
        address=address,
        tag=tag,
        payload=payload,
        headers=headers,
        trace_id=trace_id,
        span_id=span_id,
        sampled=sampled,
    )


def primary_key(envelope: Envelope[Any]) -> str | None:
    """The storage key of a request whose payload is a ``PrimaryKey``."""
    if not isinstance(envelope, Request) or not primary_key_.is_primary_key(envelope.payload):
        return None
    return primary_key_by_address(
        address=envelope.address, tag=envelope.tag, id=primary_key_.value(envelope.payload)
    )


def primary_key_by_address(*, address: EntityAddress, tag: str, id: str) -> str:
    """``<entity type>/<entity id>/<tag>/<id>``; storages with fixed-width
    key columns hash it at their own boundary."""
    return f"{address.entity_type}/{address.entity_id}/{tag}/{id}"


# --- Effect's JSON -------------------------------------------------------------------


class ShardIdEncoded(TypedDict):
    group: str
    id: int


class AddressEncoded(TypedDict):
    shardId: ShardIdEncoded
    entityType: str
    entityId: str


class PartialRequestEncoded(TypedDict):
    _tag: Literal["Request"]
    requestId: str
    address: AddressEncoded
    tag: str
    payload: object
    headers: Mapping[str, str]
    traceId: NotRequired[str]
    spanId: NotRequired[str]
    sampled: NotRequired[bool]


class AckChunkEncoded(TypedDict):
    _tag: Literal["AckChunk"]
    id: str
    address: AddressEncoded
    requestId: str
    replyId: str


class InterruptEncoded(TypedDict):
    _tag: Literal["Interrupt"]
    id: str
    address: AddressEncoded
    requestId: str


type Encoded = PartialRequestEncoded | AckChunkEncoded | InterruptEncoded


def _is_headers(u: object) -> TypeIs[Headers]:
    return isinstance(u, Headers)


HeadersSchema: S.Bottom[Headers, Mapping[str, str]] = S.Record(S.String, S.String).pipe(
    S.decode_to(
        S.declare(_is_headers, expected="Headers"),
        T.transform(decode=Headers, encode=dict),
    )
)
"""Headers as a record of strings."""

AddressSchema: S.Bottom[EntityAddress, Mapping[str, object]] = wire_codec(
    EntityAddress,
    [
        key("shardId", "shard_id", ShardId),
        key("entityType", "entity_type", S.String),
        key("entityId", "entity_id", S.String),
    ],
    identifier="EntityAddress",
)
"""An entity address with Effect's keys."""


def _accepts_anything(_: object) -> TypeIs[Any]:
    return True


def _no_json_codec(_: object) -> None:
    return None


def _bytes_codec(_: object) -> ast.Link:
    passthrough: T.Transformation[Any, Any] = T.passthrough()
    return ast.Link(S.Bytes.ast, passthrough)


OpaqueHole: S.Bottom[Any] = S.declare(
    _accepts_anything,
    expected="an already-encoded value",
    to_codec_json=_no_json_codec,
    to_codec=_bytes_codec,
)
"""A value the protocol's own codec already encoded: JSON under the text
serializations, bytes under ``SchemaBinary`` (Effect's ``OpaqueHole``)."""

PartialRequestSchema: S.Bottom[PartialRequest, Mapping[str, object]] = wire_codec(
    cast("type[PartialRequest]", Request),
    [
        Const("_tag", "Request"),
        key("requestId", "request_id", SnowflakeFromBigInt),
        key("address", "address", AddressSchema),
        key("tag", "tag", S.String),
        key("payload", "payload", OpaqueHole),
        key("headers", "headers", HeadersSchema),
        key("traceId", "trace_id", S.Union(S.String, Undefined), optional=True),
        key("spanId", "span_id", S.Union(S.String, Undefined), optional=True),
        key("sampled", "sampled", S.Union(S.Boolean, Undefined), optional=True),
    ],
    identifier="PartialRequest",
)

AckChunkSchema: S.Bottom[AckChunk, Mapping[str, object]] = wire_codec(
    AckChunk,
    [
        Const("_tag", "AckChunk"),
        key("id", "id", SnowflakeFromBigInt),
        key("address", "address", AddressSchema),
        key("requestId", "request_id", SnowflakeFromBigInt),
        key("replyId", "reply_id", SnowflakeFromBigInt),
    ],
    identifier="AckChunk",
)

InterruptSchema: S.Bottom[Interrupt, Mapping[str, object]] = wire_codec(
    Interrupt,
    [
        Const("_tag", "Interrupt"),
        key("id", "id", SnowflakeFromBigInt),
        key("address", "address", AddressSchema),
        key("requestId", "request_id", SnowflakeFromBigInt),
    ],
    identifier="Interrupt",
)

PartialSchema: S.Bottom[Partial, Mapping[str, object]] = S.Union(
    PartialRequestSchema, AckChunkSchema, InterruptSchema
)
"""A partial envelope (Effect's ``Envelope.Partial``): ids are bigints on its
encoded side, so ``SchemaBinary`` writes them as Effect does."""

PartialJson: S.Codec[Partial, object] = S.to_codec_json(PartialSchema)
"""A partial envelope as Effect's JSON: ids as strings."""

_encode_partial = S.encode_sync(PartialJson)
_decode_partial = S.decode_unknown_sync(PartialJson)


def encode(envelope: Partial) -> Encoded:
    """``envelope`` as Effect's JSON; raises ``SchemaError`` for a payload
    that is not."""
    return _encode_partial(envelope)  # pyright: ignore[reportReturnType]


def decode(encoded: object) -> Partial:
    """A partial envelope from Effect's JSON; raises ``SchemaError``."""
    return _decode_partial(encoded)


def encode_address(address: EntityAddress) -> AddressEncoded:
    return {
        "shardId": {"group": address.shard_id.group, "id": address.shard_id.id},
        "entityType": address.entity_type,
        "entityId": address.entity_id,
    }


__all__ = [
    "AckChunk",
    "AckChunkEncoded",
    "AckChunkSchema",
    "AddressEncoded",
    "AddressSchema",
    "Encoded",
    "Envelope",
    "HeadersSchema",
    "Interrupt",
    "InterruptEncoded",
    "InterruptSchema",
    "OpaqueHole",
    "Partial",
    "PartialJson",
    "PartialRequest",
    "PartialRequestEncoded",
    "PartialRequestSchema",
    "PartialSchema",
    "Request",
    "ShardIdEncoded",
    "decode",
    "encode",
    "encode_address",
    "is_envelope",
    "make_request",
    "primary_key",
    "primary_key_by_address",
]
