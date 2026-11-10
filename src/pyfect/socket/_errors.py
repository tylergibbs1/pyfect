"""Socket errors (Effect's ``SocketError`` and its reasons) and the close
event a writer sends to close the socket."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from pyfect import schema as S


@dataclass(frozen=True, slots=True)
class CloseEvent:
    """Written to a socket, closes it with ``code`` (1000 is a normal
    close)."""

    code: int = 1000
    reason: str | None = None

    def __str__(self) -> str:
        return f"{self.code}: {self.reason}" if self.reason else f"{self.code}"


class SocketReadError(S.TaggedError, identifier="effect/socket/Socket/SocketReadError"):
    cause: object = S.field(S.Defect())

    @property
    def message(self) -> str:
        return "An error occurred during Read"


class SocketWriteError(S.TaggedError, identifier="effect/socket/Socket/SocketWriteError"):
    cause: object = S.field(S.Defect())

    @property
    def message(self) -> str:
        return "An error occurred during Write"


type OpenErrorKind = Literal["Unknown", "Timeout"]


class SocketOpenError(S.TaggedError, identifier="effect/socket/Socket/SocketOpenError"):
    """Opening the socket failed; ``target`` is where it was going (a URL,
    ``host:port`` or a path) when known. Effect has no ``target``: it is
    encoded only when set, and Effect's decoder ignores it."""

    kind: OpenErrorKind = S.field(S.Literals(("Unknown", "Timeout")))
    cause: object = S.field(S.Defect())
    target: str | None = S.field(S.Union(S.String, S.Undefined), default=None)

    @property
    def message(self) -> str:
        if self.kind == "Timeout":
            return 'timeout waiting for "open"'
        return "An error occurred during Open"

    def __str__(self) -> str:
        return self.message


class SocketUpgradeError(S.TaggedError, identifier="effect/socket/Socket/SocketUpgradeError"):
    """A TLS upgrade failed; without a ``cause``, the socket does not
    support one."""

    cause: object = S.field(S.Union(S.Undefined, S.Defect()), default=None)

    @property
    def message(self) -> str:
        if self.cause is None:
            return "Socket does not support TLS upgrade"
        return "An error occurred during TLS upgrade"


class SocketCloseError(S.TaggedError, identifier="effect/socket/Socket/SocketCloseError"):
    """The socket closed: ``code`` 1000 is a normal close (the peer ended
    the stream), 1006 an abnormal one."""

    code: int = S.field(S.Int)
    close_reason: str | None = S.field(
        S.Union(S.String, S.Undefined), default=None, key="closeReason"
    )

    @property
    def message(self) -> str:
        return f"{self.code}: {self.close_reason}" if self.close_reason else f"{self.code}"


type SocketErrorReason = (
    SocketReadError | SocketWriteError | SocketOpenError | SocketUpgradeError | SocketCloseError
)

SOCKET_ERROR_REASON = S.Union(
    SocketReadError, SocketWriteError, SocketOpenError, SocketUpgradeError, SocketCloseError
)
"""The schema of every reason (Effect's ``SocketErrorReason`` schema)."""


class SocketError(S.TaggedError, identifier="~effect/socket/Socket/SocketError"):
    """A socket operation failed; ``reason`` says how. Its ``cause`` (and
    ``__cause__``) is the reason's, ``None`` for a close."""

    reason: SocketErrorReason = S.field(SOCKET_ERROR_REASON)

    def __post_init__(self) -> None:
        self.__cause__ = self.cause if isinstance(self.cause, BaseException) else None

    @property
    def cause(self) -> object:
        return None if isinstance(self.reason, SocketCloseError) else self.reason.cause

    @property
    def message(self) -> str:
        return self.reason.message


def close_error(code: int, close_reason: str | None = None) -> SocketError:
    return SocketError(reason=SocketCloseError(code=code, close_reason=close_reason))


def is_clean_close(error: SocketError) -> bool:
    """Whether ``error`` is a normal close (code 1000)."""
    return isinstance(error.reason, SocketCloseError) and error.reason.code == 1000


def read_error(cause: object) -> SocketError:
    return SocketError(reason=SocketReadError(cause=cause))


def write_error(cause: object) -> SocketError:
    return SocketError(reason=SocketWriteError(cause=cause))


def open_error(
    cause: object, kind: OpenErrorKind = "Unknown", *, target: str | None = None
) -> SocketError:
    return SocketError(reason=SocketOpenError(kind=kind, cause=cause, target=target))


def upgrade_error(cause: object = None) -> SocketError:
    return SocketError(reason=SocketUpgradeError(cause=cause))
