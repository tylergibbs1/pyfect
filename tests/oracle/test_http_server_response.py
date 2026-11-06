"""Ports of Effect's ``http/HttpServerResponse.test.ts``.

Each test's docstring is the Effect test title. Web ``Response`` objects
are ``WebResponse``; ``toWeb`` is ``web_handler.response_to_web`` and
``fromWeb`` ``response_from_web``.

Changed, with the reason:

- ``merges outer headers into a raw Response with immutable headers``:
  ``WebResponse`` headers are immutable tuples, so a plain redirect
  response stands in for Bun's frozen one.
- ``preserves raw Response metadata for HEAD``: a locked Web body has no
  Python equivalent; the body iterator is checked to be left unread.
- ``fromClientResponse preserves formData bodies``: client responses have
  no ``formData`` reader, so the encoded multipart body is checked.

Omitted, with the reason:

- ``has no Web Response for HttpClientResponse.toWeb``: pyfect client
  responses have no ``to_web``.
"""

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Any

import pytest

import pyfect as fx
from pyfect import effect, stream
from pyfect.context import Reference
from pyfect.http import body as http_body
from pyfect.http import cookies as cookies_
from pyfect.http import request as client_request
from pyfect.http import response as client_response
from pyfect.http import server_response
from pyfect.http.server_response import HttpServerResponse
from pyfect.http.web import WebResponse
from pyfect.http.web_handler import response_from_web, response_to_web


class ValueRef(Reference[int], key="test/ValueRef"):
    @classmethod
    def default(cls) -> int:
        return 0


def _two_cookies() -> cookies_.Cookies:
    return cookies_.EMPTY.set_all_unsafe([("a", "1"), ("b", "2")])


def _text(response: WebResponse) -> str:
    async def main() -> str:
        return await response.text()

    return asyncio.run(main())


@pytest.mark.parametrize(("status", "without_body"), [(204, False), (205, False), (304, True)])
def test_prefers_outer_status_and_merges_raw_response_headers(
    status: int, without_body: bool
) -> None:
    """prefers outer status $status and merges raw Response headers with withoutBody=$withoutBody"""
    native_cookies = ["sid=abc; Path=/; HttpOnly", "theme=dark; Path=/"]
    native = WebResponse(
        "cached body",
        status=200,
        status_text="Native status",
        headers=[
            ("etag", '"version-1"'),
            ("x-shared", "native"),
            *(("set-cookie", cookie) for cookie in native_cookies),
        ],
    )
    web = response_to_web(
        server_response.raw(
            native,
            status=status,
            status_text="Outer status",
            headers={"x-outer": "outer", "x-shared": "outer"},
            cookies=_two_cookies(),
        ),
        without_body=without_body,
    )
    assert web.status == status
    assert web.status_text == "Outer status"
    assert web.body is None
    assert web.get("etag") == '"version-1"'
    assert web.get("x-outer") == "outer"
    assert web.get("x-shared") == "outer"
    assert web.get_set_cookie() == [*native_cookies, "a=1", "b=2"]


def test_preserves_raw_response_metadata_for_head() -> None:
    """preserves raw Response metadata for HEAD"""
    read: list[bool] = []

    async def chunks() -> AsyncIterator[bytes]:
        read.append(True)
        yield b"body"

    native = WebResponse(
        chunks(),
        status=202,
        status_text="Accepted by upstream",
        headers={"x-probe": "native", "x-shared": "native", "set-cookie": "sid=abc"},
    )
    web = response_to_web(
        server_response.raw(
            native,
            status=200,
            status_text="Outer status",
            headers={"x-shared": "outer"},
            cookies=cookies_.EMPTY.set_all_unsafe([("a", "1")]),
        ),
        without_body=True,
    )
    assert web.body is None
    assert web.status == 202
    assert web.status_text == "Accepted by upstream"
    assert web.get("x-probe") == "native"
    assert web.get("x-shared") == "outer"
    assert web.get_set_cookie() == ["sid=abc", "a=1"]
    assert read == []


def test_merges_headers_for_get_without_modifying_the_raw_response() -> None:
    """merges headers for GET without modifying the raw Response"""
    native = WebResponse(
        "body",
        status=202,
        status_text="Accepted by upstream",
        headers={
            "x-probe": "native",
            "x-shared": "native",
            "set-cookie": "sid=abc; Path=/; HttpOnly",
        },
    )
    web = response_to_web(
        server_response.raw(
            native, headers={"x-outer": "outer", "x-shared": "outer"}, cookies=_two_cookies()
        )
    )
    assert web.status == 202
    assert web.status_text == "Accepted by upstream"
    assert web.get("x-probe") == "native"
    assert web.get("x-outer") == "outer"
    assert web.get("x-shared") == "outer"
    assert web.get_set_cookie() == ["sid=abc; Path=/; HttpOnly", "a=1", "b=2"]
    assert native.get("x-probe") == "native"
    assert native.get("x-outer") is None
    assert native.get("x-shared") == "native"
    assert native.get_set_cookie() == ["sid=abc; Path=/; HttpOnly"]
    assert _text(web) == "body"


