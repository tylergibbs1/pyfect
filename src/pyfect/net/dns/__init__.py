"""DNS (Effect's ``Dns``): the ``Dns`` service, its records and errors.

``Dns`` looks up hosts, queries records by class and reverse-resolves
addresses::

    dns = yield from Dns()
    mail = yield from dns.resolve("example.com", Mx)   # tuple[Mx, ...]

``make`` builds the service from a lookup (and optionally a resolver and
reverse lookup); ``layer_static`` answers from a fixed zone, for tests;
``layer_system`` asks the operating system. Records are
validated frozen dataclasses; ``make_record`` builds one as a ``Result``.
"""

from pyfect._public import publish
from pyfect.net.dns._error import DnsError, DnsErrorReason, DnsMethod
from pyfect.net.dns._records import (
    A,
    Aaaa,
    Caa,
    Cname,
    DnsRecord,
    Mx,
    Naptr,
    Ns,
    Ptr,
    RecordType,
    Soa,
    Srv,
    Tlsa,
    Txt,
    format_record,
    is_record_type,
    make_record,
    record_classes,
    record_types,
    reverse_name,
)
from pyfect.net.dns._service import (
    Dns,
    DnsService,
    Lookup,
    Resolve,
    Reverse,
    layer_static,
    make,
    make_static,
    name_server_from_input,
    name_server_from_string,
)
from pyfect.net.dns._system import dns_error_from_cause, layer_system, make_system

__all__ = [
    "A",
    "Aaaa",
    "Caa",
    "Cname",
    "Dns",
    "DnsError",
    "DnsErrorReason",
    "DnsMethod",
    "DnsRecord",
    "DnsService",
    "Lookup",
    "Mx",
    "Naptr",
    "Ns",
    "Ptr",
    "RecordType",
    "Resolve",
    "Reverse",
    "Soa",
    "Srv",
    "Tlsa",
    "Txt",
    "dns_error_from_cause",
    "format_record",
    "is_record_type",
    "layer_static",
    "layer_system",
    "make",
    "make_record",
    "make_static",
    "make_system",
    "name_server_from_input",
    "name_server_from_string",
    "record_classes",
    "record_types",
    "reverse_name",
]

publish(globals())
