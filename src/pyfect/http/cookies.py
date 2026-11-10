"""Cookies (Effect's ``Cookies``): what a response's ``Set-Cookie`` headers
set, and what a ``Cookie`` request header sends.

A ``Cookies`` maps names to ``Cookie`` values and is immutable. Cookie
options are keyword arguments (``CookieOptionsInput``)::

    cookies = empty.set_unsafe("session", "abc", path="/", http_only=True)
    cookies.to_set_cookie_headers()   # ["session=abc; Path=/; HttpOnly"]

For client-side storage, ``merge_into_array`` and
``to_request_cookie_header`` work on a tuple of cookies scoped by domain,
path and scheme, following RFC 6265.
"""

from __future__ import annotations

import dataclasses
import math
import re
import sys
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, fields
from datetime import UTC, datetime, timedelta
from typing import Literal, TypedDict, Unpack, final
from urllib.parse import quote, unquote

from pyfect import _js_date as js_date
from pyfect._digits import parse_signed_digits
from pyfect._js import text_encode
from pyfect.date_time._epoch import to_epoch_millis
from pyfect.duration import ZERO, Duration, Seconds, to_seconds
from pyfect.errors import TaggedError
from pyfect.http import url as _url
from pyfect.http.headers import format_http_date
from pyfect.result import Err, Ok, Result

type Priority = Literal["low", "medium", "high"]
type SameSite = Literal["lax", "strict", "none"]


class CookieOptionsInput(TypedDict, total=False):
    """The attributes a cookie may carry, as keyword arguments."""

    domain: str
    expires: datetime
    max_age: Duration
    path: str
    priority: Priority
    http_only: bool
    secure: bool
    partitioned: bool
    same_site: SameSite
    host_only: bool


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class CookieOptions:
    domain: str | None = None
    expires: datetime | None = None
    max_age: Duration | None = None
    path: str | None = None
    priority: Priority | None = None
    http_only: bool | None = None
    secure: bool | None = None
    partitioned: bool | None = None
    same_site: SameSite | None = None
    # A stored client cookie sent only to the exact ``domain``; never serialized.
    host_only: bool | None = None

    def to_json(self) -> dict[str, object]:
        return {
            f.name: getattr(self, f.name) for f in fields(self) if getattr(self, f.name) is not None
        }


@final
@dataclass(frozen=True, slots=True)
class Cookie:
    """One cookie: its name, value, the value as sent, and its options."""

    name: str
    value: str
    value_encoded: str
    options: CookieOptions | None = None

    def to_json(self) -> dict[str, object]:
        options = None if self.options is None else self.options.to_json()
        return {
            "_id": "effect/Cookies/Cookie",
            "name": self.name,
            "value": self.value,
            "options": options,
        }


type CookiesErrorTag = Literal[
    "InvalidCookieName",
    "InvalidCookieValue",
    "InvalidCookieDomain",
    "InvalidCookiePath",
    "CookieInfinityMaxAge",
]


@dataclass(frozen=True, slots=True)
class CookiesErrorReason:
    tag: CookiesErrorTag
    cause: object = None


@dataclass(eq=False)
class CookiesError(TaggedError):
    """A cookie with an invalid name, value, domain, path or max age."""

    reason: CookiesErrorReason

    @staticmethod
    def from_reason(tag: CookiesErrorTag, cause: object = None) -> CookiesError:
        return CookiesError(CookiesErrorReason(tag, cause))

    @property
    def message(self) -> str:
        return self.reason.tag


_FIELD_CONTENT = re.compile(r"[\t\x20-\x7e\x80-\xff]+")
_NAME = re.compile(r"[!#$%&'*+\-.^_`|~0-9A-Za-z]+")
_DOMAIN = re.compile(r"[\t\x20-\x3a\x3c-\x7e\x80-\xff]+")
_PATH = re.compile(r"[\x20-\x3a\x3c-\x7e]+")
_COOKIE_WHITESPACE = re.compile(r"^[\t ]+|[\t ]+$")
_MAX_SECONDS = int(sys.float_info.max)
_BAD_ESCAPE = re.compile(r"%(?![0-9A-Fa-f]{2})")