def test_merges_outer_headers_into_a_raw_response_with_immutable_headers() -> None:
    """merges outer headers into a raw Response with immutable headers"""
    native = WebResponse(None, status=302, headers={"location": "http://localhost/target"})
    web = response_to_web(
        server_response.raw(
            native,
            headers={"x-outer": "outer"},
            cookies=cookies_.EMPTY.set_all_unsafe([("a", "1")]),
        )
    )
    assert web.status == 302
    assert web.get("location") == "http://localhost/target"
    assert web.get("x-outer") == "outer"
    assert web.get_set_cookie() == ["a=1"]


@pytest.mark.parametrize(("status", "without_body"), [(200, True), (304, False)])
def test_preserves_representation_headers(status: int, without_body: bool) -> None:
    """preserves representation headers for status $status with withoutBody=$withoutBody"""
    web = response_to_web(server_response.text("body", status=status), without_body=without_body)
    assert web.body is None
    assert web.get("content-length") == "4"
    assert web.get("content-type") == "text/plain"


@pytest.mark.parametrize(
    "response",
    [
        server_response.text("body", status=204),
        server_response.raw(WebResponse("body", headers={"content-length": "4"}), status=205),
    ],
)
def test_drops_content_length_for_status(response: HttpServerResponse) -> None:
    """drops content-length for status $status"""
    assert response_to_web(response).get("content-length") is None


@pytest.mark.parametrize(("status", "headers"), [(204, None), (205, {"x-outer": "outer"})])
def test_drops_content_length_from_a_raw_response_with_status(
    status: int, headers: dict[str, str] | None
) -> None:
    """drops content-length from a raw Response with status $status"""
    raw = WebResponse(None, status=status, headers={"content-length": "4"})
    options: dict[str, Any] = {} if headers is None else {"headers": headers}
    web = response_to_web(server_response.raw(raw, **options))
    assert web.status == status
    assert web.get("content-length") is None
    assert raw.get("content-length") == "4"


@pytest.mark.parametrize(
    ("status", "without_body"), [(200, True), (204, False), (205, False), (304, False)]
)
def test_cancels_raw_streams_for_status(status: int, without_body: bool) -> None:
    """cancels raw streams for status $status with withoutBody=$withoutBody"""
    cancelled: list[bool] = []

    class Body:
        def __aiter__(self) -> AsyncIterator[bytes]:
            return self._chunks()

        async def _chunks(self) -> AsyncIterator[bytes]:
            yield b"never read"

        async def aclose(self) -> None:
            cancelled.append(True)

    web = response_to_web(server_response.raw(Body(), status=status), without_body=without_body)
    assert web.status == status
    assert web.body is None
    assert _text(web) == ""
    assert cancelled == [True]


_OMITTED: list[tuple[str, Callable[[int], HttpServerResponse]]] = [
    ("text", lambda status: server_response.text("body", status=status)),
    ("uint8Array", lambda status: server_response.bytes_(bytes([1]), status=status)),
    ("raw", lambda status: server_response.raw("body", status=status)),
    ("formData", lambda status: server_response.form_data(http_body.FormData(), status=status)),
    (
        "stream",
        lambda status: server_response.stream(stream.succeed(bytes([1])), status=status),
    ),
]


@pytest.mark.parametrize("status", [204, 205, 304])
@pytest.mark.parametrize(("name", "make"), _OMITTED)
def test_omits_bodies_for_status(
    name: str, make: Callable[[int], HttpServerResponse], status: int
) -> None:
    """omits $name bodies for status ${status}"""
    del name
    web = response_to_web(make(status))
    assert web.status == status
    assert web.body is None


def test_set_header_overrides_body_derived_content_headers() -> None:
    """setHeader overrides body-derived content headers"""
    response = (
        server_response.text("body")
        .set_header("content-type", "text/custom")
        .set_header("content-length", "1")
    )
    assert response.headers["content-type"] == "text/custom"
    assert response.headers["content-length"] == "1"


def test_from_web_preserves_content_length_through_a_web_round_trip() -> None:
    """fromWeb preserves content-length through a Web round trip"""
    response = response_from_web(WebResponse("hello", headers={"content-length": "5"}))
    round_trip = response_to_web(response)
    assert _text(round_trip) == "hello"
    assert round_trip.get("content-length") == "5"


