"""``DatagramSocketError`` and its reasons."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from pyfect.errors import TaggedError
from pyfect.net.net_address import InetAddress

type OpenErrorKind = Literal["AddressInUse", "AddressNotAvailable", "PermissionDenied", "Unknown"]
type IoErrorKind = Literal[
    "MessageTooLarge", "Unreachable", "ConnectionRefused", "PermissionDenied", "Unknown"
]


@dataclass(eq=False)
class DatagramSocketOpenError(TaggedError):
    """Opening or binding the socket, applying its options, or resolving a
    name failed."""

    kind: OpenErrorKind
    cause: object


@dataclass(eq=False)
class DatagramSocketReadError(TaggedError):
    """A receive failed, or an ICMP report arrived with no write left to
    fail."""

    kind: IoErrorKind
    cause: object


@dataclass(eq=False)
class DatagramSocketWriteError(TaggedError):
    """A send failed; ``address`` is the destination when it is known."""

    kind: IoErrorKind
    cause: object
    address: InetAddress | None = None


@dataclass(eq=False)
class DatagramSocketClosedError(TaggedError):
    """The socket closed underneath the reader, or the reader's scope
    closed."""


@dataclass(eq=False)
class DatagramSocketUnsupportedError(TaggedError):
    """The runtime lacks a capability."""

    capability: str
    runtime: str

    @property
    def message(self) -> str:
        return f"{self.runtime} does not support {self.capability}"


type DatagramSocketErrorReason = (
    DatagramSocketOpenError
    | DatagramSocketReadError
    | DatagramSocketWriteError
    | DatagramSocketClosedError
    | DatagramSocketUnsupportedError
)


@dataclass(eq=False)
class DatagramSocketError(TaggedError):
    """A ``DatagramSocket`` operation failed; ``reason`` says how. Its
    ``cause`` and message come from the reason."""

    reason: DatagramSocketErrorReason
    cause: object = field(init=False, compare=False, repr=False)

    def __post_init__(self) -> None:
        self.cause = getattr(self.reason, "cause", None)

    @property
    def message(self) -> str:
        return str(self.reason)


def open_error(cause: object, kind: OpenErrorKind = "Unknown") -> DatagramSocketError:
    return DatagramSocketError(DatagramSocketOpenError(kind, cause))


def read_error(cause: object, kind: IoErrorKind = "Unknown") -> DatagramSocketError:
    return DatagramSocketError(DatagramSocketReadError(kind, cause))


def write_error(
    cause: object, kind: IoErrorKind = "Unknown", address: InetAddress | None = None
) -> DatagramSocketError:
    return DatagramSocketError(DatagramSocketWriteError(kind, cause, address))


def closed_error() -> DatagramSocketError:
    return DatagramSocketError(DatagramSocketClosedError())
