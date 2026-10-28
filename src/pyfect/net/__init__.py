"""Networking values and services (Effect's ``effect/net``): addresses,
hosts, networks, DNS and address resolution."""

from pyfect.net import address_resolver, dns, host, ip_interface, ip_network, net_address
from pyfect.net._errors import NetAddressError

__all__ = [
    "NetAddressError",
    "address_resolver",
    "dns",
    "host",
    "ip_interface",
    "ip_network",
    "net_address",
]