def test_supports_repeated_reads_of_raw_web_response_bodies() -> None:
    """supports repeated reads of raw Web Response bodies"""
    response = server_response.to_client_response(server_response.raw(WebResponse("hello")))

    @fx.fn
    def program():
        first = yield from response.text
        second = yield from response.text
        data = yield from response.bytes_
        return first, second, data

    assert fx.run_blocking(program().or_die()) == ("hello", "hello", b"hello")


def test_leaves_the_raw_web_response_servable_after_a_client_body_read() -> None:
    """leaves the raw Web Response servable after a client-body read"""
    response = server_response.raw(WebResponse("hello"))
    assert fx.run_blocking(server_response.to_client_response(response).text.or_die()) == "hello"
    assert _text(response_to_web(response)) == "hello"


def test_from_client_response_preserves_status_headers_cookies_and_json() -> None:
    """fromClientResponse preserves status, headers, cookies, and json"""
    request = client_request.get(
        "http://localhost:3000/todos/1?existing=1", url_params={"value": "a#b"}, hash="fragment"
    )
    client = server_response.to_client_response(
        server_response.json_unsafe({"foo": "bar"}, status=201)
        .set_header("x-test", "ok")
        .set_cookie_unsafe("session", "123"),
        request=request,
    )
    response = server_response.from_client_response(client)
    round_trip = server_response.to_client_response(response, request=request)
    assert client.url == "http://localhost:3000/todos/1?existing=1&value=a%23b"
    assert round_trip.url == client.url
    assert response.status == 201
    assert response.headers["content-type"] == "application/json"
    assert response.headers["x-test"] == "ok"
    assert response.headers.get("set-cookie") is None
    session = response.cookies.get("session")
    assert session is not None
    assert session.value == "123"
    assert fx.run_blocking(round_trip.json.or_die()) == {"foo": "bar"}


def test_from_client_response_preserves_stream_requirements() -> None:
    """fromClientResponse preserves stream requirements"""
    body = stream.from_effect(ValueRef()).map(lambda value: str(value).encode())
    client = server_response.to_client_response(server_response.stream(body))
    response = server_response.from_client_response(client)
    round_trip = server_response.to_client_response(response)
    assert round_trip.url == ""
    text = round_trip.text.pipe(effect.provide_service(ValueRef, 420))
    assert fx.run_blocking(text.or_die()) == "420"


def test_from_client_response_preserves_form_data_bodies() -> None:
    """fromClientResponse preserves formData bodies"""
    form = http_body.FormData().append("foo", "bar")
    response = server_response.from_client_response(
        server_response.to_client_response(server_response.form_data(form))
    )
    round_trip = server_response.to_client_response(response)
    content_type = response.headers["content-type"]
    assert content_type.startswith("multipart/form-data; boundary=")
    boundary = content_type.split("boundary=", 1)[1]
    text = fx.run_blocking(round_trip.text.or_die())
    assert f'--{boundary}\r\nContent-Disposition: form-data; name="foo"\r\n\r\nbar\r\n' in text


def test_from_client_response_turns_empty_client_bodies_into_empty_server_streams() -> None:
    """fromClientResponse turns empty client bodies into empty server streams"""
    request = client_request.get("http://localhost:3000/empty")
    client = client_response.make(request, None, status=200)
    response = server_response.from_client_response(client)
    round_trip = server_response.to_client_response(response, request=request)
    assert response.status == 200
    assert fx.run_blocking(round_trip.text.or_die()) == ""


def test_from_client_response_ignores_malformed_or_unsafe_content_lengths() -> None:
    """fromClientResponse ignores malformed or unsafe content lengths"""
    request = client_request.get("http://localhost:3000")
    for content_length in ("2junk", "1.5", "1e3", "9007199254740992"):
        client = client_response.make(request, "hello", headers={"content-length": content_length})
        response = server_response.from_client_response(client)
        assert isinstance(response.body, http_body.Stream)
        assert response.body.content_length is None


def test_synchronizes_body_metadata_headers_for_empty_and_replaced_bodies() -> None:
    """synchronizes body metadata headers for empty and replaced bodies"""
    assert server_response.bytes_(b"").headers["content-length"] == "0"
    replaced = server_response.text("abc").set_body(http_body.EMPTY)
    assert "content-type" not in replaced.headers
    assert "content-length" not in replaced.headers
    streamed = server_response.text("abc").set_body(
        http_body.stream(stream.empty, "application/octet-stream")
    )
    assert streamed.headers["content-type"] == "application/octet-stream"
    assert "content-length" not in streamed.headers