def _encode_component(value: str) -> str:
    """``encodeURIComponent``."""
    return quote(text_encode(value), safe="!'()*")


def _decode_component(value: str) -> str:
    """``decodeURIComponent``, or ``value`` itself when it is malformed."""
    if "%" not in value:
        return value
    if _BAD_ESCAPE.search(value):
        return value
    try:
        return unquote(value, errors="strict")
    except UnicodeDecodeError:
        return value


def _validate(  # noqa: PLR0911
    name: str, encoded: str, options: CookieOptions | None
) -> CookiesError | None:
    if not _NAME.fullmatch(name):
        return CookiesError.from_reason("InvalidCookieName")
    if encoded and not _FIELD_CONTENT.fullmatch(encoded):
        return CookiesError.from_reason("InvalidCookieValue")
    if options is None:
        return None
    if options.domain is not None and not _DOMAIN.fullmatch(options.domain):
        return CookiesError.from_reason("InvalidCookieDomain")
    if options.path is not None and not _PATH.fullmatch(options.path):
        return CookiesError.from_reason("InvalidCookiePath")
    if options.max_age is not None and math.isinf(to_seconds(options.max_age)):
        return CookiesError.from_reason("CookieInfinityMaxAge")
    return None


def _options(options: CookieOptionsInput) -> CookieOptions | None:
    return CookieOptions(**options) if options else None


def make_cookie(
    name: str, value: str, **options: Unpack[CookieOptionsInput]
) -> Result[Cookie, CookiesError]:
    encoded = _encode_component(value)
    opts = _options(options)
    error = _validate(name, encoded, opts)
    if error is not None:
        return Err(error)
    return Ok(Cookie(name, value, encoded, opts))


def make_cookie_unsafe(name: str, value: str, **options: Unpack[CookieOptionsInput]) -> Cookie:
    """``make_cookie``, raising the ``CookiesError``."""
    match make_cookie(name, value, **options):
        case Ok(cookie):
            return cookie
        case Err(error):
            raise error


def serialize_cookie(cookie: Cookie) -> str:
    """The cookie as a ``Set-Cookie`` value; raises ``CookiesError`` for an
    invalid one."""
    error = _validate(cookie.name, cookie.value_encoded, cookie.options)
    if error is not None:
        raise error
    out = f"{cookie.name}={cookie.value_encoded}"
    options = cookie.options
    if options is None:
        return out
    if options.max_age is not None:
        out += f"; Max-Age={math.trunc(to_seconds(options.max_age))}"
    if options.domain is not None and not options.host_only:
        out += f"; Domain={options.domain}"
    if options.path is not None:
        out += f"; Path={options.path}"
    if options.priority is not None:
        out += f"; Priority={options.priority.capitalize()}"
    if options.expires is not None:
        out += f"; Expires={format_http_date(options.expires)}"
    if options.http_only:
        out += "; HttpOnly"
    if options.secure:
        out += "; Secure"
    if options.partitioned:
        out += "; Partitioned"
    if options.same_site is not None:
        out += f"; SameSite={options.same_site.capitalize()}"
    return out


def _parse_set_cookie(header: str) -> Cookie | None:  # noqa: PLR0912
    parts = [p.strip() for p in header.split(";") if p.strip()]
    if not parts:
        return None
    name, equal, value_encoded = parts[0].partition("=")
    name = _COOKIE_WHITESPACE.sub("", name)
    if not equal or not _NAME.fullmatch(name):
        return None
    value_encoded = _COOKIE_WHITESPACE.sub("", value_encoded)
    value = _decode_component(value_encoded)
    options: CookieOptionsInput = {}
    for part in parts[1:]:
        key, has_value, raw = part.partition("=")
        key, attribute = key.strip().lower(), raw.strip() if has_value else None
        match key:
            case "domain" if attribute is not None:
                domain = attribute.strip().removeprefix(".")
                if domain:
                    options["domain"] = domain
            case "expires" if attribute is not None:
                date = js_date.to_datetime(js_date.parse(attribute))
                if date is not None:
                    options["expires"] = date
            case "max-age" if attribute is not None:
                # RFC 6265 section 5.2.2: an optional "-", then digits.
                plus = attribute.startswith("+")
                seconds = None if plus else parse_signed_digits(attribute)
                # Past what a float holds the attribute is ignored.
                if seconds is not None and abs(seconds) <= _MAX_SECONDS:
                    options["max_age"] = Seconds(seconds)
            case "path" if attribute is not None and attribute.startswith("/"):
                options["path"] = attribute
            case "priority" if attribute is not None and attribute.lower() in (
                "low",
                "medium",
                "high",
            ):
                options["priority"] = attribute.lower()  # pyright: ignore[reportGeneralTypeIssues]
            case "httponly":
                options["http_only"] = True
            case "secure":
                options["secure"] = True
            case "partitioned":
                options["partitioned"] = True
            case "samesite" if attribute is not None and attribute.lower() in (
                "lax",
                "strict",
                "none",
            ):
                options["same_site"] = attribute.lower()  # pyright: ignore[reportGeneralTypeIssues]
            case _:
                pass
    return Cookie(name, value, value_encoded, _options(options))


