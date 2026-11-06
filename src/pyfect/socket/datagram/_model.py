"""The ``DatagramSocket`` model: packets, the reader and writer a socket
gives, and the backing-socket contract platform adapters implement."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from ipaddress import IPv4Address, IPv6Address
from typing import TYPE_CHECKING, Literal, Never, Protocol, overload

from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect.context import Tag
from pyfect.net.net_address import InetAddress, IpAddress, inet_address_from_native_unsafe
from pyfect.scope import Scope
from pyfect.socket.datagram._errors import DatagramSocketError

if TYPE_CHECKING:
    from pyfect.socket.datagram._core import ReaderState


class Datagram:
    """A packet: its ``payload`` and the sender's ``address``."""

    __slots__ = ("_address", "payload")

    def __init__(self, payload: bytes, address: InetAddress) -> None:
        self.payload = payload
        self._address = address

    @property
    def address(self) -> InetAddress:
        return self._address

    def __repr__(self) -> str:
        return f"{type(self).__name__}({self.payload!r}, {self.address!r})"


class ReceivedDatagram(Datagram):
    """A packet a platform socket received. Its sender ``address`` is parsed
    on first read. Pass it as a write's destination (or as the whole write,
    to echo it) to reply on the raw sender address."""

    __slots__ = ("_owner", "_parsed", "host", "port")

    def __init__(self, payload: bytes, host: str, port: int, owner: ReaderState) -> None:
        self.payload = payload
        self.host = host
        self.port = port
        self._owner = owner
        self._parsed: InetAddress | None = None

    @property
    def address(self) -> InetAddress:
        if self._parsed is None:
            self._parsed = inet_address_from_native_unsafe(
                self.host, self.port, self._owner.scope_ids
            )
        return self._parsed


@dataclass(frozen=True, slots=True)
class OutgoingDatagram:
    """A packet to send; text is encoded as UTF-8. ``address`` may be left
    out when the socket has a peer or is connected. A received datagram as
    the address replies on its raw sender address; on a connected socket it
    goes out on the connected path, while an explicit ``InetAddress`` fails
    the write."""

    payload: bytes | str
    address: InetAddress | Datagram | None = None


type Outgoing = OutgoingDatagram | Datagram
"""What a write takes: a packet, or a received one to echo."""


class Reader(Protocol):
    """The receive side of an open socket.

    ``pull`` returns everything queued since the last pull, or waits for the
    next packet; after a terminal error it returns what is queued, then
    fails with that error until the reader's scope closes. ``address`` is
    the bound address. ``dropped()`` counts packets the receive buffer
    discarded. ``join_multicast`` joins a group until its scope closes; its
    ``interface`` selects where packets arrive."""

    @property
    def pull(self) -> Effect[tuple[Datagram, ...], DatagramSocketError]: ...

    @property
    def address(self) -> InetAddress: ...

    def dropped(self) -> int: ...

    @overload
    def join_multicast(
        self,
        group: IPv4Address,
        *,
        interface: IPv4Address | None = None,
        source: IPv4Address | None = None,
    ) -> Effect[None, DatagramSocketError, Scope]: ...
    @overload
    def join_multicast(
        self,
        group: IPv6Address,
        *,
        interface: int | None = None,
        source: IPv6Address | None = None,
    ) -> Effect[None, DatagramSocketError, Scope]: ...


@dataclass(frozen=True, slots=True)
class Writer:
    """The send side. Writes wait until a reader is open, so a send-only
    client must still acquire a reader. ``write_all`` fails with the first
    error, without resending."""

    write: Callable[[Outgoing], Effect[None, DatagramSocketError]]
    write_all: Callable[[Sequence[Outgoing]], Effect[None, DatagramSocketError]]


@dataclass(frozen=True, slots=True)
class DatagramSocketService:
    """A UDP socket: acquiring ``reader`` in a scope opens and binds a
    socket (one at a time; another acquisition waits for it to close);
    ``writer`` writes through the open one."""

    reader: Effect[Reader, DatagramSocketError, Scope]
    writer: Effect[Writer, Never, Scope]

    def __post_init__(self) -> None:
        require_effect(self.reader, "reader")
        require_effect(self.writer, "writer")


class DatagramSocket(Tag[DatagramSocketService], key="effect/socket/DatagramSocket"):
    """The UDP socket service."""


def make(
    reader: Effect[Reader, DatagramSocketError, Scope], writer: Effect[Writer, Never, Scope]
) -> DatagramSocketService:
    return DatagramSocketService(reader, writer)


@dataclass(frozen=True, slots=True)
class ReceiveBuffer:
    """The receive queue: at most ``capacity`` packets. When it is full,
    ``"dropping"`` discards the incoming packet and ``"sliding"`` the oldest
    queued one; both count in ``Reader.dropped()``."""

    capacity: int = 1024
    strategy: Literal["dropping", "sliding"] = "dropping"


@dataclass(frozen=True, slots=True)
class BackingAddress:
    """A host and port as the platform socket writes them."""

    host: str
    port: int


type SendDone = Callable[[DatagramSocketError | None], None]
type SendManyDone = Callable[[DatagramSocketError | None, int | None], None]
type Leave = Callable[[], Effect[None]]


class BackingSocket(Protocol):
    """What a platform adapter gives ``make_from_backing_socket``.

    ``address`` is the bound address, ``scope_ids`` maps IPv6 zone names to
    scope ids, ``peer`` is the default destination and ``connected`` marks a
    connected socket, whose sends take no destination. ``send`` and
    ``send_many`` call ``done`` exactly once, from any thread, when the
    platform reports the result; ``send_many`` passes the index of the
    datagram that failed when it knows it. ``close`` does not raise."""

    @property
    def address(self) -> BackingAddress: ...
    @property
    def scope_ids(self) -> Mapping[str, int]: ...
    @property
    def peer(self) -> BackingAddress | None: ...
    @property
    def connected(self) -> bool: ...

    def send(self, payload: bytes, destination: BackingAddress | None, done: SendDone) -> None: ...

    def send_many(
        self,
        payloads: Sequence[bytes],
        destinations: Sequence[BackingAddress | None],
        done: SendManyDone,
    ) -> None: ...

    def join_multicast(
        self, group: IpAddress, interface: IPv4Address | int | None, source: IpAddress | None
    ) -> Effect[Leave, DatagramSocketError]: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class BackingEvents:
    """Callbacks given to the adapter before it opens the socket (packets
    may arrive at once), safe to call from any thread. ``on_packet`` queues
    a packet; ``on_read_error`` (a terminal receive error) and ``on_close``
    (the socket closed underneath the reader) stick; ``on_error`` reports
    an error no write is left to fail, such as an ICMP report."""

    on_packet: Callable[[bytes, str, int], None]
    on_read_error: Callable[[DatagramSocketError], None]
    on_error: Callable[[DatagramSocketError], None]
    on_close: Callable[[], None]
