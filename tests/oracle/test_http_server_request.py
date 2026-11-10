"""Ports of Effect's ``http/HttpServerRequest.test.ts``.

Each test's docstring is the Effect test title; Web ``Request`` objects
are ``WebRequest`` and ``fromWeb`` is ``web_handler.request_from_web``.

Changed, with the reason:

- ``preserves FormData through client-server-client conversion``: client
  requests have no ``toWeb``, so the round-tripped body is checked to be
  the same form.
- ``streams a raw URLSearchParams after conversion from a client
  request``: a ``UrlParams`` stands in for ``URLSearchParams``.
"""

import json
from typing import TypedDict, assert_type

import pytest

import pyfect as fx
from pyfect import effect, schema
from pyfect.exit import Success
from pyfect.http import body as http_body
from pyfect.http import request as client_request
from pyfect.http import response as client_response
from pyfect.http import server_response, url_params
from pyfect.http.multipart import Field, File
from pyfect.http.server_request import (
    HttpServerRequest,
    ServerRequest,
    from_client_request,
    schema_body_json,
    to_client_request,
    to_url,
)
from pyfect.http.web import WebRequest
from pyfect.http.web_handler import request_from_web


def test_preserves_an_extension_method() -> None:
    """preserves an extension method through web-server-client conversion"""
    request = request_from_web(WebRequest("http://localhost/", method="PROPFIND"))
    assert_type(request.method, str)
    assert request.method == "PROPFIND"
    forwarded = to_client_request(request)
    assert_type(forwarded.method, str)
    assert forwarded.method == "PROPFIND"
    assert from_client_request(forwarded).method == "PROPFIND"


def test_url_params_body_preserves_leading_question_marks() -> None:
    """urlParamsBody preserves leading question marks"""
    body = "??name=value"
    client = client_request.post("http://localhost/").body_text(
        body, "application/x-www-form-urlencoded"
    )
    messages: list[ServerRequest | client_response.HttpClientResponse] = [
        request_from_web(WebRequest("http://localhost/", method="POST", body=body)),
        from_client_request(client),
        client_response.make(client, body),
        server_response.to_client_response(server_response.text(body)),
    ]
    for message in messages:
        params = fx.run_sync(message.url_params_body.or_die())
        assert list(params) == [("??name", "value")]


def test_url_params_body_preserves_a_leading_bom() -> None:
    """urlParamsBody preserves a leading BOM"""
    request = request_from_web(
        WebRequest("http://localhost/", method="POST", body="\ufeffname=value")
    )
    assert list(fx.run_sync(request.url_params_body.or_die())) == [("\ufeffname", "value")]


def test_preserves_form_data_through_client_server_client_conversion() -> None:
    """preserves FormData through client-server-client conversion"""
    form = http_body.FormData().append("name", "alice")
    client = client_request.post("https://example.com/upload").body_form_data(form)
    round_trip = to_client_request(from_client_request(client))
    assert isinstance(round_trip.body, http_body.FormData)
    assert round_trip.body.get_all("name") == ["alice"]


def test_to_client_request() -> None:
    """toClientRequest"""
    server = request_from_web(
        WebRequest(
            "http://localhost:3000/todos/1?a=1&a=2#top",
            method="POST",
            headers={
                "host": "localhost:3000",
                "content-type": "application/json",
                "content-length": "13",
                "x-test": "ok",
            },
            body='{"foo":"bar"}',
        )
    )
    client = to_client_request(server)
    assert client.method == "POST"
    assert client.url == "http://localhost:3000/todos/1"
    assert client.hash == "top"
    assert client.headers["content-type"] == "application/json"
    assert client.headers["content-length"] == "13"
    assert client.headers["x-test"] == "ok"
    assert list(client.url_params) == [("a", "1"), ("a", "2")]
    assert isinstance(client.body, http_body.Stream)
    exit = fx.run_blocking_exit(client.body.stream.run_collect())
    assert isinstance(exit, Success)
    assert b"".join(exit.value).decode() == '{"foo":"bar"}'


def test_to_client_request_ignores_malformed_or_unsafe_content_lengths() -> None:
    """toClientRequest ignores malformed or unsafe content lengths"""
    for content_length in ("2junk", "1.5", "1e3", "9007199254740992"):
        client = to_client_request(
            request_from_web(
                WebRequest(
                    "http://localhost:3000",
                    method="POST",
                    headers={"content-length": content_length},
                    body="hello",
                )
            )
        )
        assert client.headers.get("content-length") is None
        assert isinstance(client.body, http_body.Stream)
        assert client.body.content_length is None


def test_to_client_request_keeps_empty_bodies_empty() -> None:
    """toClientRequest keeps empty bodies empty"""
    client = to_client_request(
        request_from_web(
            WebRequest(
                "http://localhost:3000/todos/1",
                method="GET",
                headers={"content-type": "application/json", "x-test": "ok"},
            )
        )
    )
    assert isinstance(client.body, http_body.Empty)
    assert client.headers["content-type"] == "application/json"
    assert client.headers["x-test"] == "ok"


