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
    """trims cookie pairs and ignores invalid cookie names"""
    cookies = c.from_set_cookie(["bad name=value", "session\t=\tabc", "encoded = %20abc%20"])
    assert cookies.get("bad name") is None
    assert cookies.get_value("session") == "abc"
    assert cookies.get_value("encoded") == " abc "


def test_ignores_invalid_max_age() -> None:
    """ignores invalid Max-Age attributes"""
    cookies = c.from_set_cookie(
        ["session=abc; Max-Age=0oops", "theme=dark; Max-Age=60; Max-Age=1.5"]
    )
    assert cookies.to_set_cookie_headers() == ["session=abc", "theme=dark; Max-Age=60"]


def test_parse_header_unquotes_padded_values() -> None:
    """unquotes values surrounded by whitespace"""
    assert c.parse_header('a="1" ; b= "2"') == {"a": "1", "b": "2"}


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


@pytest.mark.parametrize(
    ("header", "expires"),
    [
        ("a=1; Expires=Wed, 21-Oct-2015 07:28:00 GMT", datetime(2015, 10, 21, 7, 28, tzinfo=UTC)),
        ("a=1; Expires=Oct 21 2015", datetime(2015, 10, 21, 4, tzinfo=UTC)),
        ("a=1; Expires=10/21/2015 7:28 PM EST", datetime(2015, 10, 22, 0, 28, tzinfo=UTC)),
        ("a=1; Expires=nonsense", None),
    ],
)
def test_expires_is_read_as_javascript_s_date_reads_it(
    header: str, expires: datetime | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Not an Effect title: ``fromSetCookie`` reads ``Expires`` with
    ``new Date(value)``, V8's legacy forms included, local time where no
    zone is named (Effect under Node with ``TZ=America/New_York``)."""
    monkeypatch.setenv("TZ", "America/New_York")
    cookie = c.from_set_cookie(header).get("a")
    assert cookie is not None
    found = None if cookie.options is None else cookie.options.expires
    assert found == expires


# scoped storage: ``merge_into_array`` / ``to_request_cookie_header``

_NOW = 1_792_454_400_000.0  # Date.parse("2026-10-20T00:00:00Z")


def _merge(jar: tuple[c.Cookie, ...], url: str, set_cookie: str) -> tuple[c.Cookie, ...]:
    return c.merge_into_array(jar, url, c.from_set_cookie(set_cookie), _NOW)


def _header(jar: tuple[c.Cookie, ...], url: str) -> str | None:
    return c.to_request_cookie_header(jar, url, _NOW)


def test_isolates_host_only_cookies() -> None:
    """isolates host-only cookies without overwriting another host's session"""
    api = _merge((), "https://api.example.com/account", "session=secret")
    assert _header(api, "https://evil.example/hook") is None
    both = _merge(api, "https://evil.example/hook", "session=attacker")
    assert _header(both, "https://api.example.com/account") == "session=secret"
    assert _header(both, "https://evil.example/hook") == "session=attacker"
    assert _header(both, "https://sub.api.example.com/account") is None


def test_domain_cookies() -> None:
    """accepts matching Domain cookies but rejects foreign, single-label and IP domains"""
    jar = _merge((), "https://www.example.com/", "session=secret; Domain=example.com; Path=/")
    assert _header(jar, "https://api.example.com/") == "session=secret"
    assert _header(jar, "https://example.com/") == "session=secret"
    assert _header(jar, "https://notexample.com/") is None
    for url, domain in [
        ("https://evil.example/", "bank.example"),
        ("https://notexample.com/", "example.com"),
        ("https://www.example.com/", "com"),
        ("http://127.0.0.1/", "127.0.0.1"),
    ]:
        rejected = _merge((), url, f"session=secret; Domain={domain}")
        assert _header(rejected, url) is None
        assert _header(rejected, "https://bank.example/") is None


def test_normalizes_seeded_domains() -> None:
    """normalizes leading dots and case in seeded cookie domains"""
    seeded = (c.make_cookie_unsafe("session", "secret", domain=".EXAMPLE.com", path="/"),)
    merged = c.merge_into_array((), "https://api.example.com/", c.from_iterable(seeded), _NOW)
    for jar in (seeded, merged):
        assert [
            _header(jar, "https://example.com/"),
            _header(jar, "https://www.example.com/"),
            _header(jar, "https://notexample.com/"),
        ] == ["session=secret", "session=secret", None]


def test_default_path_and_segment_boundaries() -> None:
    """uses the response's default path and matches explicit paths on segment boundaries"""
    for cookie in ("session=secret", "session=secret; Path=/account"):
        jar = _merge((), "https://api.example.com/account/settings", cookie)
        assert _header(jar, "https://api.example.com/account") == "session=secret"
        assert _header(jar, "https://api.example.com/account/other") == "session=secret"
        assert _header(jar, "https://api.example.com/") is None
        assert _header(jar, "https://api.example.com/account2") is None


def test_host_only_replaces_domain_cookie() -> None:
    """replaces a Domain cookie with a host-only cookie of the same name and path"""
    domain = _merge((), "https://example.com/", "session=domain; Domain=example.com; Path=/")
    assert _header(domain, "https://sub.example.com/") == "session=domain"
    replaced = _merge(domain, "https://example.com/", "session=host; Path=/")
    assert _header(replaced, "https://example.com/") == "session=host"
    assert _header(replaced, "https://sub.example.com/") is None
    assert c.serialize_cookie(replaced[0]) == "session=host; Path=/"


def test_same_name_longest_path_first() -> None:
    """serializes same-name cookies longest path first"""
    root = _merge((), "https://example.com/", "session=root; Path=/")
    jar = _merge(root, "https://example.com/account", "session=account; Path=/account")
    assert _header(jar, "https://example.com/account/settings") == "session=account; session=root"


def test_secure_only_over_https() -> None:
    """sends Secure cookies only over HTTPS"""
    jar = _merge((), "https://api.example.com/", "session=secret; Secure")
    assert _header(jar, "https://api.example.com/") == "session=secret"
    assert _header(jar, "http://api.example.com/") is None


def test_max_age_zero_deletes() -> None:
    """deletes cookies with Max-Age=0 and does not send expired cookies"""
    stored = _merge((), "https://api.example.com/", "session=secret; Path=/")
    assert _header(stored, "https://api.example.com/") == "session=secret"
    removed = _merge(stored, "https://api.example.com/", "session=; Path=/; Max-Age=0")
    expired = _merge(
        (), "https://api.example.com/", "session=secret; Expires=Mon, 01 Jan 2024 00:00:00 GMT"
    )
    assert removed == ()
    assert _header(removed, "https://api.example.com/") is None
    assert _header(expired, "https://api.example.com/") is None


def test_storage_edges_checked_under_node() -> None:
    """Not an Effect title: 4.1.2's edges, each checked under Node. ``Max-Age``
    is an optional ``-`` and digits (``+5`` is ignored, ``-0`` is ``0``); a
    quoted header value is trimmed inside its quotes; a seeded cookie whose
    domain is the tail of an IPv4 address does not reach that address; a
    cookie without a domain is never sent; a ``Max-Age`` past JavaScript's
    ``Date`` range is never sent (Effect keeps it in the array with an
    invalid ``Date``; here it removes the stored cookie instead)."""
    parsed = c.from_set_cookie(["a=1; Max-Age=+5", "b=2; Max-Age=-0", "c=3; Max-Age= 7 "])
    assert parsed.to_set_cookie_headers() == ["a=1", "b=2; Max-Age=0", "c=3; Max-Age=7"]
    assert c.parse_header('a=" 1 "; b="2') == {"a": "1", "b": ""}
    seeded = (c.make_cookie_unsafe("s", "x", domain="0.1"),)
    assert c.to_request_cookie_header(seeded, "http://10.0.0.1/", 0) is None
    assert (
        c.to_request_cookie_header((c.make_cookie_unsafe("s", "x"),), "http://a.test/", 0) is None
    )
    far = c.from_set_cookie("t=1; Max-Age=99999999999999999999")
    jar = c.merge_into_array((), "https://a.test/x", far, 0)
    assert c.to_request_cookie_header(jar, "https://a.test/", 0) is None
