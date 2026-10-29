"""The messages between RPC clients and servers (Effect's ``RpcMessage``).

The decoded messages (``Request``, ``Ack``, ``Interrupt``, ``Eof`` from a
client; ``ResponseChunk``, ``ResponseExit``, ``ResponseDefect``,
``ClientEnd`` from a server) are what the serialization-free client and
server exchange. The encoded ones are the JSON shapes a protocol carries,
``TypedDict``s with Effect's wire keys (``requestId``, ``isNotification``),
so a pyfect peer and an Effect peer understand each other.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal, NotRequired, TypedDict

from pyfect.exit import Exit
from pyfect.http.headers import Headers

if TYPE_CHECKING:
    from pyfect.rpc.client_error import RpcClientError

type RequestId = str | int
"""A request's id, unique per client (Effect's branded ``RequestId``)."""


# --- decoded, from a client ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Request:
    """A call of the RPC ``tag`` with its decoded ``payload``."""

    id: RequestId
    tag: str
    payload: object
    headers: Headers = field(default_factory=Headers)
    trace_id: str | None = None
    span_id: str | None = None
    sampled: bool | None = None


@dataclass(frozen=True, slots=True)
class Ack:
    """The client took a chunk of the stream ``request_id``: send the next."""

    request_id: RequestId


@dataclass(frozen=True, slots=True)
class Interrupt:
    """The client cancelled ``request_id``."""

    request_id: RequestId
    interruptors: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class Eof:
    """The client sends no more requests."""


EOF = Eof()

type FromClient = Request | Ack | Interrupt | Eof


# --- decoded, from a server ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ResponseChunk:
    """Items of the stream ``request_id``."""

    client_id: int
    request_id: RequestId
    values: tuple[Any, ...]


@dataclass(frozen=True, slots=True)
class ResponseExit:
    """How the request ``request_id`` ended."""

    client_id: int
    request_id: RequestId
    exit: Exit[Any, Any]


@dataclass(frozen=True, slots=True)
class ResponseDefect:
    """The server failed for every request of the client."""

    client_id: int
    defect: BaseException


@dataclass(frozen=True, slots=True)
class ClientEnd:
    """The server is done with the client."""

    client_id: int


type FromServer = ResponseChunk | ResponseExit | ResponseDefect | ClientEnd


# --- encoded (the wire) ---------------------------------------------------------------

type EncodedHeaders = Sequence[tuple[str, str]] | Sequence[Sequence[str]]


class RequestEncoded(TypedDict):
    _tag: Literal["Request"]
    id: RequestId
    tag: str
    payload: object
    headers: EncodedHeaders
    isNotification: NotRequired[Literal[True]]
    traceId: NotRequired[str]
    spanId: NotRequired[str]
    sampled: NotRequired[bool]


class AckEncoded(TypedDict):
    _tag: Literal["Ack"]
    requestId: RequestId


class InterruptEncoded(TypedDict):
    _tag: Literal["Interrupt"]
    requestId: RequestId


class Ping(TypedDict):
    _tag: Literal["Ping"]


class EofEncoded(TypedDict):
    _tag: Literal["Eof"]


class Pong(TypedDict):
    _tag: Literal["Pong"]


class ResponseChunkEncoded(TypedDict):
    _tag: Literal["Chunk"]
    requestId: RequestId
    values: Sequence[object]


class ExitEncoded(TypedDict):
    """An exit in JSON: ``{"_tag": "Success", "value"}`` or
    ``{"_tag": "Failure", "cause": [...]}``."""

    _tag: Literal["Success", "Failure"]
    value: NotRequired[object]
    cause: NotRequired[Sequence[object]]


class ResponseExitEncoded(TypedDict):
    _tag: Literal["Exit"]
    requestId: RequestId
    exit: ExitEncoded


class ResponseDefectEncoded(TypedDict):
    _tag: Literal["Defect"]
    defect: object


class ClientProtocolError(TypedDict):
    """Delivered to a client by its protocol when the connection failed;
    never on the wire."""

    _tag: Literal["ClientProtocolError"]
    error: RpcClientError


type FromClientEncoded = RequestEncoded | AckEncoded | InterruptEncoded | Ping | EofEncoded
type FromServerEncoded = (
    ResponseChunkEncoded
    | ResponseExitEncoded
    | ResponseDefectEncoded
    | Pong
    | ClientProtocolError
    | RequestEncoded
)

PING: Ping = {"_tag": "Ping"}
PONG: Pong = {"_tag": "Pong"}
EOF_ENCODED: EofEncoded = {"_tag": "Eof"}


def response_defect_encoded(defect: object) -> ResponseDefectEncoded:
    return {"_tag": "Defect", "defect": defect}


def response_exit_die_encoded(request_id: RequestId, defect: object) -> ResponseExitEncoded:
    return {
        "_tag": "Exit",
        "requestId": request_id,
        "exit": {"_tag": "Failure", "cause": [{"_tag": "Die", "defect": defect}]},
    }


def is_terminal_response(response: FromServerEncoded) -> bool:
    """Whether ``response`` ends a request (an exit) or every request of the
    client (a defect or a protocol error)."""
    return response["_tag"] in ("Exit", "Defect", "ClientProtocolError")


__all__ = [
    "EOF",
    "EOF_ENCODED",
    "PING",
    "PONG",
    "Ack",
    "AckEncoded",
    "ClientEnd",
    "ClientProtocolError",
    "EncodedHeaders",
    "Eof",
    "EofEncoded",
    "ExitEncoded",
    "FromClient",
    "FromClientEncoded",
    "FromServer",
    "FromServerEncoded",
    "Interrupt",
    "InterruptEncoded",
    "Ping",
    "Pong",
    "Request",
    "RequestEncoded",
    "RequestId",
    "ResponseChunk",
    "ResponseChunkEncoded",
    "ResponseDefect",
    "ResponseDefectEncoded",
    "ResponseExit",
    "ResponseExitEncoded",
    "is_terminal_response",
    "response_defect_encoded",
    "response_exit_die_encoded",
]
