"""Ports of ``@effect/platform-node``'s ``NodeHttpClient.test.ts``, against
the httpx client (``pyfect.http.httpx_client``) and a local stdlib server
(``_http_server``).

Each test's docstring is the Effect test title. Effect runs each test with
its fetch, ``node:http`` and undici clients; here there is one client.

Adapted, with the reason:

- ``sends $source form data request bodies as multipart`` is one test: a
  form is a ``body.FormData`` (there is no global or undici ``FormData``),
  and the caller's ``content-type`` is replaced by httpx's boundary.
- The ``NodeHttpClient upgrade`` tests run once, against httpx, which hands
  over the connection httpcore switched (``network_stream``).

Omitted, with the reason:

- ``continues uploading while reading a streaming response`` and
  ``releases an unfinished keep-alive upload after %s before layer
  teardown``: httpx writes the whole request body before it reads the
  response.
- ``returns TransportError when a form data file cannot be read``,
  ``releases an immediately failing form data stream and connection
  before layer teardown``: they read a web ``File`` whose bytes fail to
  load inside undici's encoder; a ``body.File`` of a stream source is read
  by pyfect itself (``returns TransportError when a form data file stream
  cannot be created`` and ``reads backpressured form data files on demand
  ...`` cover its failure and its release).
- ``parses $name response form data``: response ``formData`` parsing
  (multipart) belongs with the HTTP server modules, not ported.
- ``fetch rejects an upgrade request before calling fetch``: pyfect has no
  fetch client, and httpx sends upgrade requests.
"""

import contextlib
import socket
import threading
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Any, TypedDict

import pytest

pytest.importorskip("httpx")

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.http import body, httpx_client
from pyfect.http import client as c
from pyfect.http import request as req
from pyfect.http import response as res
from pyfect.http import url as u
from pyfect.http.client import HttpClient, HttpClientService
from pyfect.http.error import HttpClientError
from pyfect.scope import scoped
from pyfect.socket import Reader, SocketError
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
    assert url.pathname == "/text"
    assert url.search == "?existing=1&value=a%23b"
    assert url.hash == ""
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


