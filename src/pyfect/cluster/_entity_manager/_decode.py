"""Decoding a message read from storage or another runner, with the
entity's RPC schemas (Effect's ``makeMessageDecode``)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from typing import Any

from pyfect import schema as S
from pyfect._core import Effect
from pyfect.cluster.envelope import Request
from pyfect.cluster.message import Incoming, IncomingEnvelope, IncomingRequest
from pyfect.cluster.reply import Reply, reply_schema
from pyfect.effect import fail, gen, succeed
from pyfect.rpc import AnyRpc
from pyfect.schema.issue import InvalidValue


@dataclass(frozen=True, slots=True)
class DecodedRequest:
    envelope: Request[Any]
    last_sent_reply: Reply | None


def _unknown_tag() -> S.SchemaError:
    return S.SchemaError(InvalidValue(annotations={"message": "Expected a known entity RPC tag"}))


def _decode_request(message: IncomingRequest, rpc: AnyRpc) -> Effect[DecodedRequest, S.SchemaError]:
    codec_for = message.codec_for

    @gen
    def run():
        payload = yield from S.decode_unknown_effect(codec_for(rpc.payload_schema))(
            message.envelope.payload
        )
        last = message.last_sent_reply
        decoded_last: Reply | None = None
        if last is not None:
            decoded_last = yield from S.decode_unknown_effect(reply_schema(rpc, codec_for))(last)
        return DecodedRequest(replace(message.envelope, payload=payload), decoded_last)

    return run


def decode_message(
    rpcs: Mapping[str, AnyRpc], message: Incoming
) -> Effect[DecodedRequest | IncomingEnvelope, S.SchemaError, Any]:
    """The request with its payload (and last sent reply) decoded; an
    envelope as it is. An unknown tag is a ``SchemaError``."""
    if isinstance(message, IncomingEnvelope):
        return succeed(message)
    rpc = rpcs.get(message.envelope.tag)
    if rpc is None:
        return fail(_unknown_tag())
    return _decode_request(message, rpc)


__all__ = ["DecodedRequest", "decode_message"]
