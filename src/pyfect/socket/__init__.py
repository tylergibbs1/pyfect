"""Sockets (Effect's ``Socket`` and ``NodeSocket``).

A ``SocketService`` has a ``reader`` and a ``writer``, both acquired in a
scope. Acquiring the reader opens the connection (closed with the scope);
its ``pull`` waits for the next batch of chunks and fails with a
``SocketError`` once the socket closes (a ``SocketCloseError`` with code
1000 when the peer ended the stream). The writer writes to the open
connection; writing a ``CloseEvent`` closes it::

    socket = make_net(8080, "127.0.0.1")

    def talk():
        writer = yield socket.writer
        reader = yield socket.reader
        yield writer.write_all([b"ping"])
        return (yield reader.pull)

    reply = yield from scoped(gen(talk))

``to_channel`` and ``to_stream`` turn a socket into a channel (input
written, output read) or a stream. The live sockets run on an asyncio loop
of their own, on a background thread, so they work under ``run_sync`` too.
``pyfect.socket.server`` listens for connections. ``from_web_socket``
adapts a browser-style WebSocket and ``make_web_socket`` opens a client
through the ``WebSocketConstructor`` service, which ``pyfect.socket.ws``
provides on the ``websockets`` library (extra ``pyfect[websockets]``).
"""

from pyfect.socket import server
from pyfect.socket._errors import (
    CloseEvent,
    OpenErrorKind,
    SocketCloseError,
    SocketError,
    SocketErrorReason,
    SocketOpenError,
    SocketReadError,
    SocketUpgradeError,
    SocketWriteError,
    is_clean_close,
)
from pyfect.socket._net import (
    from_socket,
    layer_net,
    layer_tls,
    make_net,
    make_net_channel,
    make_tls,
    make_tls_channel,
    make_unix,
)
from pyfect.socket._socket import (
    Chunk,
    PemInput,
    Reader,
    Socket,
    SocketChannel,
    SocketService,
    TlsUpgradeOptions,
    Upgrade,
    Write,
    WriteAll,
    Writer,
    make,
    make_channel,
    reader_bytes,
    reader_string,
    to_channel,
    to_channel_string,
    to_stream,
    unsupported_upgrade,
)
from pyfect.socket._web_socket import (
    Listener,
    Pausable,
    WebSocket,
    WebSocketClientOptions,
    WebSocketConstructor,
    WebSocketConstructorService,
    WebSocketEvent,
    WebSocketEventType,
    WebSocketLike,
    from_web_socket,
    layer_web_socket,
    make_web_socket,
    make_web_socket_channel,
)

__all__ = [
    "Chunk",
    "CloseEvent",
    "Listener",
    "OpenErrorKind",
    "Pausable",
    "PemInput",
    "Reader",
    "Socket",
    "SocketChannel",
    "SocketCloseError",
    "SocketError",
    "SocketErrorReason",
    "SocketOpenError",
    "SocketReadError",
    "SocketService",
    "SocketUpgradeError",
    "SocketWriteError",
    "TlsUpgradeOptions",
    "Upgrade",
    "WebSocket",
    "WebSocketClientOptions",
    "WebSocketConstructor",
    "WebSocketConstructorService",
    "WebSocketEvent",
    "WebSocketEventType",
    "WebSocketLike",
    "Write",
    "WriteAll",
    "Writer",
    "from_socket",
    "from_web_socket",
    "is_clean_close",
    "layer_net",
    "layer_tls",
    "layer_web_socket",
    "make",
    "make_channel",
    "make_net",
    "make_net_channel",
    "make_tls",
    "make_tls_channel",
    "make_unix",
    "make_web_socket",
    "make_web_socket_channel",
    "reader_bytes",
    "reader_string",
    "server",
    "to_channel",
    "to_channel_string",
    "to_stream",
    "unsupported_upgrade",
]
