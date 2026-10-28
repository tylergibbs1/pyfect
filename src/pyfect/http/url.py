"""URLs (Effect's ``Url``): parsing and immutable updates.

A URL is a ``urllib.parse.SplitResult``, normalized as WHATWG's ``URL``
normalizes it: the scheme and host lowercased, an empty path of an
``http(s)`` / ``ws(s)`` / ``ftp`` URL written ``/``, a default port dropped,
dot segments resolved, and characters outside each part's allowed set
percent-encoded (existing ``%XX`` escapes are kept as written)::

    url = from_string("HTTPS://Example.com:443/a/../b c").unwrap()
    href(url)   # "https://example.com/b%20c"

The setters give a new URL; ``href`` writes one out.
"""

from __future__ import annotations

import ipaddress
import re
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import SplitResult, unquote_to_bytes

from pyfect._js import text_encode
from pyfect.errors import IllegalArgumentError, TaggedError
from pyfect.http import url_params as _params
from pyfect.redacted import Redacted
from pyfect.redacted import value as redacted_value
from pyfect.result import Err, Ok, Result

_SPECIAL_PORTS: dict[str, int | None] = {
    "http": 80,
    "https": 443,
    "ws": 80,
    "wss": 443,
    "ftp": 21,
    "file": None,
}

_C0 = frozenset(chr(i) for i in range(0x20))
_FRAGMENT = _C0 | frozenset(' "<>`')
_QUERY = _C0 | frozenset(' "#<>')
_SPECIAL_QUERY = _QUERY | frozenset("'")
_PATH = _QUERY | frozenset("?^`{}")
_USERINFO = _PATH | frozenset("/:;=@[\\]|")
_FORBIDDEN_HOST = _C0 | frozenset(" #/:<>?@[\\]^|\x7f")
_FORBIDDEN_DOMAIN = _FORBIDDEN_HOST | frozenset("%")
_SCHEME = re.compile(r"[A-Za-z][A-Za-z0-9+.\-]*:")
_DOT = frozenset((".", "%2e"))
_DOT_DOT = frozenset(("..", ".%2e", "%2e.", "%2e%2e"))
_DRIVE = re.compile(r"[A-Za-z]:")
_IPV4_DIGITS = {
    8: frozenset("01234567"),
    10: frozenset("0123456789"),
    16: frozenset("0123456789abcdefABCDEF"),
}


def _encode(text: str, keep_out: frozenset[str]) -> str:
    out: list[str] = []
    for ch in text:
        if ch in keep_out or ord(ch) > 0x7E:
            out.extend(f"%{b:02X}" for b in text_encode(ch))
        else:
            out.append(ch)
    return "".join(out)


def _split_rest(rest: str) -> tuple[str, str | None, str | None]:
    """``path?query#fragment`` into its parts (``None`` when absent)."""
    rest, hash_mark, fragment = rest.partition("#")
    path, question, query = rest.partition("?")
    return path, query if question else None, fragment if hash_mark else None


def _remove_dots(path: str, file: bool = False) -> str:
    """Resolve ``.`` and ``..`` segments; a ``file`` URL keeps a leading
    Windows drive letter (``/C:``)."""
    segments = path.split("/")[1:]
    out: list[str] = []
    for i, segment in enumerate(segments):
        last = i == len(segments) - 1
        lower = segment.lower()
        if lower in _DOT_DOT:
            if out and not (file and len(out) == 1 and _DRIVE.fullmatch(out[0])):
                out.pop()
            if last:
                out.append("")
        elif lower in _DOT:
            if last:
                out.append("")
        else:
            out.append(segment)
    return "/" + "/".join(out)


def _host(raw: str, special: bool) -> str:
    if raw.startswith("["):
        if not raw.endswith("]"):
            raise ValueError("Invalid IPv6 address")
        return f"[{_ipv6(raw[1:-1])}]"
    if not special:
        if any(ch in _FORBIDDEN_HOST for ch in raw):
            raise ValueError("Invalid host")
        return _encode(raw, _C0)
    domain = unquote_to_bytes(raw).decode("utf-8", "replace")
    if not domain.isascii():
        domain = domain.encode("idna").decode("ascii")
    domain = domain.lower()
    if not domain or any(ch in _FORBIDDEN_DOMAIN for ch in domain):
        raise ValueError("Invalid host")
    return _ipv4(domain) if _ends_in_number(domain) else domain


