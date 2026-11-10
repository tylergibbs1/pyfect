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


def test_a_streamed_file_is_sent_in_its_part() -> None:
    """A file read from a stream source goes between its part's headers and
    the next boundary, with the encoder's boundary in the content type."""
    form = (
        body.FormData()
        .append("a", "1")
        .append("file", body.File(lambda: fx.stream.make(b"he", b"llo"), "x.txt", "text/plain"))
        .append("b", "2")
    )
    sent = _sent(form)
    boundary = sent.headers["content-type"].split("boundary=", 1)[1]
    assert (
        sent.content
        == (
            f'--{boundary}\r\nContent-Disposition: form-data; name="a"\r\n\r\n1\r\n'
            f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="x.txt"\r\n'
            f"Content-Type: text/plain\r\n\r\nhello\r\n"
            f'--{boundary}\r\nContent-Disposition: form-data; name="b"\r\n\r\n2\r\n'
            f"--{boundary}--\r\n"
        ).encode()
    )


def test_a_streamed_file_reaches_a_server_request() -> None:
    """A client request converted to a server request reads the streamed
    file, as its encoded body and as a multipart part."""
    from pyfect.http.multipart import File
    from pyfect.http.server_request import from_client_request

    form = body.FormData().append(
        "file", body.File(lambda: fx.stream.make(b"he", b"llo"), "x.txt", "text/plain")
    )
    server = from_client_request(request.post("http://test/").body_form_data(form))
    encoded = fx.run_blocking(server.stream.run_collect().or_die())
    assert b"\r\n\r\nhello\r\n" in b"".join(encoded)
    parts = fx.run_blocking(server.multipart_stream.run_collect().or_die())
    assert isinstance(parts[0], File)
    content = fx.run_blocking(parts[0].content.run_collect().or_die())
    assert b"".join(content) == b"hello"
