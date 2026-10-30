"""Live UDP sockets (Effect's ``NodeDatagramSocket``) on Python's
``socket`` module.

``make_udp`` opens and binds a new socket for each reader acquisition (names
resolved, bound and configured on a thread of its own, so no fiber
blocks); ``from_socket`` adopts a bound socket the caller makes. Packets
are read on the socket loop's thread. Sends go out from the writing fiber
without blocking; one the kernel cannot take yet waits for the socket to
become writable on the loop.
"""

from __future__ import annotations

import errno
import socket
import struct
import sys
import threading
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from ipaddress import IPv4Address, IPv6Address, ip_address
from typing import Literal, Never, overload

from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect._os_wait import Resume, os_wait
from pyfect.effect import fail, succeed, suspend, sync
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.net.net_address import (
    InetAddress,
    InetAddressV4,
    IpAddress,
    format_ip,
    format_native_host,
)
from pyfect.scope import Scope
from pyfect.socket._loop import call_soon, get_loop
from pyfect.socket.datagram._core import OnError, make_from_backing_socket
from pyfect.socket.datagram._errors import (
    DatagramSocketError,
    DatagramSocketUnsupportedError,
    IoErrorKind,
    OpenErrorKind,
    closed_error,
    open_error,
    read_error,
    write_error,
)
from pyfect.socket.datagram._model import (
    BackingAddress,
    BackingEvents,
    BackingSocket,
    DatagramSocket,
    DatagramSocketService,
    Leave,
    ReceiveBuffer,
    SendDone,
    SendManyDone,
)

type Family = Literal["ipv4", "ipv6"]

_MAX_DATAGRAM = 65536


@dataclass(frozen=True, slots=True)
class HostPort:
    """A host (an IP literal or a name, resolved once per reader
    acquisition) and a port."""

    host: str | IpAddress
    port: int


type Endpoint = HostPort | InetAddress


@dataclass(frozen=True, slots=True)
class Peer:
    """A default destination; does not filter senders."""

    endpoint: Endpoint


@dataclass(frozen=True, slots=True)
class Connect:
    """``connect(2)`` after binding: the kernel filters senders and ICMP
    errors reach ``on_error``."""

    endpoint: Endpoint


@dataclass(frozen=True, slots=True)
class Bind:
    """The local address and port; by default ``0.0.0.0`` (``::`` for
    IPv6) and an ephemeral port."""

    address: str | IpAddress | None = None
    port: int = 0


@dataclass(frozen=True, slots=True)
class Multicast:
    """Sending to groups: the egress ``interface`` (an IPv4 address, or an
    IPv6 interface index), whether sent packets loop back, and their TTL."""

    interface: IPv4Address | int | None = None
    loopback: bool | None = None
    ttl: int | None = None


@dataclass(frozen=True, slots=True, kw_only=True)
class Options:
    """How ``make_udp`` opens each socket.

    The family is ``family``, else that of an IP literal in ``bind``, else
    the remote's, else a ``bind`` name's, else IPv4. ``reuse_address`` is
    ``SO_REUSEADDR`` on Linux and ``SO_REUSEPORT`` on BSD and macOS. Kernel
    buffer sizes are in bytes."""

    bind: Bind | None = None
    family: Family | None = None
    remote: Peer | Connect | None = None
    reuse_address: bool | None = None
    reuse_port: bool | None = None
    ipv6_only: bool | None = None
    kernel_receive_buffer_size: int | None = None
    kernel_send_buffer_size: int | None = None
    broadcast: bool | None = None
    ttl: int | None = None
    multicast: Multicast | None = None
    receive_buffer: ReceiveBuffer | None = None
    on_error: OnError | None = field(default=None, compare=False)


def make_udp(options: Options | None = None) -> Effect[DatagramSocketService]:
    """A ``DatagramSocket`` that opens and binds a new socket for each reader
    acquisition. Making it never fails; binding, options and name
    resolution fail the acquisition."""
    opts = options or Options()
    return make_from_backing_socket(
        lambda events: _open(opts, events),
        receive_buffer=opts.receive_buffer,
        on_error=opts.on_error,
    )