def _ipv6(text: str) -> str:
    """WHATWG's IPv6 serialization: hexadecimal pieces, the first longest
    run of two or more zero pieces written ``::`` (never dotted IPv4)."""
    if "%" in text:
        raise ValueError("Invalid IPv6 address")
    address = int(ipaddress.IPv6Address(text))
    pieces = [(address >> (112 - 16 * i)) & 0xFFFF for i in range(8)]
    start, length = -1, 1
    for i in range(8):
        run = next((j for j in range(i, 8) if pieces[j]), 8) - i
        if run > length:
            start, length = i, run
    if start == -1:
        return ":".join(f"{piece:x}" for piece in pieces)
    head = ":".join(f"{piece:x}" for piece in pieces[:start])
    tail = ":".join(f"{piece:x}" for piece in pieces[start + length :])
    return f"{head}::{tail}"


def _ipv4_number(part: str) -> int | None:
    """A part of an IPv4 address: decimal, ``0x`` hexadecimal or ``0``
    octal; ``None`` when it is none of them."""
    digits, radix = part, 10
    if part[:2].lower() == "0x":
        digits, radix = part[2:], 16
        if not digits:
            return 0
    elif len(part) > 1 and part.startswith("0"):
        digits, radix = part[1:], 8
    if not digits or any(ch not in _IPV4_DIGITS[radix] for ch in digits):
        return None
    return int(digits, radix)


def _ends_in_number(domain: str) -> bool:
    parts = domain.split(".")
    if parts[-1] == "" and len(parts) > 1:
        parts.pop()
    last = parts[-1]
    return last != "" and ((last.isascii() and last.isdigit()) or _ipv4_number(last) is not None)


def _ipv4(domain: str) -> str:
    """WHATWG's IPv4 parser: ``127.1`` and ``0x7f.0.0.1`` are
    ``127.0.0.1``."""
    parts = domain.split(".")
    if parts[-1] == "" and len(parts) > 1:
        parts.pop()
    numbers = [_ipv4_number(part) if part else None for part in parts]
    if len(parts) > 4 or None in numbers:
        raise ValueError("Invalid IPv4 address")
    *head, last = (n for n in numbers if n is not None)
    if any(n > 255 for n in head) or last >= 256 ** (5 - len(numbers)):
        raise ValueError("Invalid IPv4 address")
    address = last + sum(n * 256 ** (3 - i) for i, n in enumerate(head))
    return str(ipaddress.IPv4Address(address))


def _authority(scheme: str, authority: str) -> str:
    special = scheme in _SPECIAL_PORTS
    userinfo, at, host_port = authority.rpartition("@")
    if host_port.startswith("["):
        end = host_port.find("]")
        if end == -1:
            raise ValueError("Invalid IPv6 address")
        raw_host, port = host_port[: end + 1], host_port[end + 1 :]
        if port and not port.startswith(":"):
            raise ValueError("Invalid port")
        port = port[1:]
    else:
        raw_host, _, port = host_port.partition(":")
    if not raw_host:
        if special and scheme != "file":
            raise ValueError("Missing host")
        if at or port:
            raise ValueError("Invalid host")
        return ""
    host = _host(raw_host, special)
    if scheme == "file" and host == "localhost":
        host = ""
    if port:
        if not port.isdigit() or not port.isascii() or int(port) > 65535:
            raise ValueError("Invalid port")
        port = "" if int(port) == _SPECIAL_PORTS.get(scheme, -1) else str(int(port))
    credentials = ""
    if at:
        username, colon, password = userinfo.partition(":")
        username, password = _encode(username, _USERINFO), _encode(password, _USERINFO)
        if username or (colon and password):
            credentials = username + (f":{password}" if password else "") + "@"
    return credentials + host + (f":{port}" if port else "")