@final
class Cookies:
    """Cookies by name. Updates give a new ``Cookies``."""

    __slots__ = ("cookies",)

    def __init__(self, cookies: Mapping[str, Cookie] | None = None) -> None:
        self.cookies: Mapping[str, Cookie] = dict(cookies or {})

    def __iter__(self) -> Iterator[Cookie]:
        return iter(self.cookies.values())

    def __len__(self) -> int:
        return len(self.cookies)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Cookies):
            return NotImplemented
        return dict(self.cookies) == dict(other.cookies)

    def __hash__(self) -> int:
        return hash(tuple(self.cookies.items()))

    def __repr__(self) -> str:
        return f"Cookies({list(self.cookies)!r})"

    def is_empty(self) -> bool:
        return not self.cookies

    def get(self, name: str) -> Cookie | None:
        return self.cookies.get(name)

    def get_value(self, name: str) -> str | None:
        cookie = self.cookies.get(name)
        return None if cookie is None else cookie.value

    def set_cookie(self, cookie: Cookie) -> Cookies:
        return Cookies({**self.cookies, cookie.name: cookie})

    def set_all_cookie(self, cookies: Iterable[Cookie]) -> Cookies:
        return Cookies({**self.cookies, **{c.name: c for c in cookies}})

    def merge(self, that: Cookies) -> Cookies:
        return Cookies({**self.cookies, **that.cookies})

    def remove(self, name: str) -> Cookies:
        return Cookies({k: v for k, v in self.cookies.items() if k != name})

    def set(
        self, name: str, value: str, **options: Unpack[CookieOptionsInput]
    ) -> Result[Cookies, CookiesError]:
        return make_cookie(name, value, **options).map(self.set_cookie)

    def set_unsafe(self, name: str, value: str, **options: Unpack[CookieOptionsInput]) -> Cookies:
        return self.set_cookie(make_cookie_unsafe(name, value, **options))

    def expire_cookie(
        self, name: str, **options: Unpack[CookieOptionsInput]
    ) -> Result[Cookies, CookiesError]:
        """Set ``name`` to an empty cookie that has already expired."""
        return self.set(name, "", **{**options, "max_age": ZERO, "expires": _EPOCH})

    def expire_cookie_unsafe(self, name: str, **options: Unpack[CookieOptionsInput]) -> Cookies:
        return self.set_unsafe(name, "", **{**options, "max_age": ZERO, "expires": _EPOCH})

    def set_all(
        self, cookies: Iterable[tuple[str, str] | tuple[str, str, CookieOptionsInput]]
    ) -> Result[Cookies, CookiesError]:
        """Set each ``(name, value[, options])``; the first invalid cookie's
        error stops it."""
        out = dict(self.cookies)
        for entry in cookies:
            options: CookieOptionsInput = entry[2] if len(entry) == 3 else {}
            match make_cookie(entry[0], entry[1], **options):
                case Ok(cookie):
                    out[cookie.name] = cookie
                case Err(error):
                    return Err(error)
        return Ok(Cookies(out))

    def set_all_unsafe(
        self, cookies: Iterable[tuple[str, str] | tuple[str, str, CookieOptionsInput]]
    ) -> Cookies:
        match self.set_all(cookies):
            case Ok(result):
                return result
            case Err(error):
                raise error

    def to_cookie_header(self) -> str:
        """The ``Cookie`` request header value."""
        return "; ".join(f"{c.name}={c.value_encoded}" for c in self.cookies.values())

    def to_record(self) -> dict[str, str]:
        return {c.name: c.value for c in self.cookies.values()}

    def to_set_cookie_headers(self) -> list[str]:
        return [serialize_cookie(c) for c in self.cookies.values()]

    def to_json(self) -> dict[str, object]:
        return {
            "_id": "effect/Cookies",
            "cookies": {k: c.to_json() for k, c in self.cookies.items()},
        }


