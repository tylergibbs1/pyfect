"""``with_cookies_ref`` is a cookie jar: a cookie a response sets goes back
only to the host that set it (or its Domain), on its Path, and over https
when it is Secure; one origin cannot overwrite another origin's cookie."""

from collections.abc import Callable
from typing import Any

import httpx

import pyfect as fx
from pyfect.http import cookies, httpx_client
from pyfect.http.client import HttpClient
from pyfect.ref import Ref

type Handler = Callable[[httpx.Request], httpx.Response]


def _run(handler: Handler, urls: list[str], jar: cookies.Cookies | None = None) -> cookies.Cookies:
    """GET each of ``urls`` in turn through one jar-bearing client (following
    redirects after the jar); return the jar at the end."""

    def program() -> Any:
        ref = yield from Ref.make(jar or cookies.EMPTY)
        client = (yield from HttpClient()).with_cookies_ref(ref).follow_redirects()
        for url in urls:
            yield from fx.scoped(client.get(url))
        return (yield from ref.get())

    http = httpx_client.layer_with(transport=httpx.MockTransport(handler))
    return fx.run_blocking(fx.gen(program).pipe(fx.provide(http)).or_die())


class _Sites:
    """a.test sets ``sid=secret`` (Secure, Path=/app); evil.test tries to
    overwrite it; each host's received ``Cookie`` header is recorded."""

    def __init__(self) -> None:
        self.received: list[tuple[str, str | None]] = []

    def __call__(self, sent: httpx.Request) -> httpx.Response:
        self.received.append((str(sent.url), sent.headers.get("cookie")))
        match sent.url.host, sent.url.path:
            case "a.test", "/login":
                return httpx.Response(200, headers={"set-cookie": "sid=secret; Path=/app; Secure"})
            case "a.test", "/redir":
                return httpx.Response(302, headers={"location": "https://evil.test/"})
            case "evil.test", _:
                return httpx.Response(200, headers={"set-cookie": "sid=attacker"})
            case _:
                return httpx.Response(200)

    def cookie_for(self, url: str) -> str | None:
        return next(cookie for sent, cookie in self.received if sent == url)


def test_a_cookie_goes_back_to_its_own_host_and_path_only() -> None:
    sites = _Sites()
    _run(
        sites,
        [
            "https://a.test/login",
            "https://a.test/app/x",
            "https://a.test/other",
            "https://evil.test/",
            "https://sub.evil.test/",
        ],
    )
    assert sites.cookie_for("https://a.test/app/x") == "sid=secret"
    assert sites.cookie_for("https://a.test/other") is None
    assert sites.cookie_for("https://evil.test/") is None


def test_a_secure_cookie_is_not_sent_over_http() -> None:
    sites = _Sites()
    _run(sites, ["https://a.test/login", "http://a.test/app/x"])
    assert sites.cookie_for("http://a.test/app/x") is None


def test_another_origin_cannot_overwrite_a_cookie() -> None:
    sites = _Sites()
    jar = _run(sites, ["https://a.test/login", "https://evil.test/", "https://a.test/app/x"])
    assert sites.cookie_for("https://a.test/app/x") == "sid=secret"
    assert jar.get_value("sid") == "secret"


def test_a_redirect_hop_to_another_origin_cannot_overwrite_a_cookie() -> None:
    sites = _Sites()
    jar = _run(sites, ["https://a.test/login", "https://a.test/redir"])
    assert sites.cookie_for("https://evil.test/") is None
    assert jar.get_value("sid") == "secret"


def test_a_domain_cookie_reaches_subdomains_but_not_a_foreign_domain() -> None:
    received: dict[str, str | None] = {}

    def handler(sent: httpx.Request) -> httpx.Response:
        received[sent.url.host] = sent.headers.get("cookie")
        if sent.url.host == "www.a.test":
            return httpx.Response(
                200,
                headers=[
                    ("set-cookie", "d=1; Domain=a.test"),
                    ("set-cookie", "foreign=1; Domain=evil.test"),
                ],
            )
        return httpx.Response(200)

    jar = _run(handler, ["https://www.a.test/", "https://api.a.test/", "https://evil.test/"])
    assert received["api.a.test"] == "d=1"
    assert received["evil.test"] is None
    assert jar.get("foreign") is None


def test_cookies_put_in_the_jar_by_the_program_are_sent_everywhere() -> None:
    received: list[str | None] = []

    def handler(sent: httpx.Request) -> httpx.Response:
        received.append(sent.headers.get("cookie"))
        return httpx.Response(200)

    _run(handler, ["https://api.test/"], jar=cookies.EMPTY.set_unsafe("token", "foo"))
    assert received == ["token=foo"]


def test_a_cookie_for_a_whole_top_level_domain_is_refused() -> None:
    """``Domain=test`` would send a.test's cookie to every ``*.test`` host and
    let evil.test plant a cookie for a.test (session fixation); a browser
    refuses a public suffix, and without a suffix list a single label is
    the one that can always be refused."""
    received: dict[str, str | None] = {}

    def handler(sent: httpx.Request) -> httpx.Response:
        received[sent.url.host] = sent.headers.get("cookie")
        match sent.url.host:
            case "a.test":
                return httpx.Response(200, headers={"set-cookie": "sid=secret; Domain=test"})
            case "evil.test":
                return httpx.Response(200, headers={"set-cookie": "planted=1; Domain=TEST"})
            case _:
                return httpx.Response(200)

    jar = _run(handler, ["https://a.test/", "https://evil.test/", "https://b.test/"])
    assert received["evil.test"] is None
    assert received["b.test"] is None
    assert jar.is_empty()


def test_a_single_label_host_may_set_a_cookie_for_itself() -> None:
    def handler(sent: httpx.Request) -> httpx.Response:
        return httpx.Response(200, headers={"set-cookie": "sid=1; Domain=localhost"})

    jar = _run(handler, ["http://localhost/"])
    assert jar.get_value("sid") == "1"
