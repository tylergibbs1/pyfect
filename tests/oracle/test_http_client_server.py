"""Ports of Effect's ``effect/test/HttpClient.test.ts``, against the httpx client
(``pyfect.http.httpx_client``) and a local stdlib server (``_http_server``)
in place of ``FetchHttpClient`` and the Node server.

Each test's docstring is the Effect test title. ``/redirect-fragment`` is
the server's ``/redirect`` of the Effect test.

Adapted, with the reason:

- ``followRedirects``: httpx does not follow redirects itself, so the
  client's ``follow_redirects`` makes the second request and the response
  keeps it (Effect's fetch follows natively and keeps the first).

Omitted, with the reason:

- ``followRedirects with manual fetch redirects``: the fetch
  ``RequestInit`` option; the adapted ``followRedirects`` above is that
  case.
"""

from typing import TypedDict

import pytest

pytest.importorskip("httpx")

from pyfect import schema as S
from pyfect import testing
from pyfect.http import client as c
from pyfect.http import request as req
from pyfect.http import response as res
from pyfect.http import url as u
from pyfect.http.client import HttpClient
from pyfect.testing import Services

from ._http_server import layer_test_client

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


@testing.live(timeout="10 seconds")
def test_get(http: Services[HttpClient]):
    """get"""
    assert (yield from c.get("/").flat_map(lambda r: r.text)) == "test"


@testing.live(timeout="10 seconds")
def test_follow_redirects(http: Services[HttpClient]):
    """followRedirects"""
    client = (yield from HttpClient()).follow_redirects()
    response = yield from client.get("/redirect-fragment")
    assert u.parse(response.request.url).path == "/"
    url = u.parse(response.url)
    assert url.path == "/"
    assert url.query == "value=a%23b"
    assert url.fragment == ""
    assert (yield from response.text) == "test"


@testing.live(timeout="10 seconds")
def test_stream(http: Services[HttpClient]):
    """stream"""
    client = yield from HttpClient()
    assert (yield from res.stream(client.get("/stream")).decode_text().run_string()) == "test"


@testing.live(timeout="10 seconds")
def test_jsonplaceholder(http: Services[HttpClient]):
    """jsonplaceholder"""
    client = yield from HttpClient()
    todo = yield from client.get("/todos/1").flat_map(res.schema_body_json(S.Struct(Todo)))
    assert todo["id"] == 1


@testing.live(timeout="10 seconds")
def test_jsonplaceholder_schema_body_json(http: Services[HttpClient]):
    """jsonplaceholder schemaBodyJson"""
    client = yield from HttpClient()
    request = yield from req.schema_body_json(S.Struct(TodoWithoutId))(
        req.post("/todos"), {"userId": 1, "title": "test", "completed": False}
    )
    todo = yield from client.execute(request).flat_map(res.schema_body_json(S.Struct(Todo)))
    assert todo["title"] == "test"


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
    assert (
        yield from client.get("/interrupt").flat_map(lambda r: r.text).timeout("1 second").option()
    ) is None


@testing.live(timeout="10 seconds")
def test_close_early(http: Services[HttpClient]):
    """close early"""
    response = yield from c.get("/stream")
    assert response.status == 200