def test_from_client_request_preserves_request_metadata_and_shares_stream_body_accessors() -> None:
    """fromClientRequest preserves request metadata and shares concurrent stream body accessors"""
    client = (
        client_request.post("http://localhost:3000/items?existing=1#top")
        .append_url_param("page", "1")
        .set_header("cookie", "session=123")
        .body_json_unsafe({"foo": "bar"})
    )
    request = from_client_request(client)

    @fx.fn
    def program():
        data = yield from request.bytes_
        parsed = yield from request.json
        text = yield from request.text
        return data, parsed, text

    data, parsed, text = fx.run_blocking(program().or_die())
    assert request.source is client
    assert request.method == "POST"
    assert request.original_url == "http://localhost:3000/items?existing=1&page=1#top"
    assert request.url == "/items?existing=1&page=1#top"
    assert request.headers["content-type"] == "application/json"
    assert request.cookies["session"] == "123"
    assert parsed == {"foo": "bar"}
    assert text == '{"foo":"bar"}'
    assert data.decode() == '{"foo":"bar"}'


def test_from_client_request_exposes_form_data_bodies_as_multipart_parts() -> None:
    """fromClientRequest exposes FormData bodies as multipart parts"""
    form = (
        http_body.FormData()
        .append("name", "alice")
        .append("file", http_body.File(b"hello", "hello.txt", "text/plain"))
    )
    request = from_client_request(client_request.post("/upload").body_form_data(form))
    parts = fx.run_blocking(request.multipart_stream.run_collect().or_die())
    assert len(parts) == 2
    field, file = parts
    assert isinstance(field, Field)
    assert field.key == "name"
    assert field.value == "alice"
    assert isinstance(file, File)
    assert file.key == "file"
    assert file.name == "hello.txt"
    assert file.content_type == "text/plain"
    assert fx.run_blocking(file.content_effect.or_die()) == b"hello"


def test_reads_a_raw_body_init_after_conversion_from_a_client_request() -> None:
    """reads a raw BodyInit after conversion from a client request"""
    client = client_request.post("https://example.com").set_body(http_body.raw("abc"))
    assert fx.run_blocking(from_client_request(client).text.or_die()) == "abc"


def test_reads_raw_body_init_bytes_after_conversion_from_a_client_request() -> None:
    """reads raw BodyInit bytes after conversion from a client request"""
    client = client_request.post("https://example.com").set_body(http_body.raw("abc"))
    assert fx.run_blocking(from_client_request(client).bytes_.or_die()) == bytes([97, 98, 99])


def test_streams_a_raw_url_search_params_after_conversion_from_a_client_request() -> None:
    """streams a raw URLSearchParams after conversion from a client request"""
    params = url_params.from_input({"a": "1", "b": "two"})
    client = client_request.post("https://example.com").set_body(http_body.raw(params))
    chunks = fx.run_blocking(from_client_request(client).stream.run_collect().or_die())
    assert b"".join(chunks).decode() == "a=1&b=two"


class _Status(TypedDict):
    status: str
    name: str


def test_schema_body_json_applies_parse_options() -> None:
    """schemaBodyJson applies parse options"""
    request = request_from_web(
        WebRequest(
            "http://localhost:3000",
            method="POST",
            headers={"content-type": "application/json"},
            body=json.dumps({"status": "ok", "name": "svc", "sha": "abc", "version": "1.0.0"}),
        )
    )
    decoded = fx.run_blocking(
        schema_body_json(
            schema.Struct(_Status),
            on_excess_property="ignore",
            reviver=lambda key, value: "revived" if key == "status" else value,
        )
        .pipe(effect.provide_service(HttpServerRequest, request))
        .or_die()
    )
    assert decoded == {"status": "revived", "name": "svc"}


@pytest.mark.parametrize(
    ("url", "headers", "expected"),
    [
        ("https://example.test/a?b=1", {"host": "example.test"}, "https://example.test/a?b=1"),
        (
            "http://example.test/a",
            {"host": "example.test", "x-forwarded-proto": "https"},
            "http://example.test/a",
        ),
    ],
)
def test_to_url(url: str, headers: dict[str, str], expected: str) -> None:
    """${url} ${JSON.stringify(headers)} -> ${expected}"""
    parsed = to_url(request_from_web(WebRequest(url, headers=headers)))
    assert parsed is not None
    assert parsed.href == expected


def test_remote_address_defaults_to_none_for_web_requests() -> None:
    """remoteAddress defaults to none for web requests"""
    assert request_from_web(WebRequest("http://example.com")).remote_address is None


def test_modify_distinguishes_missing_and_explicit_none_remote_address() -> None:
    """modify distinguishes missing and explicit none remoteAddress"""
    request = request_from_web(WebRequest("http://example.com"))
    with_remote = request.modify(remote_address="127.0.0.1")
    assert with_remote.remote_address == "127.0.0.1"
    assert with_remote.modify().remote_address == "127.0.0.1"
    assert with_remote.modify(remote_address=None).remote_address is None