_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)

EMPTY: Cookies = Cookies()


def from_record(cookies: Mapping[str, Cookie]) -> Cookies:
    return Cookies(cookies)


def from_iterable(cookies: Iterable[Cookie]) -> Cookies:
    return Cookies({c.name: c for c in cookies})


def from_set_cookie(headers: Iterable[str] | str) -> Cookies:
    """The cookies of ``Set-Cookie`` header values; invalid ones are skipped."""
    values = [headers] if isinstance(headers, str) else headers
    return from_iterable(c for c in (_parse_set_cookie(h.strip()) for h in values) if c is not None)


def parse_header(header: str) -> dict[str, str]:
    """A ``Cookie`` request header as names to decoded values; the first of
    a repeated name wins."""
    result: dict[str, str] = {}
    length, pos = len(header), 0
    while pos < length:
        end = header.find(";", pos)
        if end == -1:
            end = length
        eq = header.find("=", pos)
        if eq == -1:
            break
        if eq > end:
            pos = end + 1
            continue
        key = header[pos:eq].strip()
        if key not in result:
            val = header[eq + 1 : end].strip()
            if val.startswith('"'):
                val = val[1:-1].strip()
            result[key] = _decode_component(val) if "%" in val else val
        pos = end + 1
    return result


# Client storage (RFC 6265): a tuple of cookies, each scoped by domain and path.


def merge_into_array(
    jar: Sequence[Cookie], url: str, cookies: Cookies, now: float
) -> tuple[Cookie, ...]:
    """``jar`` with the cookies a response from ``url`` set, at ``now``
    (epoch milliseconds).

    A cookie without ``Domain`` is ``host_only`` for the host of ``url``; a
    ``Domain`` is accepted only when that host domain-matches it (never for
    an IP address or a single label such as ``com``; there is no public
    suffix list). Without ``Path`` the cookie takes the default path of
    ``url``. ``Max-Age`` wins over ``Expires``; both become an absolute
    ``expires``. A cookie replaces the one with the same name, domain and
    path in place; an expired one removes it. ``jar`` is returned unchanged
    when ``url`` is not an absolute URL."""
    parsed = _parse_url(url)
    if parsed is None:
        return tuple(jar)
    stored = list(jar)
    for cookie in cookies:
        scoped = _scope_cookie(parsed, cookie, now)
        if scoped is None:
            continue
        key = (scoped.name, _cookie_domain(scoped), _cookie_path(scoped))
        index = next(
            (
                i
                for i, held in enumerate(stored)
                if (held.name, _cookie_domain(held), _cookie_path(held)) == key
            ),
            None,
        )
        if _expired(scoped, now):
            if index is not None:
                del stored[index]
        elif index is None:
            stored.append(scoped)
        else:
            stored[index] = scoped
    return tuple(stored)


def to_request_cookie_header(jar: Sequence[Cookie], url: str, now: float) -> str | None:
    """The ``Cookie`` header value for a request to ``url`` at ``now``
    (epoch milliseconds): the unexpired cookies whose domain and path match
    ``url`` (``Secure`` ones only over https), same names included, longest
    path first; ``None`` when none match. A cookie without a ``domain`` is
    never sent; one without a ``path`` matches every path."""
    parsed = _parse_url(url)
    if parsed is None:
        return None
    host = parsed.hostname
    secure = parsed.protocol == "https:"

    def matches(cookie: Cookie) -> bool:
        domain = _cookie_domain(cookie)
        options = cookie.options or _NO_OPTIONS
        return (
            domain is not None
            and (host == domain if options.host_only else _domain_matches(host, domain))
            and _path_matches(parsed.pathname, _cookie_path(cookie))
            and not _expired(cookie, now)
            and (secure or not options.secure)
        )

    matching = sorted(
        (cookie for cookie in jar if matches(cookie)), key=lambda c: -len(_cookie_path(c))
    )
    if not matching:
        return None
    return "; ".join(f"{c.name}={c.value_encoded}" for c in matching)


