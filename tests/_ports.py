"""Local ports for tests, each held by a socket for as long as it is used.

Never bind a probe socket to port 0, close it and use its number later: the
port is free in between, and another process (or one of its outgoing
connections) can take it. tests/test_ports.py bans that pattern outside
this module.
"""

import atexit
import errno
import socket

_HOST = "127.0.0.1"
_ATTEMPTS = 100

# Sockets that keep refused ports taken until the test process exits.
_held: list[socket.socket] = []


@atexit.register
def _release() -> None:
    for sock in _held:
        sock.close()


def tcp_and_udp(host: str = _HOST) -> tuple[socket.socket, socket.socket]:
    """A bound TCP socket and a bound UDP socket on the same port; a port
    whose other protocol is taken is skipped for a fresh one."""
    for _ in range(_ATTEMPTS):
        udp = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        tcp = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            udp.bind((host, 0))
            tcp.bind((host, udp.getsockname()[1]))
        except OSError as error:
            udp.close()
            tcp.close()
            if error.errno != errno.EADDRINUSE:
                raise
            continue
        return tcp, udp
    raise OSError(errno.EADDRINUSE, f"no port free for both TCP and UDP on {host}")


def refused_tcp_port(host: str = _HOST) -> int:
    """A port where TCP connects are refused, for the rest of the run.

    A connected socket holds it: nothing else can bind it, and with no
    listener a SYN from any other peer is reset (a socket bound without
    listening only drops it on macOS)."""
    with socket.create_server((host, 0)) as listener:
        client = socket.create_connection(listener.getsockname()[:2])
        accepted, _ = listener.accept()
    _held.extend((client, accepted))
    return client.getsockname()[1]


def refused_udp_port(host: str = _HOST) -> int:
    """A port where UDP datagrams are refused (ICMP port unreachable), for the
    rest of the run: a UDP socket connected to another peer holds it and
    takes no datagrams from anyone else."""
    holder = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    peer = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    holder.bind((host, 0))
    peer.bind((host, 0))
    holder.connect(peer.getsockname())
    _held.extend((holder, peer))
    return holder.getsockname()[1]


def reserved_port(host: str = _HOST) -> int:
    """A port for a server that binds the number itself with SO_REUSEADDR
    (asyncio, uvicorn, PostgreSQL, Redis).

    The port is left in TIME_WAIT from an accepted connection: for about a
    minute the OS hands it to no ``bind(("", 0))`` and no outgoing
    connection, and a plain bind fails, but a SO_REUSEADDR listener may
    take it."""
    with socket.socket() as listener:
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind((host, 0))
        listener.listen(1)
        port = listener.getsockname()[1]
        with socket.create_connection((host, port)) as client:
            accepted, _ = listener.accept()
            # The accepted side closes first, so the TIME_WAIT is on ``port``.
            accepted.close()
            client.recv(1)
    return port