def _resolve(base: SplitResult, reference: str) -> str:  # noqa: PLR0911
    """RFC 3986 §5.2 resolution of a reference without a scheme."""
    scheme = base.scheme
    prefix = (
        f"{scheme}://{base.netloc}" if base.netloc or scheme in _SPECIAL_PORTS else f"{scheme}:"
    )
    if reference.startswith("//"):
        return f"{scheme}:{reference}"
    if not base.path.startswith("/") and scheme not in _SPECIAL_PORTS:
        if reference.startswith("#"):
            return href(base._replace(fragment="")).split("#")[0] + reference
        raise ValueError("Cannot resolve against an opaque URL")
    if reference.startswith("/"):
        return prefix + reference
    without_fragment = prefix + base.path + (f"?{base.query}" if base.query else "")
    if reference == "":
        return without_fragment
    if reference.startswith("#"):
        return without_fragment + reference
    if reference.startswith("?"):
        return prefix + base.path + reference
    directory = base.path[: base.path.rfind("/") + 1] or "/"
    return prefix + directory + reference


def parse(text: str, base: str | SplitResult | None = None) -> SplitResult:
    """``text`` as an absolute URL, resolved against ``base`` when it has no
    scheme; raises ``ValueError`` when it is not a valid URL."""
    text = re.sub(r"[\t\n\r]", "", text.strip("".join(_C0) + " "))
    if _SCHEME.match(text) is None:
        if base is None:
            raise ValueError(f"Invalid URL: {text!r}")
        base_url = parse(base) if isinstance(base, str) else base
        if base_url.scheme in _SPECIAL_PORTS:
            text = _backslashes(text)
        text = _resolve(base_url, text)
    scheme, _, rest = text.partition(":")
    scheme = scheme.lower()
    special = scheme in _SPECIAL_PORTS
    if scheme == "file":
        rest = _backslashes(rest)
        rest = rest if rest.startswith("//") else "///" + rest.lstrip("/")
    elif special:
        rest = "//" + _backslashes(rest).lstrip("/")
    if rest.startswith("//"):
        end = re.search(r"[/?#]", rest[2:])
        authority = rest[2:] if end is None else rest[2 : 2 + end.start()]
        netloc = _authority(scheme, authority)
        path, query, fragment = _split_rest(rest[2 + len(authority) :])
        path = _remove_dots(path or "/", scheme == "file") if path or special else path
        path = _encode(path, _PATH)
    else:
        netloc = ""
        path, query, fragment = _split_rest(rest)
        path = _encode(_remove_dots(path), _PATH) if path.startswith("/") else _encode(path, _C0)
    return SplitResult(
        scheme,
        netloc,
        path,
        "" if query is None else _encode(query, _SPECIAL_QUERY if special else _QUERY),
        "" if fragment is None else _encode(fragment, _FRAGMENT),
    )


def _backslashes(text: str) -> str:
    """A special URL reads ``\\`` as ``/`` before its query and fragment."""
    end = re.search(r"[?#]", text)
    head = text if end is None else text[: end.start()]
    return head.replace("\\", "/") + text[len(head) :]


def href(url: SplitResult) -> str:
    """The URL written out."""
    authority = f"//{url.netloc}" if url.netloc or url.scheme in _SPECIAL_PORTS else ""
    query = f"?{url.query}" if url.query else ""
    fragment = f"#{url.fragment}" if url.fragment else ""
    return f"{url.scheme}:{authority}{url.path}{query}{fragment}"


def origin(url: SplitResult) -> str:
    """``scheme://host[:port]`` for the special schemes but ``file``; else
    ``"null"``."""
    if url.scheme not in _SPECIAL_PORTS or url.scheme == "file":
        return "null"
    return f"{url.scheme}://{url.netloc.rpartition('@')[2]}"


@dataclass(eq=False)
class UrlError(TaggedError):
    """A request's URL could not be built."""

    cause: object


def make(url: str, params: _params.UrlParams, hash: str | None) -> Result[SplitResult, UrlError]:
    """``url`` with ``params`` appended to its query (rewritten as
    ``URLSearchParams`` writes it when there are any) and ``hash`` as its
    fragment."""
    try:
        parsed = parse(url)
    except ValueError as cause:
        return Err(UrlError(cause))
    if params.params:
        query = _params.parse(parsed.query).append_all(params)
        parsed = parsed._replace(query=_params.to_string(query))
    if hash is not None:
        parsed = parsed._replace(fragment=_encode(hash.removeprefix("#"), _FRAGMENT))
    return Ok(parsed)