@overload
def from_socket(
    acquire: Effect[socket.socket, DatagramSocketError, Scope],
    *,
    peer: Endpoint | None = None,
    receive_buffer: ReceiveBuffer | None = None,
    on_error: OnError | None = None,
) -> Effect[DatagramSocketService]: ...
@overload
def from_socket[R](
    acquire: Effect[socket.socket, DatagramSocketError, R | Scope],
    *,
    peer: Endpoint | None = None,
    receive_buffer: ReceiveBuffer | None = None,
    on_error: OnError | None = None,
) -> Effect[DatagramSocketService, Never, R]: ...
def from_socket(
    acquire: Effect[socket.socket, DatagramSocketError, object],
    *,
    peer: Endpoint | None = None,
    receive_buffer: ReceiveBuffer | None = None,
    on_error: OnError | None = None,
) -> Effect[DatagramSocketService, Never, object]:
    """Adopt a bound UDP ``socket.socket``: ``acquire`` runs for each
    reader acquisition, in the reader's scope, and the socket is closed
    with it. A connected socket sends to its remote address."""
    require_effect(acquire, "acquire")
    return make_from_backing_socket(
        lambda events: acquire.flat_map(lambda sock: _adopt(sock, peer, events)),
        receive_buffer=receive_buffer,
        on_error=on_error,
    )


def layer_udp(options: Options | None = None) -> Layer[DatagramSocket]:
    """Provide a ``DatagramSocket`` built with ``make_udp``."""
    return layer_effect(DatagramSocket, make_udp(options))


# --- errors ---------------------------------------------------------------


def _open_kind(cause: OSError) -> OpenErrorKind:
    match cause.errno:
        case errno.EADDRINUSE:
            return "AddressInUse"
        case errno.EADDRNOTAVAIL:
            return "AddressNotAvailable"
        case errno.EACCES | errno.EPERM:
            return "PermissionDenied"
        case _:
            return "Unknown"


def _io_kind(cause: OSError) -> IoErrorKind:
    match cause.errno:
        case errno.EMSGSIZE:
            return "MessageTooLarge"
        case errno.EHOSTUNREACH | errno.ENETUNREACH | errno.EHOSTDOWN | errno.ENETDOWN:
            return "Unreachable"
        case errno.ECONNREFUSED:
            return "ConnectionRefused"
        case errno.EACCES | errno.EPERM:
            return "PermissionDenied"
        case _:
            return "Unknown"


_GONE = (errno.EBADF, errno.ENOTSOCK)


def _send_error(cause: OSError) -> DatagramSocketError:
    return closed_error() if cause.errno in _GONE else write_error(cause, _io_kind(cause))


class _OpenFailed(Exception):
    def __init__(self, error: DatagramSocketError) -> None:
        super().__init__(error)
        self.error = error


# --- opening --------------------------------------------------------------


def _scope_ids(family: Family) -> Mapping[str, int]:
    if family == "ipv4" or sys.platform == "win32":
        return {}
    try:
        return {name: index for index, name in socket.if_nameindex()}
    except OSError:
        return {}


def _literal_family(address: str | IpAddress) -> Family | None:
    if isinstance(address, str):
        try:
            address = ip_address(address)
        except ValueError:
            return None
    return "ipv4" if isinstance(address, IPv4Address) else "ipv6"


def _lookup(host: str, family: Family | None) -> tuple[str, Family]:
    """Resolve a name to an IP literal: IPv4 first unless ``family`` is
    set."""
    want = {"ipv4": socket.AF_INET, "ipv6": socket.AF_INET6, None: socket.AF_UNSPEC}[family]
    try:
        results = socket.getaddrinfo(host, None, want, socket.SOCK_DGRAM)
    except OSError as cause:
        raise _OpenFailed(open_error(cause, "AddressNotAvailable")) from cause
    found = next((r for r in results if r[0] == socket.AF_INET), None) or (
        results[0] if results else None
    )
    if found is None:
        raise _OpenFailed(open_error(OSError(f"{host} has no addresses"), "AddressNotAvailable"))
    return str(found[4][0]), "ipv6" if found[0] == socket.AF_INET6 else "ipv4"


def _endpoint_host(endpoint: Endpoint, scope_ids: Mapping[str, int]) -> str:
    if isinstance(endpoint, HostPort):
        host = endpoint.host
        return host if isinstance(host, str) else format_ip(host)
    return format_native_host(endpoint, scope_ids)


def _endpoint_family(endpoint: Endpoint) -> Family | None:
    if isinstance(endpoint, HostPort):
        return _literal_family(endpoint.host)
    return "ipv4" if isinstance(endpoint, InetAddressV4) else "ipv6"


def _resolve(address: str | IpAddress | None, family: Family | None) -> tuple[str, Family] | None:
    """A name resolved to a literal; ``None`` for no address or a
    literal."""
    if not isinstance(address, str) or _literal_family(address) is not None:
        return None
    return _lookup(address, family)


