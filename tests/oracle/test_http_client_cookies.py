"""Ports of the ``withCookiesRef`` tests of Effect's ``http/HttpClient.test.ts``.

Each test's docstring is the Effect test title. The cookie jar is a
``Ref[tuple[Cookie, ...]]``, as Effect's ``Ref<ReadonlyArray<Cookie>>``.
"""

from typing import Any

import pyfect as fx
from pyfect import clock, testing
from pyfect.http import client as c
from pyfect.http import cookies as ck
from pyfect.http import request as req
from pyfect.http import response as res
from pyfect.http.abort import AbortSignal
from pyfect.http.error import HttpClientError
from pyfect.ref import Ref

type Jar = tuple[ck.Cookie, ...]


def _seeded(url: str, set_cookie: str) -> Jar:
    return ck.merge_into_array((), url, ck.from_set_cookie(set_cookie), 0)


@testing.effect
def test_matching_host_only():
    """sends stored response cookies only to the matching host"""
    jar = yield from Ref[Jar].make(())
    seen: list[str | None] = []

    def handle(request: req.HttpClientRequest) -> res.HttpClientResponse:
        seen.append(request.headers.get("cookie"))
        host = request.url.split("/")[2]
        set_cookie = "session=secret" if host == "api.example.com" else "session=attacker"
        return res.make(request, headers={"set-cookie": set_cookie})

    client = c.make(
        lambda request, _url, _signal, _fiber: fx.sync(lambda: handle(request))
    ).with_cookies_ref(jar)
    yield from client.get("https://api.example.com/account")
    yield from client.get("https://evil.example/hook")
    yield from client.get("https://api.example.com/account")
    yield from client.get("https://evil.example/hook")
    assert seen == [None, None, "session=secret", "session=attacker"]


@testing.effect
def test_final_response_host_and_default_path():
    """stores cookies using the final response host and default path"""
    jar = yield from Ref[Jar].make(())
    client = c.make(
        lambda request, _url, _signal, _fiber: fx.succeed(
            res.make(
                request,
                headers={"set-cookie": "session=final"},
                url="https://login.example.com/auth/callback",
            )
        )
    ).with_cookies_ref(jar)
    yield from client.get("https://api.example.com/start")
    stored = yield from jar.get()
    now = yield from clock.current_time_millis()
    header = ck.to_request_cookie_header
    assert header(stored, "https://login.example.com/auth/next", now) == "session=final"
    assert header(stored, "https://api.example.com/start", now) is None
    assert header(stored, "https://login.example.com/other", now) is None


@testing.effect
def test_prepended_url_after_with_cookies_ref():
    """sends stored cookies when the URL is prepended after withCookiesRef"""
    jar = yield from Ref[Jar].make(())
    seen: list[str | None] = []

    def handle(request: req.HttpClientRequest) -> res.HttpClientResponse:
        seen.append(request.headers.get("cookie"))
        return res.make(request, headers={"set-cookie": "session=abc; Path=/"})

    client = (
        c.make(lambda request, _url, _signal, _fiber: fx.sync(lambda: handle(request)))
        .with_cookies_ref(jar)
        .map_request(lambda request: request.prepend_url("https://api.example.com"))
    )
    yield from client.post("/login")
    yield from client.get("/me")
    assert seen == [None, "session=abc"]


@testing.effect
def test_each_redirect_hop():
    """selects stored cookies for each redirect hop"""
    jar = yield from Ref[Jar].make(_seeded("https://b.test/", "b=1"))
    redirects = {
        "https://a.test/start": {"location": "https://a.test/next", "set-cookie": "a=1"},
        "https://a.test/next": {"location": "https://b.test/final"},
    }
    seen: list[str | None] = []

    def handle(request: req.HttpClientRequest) -> res.HttpClientResponse:
        seen.append(request.headers.get("cookie"))
        headers = redirects.get(request.url)
        return res.make(request, status=302 if headers else 200, headers=headers)

    client = (
        c.make(lambda request, _url, _signal, _fiber: fx.sync(lambda: handle(request)))
        .with_cookies_ref(jar)
        .follow_redirects()
    )
    yield from client.get("https://a.test/start")
    assert seen == [None, "a=1", "b=1"]


@testing.effect
def test_with_scope_still_aborts():
    """keeps withScope aborting a request that withCookiesRef adds cookies to"""
    jar = yield from Ref[Jar].make(_seeded("https://api.example.com/", "session=abc"))
    started = yield from fx.Deferred[AbortSignal].make()
    cookie: list[str | None] = []

    def send(
        request: req.HttpClientRequest, _url: Any, signal: AbortSignal, _fiber: Any
    ) -> fx.Effect[res.HttpClientResponse, HttpClientError]:
        cookie.append(request.headers.get("cookie"))
        return started.succeed(signal).and_then(fx.never)

    client = c.make(send).with_cookies_ref(jar).with_scope()
    scope = fx.CloseableScope()
    yield from client.get("https://api.example.com/slow").pipe(fx.scope.provide(scope)).fork()
    signal = yield from started.wait()
    assert not signal.aborted
    assert cookie == ["session=abc"]
    yield from scope.close(fx.Success(None))
    assert signal.aborted
