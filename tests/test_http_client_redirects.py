"""``follow_redirects`` never leaves TLS: a redirect from ``https`` to
``http`` is returned, not followed (Effect follows it)."""

import httpx
import pytest

import pyfect as fx
from pyfect.http import httpx_client, request
from pyfect.http.client import HttpClient


def _follow(start: str, location: str) -> tuple[int, list[str]]:
    """The final status and the URLs the transport saw."""
    seen: list[str] = []

    def handler(sent: httpx.Request) -> httpx.Response:
        seen.append(str(sent.url))
        if len(seen) == 1:
            return httpx.Response(307, headers={"location": location})
        return httpx.Response(200)

    http = httpx_client.layer_with(transport=httpx.MockTransport(handler))
    send = HttpClient().flat_map(
        lambda client: client.follow_redirects().execute(request.post(start).body_text("secret"))
    )
    response = fx.run_blocking(fx.scoped(send).pipe(fx.provide(http)).or_die())
    return response.status, seen


@pytest.mark.parametrize("location", ["http://a.test/next", "http://b.test/next"])
def test_a_redirect_from_https_to_http_is_not_followed(location: str):
    assert _follow("https://a.test/", location) == (307, ["https://a.test/"])


@pytest.mark.parametrize(
    ("start", "location"),
    [
        ("https://a.test/", "https://b.test/next"),
        ("http://a.test/", "http://b.test/next"),
        ("http://a.test/", "https://a.test/next"),
    ],
)
def test_other_redirects_are_followed(start: str, location: str):
    assert _follow(start, location) == (200, [start, location])


def _native(follow_redirects: bool, under: bool | None) -> list[str]:
    """The URLs httpx sent for a redirected request, on a client made with
    ``follow_redirects`` and sent under ``FollowRedirects(under)``."""
    seen: list[str] = []

    def handler(sent: httpx.Request) -> httpx.Response:
        seen.append(str(sent.url))
        if len(seen) == 1:
            return httpx.Response(307, headers={"location": "https://b.test/next"})
        return httpx.Response(200)

    http = httpx_client.layer_with(
        transport=httpx.MockTransport(handler), follow_redirects=follow_redirects
    )
    send = HttpClient().flat_map(lambda client: client.execute(request.get("https://a.test/")))
    if under is not None:
        send = send.pipe(fx.provide_service(httpx_client.FollowRedirects, under))
    fx.run_blocking(fx.scoped(send).pipe(fx.provide(http)).or_die())
    return seen


@pytest.mark.parametrize(
    ("follow_redirects", "under", "followed"),
    [(True, None, True), (False, None, False), (True, False, False), (False, True, True)],
)
def test_follow_redirects_overrides_the_clients_own_setting(
    follow_redirects: bool, under: bool | None, followed: bool
):
    """As Effect's ``FetchHttpClient.RequestInit`` sets ``redirect`` for the requests under it."""
    first = ["https://a.test/"]
    expected = [*first, "https://b.test/next"] if followed else first
    assert _native(follow_redirects, under) == expected
