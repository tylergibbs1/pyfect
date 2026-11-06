"""The httpx client sends every ``FormData`` as ``multipart/form-data``,
an empty one included (httpx alone sends an empty form as no body)."""

import httpx

import pyfect as fx
from pyfect.http import body, httpx_client, request
from pyfect.http.client import HttpClient


def _sent(form: body.FormData) -> httpx.Request:
    seen: list[httpx.Request] = []

    def handler(sent: httpx.Request) -> httpx.Response:
        sent.read()
        seen.append(sent)
        return httpx.Response(200)

    http = httpx_client.layer_with(transport=httpx.MockTransport(handler))
    send = HttpClient().flat_map(
        lambda client: client.execute(request.post("http://test/").body_form_data(form))
    )
    fx.run_blocking(fx.scoped(send).pipe(fx.provide(http)).or_die())
    return seen[0]


def test_an_empty_form_is_an_empty_multipart_body() -> None:
    sent = _sent(body.FormData())
    content_type = sent.headers["content-type"]
    assert content_type.startswith("multipart/form-data; boundary=")
    boundary = content_type.split("boundary=", 1)[1]
    assert sent.content == f"--{boundary}--\r\n".encode()


def test_a_form_with_entries_is_multipart() -> None:
    sent = _sent(body.FormData().append("name", "value"))
    assert sent.headers["content-type"].startswith("multipart/form-data; boundary=")
    assert b'name="name"' in sent.content
