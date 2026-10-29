"""The errors of RPC clients (Effect's ``RpcClientError``)."""

from __future__ import annotations

from dataclasses import dataclass

from pyfect.errors import TaggedError
from pyfect.http.error import HttpClientError
from pyfect.socket import SocketErrorReason


@dataclass(eq=False)
class RpcClientDefect(TaggedError):
    """The client could not make sense of what the protocol gave it."""

    message: str
    cause: object = None


type RpcClientErrorReason = SocketErrorReason | HttpClientError | RpcClientDefect


@dataclass(eq=False)
class RpcClientError(TaggedError):
    """A request could not be sent or answered; ``reason`` says why: the
    socket's error, the HTTP client's, or an ``RpcClientDefect``."""

    reason: RpcClientErrorReason

    @property
    def message(self) -> str:
        return f"{type(self.reason).__name__}: {self.reason.message}"


__all__ = ["RpcClientDefect", "RpcClientError", "RpcClientErrorReason"]
