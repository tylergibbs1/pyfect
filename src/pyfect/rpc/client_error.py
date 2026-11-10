"""The errors of RPC clients (Effect's ``RpcClientError``).

Both are schema classes, so an ``RpcClientError`` encodes as Effect's does:
its ``reason`` is a worker or socket error reason, an
``HttpClientErrorSchema`` or an ``RpcClientDefect``."""

from __future__ import annotations

from pyfect import schema as S
from pyfect.http.error import HttpClientErrorSchema
from pyfect.socket import SOCKET_ERROR_REASON, SocketErrorReason
from pyfect.workers.worker_error import WORKER_ERROR_REASON, WorkerErrorReason


class RpcClientDefect(S.TaggedError, identifier="effect/rpc/RpcClientError/RpcClientDefect"):
    """The client could not make sense of what the protocol gave it."""

    message: str
    cause: object = S.field(S.Defect(), default=None)


type RpcClientErrorReason = (
    WorkerErrorReason | SocketErrorReason | HttpClientErrorSchema | RpcClientDefect
)

RPC_CLIENT_ERROR_REASON = S.Union(
    WORKER_ERROR_REASON, SOCKET_ERROR_REASON, HttpClientErrorSchema, RpcClientDefect
)
"""The schema of every reason (the ``reason`` of Effect's ``RpcClientError``)."""


class RpcClientError(S.TaggedError, identifier="~effect/rpc/RpcClientError"):
    """A request could not be sent or answered; ``reason`` says why: the
    worker's or socket's error, the HTTP client's (as an
    ``HttpClientErrorSchema``), or an ``RpcClientDefect``."""

    reason: RpcClientErrorReason = S.field(RPC_CLIENT_ERROR_REASON)

    @property
    def message(self) -> str:
        return f"{self.reason._tag}: {self.reason.message}"


__all__ = [
    "RPC_CLIENT_ERROR_REASON",
    "RpcClientDefect",
    "RpcClientError",
    "RpcClientErrorReason",
]
