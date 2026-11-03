"""Ports of Effect's ``http/Cookies.test.ts``.

Each test's docstring is the Effect test title. Cookie options are keyword
arguments; ``get`` / ``get_value`` give ``None`` for a missing cookie; the
cookie operations are ``Cookies`` methods.

Omitted, with the reason:

- ``serializerIso annotation``: it reads through ``Schema.toIso``, which
  is not ported (docs/PARITY.md section 4). The cookie schemas are
  ``pyfect.http.schema``.
- ``identifies cookies errors``: ``isinstance(e, CookiesError)`` is the
  guard; a plain object with a ``_tag`` cannot pass for one.
"""

from datetime import UTC, datetime

import pytest

from pyfect import schema as S
from pyfect.http import cookies as c
from pyfect.http import schema as HS
from pyfect.result import Err, Ok


def test_rejects_delimiters() -> None:
    """rejects cookie attribute delimiters in names, domains, and paths"""
    assert c.make_cookie("a; Domain=evil.com; b", "token") == Err(
        c.CookiesError.from_reason("InvalidCookieName")
    )
    assert c.make_cookie("session", "token", domain="legit.com; Domain=.parent.tld") == Err(
        c.CookiesError.from_reason("InvalidCookieDomain")
    )
    assert c.make_cookie("session", "token", path="/; HttpOnly") == Err(
        c.CookiesError.from_reason("InvalidCookiePath")
    )


def test_accepts_tokens() -> None:
    """accepts RFC 6265 token names and legitimate domains and paths"""
    for domain in ("sub.example.com", ".sub.example.com"):
        cookie = c.make_cookie_unsafe(
            "!#$%&'*+-.^_`|~", "token", domain=domain, path="/some-path_with~chars/%20"
        )
        assert c.serialize_cookie(cookie) == (
            f"!#$%&'*+-.^_`|~=token; Domain={domain}; Path=/some-path_with~chars/%20"
        )


def test_from_set_cookie_ignores_invalid_names() -> None:
    """ignores invalid cookie names"""
    cookies = c.from_set_cookie(["bad name=value", "session=abc"])
    assert cookies.get("bad name") is None
    assert cookies.get_value("session") == "abc"


_INVALID = c.Cookie(
    "session", "token", "token", c.CookieOptions(domain="legit.com; Domain=.evil.com")
)


def test_rejects_from_iterable() -> None:
    """rejects invalid cookies supplied through fromIterable"""
    with pytest.raises(c.CookiesError, match="InvalidCookieDomain"):
        c.from_iterable([_INVALID]).to_set_cookie_headers()


def test_rejects_set_cookie() -> None:
    """rejects invalid cookies supplied through setCookie"""
    with pytest.raises(c.CookiesError, match="InvalidCookieDomain"):
        c.EMPTY.set_cookie(_INVALID).to_set_cookie_headers()


_EXPIRED = c.from_record(
    {
        "session": c.make_cookie_unsafe(
            "session",
            "",
            path="/",
            secure=True,
            max_age=0,
            expires=datetime(1970, 1, 1, tzinfo=UTC),
        )
    }
)


def test_expire_cookie() -> None:
    """expireCookie returns a Result with an expired Set-Cookie value"""
    assert c.EMPTY.expire_cookie("session", path="/", secure=True) == Ok(_EXPIRED)
    assert _EXPIRED.to_set_cookie_headers() == [
        "session=; Max-Age=0; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT; Secure"
    ]


def test_expire_cookie_unsafe() -> None:
    """expireCookieUnsafe adds an expired Set-Cookie value"""
    assert c.EMPTY.expire_cookie_unsafe("session", path="/", secure=True) == _EXPIRED


def test_get_and_get_value() -> None:
    """get and getValue return Option"""
    cookies = c.from_set_cookie("session=abc; Path=/")
    assert cookies.get("session") is not None
    assert cookies.get_value("session") == "abc"
    assert cookies.get("missing") is None
    assert cookies.get_value("missing") is None
    assert c.EMPTY.get("constructor") is None


def test_schema_cookies_to_codec_json() -> None:
    """Schema.Cookies / toCodecJson"""
    cookies = c.from_set_cookie(
        [
            "sessionId=abc123; Path=/; HttpOnly; Secure",
            "theme=dark; Path=/; Max-Age=3600",
            "language=en; Domain=.example.com; SameSite=Lax",
        ]
    )
    encoded = S.encode_sync(S.to_codec_json(S.to_type(HS.Cookies)))(cookies)
    assert encoded == (
        "sessionId=abc123; Path=/; HttpOnly; Secure",
        "theme=dark; Max-Age=3600; Path=/",
        "language=en; Domain=example.com; SameSite=Lax",
    )


def test_record_from_cookies_converts_cookies_to_decoded_string_values() -> None:
    """RecordFromCookies converts cookies to decoded string values"""
    cookies = c.from_set_cookie(["session=abc", "theme=dark"])
    assert S.decode_sync(HS.RecordFromCookies)(cookies) == {"session": "abc", "theme": "dark"}
    encoded = S.encode_sync(HS.RecordFromCookies)({"session": "abc", "theme": "dark"})
    assert encoded.to_set_cookie_headers() == ["session=abc", "theme=dark"]