@dataclass(frozen=True, slots=True)
class _Plan:
    family: Family
    scope_ids: Mapping[str, int]
    bind_host: str
    peer: BackingAddress | None
    connect: BackingAddress | None


def _plan(options: Options) -> _Plan:
    bind = options.bind
    remote = options.remote.endpoint if options.remote is not None else None
    fixed = options.family or (
        None if bind is None or bind.address is None else _literal_family(bind.address)
    )
    resolved_remote = _resolve(remote.host, fixed) if isinstance(remote, HostPort) else None
    remote_family = (
        resolved_remote[1]
        if resolved_remote is not None
        else (None if remote is None else _endpoint_family(remote))
    )
    resolved_bind = _resolve(None if bind is None else bind.address, fixed or remote_family)
    family: Family = (
        fixed or remote_family or (resolved_bind[1] if resolved_bind is not None else "ipv4")
    )
    scope_ids = _scope_ids(family)
    if resolved_bind is not None:
        bind_host = resolved_bind[0]
    elif bind is not None and bind.address is not None:
        bind_host = _endpoint_host(HostPort(bind.address, bind.port), scope_ids)
    else:
        bind_host = "::" if family == "ipv6" else "0.0.0.0"
    remote_address = None
    if remote is not None:
        host = (
            resolved_remote[0] if resolved_remote is not None else _endpoint_host(remote, scope_ids)
        )
        remote_address = BackingAddress(host, remote.port)
    if isinstance(options.remote, Connect):
        return _Plan(family, scope_ids, bind_host, None, remote_address)
    return _Plan(family, scope_ids, bind_host, remote_address, None)


def _in_thread(
    name: str, work: Callable[[], BackingSocket]
) -> Effect[BackingSocket, DatagramSocketError]:
    """Run ``work`` on a thread of its own; the core closes what an
    abandoned open gives."""

    def register(resume: Resume[BackingSocket, DatagramSocketError]) -> None:
        def run() -> None:
            try:
                resume(succeed(work()))
            except _OpenFailed as failed:
                resume(fail(failed.error))

        threading.Thread(target=run, name=name, daemon=True).start()

    return os_wait(register)


def _open(options: Options, events: BackingEvents) -> Effect[BackingSocket, DatagramSocketError]:
    return _in_thread("pyfect-udp-open", lambda: _bind(options, events, _plan(options)))


def _configure_before_bind(sock: socket.socket, options: Options, family: Family) -> None:
    if options.reuse_address:
        reuse = socket.SO_REUSEADDR if sys.platform.startswith("linux") else socket.SO_REUSEPORT
        sock.setsockopt(socket.SOL_SOCKET, reuse, 1)
    if options.reuse_port:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
    if options.ipv6_only is not None and family == "ipv6":
        sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, int(options.ipv6_only))


def _configure_after_bind(sock: socket.socket, options: Options, family: Family) -> None:
    if family == "ipv6":
        ip, ttl, multicast_ttl, multicast_loop = (
            socket.IPPROTO_IPV6,
            socket.IPV6_UNICAST_HOPS,
            socket.IPV6_MULTICAST_HOPS,
            socket.IPV6_MULTICAST_LOOP,
        )
    else:
        ip, ttl, multicast_ttl, multicast_loop = (
            socket.IPPROTO_IP,
            socket.IP_TTL,
            socket.IP_MULTICAST_TTL,
            socket.IP_MULTICAST_LOOP,
        )
    multicast = options.multicast or Multicast()
    egress = multicast.interface
    settings: list[tuple[int, int, int | bool | bytes | None]] = [
        (socket.SOL_SOCKET, socket.SO_RCVBUF, options.kernel_receive_buffer_size),
        (socket.SOL_SOCKET, socket.SO_SNDBUF, options.kernel_send_buffer_size),
        (socket.SOL_SOCKET, socket.SO_BROADCAST, options.broadcast),
        (ip, ttl, options.ttl),
        (ip, multicast_ttl, multicast.ttl),
        (ip, multicast_loop, multicast.loopback),
        (socket.IPPROTO_IP, socket.IP_MULTICAST_IF, egress.packed)
        if isinstance(egress, IPv4Address)
        else (socket.IPPROTO_IPV6, socket.IPV6_MULTICAST_IF, egress),
    ]
    for level, name, value in settings:
        if value is not None:
            sock.setsockopt(level, name, int(value) if isinstance(value, bool) else value)


