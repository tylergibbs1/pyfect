"""``Authority``: the one check of a client-sent host, and the guard that
servers build a request's absolute URL only from one."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from pyfect.http._authority import parse_authority, parse_origin_form

_SRC = Path(__file__).parent.parent / "src" / "pyfect" / "http"


@pytest.mark.parametrize(
    "text", ["a", "example.test", "example.test:8080", "[::1]", "[::1]:65535", "10.0.0.1:1"]
)
def test_an_authority_is_parsed(text: str) -> None:
    assert parse_authority(text) == text


@pytest.mark.parametrize(
    "text",
    [
        "",
        "x/admin",
        "x?q",
        "x#f",
        "u@x",
        "a, b",
        "x:port",
        "x:65536",
        "x:",
        "x\n",
        "[::1",
        "x y",
        "[1]",
    ],
)
def test_anything_else_is_not_an_authority(text: str) -> None:
    assert parse_authority(text) is None


# Where a ``scheme://{...}`` f-string does not take a client-sent host: the
# Authority module itself, URL parsing, and the server's own listen address.
_NOT_A_REQUEST_HOST = {"_authority.py", "url.py", "server.py"}


def test_servers_join_a_host_into_a_url_only_through_absolute_url() -> None:
    """A ``scheme://{host}`` f-string in a server-side module would join a
    host no ``Authority`` vouches for into a request's URL (the client,
    which builds URLs from its own configuration, is left out)."""
    joined = re.compile(r"""f["'][^"']*://\{""")
    offenders = [
        f"{path.relative_to(_SRC)}:{number}"
        for path in sorted(_SRC.rglob("*.py"))
        if path.relative_to(_SRC).parts[0] != "client"
        and str(path.relative_to(_SRC)) not in _NOT_A_REQUEST_HOST
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if joined.search(line)
    ]
    assert offenders == []


def test_the_host_header_is_read_only_through_parse_authority() -> None:
    """Every server-side read of the ``host`` header hands it to
    ``parse_authority`` in the same expression."""
    read = re.compile(r"""headers\.get\(["']host["']""")
    offenders = [
        f"{path.relative_to(_SRC)}:{number}"
        for path in sorted(_SRC.rglob("*.py"))
        if path.relative_to(_SRC).parts[0] != "client"
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if read.search(line) and "parse_authority(" not in line and "_authority(" not in line
    ]
    assert offenders == []


@pytest.mark.parametrize("text", ["/", "/a?b", "//x/admin"])
def test_an_origin_form_starts_with_a_slash(text: str) -> None:
    assert parse_origin_form(text) == text


@pytest.mark.parametrize("text", ["", "admin", "evil.test/admin", "http://evil/admin", "*"])
def test_anything_else_is_not_an_origin_form(text: str) -> None:
    assert parse_origin_form(text) is None


def test_authorities_and_origin_forms_are_made_only_by_their_parsers() -> None:
    """Calling the ``NewType`` directly would vouch for unchecked text."""
    made = re.compile(r"\b(?:Authority|OriginForm)\(")
    offenders = [
        f"{path.relative_to(_SRC.parent)}:{number}"
        for path in sorted(_SRC.parent.rglob("*.py"))
        if path.name != "_authority.py"
        for number, line in enumerate(path.read_text().splitlines(), 1)
        if made.search(line)
    ]
    assert offenders == []
