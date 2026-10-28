"""Ports of Effect's ``http/Url.test.ts``.

Each test's docstring is the Effect test title. A URL is an immutable
``SplitResult``; ``href`` writes it out.

Omitted, with the reason:

- ``mutate``: a ``SplitResult`` cannot be mutated; a function from URL to
  URL is just a call.
- ``accepts absolute URLs in opaque-origin documents``: there is no
  browser ``location`` to stub; ``make`` never reads one.
"""

from urllib.parse import SplitResult

from pyfect.errors import IllegalArgumentError
from pyfect.http import url as u
from pyfect.http import url_params as up
from pyfect.redacted import Redacted
from pyfect.result import Err, Ok

TEST_URL = u.parse("https://example.com/test")


def _expect(updated: SplitResult, expected: str) -> None:
    assert updated != TEST_URL
    assert u.href(updated) == expected


def test_make_appends() -> None:
    """appends query parameters and hash"""
    made = u.make(
        "https://example.com/test?existing=true",
        up.from_input([("foo", "bar"), ("foo", "baz")]),
        "section",
    )
    assert made == Ok(u.parse("https://example.com/test?existing=true&foo=bar&foo=baz#section"))


def test_make_fails() -> None:
    """fails when the URL cannot be constructed"""
    match u.make("http://%", up.EMPTY, None):
        case Err(error):
            assert isinstance(error, u.UrlError)
        case Ok(_):
            raise AssertionError("made")


def test_from_string_absolute() -> None:
    """parses absolute URLs"""
    assert u.from_string(u.href(TEST_URL)) == Ok(TEST_URL)


def test_from_string_relative() -> None:
    """resolves relative URLs against a base URL"""
    assert u.from_string("??") == Err(IllegalArgumentError('Invalid URL: "??"'))


def test_set_hash() -> None:
    """setHash"""
    _expect(u.set_hash(TEST_URL, "test"), "https://example.com/test#test")


def test_set_host() -> None:
    """setHost"""
    _expect(u.set_host(TEST_URL, "newhost.com"), "https://newhost.com/test")


def test_set_hostname() -> None:
    """setHostname"""
    _expect(u.set_hostname(TEST_URL, "newhostname.com"), "https://newhostname.com/test")


def test_set_href() -> None:
    """setHref"""
    _expect(u.set_href(TEST_URL, "https://newhref.com"), "https://newhref.com/")


def test_set_password() -> None:
    """setPassword"""
    _expect(u.set_password(TEST_URL, "newpassword"), "https://:newpassword@example.com/test")


def test_set_password_redacted() -> None:
    """setPassword - Redacted"""
    _expect(
        u.set_password(TEST_URL, Redacted("newpassword")), "https://:newpassword@example.com/test"
    )


def test_set_pathname() -> None:
    """setPathname"""
    _expect(u.set_pathname(TEST_URL, "/newpath"), "https://example.com/newpath")


def test_set_port() -> None:
    """setPort"""
    _expect(u.set_port(TEST_URL, "8080"), "https://example.com:8080/test")
    _expect(u.set_port(TEST_URL, 8080), "https://example.com:8080/test")


def test_set_protocol() -> None:
    """setProtocol"""
    _expect(u.set_protocol(TEST_URL, "http"), "http://example.com/test")


def test_set_search() -> None:
    """setSearch"""
    _expect(u.set_search(TEST_URL, "?key=value"), "https://example.com/test?key=value")


def test_set_username() -> None:
    """setUsername"""
    _expect(u.set_username(TEST_URL, "newuser"), "https://newuser@example.com/test")


def test_modify_url_params() -> None:
    """modifyUrlParams"""
    _expect(
        u.modify_url_params(TEST_URL, lambda params: params.append("key", "value")),
        "https://example.com/test?key=value",
    )


def test_url_params() -> None:
    """urlParams"""
    params = u.url_params(u.parse("https://example.com?foo=bar&baz=qux"))
    assert params == up.from_input([("foo", "bar"), ("baz", "qux")])


def test_set_url_params() -> None:
    """setUrlParams"""
    url = u.parse("https://example.com/?foo=bar&a=b")
    updated = u.set_url_params(url, up.from_input([("foo", "bar2"), ("baz", "qux")]))
    assert u.href(updated) == "https://example.com/?foo=bar2&baz=qux"
