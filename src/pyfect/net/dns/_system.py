"""The operating system's resolver as the ``Dns`` service (Effect's
``NodeDns``, minus record queries).

Lookups go through ``getaddrinfo`` (the hosts file and the system's DNS
configuration, as Node's ``dns.lookup``); reverse lookups through
``gethostbyaddr``. Python's standard library has no DNS record queries, so
``resolve`` fails with ``Unsupported``. Each call runs on a thread of its
own and resumes the fiber through its scheduler; an interrupted call's
answer is dropped.
"""

from __future__ import annotations

import socket
import threading
from collections.abc import Callable, Sequence
from ipaddress import ip_address

from pyfect._core import Effect
from pyfect.effect import fail, succeed
from pyfect.layer import Layer
from pyfect.layer import succeed as layer_succeed
from pyfect.net.dns._error import DnsError, DnsErrorReason, DnsMethod
from pyfect.net.dns._service import Dns, DnsService, make
from pyfect.net.host import DomainName
from pyfect.net.net_address._ip import IpAddress, IpFamily, format_ip
from pyfect.process._os import Resume, os_wait

_REASON_NAMES: list[tuple[str, DnsErrorReason]] = [
    ("EAI_NONAME", "NotFound"),
    ("EAI_NODATA", "NotFound"),
    ("EAI_AGAIN", "Temporary"),
    ("EAI_FAIL", "Refused"),
    ("EAI_FAMILY", "BadName"),
]
_REASONS: dict[int, DnsErrorReason] = {
    code: reason
    for name, reason in _REASON_NAMES
    if isinstance(code := getattr(socket, name, None), int)
}

_FAMILIES = {None: socket.AF_UNSPEC, "IPv4": socket.AF_INET, "IPv6": socket.AF_INET6}


def dns_error_from_cause(cause: OSError, method: DnsMethod, hostname: str) -> DnsError:
    """The ``DnsError`` of a resolver failure, by its error code."""
    if isinstance(cause, socket.herror):
        return DnsError("NotFound", method, hostname, cause=cause)
    reason = _REASONS.get(cause.errno, "Unknown") if cause.errno is not None else "Unknown"
    return DnsError(reason, method, hostname, cause=cause)


def _on_thread[A](method: DnsMethod, hostname: str, call: Callable[[], A]) -> Effect[A, DnsError]:
    def register(resume: Resume[A, DnsError]) -> None:
        def run() -> None:
            try:
                resume(succeed(call()))
            except OSError as cause:
                resume(fail(dns_error_from_cause(cause, method, hostname)))

        threading.Thread(target=run, name=f"pyfect-dns-{method}", daemon=True).start()

    return os_wait(register)


def _lookup(host: DomainName, family: IpFamily | None) -> Effect[Sequence[IpAddress], DnsError]:
    def call() -> list[IpAddress]:
        entries = socket.getaddrinfo(host, None, _FAMILIES[family], socket.SOCK_STREAM)
        return [ip_address(str(entry[4][0]).partition("%")[0]) for entry in entries]

    return _on_thread("lookup", host, call)


def _reverse(address: IpAddress) -> Effect[Sequence[str], DnsError]:
    def call() -> list[str]:
        name, aliases, _ = socket.gethostbyaddr(format_ip(address))
        return [name, *aliases]

    return _on_thread("reverse", format_ip(address), call)


def make_system() -> DnsService:
    """The system resolver as a ``DnsService``."""
    return make(_lookup, reverse=_reverse)


def layer_system() -> Layer[Dns]:
    """``Dns`` answered by the operating system's resolver."""
    return layer_succeed(Dns, make_system())
