"""Ports of platform-node's ``NodeHttpServer.test.ts`` that exercise the
server's features through the live server and its httpx test client.
Each test's docstring is the Effect test title. Omissions are listed in
``test_node_http_server.py``."""

from __future__ import annotations

import socket
import ssl
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, TypedDict

import pytest

import pyfect as fx
from pyfect import effect, layer, stream
from pyfect import schema as S
from pyfect.byte_size import ByteSize
from pyfect.clock import sleep
from pyfect.http import body as http_body
from pyfect.http import live_server, multipart, router, server, server_response
from pyfect.http.client import HttpClient
from pyfect.http.middleware import search_params_parser
from pyfect.http.request import post as post_request
from pyfect.http.server_request import (
    HttpServerRequest,
    ParsedSearchParams,
    schema_body_form,
    schema_body_form_json,
    schema_body_url_params,
)
from pyfect.http.server_response import HttpServerResponse
from pyfect.layer import effect as layer_effect
from pyfect.layer import provide_merge

from ._live_http import parse_responses, port, run_live

FIXTURES = Path(__file__).parent / "fixtures" / "node-http-server"


class Todo(TypedDict):
    id: float
    title: str


class IdParams(TypedDict):
    id: float


TodoSchema = S.Struct(Todo)
IdParamsSchema = S.Struct(IdParams, id=S.FiniteFromString)
todo_response = server_response.schema_json(TodoSchema)


def _routed(app: fx.Layer[Any, Any, Any], program: fx.Effect[Any, Any, Any]) -> Any:
    return run_live(program.pipe(fx.provide(router.serve(app, disable_logger=True))))


def _get_json(path: str) -> fx.Effect[Any, Any, HttpClient]:
    return HttpClient().flat_map(lambda client: client.get(path)).flat_map(lambda r: r.json)


def _post(path: str, body: Any) -> fx.Effect[Any, Any, HttpClient]:
    return HttpClient().flat_map(lambda client: client.post(path, body=body))


def test_schema() -> None:
    """schema"""
    app = router.add(
        "GET",
        "/todos/:id",
        router.schema_params(IdParamsSchema).flat_map(
            lambda params: todo_response({"id": params["id"], "title": "test"})
        ),
    )
    assert _routed(app, _get_json("/todos/1")) == {"id": 1, "title": "test"}


class Value(TypedDict):
    value: str


class Body(TypedDict):
    body: Value


def test_schema_json_applies_a_json_reviver() -> None:
    """schemaJson applies a JSON reviver"""
    decoded: list[object] = []
    app = router.add(
        "POST",
        "/json",
        router.schema_json(
            S.Struct(Body, body=S.Struct(Value)),
            reviver=lambda key, value: "revived" if key == "value" else value,
        )
        .tap(lambda value: effect.sync(lambda: decoded.append(value)))
        .as_(server_response.empty()),
    )
    response = _routed(app, _post("/json", http_body.json_unsafe({"value": "original"})))
    assert response.status == 204
    assert decoded == [{"body": {"value": "revived"}}]


def _form_with_file(name: str = "file") -> http_body.FormData:
    return http_body.FormData().append(name, http_body.File(b"test", "test.txt", "text/plain"))


def test_form_data() -> None:
    """formData"""

    @fx.fn
    def upload():
        request = yield from HttpServerRequest()
        form = yield from request.multipart
        [file] = form["file"]
        assert isinstance(file, multipart.PersistedFile)
        assert file.path.endswith("/test.txt")
        assert file.content_type == "text/plain"
        return (yield from server_response.json({"ok": "file" in form}))

    app = router.add("POST", "/upload", upload())
    result = _routed(app, _post("/upload", _form_with_file()).flat_map(lambda r: r.json))
    assert result == {"ok": True}


def test_schema_body_form() -> None:
    """schemaBodyForm"""

    class Upload(TypedDict):
        file: tuple[multipart.PersistedFile, ...]
        test: str

    seen: list[object] = []
    app = router.add(
        "POST",
        "/upload",
        schema_body_form(S.Struct(Upload, file=multipart.FilesSchema))
        .tap(lambda files: effect.sync(lambda: seen.append(sorted(files))))
        .as_(server_response.empty()),
    )
    form = _form_with_file().append("test", "test")
    assert _routed(app, _post("/upload", form)).status == 204
    assert seen == [["file", "test"]]