def _bind(options: Options, events: BackingEvents, plan: _Plan) -> BackingSocket:
    family = socket.AF_INET6 if plan.family == "ipv6" else socket.AF_INET
    try:
        sock = socket.socket(family, socket.SOCK_DGRAM)
    except OSError as cause:
        raise _OpenFailed(open_error(cause, _open_kind(cause))) from cause
    try:
        _configure_before_bind(sock, options, plan.family)
        sock.bind((plan.bind_host, options.bind.port if options.bind is not None else 0))
        _configure_after_bind(sock, options, plan.family)
        if plan.connect is not None:
            sock.connect((plan.connect.host, plan.connect.port))
        sock.setblocking(False)
    except OSError as cause:
        sock.close()
        raise _OpenFailed(open_error(cause, _open_kind(cause))) from cause
    if plan.connect is not None:
        return _NativeSocket(sock, events, plan.scope_ids, plan.connect, connected=True)
    return _NativeSocket(sock, events, plan.scope_ids, plan.peer, connected=False)


def _adopt(
    sock: socket.socket, peer: Endpoint | None, events: BackingEvents
) -> Effect[BackingSocket, DatagramSocketError]:
    def work() -> BackingSocket:
        try:
            family: Family = "ipv6" if sock.family == socket.AF_INET6 else "ipv4"
            sock.setblocking(False)
        except OSError as cause:
            sock.close()
            raise _OpenFailed(open_error(cause, _open_kind(cause))) from cause
        scope_ids = _scope_ids(family)
        try:
            remote = sock.getpeername()
        except OSError:
            remote = None
        if remote is not None:
            address = BackingAddress(str(remote[0]), int(remote[1]))
            return _NativeSocket(sock, events, scope_ids, address, connected=True)
        default = None
        if peer is not None:
            resolved = _resolve(peer.host, family) if isinstance(peer, HostPort) else None
            host = resolved[0] if resolved is not None else _endpoint_host(peer, scope_ids)
            default = BackingAddress(host, peer.port)
        return _NativeSocket(sock, events, scope_ids, default, connected=False)

    return _in_thread("pyfect-udp-adopt", work)


# --- the open socket ------------------------------------------------------


class _NativeSocket:
    """A bound, non-blocking UDP socket: read on the loop, written from
    fibers."""

    def __init__(
        self,
        sock: socket.socket,
        events: BackingEvents,
        scope_ids: Mapping[str, int],
        peer: BackingAddress | None,
        *,
        connected: bool,
    ) -> None:
        self._sock = sock
        self._fd = sock.fileno()
        self._events = events
        bound = sock.getsockname()
        self.address = BackingAddress(str(bound[0]), int(bound[1]))
        self.scope_ids = scope_ids
        self.peer = peer
        self.connected = connected
        self._lock = threading.Lock()
        self._closing = False
        # Sends the kernel could not take yet, written in order on the loop.
        self._backlog: deque[tuple[bytes, BackingAddress | None, SendDone]] = deque()
        call_soon(self._start_reading)

    # --- loop side ----------------------------------------------------------

    def _start_reading(self) -> None:
        with self._lock:
            if self._closing:
                return
            get_loop().add_reader(self._fd, self._readable)

    def _readable(self) -> None:
        while True:
            try:
                payload, sender = self._sock.recvfrom(_MAX_DATAGRAM)
            except (BlockingIOError, InterruptedError):
                return
            except OSError as cause:
                if cause.errno in _GONE:
                    self._closed_underneath()
                else:
                    # An error after opening has no write left to fail, such
                    # as an ICMP report on a connected socket.
                    self._events.on_error(read_error(cause, _io_kind(cause)))
                return
            self._events.on_packet(payload, str(sender[0]), int(sender[1]))

    def _closed_underneath(self) -> None:
        with self._lock:
            closing = self._closing
        get_loop().remove_reader(self._fd)
        if not closing:
            self._events.on_close()

    def _writable(self) -> None:
        while True:
            with self._lock:
                if not self._backlog:
                    get_loop().remove_writer(self._fd)
                    return
                payload, destination, done = self._backlog[0]
            try:
                self._send_now(payload, destination)
            except (BlockingIOError, InterruptedError):
                return
            except OSError as cause:
                self._pop()
                done(_send_error(cause))
                continue
            self._pop()
            done(None)

    def _pop(self) -> None:
        with self._lock:
            self._backlog.popleft()

    def _wait_writable(self) -> None:
        with self._lock:
            if self._closing:
                backlog = list(self._backlog)
                self._backlog.clear()
            else:
                backlog = None
                get_loop().add_writer(self._fd, self._writable)
        for _payload, _destination, done in backlog or ():
            done(closed_error())

    # --- fibers' side -------------------------------------------------------

    def _send_now(self, payload: bytes, destination: BackingAddress | None) -> None:
        if destination is None:
            self._sock.send(payload)
        else:
            self._sock.sendto(payload, (destination.host, destination.port))

    def send(self, payload: bytes, destination: BackingAddress | None, done: SendDone) -> None:
        with self._lock:
            queued = bool(self._backlog)
            if queued:
                self._backlog.append((payload, destination, done))
        if queued:
            return
        try:
            self._send_now(payload, destination)
        except (BlockingIOError, InterruptedError):
            with self._lock:
                self._backlog.append((payload, destination, done))
            call_soon(self._wait_writable)
            return
        except OSError as cause:
            done(_send_error(cause))
            return
        done(None)

    def send_many(
        self,
        payloads: Sequence[bytes],
        destinations: Sequence[BackingAddress | None],
        done: SendManyDone,
    ) -> None:
        batch = _Batch(len(payloads), done)
        for index, (payload, destination) in enumerate(zip(payloads, destinations, strict=True)):
            self.send(payload, destination, batch.reporter(index))

    def join_multicast(
        self, group: IpAddress, interface: IPv4Address | int | None, source: IpAddress | None
    ) -> Effect[Leave, DatagramSocketError]:
        def join() -> Effect[Leave, DatagramSocketError]:
            option = _membership(group, interface, source)
            if isinstance(option, DatagramSocketError):
                return fail(option)
            level, add, drop, value = option
            try:
                self._sock.setsockopt(level, add, value)
            except OSError as cause:
                return fail(open_error(cause, _open_kind(cause)))
            return succeed(lambda: sync(lambda: self._sock.setsockopt(level, drop, value)))

        return suspend(join)

    def close(self) -> None:
        with self._lock:
            if self._closing:
                return
            self._closing = True
        call_soon(self._close_on_loop)

    def _close_on_loop(self) -> None:
        loop = get_loop()
        loop.remove_reader(self._fd)
        loop.remove_writer(self._fd)
        with self._lock:
            backlog = list(self._backlog)
            self._backlog.clear()
        self._sock.close()
        for _payload, _destination, done in backlog:
            done(closed_error())