@pytest.mark.parametrize("source", ["bytes", "stream"])
@testing.live(timeout="10 seconds")
def test_form_data(http: Services[HttpClient], source: str):
    """sends $source form data request bodies as multipart"""
    content: body.FileContent = (
        b"file contents" if source == "bytes" else lambda: fx.stream.make(b"file ", b"contents")
    )
    form = (
        body.FormData()
        .append("title", "effect")
        .append("file", body.File(content, "notes.txt", "text/plain"))
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
    assert u.parse(response.url).pathname == "/redirected"
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
def test_upgrade_refused(http: Services[HttpClient]):
    """reads a refused upgrade as an ordinary response"""
    response = yield from c.execute(req.post("/upgrade").upgrade("tcp"))
    assert response.status == 401
    error = yield from response.upgrade.flip()
    assert error.reason.tag == "StatusCodeError"
    assert (yield from response.json) == {"message": "unauthorized"}


@contextmanager
def _upgrade_server() -> Generator[tuple[str, threading.Event]]:
    """Effect's ``makeUpgradeServer``: answers an upgrade with a 101 (echoing
    the path and the authorization), sends ``hello|``, echoes each chunk and
    answers the client's half-close with ``bye``; the event is set once the
    client closes the connection."""
    listener = socket.create_server(("127.0.0.1", 0))
    closed = threading.Event()

    def serve() -> None:
        with contextlib.suppress(OSError):
            conn, _ = listener.accept()
            with conn:
                head = b""
                while b"\r\n\r\n" not in head:
                    head += conn.recv(4096)
                lines = head.decode().split("\r\n")
                fields = {k.lower(): v for k, _, v in (h.partition(": ") for h in lines[1:] if h)}
                conn.sendall(
                    "HTTP/1.1 101 Switching Protocols\r\nConnection: Upgrade\r\n"
                    f"Upgrade: {fields['upgrade']}\r\nX-Url: {lines[0].split()[1]}\r\n"
                    f"X-Authorization: {fields['authorization']}\r\n\r\nhello|".encode()
                )
                while chunk := conn.recv(4096):
                    conn.sendall(b"echo:" + chunk + b"|")
                conn.sendall(b"bye")
            closed.set()

    threading.Thread(target=serve, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{listener.getsockname()[1]}", closed
    finally:
        listener.close()


def _upgrade_client(
    base_url: str, client: HttpClientService[HttpClientError]
) -> HttpClientService[HttpClientError]:
    def prefixed(request: req.HttpClientRequest) -> req.HttpClientRequest:
        return request.prepend_url(f"{base_url}/base").bearer_token("token")

    return client.map_request(prefixed)


def _read_until_close(reader: Reader) -> fx.Effect[str]:
    def until_closed(_: SocketError) -> fx.Effect[tuple[str | bytes, ...] | None]:
        return fx.succeed(None)

    def loop() -> Generator[Any, Any, str]:
        text = ""
        while True:
            chunks = yield from reader.pull.catch_all(until_closed)
            if chunks is None:
                return text
            for chunk in chunks:
                text += chunk if isinstance(chunk, str) else chunk.decode()

    return fx.gen(loop)


@testing.live(timeout="10 seconds")
def test_upgrade_hands_over_the_connection(http: Services[HttpClient]):
    """NodeHttpClient upgrade / hands over the connection of a 101 response"""
    with _upgrade_server() as (base_url, _closed):
        client = _upgrade_client(base_url, (yield from httpx_client.make()))
        response = yield from client.execute(req.post("/attach").upgrade("tcp"))
        assert response.status == 101
        assert response.headers["upgrade"] == "tcp"
        assert response.headers["x-url"] == "/base/attach"
        assert response.headers["x-authorization"] == "Bearer token"
        upgraded = yield from response.upgrade
        reader = yield from upgraded.reader
        # releasing the writer half-closes, so the server answers "bye"
        yield from scoped(upgraded.writer.flat_map(lambda writer: writer.write("ping")))
        assert (yield from _read_until_close(reader)) == "hello|echo:ping|bye"


@testing.live(timeout="10 seconds")
def test_upgrade_closes_with_the_request_scope(http: Services[HttpClient]):
    """NodeHttpClient upgrade / closes the upgraded connection when the request scope closes"""
    with _upgrade_server() as (base_url, closed):
        client = _upgrade_client(base_url, (yield from httpx_client.make())).with_scope()

        def request() -> Any:
            response = yield from client.execute(req.post("/attach").upgrade("tcp"))
            assert response.status == 101

        yield from scoped(fx.gen(request))
        assert (yield from fx.sync(lambda: closed.wait(1))), "the connection is still open"


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


def test_url_params_body_preserves_a_leading_question_mark() -> None:
    """request and response urlParamsBody preserve a leading question mark

    Against the live server, whose handler parses the request body and echoes
    its key behind another raw question mark."""
    from pyfect.http import router, server_response
    from pyfect.http import url_params as up
    from pyfect.http.server_request import HttpServerRequest

    from ._live_http import run_live

    echo = HttpServerRequest().flat_map(
        lambda request: request.url_params_body.map(
            lambda params: server_response.text(
                f"?{up.to_string(params)}", content_type="application/x-www-form-urlencoded"
            )
        )
    )
    app = router.add("POST", "/question-form", echo)

    @fx.fn
    def program():
        client = yield from HttpClient()
        response = yield from client.post(
            "/question-form",
            body=body.text("?name=value", "application/x-www-form-urlencoded"),
        )
        return list((yield from response.url_params_body))

    served = program().pipe(fx.provide(router.serve(app, disable_logger=True)))
    assert run_live(served) == [("??name", "value")]


def _single_connection_client() -> fx.Layer[HttpClient]:
    """``layerNodeHttpOptions({ maxSockets: 1 })``: an httpx client with one
    connection, sending relative URLs to the server."""
    import httpx

    from pyfect.http import httpx_client

    from ._http_server import base_url

    base = base_url()
    return fx.layer.effect(
        HttpClient,
        httpx_client.make(limits=httpx.Limits(max_connections=1)).map(
            lambda client: client.map_request(lambda r: r.prepend_url(base))
        ),
    )


single_connection = testing.layer_fixture(_single_connection_client(), live=True)


@testing.live(timeout="10 seconds")
def test_follow_redirects_releases_bodies(single_connection: Services[HttpClient]):
    """followRedirects releases redirect response bodies with a single socket"""
    client = (yield from HttpClient()).follow_redirects()
    response = yield from client.get("/redirect-body").timeout("2 seconds")
    assert (yield from response.text) == "redirected"


@testing.live(timeout="10 seconds")
def test_follow_redirects_releases_scoped_bodies(single_connection: Services[HttpClient]):
    """followRedirects releases scoped redirect response bodies with a single socket"""

    @fx.fn
    def program():
        client = (yield from HttpClient()).with_scope().follow_redirects()
        response = yield from client.get("/redirect-body")
        return (yield from response.text)

    assert (yield from fx.scoped(program()).timeout("2 seconds")) == "redirected"


@testing.live(timeout="10 seconds")
def test_form_data_file_stream_cannot_be_created(http: Services[HttpClient]):
    """returns TransportError when a form data file stream cannot be created"""

    def throwing() -> fx.Stream[bytes]:
        raise RuntimeError("file stream failed")

    form = body.FormData().append("file", body.File(throwing, "notes.txt"))
    error = yield from c.post("/", body=body.form_data(form)).flip()
    assert isinstance(error, c.HttpClientError)
    assert error.reason.tag == "TransportError"
    assert isinstance(error.reason.cause, RuntimeError)


def _paused_server() -> tuple[str, Callable[[], None]]:
    """``createServer((request) => request.pause())``: a server that accepts
    connections and never reads them; the function closes it."""
    import socket
    import threading

    listener = socket.create_server(("127.0.0.1", 0))
    accepted: list[socket.socket] = []

    def accept() -> None:
        while True:
            try:
                conn, _ = listener.accept()
            except OSError:
                return
            conn.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 64 * 1024)
            accepted.append(conn)

    threading.Thread(target=accept, daemon=True).start()

    def close() -> None:
        listener.close()
        for conn in accepted:
            conn.close()

    return f"http://127.0.0.1:{listener.getsockname()[1]}", close


@testing.live(timeout="10 seconds")
def test_form_data_files_read_on_demand():
    """reads backpressured form data files on demand and releases them on interruption"""
    from pyfect.http import httpx_client
    from pyfect.schedule import spaced

    url, close = _paused_server()
    chunk = bytes(64 * 1024)
    read = [0]
    released = [False]

    def next_chunk(n: int) -> fx.Effect[tuple[bytes, int] | None]:
        def pull() -> tuple[bytes, int] | None:
            if read[0] == 64 * 1024 * 1024:
                return None
            read[0] += len(chunk)
            return chunk, n + 1

        return fx.sync(pull)

    def large() -> fx.Stream[bytes]:
        return fx.stream.unfold(0, next_chunk).ensuring(
            fx.sync(lambda: released.__setitem__(0, True))
        )

    @fx.fn
    def program():
        form = body.FormData().append("file", body.File(large, "large.bin"))
        yield from c.post(f"{url}/", body=body.form_data(form)).timeout("1 second").ignore()
        # The server never reads the upload, so only socket buffers should fill.
        assert read[0] < 16 * 1024 * 1024
        yield from (
            fx.sync(lambda: released[0])
            .repeat(while_=lambda done: not done, schedule=spaced("10 millis"))
            .timeout("1 second")
        )

    try:
        yield from program().pipe(fx.provide(httpx_client.layer))
    finally:
        close()
