"""Credentials configured on the httpx client never follow a redirect to
another origin: ``follow_redirects`` strips them like per-request ones."""

import inspect
from typing import Any

import httpx
import pytest

import pyfect as fx
from pyfect.http import httpx_client, request
from pyfect.http._httpx_options import REQUEST_DEFAULT_OPTIONS
from pyfect.http.client import HttpClient


def _sent(**options: Any) -> dict[str, httpx.Request]:
    """Send ``GET https://a.test/`` (redirected to ``https://evil.test/x``)
    through ``follow_redirects`` and return the request each host saw."""
    seen: dict[str, httpx.Request] = {}

    def handler(sent: httpx.Request) -> httpx.Response:
        seen[sent.url.host] = sent
        if sent.url.host == "a.test":
            return httpx.Response(302, headers={"location": "https://evil.test/x"})
        return httpx.Response(200)

    http = httpx_client.layer_with(transport=httpx.MockTransport(handler), **options)
    send = HttpClient().flat_map(
        lambda client: client.follow_redirects().execute(request.get("https://a.test/"))
    )
    fx.run_blocking(fx.scoped(send).pipe(fx.provide(http)).or_die())
    return seen


def _hops(**options: Any) -> dict[str, httpx.Headers]:
    return {host: sent.headers for host, sent in _sent(**options).items()}


@pytest.mark.parametrize(
    ("options", "name"),
    [
        ({"headers": {"Authorization": "Bearer secret"}}, "authorization"),
        ({"headers": {"Proxy-Authorization": "Basic cDpw"}}, "proxy-authorization"),
        ({"headers": {"Cookie": "sid=secret"}}, "cookie"),
        ({"cookies": {"sid": "secret"}}, "cookie"),
        ({"auth": ("u", "p")}, "authorization"),
    ],
)
def test_client_level_credentials_reach_the_first_origin_only(
    options: dict[str, Any], name: str
) -> None:
    seen = _hops(**options)
    assert name in seen["a.test"]
    assert name not in seen["evil.test"]


def test_client_level_params_stay_on_the_first_origin() -> None:
    seen = _sent(params={"key": "secret"})
    assert seen["a.test"].url.params["key"] == "secret"
    assert "key" not in seen["evil.test"].url.params


def test_every_httpx_option_merged_into_requests_is_taken_over() -> None:
    """A new ``httpx.AsyncClient`` parameter must be classified: either it
    is a request default pyfect applies itself, or it does not add to
    requests."""
    transport_level = {
        "verify", "cert", "trust_env", "http1", "http2", "proxy", "mounts", "timeout",
        "follow_redirects", "limits", "max_redirects", "event_hooks", "base_url",
        "transport", "default_encoding",
    }  # fmt: skip
    parameters = set(inspect.signature(httpx.AsyncClient.__init__).parameters) - {"self"}
    assert parameters == REQUEST_DEFAULT_OPTIONS | transport_level


def test_client_level_basic_auth_is_the_basic_header() -> None:
    assert _hops(auth=("u", "p"))["a.test"]["authorization"] == "Basic dTpw"


def test_client_level_headers_still_reach_every_hop_unless_secret() -> None:
    seen = _hops(headers={"user-agent": "pyfect-test", "authorization": "Bearer secret"})
    assert seen["evil.test"]["user-agent"] == "pyfect-test"


def test_request_headers_override_client_level_headers() -> None:
    seen: list[httpx.Headers] = []

    def handler(sent: httpx.Request) -> httpx.Response:
        seen.append(sent.headers)
        return httpx.Response(200)

    http = httpx_client.layer_with(
        transport=httpx.MockTransport(handler), headers={"x-env": "client"}
    )
    send = HttpClient().flat_map(
        lambda client: client.execute(request.get("https://a.test/").set_header("x-env", "req"))
    )
    fx.run_blocking(fx.scoped(send).pipe(fx.provide(http)).or_die())
    assert seen[0].get_list("x-env") == ["req"]


def test_an_auth_flow_the_redirect_follower_cannot_strip_is_refused() -> None:
    with pytest.raises(TypeError, match="auth"):
        httpx_client.layer_with(auth=httpx.DigestAuth("u", "p"))