class _Batch:
    """Collects the sends of a ``send_many``: ``done`` gets the first
    failure, and its index, once every send has reported."""

    __slots__ = ("_done", "_failure", "_lock", "_remaining")

    def __init__(self, size: int, done: SendManyDone) -> None:
        self._lock = threading.Lock()
        self._remaining = size
        self._failure: tuple[DatagramSocketError, int] | None = None
        self._done = done

    def reporter(self, index: int) -> SendDone:
        def report(error: DatagramSocketError | None) -> None:
            with self._lock:
                if error is not None and self._failure is None:
                    self._failure = (error, index)
                self._remaining -= 1
                finished = self._remaining == 0
            if finished:
                failure = self._failure
                self._done(*(failure or (None, None)))

        return report


type _Membership = tuple[int, int, int, bytes]

# ``struct ip_mreq_source``: Linux puts the interface before the source,
# BSD and macOS after it.
_SOURCE_FIRST = not sys.platform.startswith("linux")


def _membership(
    group: IpAddress, interface: IPv4Address | int | None, source: IpAddress | None
) -> _Membership | DatagramSocketError:
    if isinstance(group, IPv6Address):
        index = interface if isinstance(interface, int) else 0
        if source is not None:
            return DatagramSocketError(
                DatagramSocketUnsupportedError("IPv6 source-specific multicast", "pyfect")
            )
        value = group.packed + struct.pack("@I", index)
        return (socket.IPPROTO_IPV6, socket.IPV6_JOIN_GROUP, socket.IPV6_LEAVE_GROUP, value)
    ingress = (interface if isinstance(interface, IPv4Address) else IPv4Address(0)).packed
    if source is None:
        return (
            socket.IPPROTO_IP,
            socket.IP_ADD_MEMBERSHIP,
            socket.IP_DROP_MEMBERSHIP,
            group.packed + ingress,
        )
    if not hasattr(socket, "IP_ADD_SOURCE_MEMBERSHIP"):
        return DatagramSocketError(
            DatagramSocketUnsupportedError("source-specific multicast", "pyfect")
        )
    origin = source.packed
    value = group.packed + (origin + ingress if _SOURCE_FIRST else ingress + origin)
    return (
        socket.IPPROTO_IP,
        socket.IP_ADD_SOURCE_MEMBERSHIP,
        socket.IP_DROP_SOURCE_MEMBERSHIP,
        value,
    )
