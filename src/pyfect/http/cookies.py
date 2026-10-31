"""Cookies (Effect's ``Cookies``): what a response's ``Set-Cookie`` headers
set, and what a ``Cookie`` request header sends.

A ``Cookies`` maps names to ``Cookie`` values and is immutable. Cookie
options are keyword arguments (``CookieOptionsInput``)::

    cookies = empty.set_unsafe("session", "abc", path="/", http_only=True)
    cookies.to_set_cookie_headers()   # ["session=abc; Path=/; HttpOnly"]
"""

from __future__ import annotations

import math
import re
import sys
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass, fields
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from typing import Literal, TypedDict, Unpack, final
from urllib.parse import quote, unquote

from pyfect import _js_date as js_date
from pyfect._digits import parse_signed_digits
from pyfect._js import text_encode
from pyfect.duration import Duration, to_seconds
from pyfect.errors import TaggedError
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
_LEADING_INT = re.compile(r"\s*([+-]?\d+)")
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
    if options.domain is not None:
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


def _parse_date(value: str) -> datetime | None:
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return js_date.parse(value)
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


def _parse_set_cookie(header: str) -> Cookie | None:  # noqa: PLR0912
    parts = [p.strip() for p in header.split(";") if p.strip()]
    if not parts:
        return None
    name, equal, value_encoded = parts[0].partition("=")
    if not equal or not _NAME.fullmatch(name):
        return None
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
                date = _parse_date(attribute)
                if date is not None:
                    options["expires"] = date
            case "max-age" if attribute is not None:
                found = _LEADING_INT.match(attribute)
                seconds = None if found is None else parse_signed_digits(found[1])
                # Past what a float holds the attribute is ignored.
                if seconds is not None and abs(seconds) <= _MAX_SECONDS:
                    options["max_age"] = float(seconds)
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
        return self.set(name, "", **{**options, "max_age": 0.0, "expires": _EPOCH})

    def expire_cookie_unsafe(self, name: str, **options: Unpack[CookieOptionsInput]) -> Cookies:
        return self.set_unsafe(name, "", **{**options, "max_age": 0.0, "expires": _EPOCH})

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
            raw = header[eq + 1 : end]
            val = raw[1:-1].strip() if raw.startswith('"') else raw.strip()
            result[key] = _decode_component(val) if "%" in val else val
        pos = end + 1
    return result


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
    "parse_header",
    "serialize_cookie",
]
