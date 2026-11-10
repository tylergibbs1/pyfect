"""The operating system's resolver as the ``Dns`` service (Effect's
``NodeDns``, with PTR as the only record query).

Lookups go through ``getaddrinfo`` (the hosts file and the system's DNS
configuration, as Node's ``dns.lookup``). PTR queries go to the name servers
in ``/etc/resolv.conf`` (or the ones given), and reverse lookups are PTR
queries, as in Effect: the names are the records' targets, and the hosts file
is not read. Other record types fail with ``Unsupported``. Each call runs on a
thread of its own and resumes the fiber through its scheduler; an interrupted
call's answer is dropped.
"""

from __future__ import annotations

import socket
import threading
from collections.abc import Callable, Sequence
from ipaddress import ip_address

from pyfect._core import Effect
from pyfect._os_wait import Resume, os_wait
from pyfect.effect import fail, succeed
from pyfect.layer import Layer
from pyfect.layer import succeed as layer_succeed
from pyfect.net.dns._error import DnsError, DnsErrorReason, DnsMethod
from pyfect.net.dns._records import DnsRecord, Ptr, RecordType
from pyfect.net.dns._service import Dns, DnsService, Resolve, make
from pyfect.net.dns._wire import query_ptr_from
from pyfect.net.host import DomainName
from pyfect.net.net_address._inet import InetAddress
from pyfect.net.net_address._ip import IpAddress, IpFamily
from pyfect.result import Err, Ok, Result

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

    return os_wait(register, waits_for="work")


def _lookup(host: DomainName, family: IpFamily | None) -> Effect[Sequence[IpAddress], DnsError]:
    def call() -> list[IpAddress]:
        entries = socket.getaddrinfo(host, None, _FAMILIES[family], socket.SOCK_STREAM)
        return [ip_address(str(entry[4][0]).partition("%")[0]) for entry in entries]

    return _on_thread("lookup", host, call)


def _resolver(name_servers: Sequence[InetAddress]) -> Resolve:
    def resolve(name: DomainName, record_type: RecordType) -> Effect[Sequence[DnsRecord], DnsError]:
        if record_type != "PTR":
            return fail(DnsError("Unsupported", "resolve", name, record_type))

        def answered(
            found: Result[list[str], DnsErrorReason],
        ) -> Effect[Sequence[DnsRecord], DnsError]:
            match found:
                case Ok(targets):
                    return succeed([Ptr(target) for target in targets])
                case Err(reason):
                    return fail(DnsError(reason, "resolve", name, record_type))

        return _on_thread("resolve", name, lambda: query_ptr_from(name, name_servers)).flat_map(
            answered
        )

    return resolve


def make_system(name_servers: Sequence[InetAddress] = ()) -> DnsService:
    """The system resolver as a ``DnsService``; PTR queries and reverse
    lookups ask ``name_servers`` (from ``dns.name_server_from_input``) instead
    of the system's name servers when given."""
    return make(_lookup, _resolver(name_servers))


def layer_system(name_servers: Sequence[InetAddress] = ()) -> Layer[Dns]:
    """``Dns`` answered by the operating system's resolver."""
    return layer_succeed(Dns, make_system(name_servers))
