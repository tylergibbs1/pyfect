"""``ssl.SSLContext`` from ``TlsUpgradeOptions``, as Node's
``tls.createSecureContext`` builds one: ``ca`` replaces the system roots,
``reject_unauthorized=False`` turns verification off, and a server only
asks for a client certificate when ``request_cert`` is set."""

from __future__ import annotations

import ipaddress
import os
import ssl
import tempfile
from collections.abc import Sequence
from dataclasses import dataclass

from pyfect import redacted
from pyfect.redacted import Redacted
from pyfect.socket._socket import PemInput, TlsUpgradeOptions

DEFAULT_SERVERNAME = "localhost"
"""The name a client checks the certificate against without a
``servername`` or a connected host name (Node's default ``host``)."""


@dataclass(frozen=True, slots=True)
class ClientSide:
    """A socket whose TLS upgrades are clients checking the certificate
    against ``servername``, else ``host``. Make one with ``client_side``."""

    host: str


@dataclass(frozen=True, slots=True)
class ServerSide:
    """A socket whose TLS upgrades take the server side."""


type UpgradeSide = ClientSide | ServerSide


def client_side(host: str | None) -> ClientSide:
    """The client side of a socket connected to ``host`` (``None``: a Unix or
    adopted socket). As Node records ``socket._host`` only for a name it looked
    up, an IP literal falls back to ``localhost`` too."""
    if host is None:
        return ClientSide(DEFAULT_SERVERNAME)
    try:
        ipaddress.ip_address(host)
    except ValueError:
        return ClientSide(host)
    return ClientSide(DEFAULT_SERVERNAME)


def _pem(value: PemInput) -> str:
    return value.decode() if isinstance(value, bytes) else value


def _pems(value: PemInput | Sequence[PemInput]) -> list[str]:
    if isinstance(value, (str, bytes)):
        return [_pem(value)]
    return [_pem(v) for v in value]


def _keys(value: Redacted[PemInput] | Sequence[Redacted[PemInput]]) -> list[str]:
    if isinstance(value, Redacted):
        return [_pem(redacted.value(value))]
    return [_pem(redacted.value(v)) for v in value]


def check_credentials(options: TlsUpgradeOptions, *, server: bool) -> str | None:
    """Why the key and certificate options cannot be used, or ``None``."""
    has_key, has_cert = options.key is not None, options.cert is not None
    if server and not (has_key and has_cert):
        return "server TLS upgrade requires both key and cert"
    if has_key != has_cert:
        return "TLS upgrade credentials must include both key and cert"
    return None


def _load_chain(context: ssl.SSLContext, options: TlsUpgradeOptions) -> None:
    if options.key is None or options.cert is None:
        return
    password = None if options.passphrase is None else redacted.value(options.passphrase)
    # ``load_cert_chain`` reads files only; they live just long enough to load.
    with tempfile.TemporaryDirectory(prefix="pyfect-tls-") as directory:
        cert_path = os.path.join(directory, "cert.pem")
        key_path = os.path.join(directory, "key.pem")
        for path, pems in ((cert_path, _pems(options.cert)), (key_path, _keys(options.key))):
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w") as file:
                file.write("\n".join(pems))
        context.load_cert_chain(cert_path, key_path, password)


def client_context(options: TlsUpgradeOptions) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    if options.ca is None:
        context.load_default_certs()
    else:
        context.load_verify_locations(cadata="\n".join(_pems(options.ca)))
    if options.reject_unauthorized is False:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    _load_chain(context, options)
    if options.alpn_protocols is not None:
        context.set_alpn_protocols(list(options.alpn_protocols))
    return context


def server_context(options: TlsUpgradeOptions) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    _load_chain(context, options)
    if options.request_cert:
        if options.ca is not None:
            context.load_verify_locations(cadata="\n".join(_pems(options.ca)))
        rejecting = options.reject_unauthorized is not False
        context.verify_mode = ssl.CERT_REQUIRED if rejecting else ssl.CERT_OPTIONAL
    if options.alpn_protocols is not None:
        context.set_alpn_protocols(list(options.alpn_protocols))
    return context