@pytest.mark.parametrize(
    ("limit", "tag", "form"),
    [
        (
            multipart.MaxFileSize,
            "FileTooLarge",
            http_body.FormData().append(
                "file", http_body.File(bytes(1000), "test.txt", "text/plain")
            ),
        ),
        (
            multipart.MaxFieldSize,
            "FieldTooLarge",
            http_body.FormData().append("file", "\x01" * 1000),
        ),
    ],
    ids=["formData withMaxFileSize", "formData withMaxFieldSize"],
)
def test_form_data_with_max_size(limit: Any, tag: str, form: http_body.FormData) -> None:
    """formData withMaxFileSize / formData withMaxFieldSize"""

    def recover(error: Any) -> fx.Effect[HttpServerResponse, Any]:
        if isinstance(error, multipart.MultipartError) and error.reason.tag == tag:
            return effect.succeed(server_response.empty(status=413))
        return effect.fail(error)

    handler: fx.Effect[HttpServerResponse, Any, Any] = (
        HttpServerRequest()
        .flat_map(lambda request: request.multipart)
        .as_(server_response.empty())
        .catch_all(recover)
    )
    app = router.add("POST", "/upload", handler)
    program = _post("/upload", form).map(lambda r: r.status)
    served: fx.Effect[int, Any, Any] = program.pipe(
        fx.provide(router.serve(app, disable_logger=True))
    )
    assert run_live(served.pipe(effect.provide_service(limit, ByteSize(100)))) == 413


def test_mount_app() -> None:
    """mountApp"""
    child = HttpServerRequest().map(lambda request: server_response.text(request.url))
    app = router.use(lambda service: service.prefixed("/child").add("*", "*", child))

    @fx.fn
    def program():
        client = yield from HttpClient()
        texts: list[str] = []
        for path in ("/child/1", "/child", "/child?foo=bar", "/child/"):
            response = yield from client.get(path)
            texts.append((yield from response.text))
        invalid = yield from client.get("/child1/", url_params={"foo": "bar"})
        return texts, invalid.status

    assert _routed(app, program()) == (["/1", "/", "/?foo=bar", "/"], 404)


def test_file() -> None:
    """file"""
    from pyfect.http.platform import HttpPlatform

    def with_etag(platform: Any) -> Any:
        def tagged(response: HttpServerResponse) -> HttpServerResponse:
            return response.set_header("etag", '"etag"')

        def file_response(path: str, **options: Any) -> fx.Effect[HttpServerResponse, Any]:
            response: fx.Effect[HttpServerResponse, Any] = platform.file_response(path, **options)
            return response.map(tagged)

        return type(platform)(
            platform.platform, platform.compression, file_response, platform.file_web_response
        )

    @fx.fn
    def program():
        platform = yield from HttpPlatform()
        response = yield from server_response.file(str(FIXTURES / "text.txt")).pipe(
            effect.provide_service(HttpPlatform, with_etag(platform))
        )
        yield from server.serve_effect(effect.succeed(response))
        client = yield from HttpClient()
        res = yield from client.get("/")
        return res.status, res.headers, (yield from res.text)

    status, headers, text = run_live(program())
    assert status == 200
    assert headers["content-type"] == "text/plain"
    assert headers["content-length"] == "27"
    assert headers["etag"] == '"etag"'
    assert text.strip() == "lorem ipsum dolar sit amet"


class TodoForm(TypedDict):
    id: float
    title: str


TodoFormSchema = S.Struct(TodoForm, id=S.FiniteFromString)


def test_schema_body_url_params() -> None:
    """schemaBodyUrlParams"""
    app = router.add(
        "POST",
        "/todos",
        schema_body_url_params(TodoFormSchema).flat_map(
            lambda todo: todo_response({"id": todo["id"], "title": todo["title"]})
        ),
    )

    @fx.fn
    def program():
        client = yield from HttpClient()
        request = post_request("/todos", body=http_body.url_params({"id": "1", "title": "test"}))
        response = yield from client.execute(request)
        return (yield from response.json)

    assert _routed(app, program()) == {"id": 1, "title": "test"}


def test_schema_body_url_params_error() -> None:
    """schemaBodyUrlParams error"""

    def bad_request(error: Any) -> fx.Effect[HttpServerResponse]:
        if isinstance(error, S.SchemaError):
            return effect.succeed(server_response.json_unsafe({"error": str(error)}, status=400))
        return effect.die(error)

    app = router.add(
        "GET",
        "/todos",
        schema_body_url_params(TodoFormSchema)
        .flat_map(lambda todo: todo_response({"id": todo["id"], "title": todo["title"]}))
        .catch_all(bad_request),
    )
    program = HttpClient().flat_map(lambda client: client.get("/todos")).map(lambda r: r.status)
    assert _routed(app, program) == 400


class JsonField(TypedDict):
    test: str


def _revive_test(key: str, value: object) -> object:
    return "revived" if key == "test" else value


@pytest.mark.parametrize(
    ("body", "reviver", "expected"),
    [
        (
            http_body.FormData().append("json", '{"test": "content"}'),
            _revive_test,
            "revived",
        ),
        (
            http_body.FormData().append(
                "json", http_body.File(b'{"test": "content"}', "test.json", "application/json")
            ),
            None,
            "content",
        ),
        (http_body.url_params({"json": '{"test": "content"}'}), None, "content"),
    ],
    ids=["schemaBodyFormJson", "schemaBodyFormJson file", "schemaBodyFormJson url encoded"],
)
def test_schema_body_form_json(body: Any, reviver: Any, expected: str) -> None:
    """schemaBodyFormJson / schemaBodyFormJson file / schemaBodyFormJson url encoded"""
    seen: list[str] = []
    app = router.add(
        "POST",
        "/upload",
        schema_body_form_json(S.Struct(JsonField), reviver=reviver)("json")
        .tap(lambda result: effect.sync(lambda: seen.append(result["test"])))
        .as_(server_response.empty()),
    )
    assert _routed(app, _post("/upload", body)).status == 204
    assert seen == [expected]


