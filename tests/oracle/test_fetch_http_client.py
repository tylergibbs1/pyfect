"""Ports of Effect's ``http/FetchHttpClient.test.ts``, against the httpx
client (``pyfect.http.httpx_client``) and a local stdlib server
(``_http_server``), whose ``POST /`` answers with the request body.

Each test's docstring is the Effect test title.

Adapted, with the reason:

- ``sends bodies from Web requests``: there is no web ``Request``; a
  request with a ``raw`` body (as ``fromWeb`` makes) is sent instead.

Omitted, with the reason:

- ``exposes the original Web response body``, ``exposes the original Web
  response body while streaming an upload``: ``HttpClientResponse.toWeb``
  and web ``Response`` objects.
"""

import pytest

pytest.importorskip("httpx")

from pyfect import testing
from pyfect.http import body, httpx_client
from pyfect.http import request as req
from pyfect.http.client import HttpClient
from pyfect.testing import Services

from ._http_server import base_url

http = testing.layer_fixture(httpx_client.layer, live=True)


@testing.live(timeout="10 seconds")
def test_sends_bodies(http: Services[HttpClient]):
    """sends bodies from Web requests"""
    request = (
        req.post(f"{base_url()}/?existing=1#fragment")
        .set_body(body.raw(b"hello"))
        .set_url_param("value", "a#b")
    )
    client = yield from HttpClient()
    response = yield from client.execute(request)
    assert response.url == f"{base_url()}/?existing=1&value=a%23b"
    assert (yield from response.text) == "hello"
