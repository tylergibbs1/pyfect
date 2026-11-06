"""UDP sockets (Effect's ``DatagramSocket`` and ``NodeDatagramSocket``).

Acquiring a socket's ``reader`` in a scope opens and binds a socket owned
by that scope; only one reader is open at a time. ``pull`` returns every
packet queued since the last pull, or waits for the next. Writes wait while
no reader is open, so a send-only client still acquires a reader::

    server = InetAddressV4(IPv4Address("127.0.0.1"), 5353)

    def request(payload: str):
        socket = yield from DatagramSocket
        reader = yield from socket.reader
        writer = yield from socket.writer
        yield from writer.write(OutgoingDatagram(payload, server))
        (response, *_) = yield from reader.pull
        return response.payload

``make_udp`` / ``layer_udp`` open sockets with Python's ``socket`` module (read on
the socket loop's thread, so they work under ``run_blocking`` too);
``from_socket`` adopts a bound one; ``make_from_backing_socket`` is the
contract other transports implement.
"""

from pyfect._public import publish
from pyfect.socket.datagram._core import OnError, make_from_backing_socket
from pyfect.socket.datagram._errors import (
    DatagramSocketClosedError,
    DatagramSocketError,
    DatagramSocketErrorReason,
    DatagramSocketOpenError,
    DatagramSocketReadError,
    DatagramSocketUnsupportedError,
    DatagramSocketWriteError,
    IoErrorKind,
    OpenErrorKind,
)
from pyfect.socket.datagram._live import (
    Bind,
    Connect,
    Endpoint,
    Family,
    HostPort,
    Multicast,
    Options,
    Peer,
    from_socket,
    layer_udp,
    make_udp,
)
from pyfect.socket.datagram._model import (
    BackingAddress,
    BackingEvents,
    BackingSocket,
    Datagram,
    DatagramSocket,
    DatagramSocketService,
    Leave,
    Outgoing,
    OutgoingDatagram,
    Reader,
    ReceiveBuffer,
    ReceivedDatagram,
    SendDone,
    SendManyDone,
    Writer,
    make,
)

__all__ = [
    "BackingAddress",
    "BackingEvents",
    "BackingSocket",
    "Bind",
    "Connect",
    "Datagram",
    "DatagramSocket",
    "DatagramSocketClosedError",
    "DatagramSocketError",
    "DatagramSocketErrorReason",
    "DatagramSocketOpenError",
    "DatagramSocketReadError",
    "DatagramSocketService",
    "DatagramSocketUnsupportedError",
    "DatagramSocketWriteError",
    "Endpoint",
    "Family",
    "HostPort",
    "IoErrorKind",
    "Leave",
    "Multicast",
    "OnError",
    "OpenErrorKind",
    "Options",
    "Outgoing",
    "OutgoingDatagram",
    "Peer",
    "Reader",
    "ReceiveBuffer",
    "ReceivedDatagram",
    "SendDone",
    "SendManyDone",
    "Writer",
    "from_socket",
    "layer_udp",
    "make",
    "make_from_backing_socket",
    "make_udp",
]

publish(globals())
