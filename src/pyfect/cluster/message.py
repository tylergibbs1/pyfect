"""Envelopes on their way (Effect's ``Message``).

An ``Outgoing`` message is what a sender holds: an ``OutgoingRequest``
(its decoded envelope, the services its schemas need, and how to answer
the caller) or an ``OutgoingEnvelope``. An ``Incoming`` message is what an
entity receives: an ``IncomingRequest`` whose payload is still encoded
(from another runner or from storage), an ``IncomingRequestLocal``
decoded on this runner, or an ``IncomingEnvelope``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any

from pyfect import schema as S
from pyfect._core import Effect
from pyfect.cluster import envelope as envelope_
from pyfect.cluster.cluster_error import MalformedMessage, PersistenceError
from pyfect.cluster.cluster_schema import Dynamic
from pyfect.cluster.entity_address import EntityAddress
from pyfect.cluster.envelope import AckChunk, Encoded, Interrupt, Partial, PartialRequest, Request
from pyfect.cluster.reply import Encoded as ReplyEncoded
from pyfect.cluster.reply import Reply, ReplyWithContext
from pyfect.cluster.snowflake import Snowflake
from pyfect.context import Context
from pyfect.effect import fail, provide_context, succeed, suspend
from pyfect.rpc import AnyRpc
from pyfect.rpc import make as make_rpc
from pyfect.rpc.serialization import CodecFor

if TYPE_CHECKING:
    from pyfect.scope import CloseableScope


def codec_for_json(schema: S.Top) -> S.Codec[Any, Any, Any, Any]:
    """Effect's ``Schema.toCodecJson`` as a ``CodecFor``: storage encodes
    with it."""
    return S.to_codec_json(schema)


def dynamic_annotations(rpc: AnyRpc, request: Request[Any]) -> Context[Any]:
    """``rpc``'s annotations for ``request`` (``ClusterSchema.Dynamic``)."""
    return rpc.annotations.get(Dynamic)(rpc.annotations, request)


@dataclass(frozen=True, slots=True, kw_only=True)
class IncomingRequest:
    """A request with its payload still encoded by ``codec_for``; the
    entity answers through ``respond``."""

    envelope: PartialRequest
    last_sent_reply: ReplyEncoded | None
    respond: Callable[[ReplyWithContext], Effect[None, MalformedMessage | PersistenceError]]
    codec_for: CodecFor
    caller_scope: CloseableScope | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class IncomingRequestLocal[P = Any]:
    """A request decoded on this runner."""

    envelope: Request[P]
    last_sent_reply: Reply | None
    respond: Callable[[Reply], Effect[None, MalformedMessage | PersistenceError]]
    annotations: Context[Any]
    caller_scope: CloseableScope | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class IncomingEnvelope:
    envelope: AckChunk | Interrupt


type Incoming = IncomingRequest | IncomingEnvelope
type IncomingLocal = IncomingRequestLocal | IncomingEnvelope


@dataclass(frozen=True, slots=True)
class _EncodedCache:
    codec_for: CodecFor
    envelope: PartialRequest


@dataclass(slots=True, kw_only=True, eq=False)
class OutgoingRequest[P = Any]:
    """A request a sender holds: ``context`` has the services its schemas
    need, ``respond`` answers the caller."""

    envelope: Request[P]
    context: Context[Any]
    last_received_reply: Reply | None
    rpc: AnyRpc
    respond: Callable[[Reply], Effect[None]]
    annotations: Context[Any]
    encoded_cache: _EncodedCache | None = field(default=None, repr=False)


_never_rpc = make_rpc("Never", success=S.Never)


@dataclass(frozen=True, slots=True, kw_only=True)
class OutgoingEnvelope:
    envelope: AckChunk | Interrupt
    rpc: AnyRpc = _never_rpc

    @staticmethod
    def interrupt(
        *, address: EntityAddress, id: Snowflake, request_id: Snowflake
    ) -> OutgoingEnvelope:
        return OutgoingEnvelope(envelope=Interrupt(id=id, address=address, request_id=request_id))


type Outgoing = OutgoingRequest | OutgoingEnvelope


def incoming_local_from_outgoing(message: Outgoing) -> IncomingLocal:
    """The message as its entity on this runner receives it."""
    if isinstance(message, OutgoingEnvelope):
        return IncomingEnvelope(envelope=message.envelope)
    return IncomingRequestLocal(
        envelope=message.envelope,
        last_sent_reply=None,
        respond=message.respond,
        annotations=dynamic_annotations(message.rpc, message.envelope),
    )


def serialize_request(
    message: OutgoingRequest, codec_for: CodecFor
) -> Effect[PartialRequest, MalformedMessage]:
    """The request with its payload encoded by ``codec_for``."""
    request = message.envelope
    encode = S.encode_unknown_effect(codec_for(message.rpc.payload_schema))
    return MalformedMessage.refail(
        encode(request.payload).pipe(provide_context(message.context))
    ).map(lambda payload: _with_payload(request, payload))


def _with_payload(request: Request[Any], payload: object) -> Request[Any]:
    return replace(request, payload=payload)


def serialize(message: Outgoing, codec_for: CodecFor) -> Effect[Partial, MalformedMessage]:
    """The partial envelope of ``message`` (a request's encoding is cached
    per ``codec_for``)."""
    if isinstance(message, OutgoingEnvelope):
        return succeed(message.envelope)

    def run() -> Effect[Partial, MalformedMessage]:
        cached = message.encoded_cache
        if cached is not None and cached.codec_for is codec_for:
            return succeed(cached.envelope)

        def remember(envelope: PartialRequest) -> PartialRequest:
            message.encoded_cache = _EncodedCache(codec_for, envelope)
            return envelope

        return serialize_request(message, codec_for).map(remember)

    return suspend(run)


def serialize_envelope(message: Outgoing) -> Effect[Encoded, MalformedMessage]:
    """``message`` as Effect's JSON."""
    return serialize(message, codec_for_json).flat_map(
        lambda partial: MalformedMessage.refail(S.encode_effect(envelope_.PartialJson)(partial))
    )  # pyright: ignore[reportReturnType]


def deserialize_local(
    message: Outgoing, encoded: Partial, codec_for: CodecFor
) -> Effect[IncomingLocal, MalformedMessage]:
    """``encoded`` decoded again with ``message``'s schemas, as an entity on
    this runner receives it (what a remote runner would see)."""
    if not isinstance(encoded, Request):
        return succeed(IncomingEnvelope(envelope=encoded))
    if not isinstance(message, OutgoingRequest):
        return fail(
            MalformedMessage(
                cause=ValueError("Can only deserialize a Request with an OutgoingRequest message")
            )
        )
    rpc = message.rpc
    decode = S.decode_unknown_effect(codec_for(rpc.payload_schema))

    def received(payload: object) -> IncomingLocal:
        request = _with_payload(encoded, payload)
        return IncomingRequestLocal(
            envelope=request,
            last_sent_reply=None,
            respond=message.respond,
            annotations=dynamic_annotations(rpc, request),
        )

    return MalformedMessage.refail(
        decode(encoded.payload).pipe(provide_context(message.context))
    ).map(received)


__all__ = [
    "Incoming",
    "IncomingEnvelope",
    "IncomingLocal",
    "IncomingRequest",
    "IncomingRequestLocal",
    "MalformedMessage",
    "Outgoing",
    "OutgoingEnvelope",
    "OutgoingRequest",
    "codec_for_json",
    "deserialize_local",
    "dynamic_annotations",
    "incoming_local_from_outgoing",
    "serialize",
    "serialize_envelope",
    "serialize_request",
]
