"""Ports of ``@effect/platform-node``'s ``NodeHttpClient.test.ts``, against
the httpx client (``pyfect.http.httpx_client``) and a local stdlib server
(``_http_server``).

Each test's docstring is the Effect test title. Effect runs each test with
its fetch, ``node:http`` and undici clients; here there is one client.

Adapted, with the reason:

- ``sends $source form data request bodies as multipart`` is one test: a
  form is a ``body.FormData`` (there is no global or undici ``FormData``),
  and the caller's ``content-type`` is replaced by httpx's boundary.
- ``fetch rejects an upgrade request before calling fetch``: httpx cannot
  upgrade a connection either, so the request fails with a
  ``TransportError`` before it is sent.

Omitted, with the reason:

- ``continues uploading while reading a streaming response`` and
  ``releases an unfinished keep-alive upload after %s before layer
  teardown``: httpx writes the whole request body before it reads the
  response.
- ``returns TransportError when a form data file cannot be read``,
  ``releases an immediately failing form data stream and connection
  before layer teardown``: a form's files are bytes in memory here, so
  reading one cannot fail.
- ``parses $name response form data``: response ``formData`` parsing
  (multipart) belongs with the HTTP server modules, not ported.
- ``reads a refused upgrade as an ordinary response`` and the ``NodeHttpClient
  upgrade`` tests: upgrades hand over a ``Socket``; the socket modules are
  not ported and httpx cannot upgrade.
"""

from typing import TypedDict

import pytest

pytest.importorskip("httpx")

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.http import body
from pyfect.http import client as c
from pyfect.http import request as req
from pyfect.http import response as res
from pyfect.http import url as u
from pyfect.http.client import HttpClient
from pyfect.testing import Services

from ._http_server import RESPONSE_BYTES, layer_test_client

http = testing.layer_fixture(layer_test_client(), live=True)


class Todo(TypedDict):
    userId: int
    id: int
    title: str
    completed: bool


class TodoWithoutId(TypedDict):
    userId: int
    title: str
    completed: bool


def _create_todo(todo: TodoWithoutId) -> fx.Effect[Todo, object, HttpClient]:
    return HttpClient().flat_map(
        lambda client: (
            req.schema_body_json(S.Struct(TodoWithoutId))(req.post("/todos"), todo)
            .flat_map(client.execute)
            .flat_map(res.schema_body_json(S.Struct(Todo)))
        )
    )


@testing.live(timeout="10 seconds")
def test_text(http: Services[HttpClient]):
    """text"""
    response = yield from c.get("/text?existing=1", url_params={"value": "a#b"}, hash="fragment")
    url = u.parse(response.url)
    assert url.path == "/text"
    assert url.query == "existing=1&value=a%23b"
    assert url.fragment == ""
    assert (yield from response.text) == "test"


@testing.live(timeout="10 seconds")
def test_text_preserves_bytes(http: Services[HttpClient]):
    """accessing text preserves response bytes"""
    response = yield from c.get("/bytes")
    yield from response.text
    assert (yield from response.bytes_) == RESPONSE_BYTES


@testing.live(timeout="10 seconds")
def test_bom_json(http: Services[HttpClient]):
    """request and response json ignore a leading UTF-8 BOM"""
    response = yield from c.post("/bom-json", body=body.text('﻿{"a":1}', "application/json"))
    assert (yield from response.json) == {"a": 1}


@testing.live(timeout="10 seconds")
def test_form_data(http: Services[HttpClient]):
    """sends $source form data request bodies as multipart"""
    form = (
        body.FormData()
        .append("title", "effect")
        .append("file", body.File(b"file contents", "notes.txt", "text/plain"))
    )
    response = yield from c.post(
        "/multipart",
        body=body.form_data(form),
        headers={"content-type": "multipart/form-data; boundary=caller-boundary"},
    ).timeout("2 seconds")
    assert (yield from response.json) == [
        {"key": "title", "value": "effect"},
        {
            "key": "file",
            "name": "notes.txt",
            "contentType": "text/plain",
            "content": "file contents",
        },
    ]


@testing.live(timeout="10 seconds")
def test_follow_redirects(http: Services[HttpClient]):
    """local server followRedirects"""
    client = (yield from HttpClient()).follow_redirects()
    response = yield from client.get("/redirect")
    assert u.parse(response.url).path == "/redirected"
    assert (yield from response.text) == "redirected"


@testing.live(timeout="10 seconds")
def test_text_stream(http: Services[HttpClient]):
    """text stream"""
    client = yield from HttpClient()
    text = yield from res.stream(client.get("/text")).decode_text().run_string()
    assert text == "test"


@testing.live(timeout="10 seconds")
def test_local_server(http: Services[HttpClient]):
    """local server"""
    client = yield from HttpClient()

    def reviver(key: str, value: object) -> object:
        return "revived" if key == "title" else value

    todo = yield from client.get("/todos/1").flat_map(
        res.schema_body_json(S.Struct(Todo), reviver=reviver)
    )
    assert todo["id"] == 1
    assert todo["title"] == "revived"


@testing.live(timeout="10 seconds")
def test_local_server_schema_body_json(http: Services[HttpClient]):
    """local server schemaBodyJson"""
    todo = yield from _create_todo({"userId": 1, "title": "test", "completed": False})
    assert todo["title"] == "test"


@testing.live(timeout="10 seconds")
def test_query_round_trip(http: Services[HttpClient]):
    """round trips QUERY method, body, and content type through the local server"""
    text = '{"query": "effect"}'
    response = yield from c.query("/search", body=body.text(text, "application/json"))
    assert response.status == 200
    assert (yield from response.json) == {
        "method": "QUERY",
        "contentType": "application/json",
        "body": text,
    }


class _Status(TypedDict):
    status: int


@testing.live(timeout="10 seconds")
def test_head_schema_json(http: Services[HttpClient]):
    """head request with schemaJson"""
    client = yield from HttpClient()
    decoded = yield from client.head("/todos").flat_map(
        res.schema_json(S.Struct(_Status, status=S.Literal(200)))
    )
    assert decoded == {"status": 200}


@testing.live(timeout="10 seconds")
def test_interrupt(http: Services[HttpClient]):
    """interrupt"""
    client = yield from HttpClient()
    result = yield from client.get("/hang").flat_map(lambda r: r.text).timeout("1 second").option()
    assert result is None


@testing.live(timeout="10 seconds")
def test_upgrade_rejected(http: Services[HttpClient]):
    """fetch rejects an upgrade request before calling fetch"""
    error = yield from c.execute(req.post("/attach").upgrade("tcp")).flip()
    assert error.reason.tag == "TransportError"


@testing.live(timeout="10 seconds")
def test_close_early(http: Services[HttpClient]):
    """close early"""
    response = yield from c.get("/large")
    assert response.status == 200


@testing.live(timeout="10 seconds")
def test_stream_encode_failure(http: Services[HttpClient]):
    """returns a stream body encoding failure"""
    error = (
        yield from c.post("/", body=body.stream(fx.stream.fail("encode failure")))
        .timeout("1 second")
        .flip()
    )
    assert isinstance(error, c.HttpClientError)
    assert error.reason.tag == "EncodeError"
    assert error.reason.cause == "encode failure"