def from_string(
    url: str, base: str | SplitResult | None = None
) -> Result[SplitResult, IllegalArgumentError]:
    try:
        return Ok(parse(url, base))
    except ValueError:
        suffix = (
            "" if base is None else f' with base "{base if isinstance(base, str) else href(base)}"'
        )
        return Err(IllegalArgumentError(f'Invalid URL: "{url}"{suffix}'))


def _reparse(url: SplitResult, **parts: str) -> SplitResult:
    return parse(href(url._replace(**parts)))


def set_hash(url: SplitResult, hash: str) -> SplitResult:
    return url._replace(fragment=_encode(hash.removeprefix("#"), _FRAGMENT))


def set_host(url: SplitResult, host: str) -> SplitResult:
    credentials = url.netloc.rpartition("@")[0]
    return _reparse(url, netloc=f"{credentials}@{host}" if credentials else host)


def set_hostname(url: SplitResult, hostname: str) -> SplitResult:
    port = f":{url.port}" if url.port is not None else ""
    return set_host(url, hostname + port)


def set_href(url: SplitResult, href: str) -> SplitResult:
    return parse(href)


def _set_userinfo(url: SplitResult, username: str, password: str) -> SplitResult:
    host = url.netloc.rpartition("@")[2]
    username, password = _encode(username, _USERINFO), _encode(password, _USERINFO)
    credentials = username + (f":{password}" if password else "")
    return _reparse(url, netloc=f"{credentials}@{host}" if credentials else host)


def set_password(url: SplitResult, password: str | Redacted[str]) -> SplitResult:
    plain = password if isinstance(password, str) else redacted_value(password)
    return _set_userinfo(url, url.username or "", plain)


def set_username(url: SplitResult, username: str) -> SplitResult:
    return _set_userinfo(url, username, url.password or "")


def set_pathname(url: SplitResult, pathname: str) -> SplitResult:
    special = url.scheme in _SPECIAL_PORTS
    path = pathname if pathname.startswith("/") or not special else f"/{pathname}"
    return url._replace(path=_encode(_remove_dots(path), _PATH) if path.startswith("/") else path)


def set_port(url: SplitResult, port: str | int) -> SplitResult:
    host = url.netloc.rpartition("@")[2]
    hostname = host[: host.rfind("]") + 1] if host.startswith("[") else host.partition(":")[0]
    credentials = url.netloc.rpartition("@")[0]
    netloc = f"{hostname}:{port}" if str(port) else hostname
    return _reparse(url, netloc=f"{credentials}@{netloc}" if credentials else netloc)


def set_protocol(url: SplitResult, protocol: str) -> SplitResult:
    """A new scheme; switching between a special scheme (``http``, ...) and
    another is ignored, as ``URL`` ignores it."""
    scheme = protocol.removesuffix(":").lower()
    if (scheme in _SPECIAL_PORTS) != (url.scheme in _SPECIAL_PORTS) or not _SCHEME.fullmatch(
        f"{scheme}:"
    ):
        return url
    return _reparse(url, scheme=scheme)


def set_search(url: SplitResult, search: str) -> SplitResult:
    query_set = _SPECIAL_QUERY if url.scheme in _SPECIAL_PORTS else _QUERY
    return url._replace(query=_encode(search.removeprefix("?"), query_set))


def url_params(url: SplitResult) -> _params.UrlParams:
    return _params.parse(url.query)


def set_url_params(url: SplitResult, input: _params.Input) -> SplitResult:
    return url._replace(query=_params.to_string(input))


def modify_url_params(
    url: SplitResult, f: Callable[[_params.UrlParams], _params.Input]
) -> SplitResult:
    return url._replace(query=_params.to_string(f(url_params(url))))


__all__ = [
    "UrlError",
    "from_string",
    "href",
    "make",
    "modify_url_params",
    "origin",
    "parse",
    "set_hash",
    "set_host",
    "set_hostname",
    "set_href",
    "set_password",
    "set_pathname",
    "set_port",
    "set_protocol",
    "set_search",
    "set_url_params",
    "set_username",
    "url_params",
]
