"""Socket errors (Effect's ``SocketError`` and its reasons) and the close
event a writer sends to close the socket."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pyfect.errors import TaggedError


@dataclass(frozen=True, slots=True)
class CloseEvent:
    """Written to a socket, closes it with ``code`` (1000 is a normal
    close)."""

    code: int = 1000
    reason: str | None = None

    def __str__(self) -> str:
        return f"{self.code}: {self.reason}" if self.reason else f"{self.code}"


@dataclass(eq=False)
class SocketReadError(TaggedError):
    cause: object

    @property
    def message(self) -> str:
        return "An error occurred during Read"


@dataclass(eq=False)
class SocketWriteError(TaggedError):
    cause: object

    @property
    def message(self) -> str:
        return "An error occurred during Write"


type OpenErrorKind = Literal["Unknown", "Timeout"]


@dataclass(eq=False)
class SocketOpenError(TaggedError):
    kind: OpenErrorKind
    cause: object

    @property
    def message(self) -> str:
        if self.kind == "Timeout":
            return 'timeout waiting for "open"'
        return "An error occurred during Open"


@dataclass(eq=False)
class SocketUpgradeError(TaggedError):
    """A TLS upgrade failed; without a ``cause``, the socket does not
    support one."""

    cause: object = None

    @property
    def message(self) -> str:
        if self.cause is None:
            return "Socket does not support TLS upgrade"
        return "An error occurred during TLS upgrade"


@dataclass(eq=False)
class SocketCloseError(TaggedError):
    """The socket closed: ``code`` 1000 is a normal close (the peer ended
    the stream), 1006 an abnormal one."""

    code: int
    close_reason: str | None = None

    @property
    def message(self) -> str:
        return f"{self.code}: {self.close_reason}" if self.close_reason else f"{self.code}"


type SocketErrorReason = (
    SocketReadError | SocketWriteError | SocketOpenError | SocketUpgradeError | SocketCloseError
)


@dataclass(eq=False)
class SocketError(TaggedError):
    """A socket operation failed; ``reason`` says how."""

    reason: SocketErrorReason
    cause: object = field(init=False, compare=False, repr=False)

    def __post_init__(self) -> None:
        self.cause = None if isinstance(self.reason, SocketCloseError) else self.reason.cause

    @property
    def message(self) -> str:
        return self.reason.message


def close_error(code: int, close_reason: str | None = None) -> SocketError:
    return SocketError(SocketCloseError(code, close_reason))


def is_clean_close(error: SocketError) -> bool:
    """Whether ``error`` is a normal close (code 1000)."""
    return isinstance(error.reason, SocketCloseError) and error.reason.code == 1000


def read_error(cause: object) -> SocketError:
    return SocketError(SocketReadError(cause))


def write_error(cause: object) -> SocketError:
    return SocketError(SocketWriteError(cause))


def open_error(cause: object, kind: OpenErrorKind = "Unknown") -> SocketError:
    return SocketError(SocketOpenError(kind, cause))


def upgrade_error(cause: object = None) -> SocketError:
    return SocketError(SocketUpgradeError(cause))
