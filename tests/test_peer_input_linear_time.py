"""(pyfect) Parsing what a peer sends takes time linear in its length.

Each case is input a client controls (a request path, a header, an MCP resource
URI) given to the parser that reads it, at two sizes eight times apart. A new
parser of peer input belongs in this table."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypedDict

import pytest
from _growth import assert_near_linear
from _guards import guards

from pyfect import schema as S
from pyfect.http import cookies
from pyfect.http.find_my_way._router import (
    Router,
    _safe_decode_uri,  # pyright: ignore[reportPrivateUsage]
)
from pyfect.http.web import WebRequest
from pyfect.http_api._path import to_router_path

type Case = Callable[[int], Callable[[], object]]


def _percent_25_path(n: int) -> Callable[[], object]:
    path = "/" + "%25" * n
    return lambda: _safe_decode_uri(path)


class _Three(TypedDict):
    a: str
    b: str
    c: str


def _comma_params(n: int) -> Callable[[], object]:
    """An HttpApi path whose parameters are joined by a character find-my-way
    does not split on, and a segment of them ending where no split matches."""
    params = S.Struct(_Three)
    router = Router[str]()
    router.on("GET", to_router_path("/geo/:a,:b,:c", params), "geo")
    path = "/geo/" + "," * n + "%0A"
    return lambda: router.find("GET", path)


def _repeated_header(n: int) -> Callable[[], object]:
    """An ASGI request's head: some servers (httptools) set no head limit."""
    request = WebRequest("http://localhost/", headers=[("x", "a")] * n)
    return lambda: request.headers


def _cookie_without_equals(n: int) -> Callable[[], object]:
    header = ";" * n + "=x"
    return lambda: cookies.parse_header(header)


CASES: dict[str, tuple[Case, int]] = {
    "Cookie header of segments without =": (_cookie_without_equals, 5_000),
    "ASGI request with many lines of one header": (_repeated_header, 5_000),
    "find-my-way path with %25 runs": (_percent_25_path, 20_000),
    "HttpApi parameters joined by a comma": (_comma_params, 100),
}
"""Each case and an input size (the cost of a quadratic case at 8x should
stay at seconds, so it fails quickly)."""


_GUARDS = {
    "Cookie header of segments without =": guards("0be98c4b", "cookie-segments-rescanned"),
    "ASGI request with many lines of one header": guards(
        "ce40a38a", "header-lines-joined-per-line"
    ),
    "find-my-way path with %25 runs": guards("b81c53e9", "router-escapes-spliced"),
    "HttpApi parameters joined by a comma": guards(
        "3db5d666", "http-api-parameter-crosses-separator"
    ),
}


@pytest.mark.parametrize(
    "name", [pytest.param(name, marks=[_GUARDS[name]]) for name in sorted(CASES)]
)
def test_peer_input_is_parsed_in_linear_time(name: str) -> None:
    make, size = CASES[name]
    assert_near_linear(make, size, 8 * size, bound=16)


def test_comma_joined_parameters_still_match() -> None:
    params = S.Struct(_Three)
    router = Router[str]()
    router.on("GET", to_router_path("/geo/:a,:b,:c", params), "geo")
    found = router.find("GET", "/geo/1,2,3,4")
    assert found is not None
    assert dict(found.params) == {"a": "1", "b": "2", "c": "3,4"}


def test_cookie_segments_without_equals_are_skipped() -> None:
    assert cookies.parse_header("a;b;c=1; d ;e=2") == {"c": "1", "e": "2"}
    assert cookies.parse_header(";;;=x") == {"": "x"}


def test_percent_25_is_kept_encoded_for_parameters() -> None:
    assert _safe_decode_uri("/a%25b%41?q") == ("/a%25bA", "q", True)
    assert _safe_decode_uri("/%25%25") == ("/%25%25", "", True)
