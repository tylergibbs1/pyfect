"""``RpcMessage.EncodedSchema``: the schema of every transport-encoded message,
for binary serializations, once each value hole is bytes. Its layout is Effect's,
so a fingerprint-mode frame reads across the two."""

from __future__ import annotations

from typing import Any, Literal, NotRequired, TypedDict

from pyfect import schema as S
from pyfect.schema._undefined import Undefined

type _RequestId = str | float


class _Request(TypedDict):
    _tag: Literal["Request"]
    id: _RequestId
    tag: str
    payload: bytes
    headers: tuple[tuple[str, str], ...]
    isNotification: NotRequired[Literal[True] | None]
    traceId: NotRequired[str | None]
    spanId: NotRequired[str | None]
    sampled: NotRequired[bool | None]


class _RequestIdMessage(TypedDict):
    _tag: str
    requestId: _RequestId


class _Tagged(TypedDict):
    _tag: str


class _Values(TypedDict):
    _tag: str
    requestId: _RequestId
    values: bytes


class _ExitMessage(TypedDict):
    _tag: str
    requestId: _RequestId
    exit: bytes


class _Defect(TypedDict):
    _tag: str
    defect: bytes


_RequestIdSchema = S.Union(S.String, S.Number)


def _optional(schema: Any) -> Any:
    """Effect's ``Schema.optional``: the key may be absent or undefined."""
    return S.Union(schema, Undefined)


def _tag(tag: Any) -> Any:
    return S.Literal(tag)


EncodedSchema: S.Codec[Any, Any] = S.Union(
    S.Struct(
        _Request,
        _tag=_tag("Request"),
        id=_RequestIdSchema,
        tag=S.String,
        payload=S.Bytes,
        headers=S.Array(S.Tuple(S.String, S.String)),
        isNotification=_optional(S.Literal(True)),
        traceId=_optional(S.String),
        spanId=_optional(S.String),
        sampled=_optional(S.Boolean),
    ),
    S.Struct(_RequestIdMessage, _tag=_tag("Ack"), requestId=_RequestIdSchema),
    S.Struct(_RequestIdMessage, _tag=_tag("Interrupt"), requestId=_RequestIdSchema),
    S.Struct(_Tagged, _tag=_tag("Ping")),
    S.Struct(_Tagged, _tag=_tag("Eof")),
    S.Struct(_Values, _tag=_tag("Chunk"), requestId=_RequestIdSchema, values=S.Bytes),
    S.Struct(_ExitMessage, _tag=_tag("Exit"), requestId=_RequestIdSchema, exit=S.Bytes),
    S.Struct(_Defect, _tag=_tag("Defect"), defect=S.Bytes),
    S.Struct(_Tagged, _tag=_tag("Pong")),
)
