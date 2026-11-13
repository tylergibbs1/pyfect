"""The soak connects to the exact address its server listens on.

Its HTTP and WebSocket clients once connected to ``localhost`` while the server listened
on 127.0.0.1 only, on an ephemeral port. ``localhost`` also resolves to ``::1``, tried
first, where nothing listened: about once per ephemeral port range the kernel picked the
server's port number as the source port and the socket connected to itself (TCP
simultaneous open), so the TLS handshake read its own ClientHello and failed with
``[SSL: UNEXPECTED_MESSAGE]`` (1 in about 20,000 requests).
"""

from __future__ import annotations

import ast
from ipaddress import IPv4Address
from pathlib import Path

from pyfect.net.net_address import InetAddressV4

from ._http import base_url

_SOAK = Path(__file__).parent


def test_the_base_url_is_the_listening_address() -> None:
    assert base_url(InetAddressV4(IPv4Address("127.0.0.1"), 4433)) == "https://127.0.0.1:4433"


def test_no_soak_client_connects_by_host_name() -> None:
    """``localhost`` only names the certificate (``_tls.py``)."""
    found = [
        f"{path.name}:{node.lineno}"
        for path in sorted(_SOAK.glob("*.py"))
        if path.name != "_tls.py" and not path.name.startswith("test_")
        for node in ast.walk(ast.parse(path.read_text()))
        if (
            isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and "localhost" in node.value
        )
        or (
            isinstance(node, ast.JoinedStr)
            and any(
                isinstance(part, ast.Constant) and "localhost" in str(part.value)
                for part in node.values
            )
        )
    ]
    assert found == []