_NO_OPTIONS = CookieOptions()
_IPV4 = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+")


def _parse_url(url: str) -> _url.Url | None:
    try:
        return _url.parse(url)
    except ValueError:
        return None


def _cookie_domain(cookie: Cookie) -> str | None:
    domain = None if cookie.options is None else cookie.options.domain
    return (domain or "").removeprefix(".").lower() or None


def _cookie_path(cookie: Cookie) -> str:
    path = None if cookie.options is None else cookie.options.path
    return path if path is not None and path.startswith("/") else "/"


def _expires_millis(expires: datetime) -> int:
    return to_epoch_millis(expires if expires.tzinfo else expires.replace(tzinfo=UTC))


def _expired(cookie: Cookie, now: float) -> bool:
    expires = None if cookie.options is None else cookie.options.expires
    return expires is not None and _expires_millis(expires) <= now


def _is_ip_address(host: str) -> bool:
    return host.startswith("[") or _IPV4.fullmatch(host) is not None


def _domain_matches(host: str, domain: str) -> bool:
    return host == domain or (host.endswith("." + domain) and not _is_ip_address(host))


def _path_matches(request_path: str, cookie_path: str) -> bool:
    return request_path == cookie_path or (
        request_path.startswith(cookie_path)
        and (
            cookie_path.endswith("/")
            or request_path[len(cookie_path) : len(cookie_path) + 1] == "/"
        )
    )


def _default_path(pathname: str) -> str:
    index = pathname.rfind("/")
    return "/" if index <= 0 else pathname[:index]


_MAX_DATE_MILLIS = 8_640_000_000_000_000
"""JavaScript's ``Date`` range; past it ``new Date(...)`` is invalid."""


def _expiry(now: float, max_age: Duration) -> datetime:
    """``now`` plus ``max_age`` as an ``expires``: clamped to what ``datetime``
    holds, and expired outright past JavaScript's ``Date`` range (Effect
    stores an invalid ``Date`` there, which is never sent)."""
    millis = now + to_seconds(max_age) * 1000
    if abs(millis) > _MAX_DATE_MILLIS:
        return _EPOCH
    try:
        return _EPOCH + timedelta(milliseconds=millis)
    except OverflowError:
        return datetime.max.replace(tzinfo=UTC) if millis > 0 else _EPOCH


def _scope_cookie(url: _url.Url, cookie: Cookie, now: float) -> Cookie | None:
    host = url.hostname
    domain, host_only = host, True
    attribute = _cookie_domain(cookie)
    if attribute is not None:
        if _is_ip_address(host) or not _domain_matches(host, attribute):
            return None
        if "." in attribute:
            domain, host_only = attribute, False
        elif attribute != host:
            # a single-label domain such as "com" is treated like a public suffix
            return None
    options = cookie.options or _NO_OPTIONS
    path = options.path
    return Cookie(
        cookie.name,
        cookie.value,
        cookie.value_encoded,
        dataclasses.replace(
            options,
            domain=domain,
            host_only=True if host_only else None,
            path=path if path is not None and path.startswith("/") else _default_path(url.pathname),
            expires=options.expires if options.max_age is None else _expiry(now, options.max_age),
            max_age=None,
        ),
    )


__all__ = [
    "EMPTY",
    "Cookie",
    "CookieOptions",
    "CookieOptionsInput",
    "Cookies",
    "CookiesError",
    "CookiesErrorReason",
    "CookiesErrorTag",
    "Priority",
    "SameSite",
    "from_iterable",
    "from_record",
    "from_set_cookie",
    "make_cookie",
    "make_cookie_unsafe",
    "merge_into_array",
    "parse_header",
    "serialize_cookie",
    "to_request_cookie_header",
]