def test_html() -> None:
    """html"""
    app = router.add_all(
        [
            router.route("GET", "/home", server_response.html("<html />")),
            router.route(
                "GET",
                "/about",
                server_response.html_template(["<html>", "</html>"], effect.succeed("<body />")),
            ),
            router.route(
                "GET",
                "/stream",
                server_response.html_stream(
                    ["<html>", "</html>"], stream.make("<body />", 123, "hello")
                ),
            ),
        ]
    )

    @fx.fn
    def program():
        client = yield from HttpClient()
        texts: list[str] = []
        for path in ("/home", "/about", "/stream"):
            response = yield from client.get(path)
            texts.append((yield from response.text))
        return texts

    assert _routed(app, program()) == [
        "<html />",
        "<html><body /></html>",
        "<html><body />123hello</html>",
    ]


def test_set_cookie() -> None:
    """setCookie"""
    expires = datetime(2022, 2, 1, tzinfo=UTC)
    response = (
        server_response.empty()
        .set_cookie_unsafe("test", "value")
        .set_cookie_unsafe(
            "test2",
            "value2",
            http_only=True,
            secure=True,
            same_site="lax",
            partitioned=True,
            path="/",
            domain="example.com",
            expires=expires,
            max_age=300,
        )
    )
    app = router.add("GET", "/home", response)
    program = HttpClient().flat_map(lambda client: client.get("/home")).map(lambda r: r.cookies)
    cookies = _routed(app, program)
    assert cookies == response.cookies


def test_uninterruptible_routes() -> None:
    """uninterruptible routes"""
    from pyfect._fiber import Fiber

    @fx.fn
    def handler():
        fiber = Fiber.get_current()
        assert fiber is not None
        yield from (
            effect.sync(lambda: fiber.interrupt_as_unsafe(fiber.id)).delay(0.01).fork_daemon()
        )
        yield from sleep(0.05)
        return server_response.empty()

    app = router.add("GET", "/home", handler(), uninterruptible=True)
    program = HttpClient().flat_map(lambda client: client.get("/home")).map(lambda r: r.status)
    assert _routed(app, program) == 204


def test_error_schema() -> None:
    """HttpServerRespondable error/schema"""

    class CustomError(S.TaggedError):
        name: str

        def __http_response__(self) -> fx.Effect[HttpServerResponse, Any]:
            return server_response.schema_json(CustomError)(self, status=599)

    app = router.add("GET", "/home", effect.fail(CustomError(name="test")))

    @fx.fn
    def program():
        client = yield from HttpClient()
        response = yield from client.get("/home")
        return response.status, (yield from response.json)

    status, body = _routed(app, program())
    assert status == 599
    decoded = fx.run_blocking(S.decode_unknown_effect(CustomError)(body).or_die())
    assert decoded == CustomError(name="test")


def test_search_params_parser_parses_the_query() -> None:
    """request URL searchParamsParser parses the query"""
    app = router.add(
        "GET",
        "/search",
        search_params_parser(
            ParsedSearchParams().flat_map(lambda params: server_response.json(dict(params)))
        ),
    )
    assert _routed(app, _get_json("/search?a=1&a=2&b=3")) == {"a": ["1", "2"], "b": "3"}


@dataclass(frozen=True)
class _Tls:
    port: int


def test_to_url_reports_https_over_tls() -> None:
    """request URL toURL reports https over TLS"""
    echo = HttpServerRequest().map(
        lambda request: server_response.text(
            f"{request.headers.get('host')} {request.url} {request.original_url}"
        )
    )
    app = router.add("GET", "*", echo)
    tls_server = layer_effect(
        server.HttpServer,
        live_server.make_tls(
            cert=(FIXTURES / "cert.pem").read_text(),
            key=(FIXTURES / "key.pem").read_text(),
            host="127.0.0.1",
        ),
    )
    served = router.serve(app, disable_logger=True).pipe(
        provide_merge(layer.merge(tls_server, live_server.layer_services))
    )

    def request(at: int) -> bytes:
        context = ssl.create_default_context()
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
        with (
            socket.create_connection(("127.0.0.1", at), timeout=5) as raw,
            context.wrap_socket(raw) as conn,
        ):
            conn.sendall(
                f"GET /x?y=1 HTTP/1.1\r\nHost: 127.0.0.1:{at}\r\nConnection: close\r\n\r\n".encode()
            )
            received = bytearray()
            while chunk := conn.recv(65536):
                received += chunk
            return bytes(received)

    @fx.fn
    def program():
        at = yield from port
        return at, (yield from effect.blocking(lambda: request(at)))

    at, received = fx.run_blocking(program().pipe(fx.provide(served)).or_die())
    [response] = parse_responses(received)
    assert response.body.decode() == f"127.0.0.1:{at} /x?y=1 https://127.0.0.1:{at}/x?y=1"
