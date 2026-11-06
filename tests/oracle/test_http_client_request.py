"""Ports of Effect's ``http/HttpClientRequest.test.ts``.

Each test's docstring is the Effect test title. The request operations are
``HttpClientRequest`` methods; the ``Uint8Array`` body is ``body.Bytes``;
``hash`` is ``None`` when absent; ``Formatter.format`` and ``inspect`` are
``repr``.

Adapted, with the reason:

- ``round-trips $name as compressed bytes`` and ``sets the exact outgoing
  Content-Length for $name`` drop their ``toWeb`` checks: there is no web
  ``Request``; the httpx backend sends the body and headers checked here.

Omitted, with the reason:

- ``fromWeb``, ``fromWeb ignores malformed or unsafe content lengths``,
  ``toWeb stream body``, ``toWebResult returns failure for invalid url``:
  web ``Request`` conversions (``to_url`` covers the invalid URL).
- ``supports the data-first overload``, ``preserves the request
  prototype`` (twice): there is one method form, and every operation gives
  an ``HttpClientRequest``.
"""

import gzip
import json
import zlib
from typing import Any

import pytest

import pyfect as fx
from pyfect import stream as stream_
from pyfect.byte_size import ByteSize
from pyfect.file_system import FileInfo, FileSystem, NoopFileSystem
from pyfect.http import body as b
from pyfect.http import headers as h
from pyfect.http import request as r
from pyfect.http import url as u
from pyfect.http._compression import CompressionAlgorithm
from pyfect.platform_error import PlatformError
from pyfect.redacted import Redacted
from pyfect.stream import Stream


def _run[A](eff: fx.Effect[A, object]) -> A:
    return fx.run_blocking(eff.or_die())


URL = "https://example.com"
TEXT = "hello compression " * 100
DATA = TEXT.encode()


def _decompress(algorithm: CompressionAlgorithm, data: bytes) -> str:
    return (gzip.decompress(data) if algorithm == "gzip" else zlib.decompress(data)).decode()


def _bytes_body(request: r.HttpClientRequest) -> b.Bytes:
    assert isinstance(request.body, b.Bytes)
    return request.body


@pytest.mark.parametrize(
    ("body", "expected", "algorithm"),
    [
        pytest.param(b.bytes_(DATA, "application/custom"), TEXT, "gzip", id="bytes"),
        pytest.param(b.text(TEXT), TEXT, "gzip", id="lazy text"),
        pytest.param(
            b.json_unsafe({"text": TEXT}),
            json.dumps({"text": TEXT}, separators=(",", ":")),
            "gzip",
            id="JSON",
        ),
        pytest.param(b.bytes_(DATA), TEXT, "deflate", id="deflate"),
    ],
)
def test_compress_round_trip(body: b.Bytes, expected: str, algorithm: CompressionAlgorithm) -> None:
    """round-trips $name as compressed bytes"""
    request = _run(r.post(URL).set_body(body).compress_body(algorithm))
    compressed = _bytes_body(request)
    assert _decompress(algorithm, compressed.body) == expected
    assert compressed.text is None
    assert compressed.content_type == body.content_type
    assert compressed.content_length == len(compressed.body)
    assert request.headers["content-type"] == body.content_type
    assert request.headers["content-encoding"] == algorithm
    assert request.headers["content-length"] == str(len(compressed.body))
    assert _run(request.compress_body(algorithm)) is request


@pytest.mark.parametrize(
    ("text", "options", "compressed"),
    [
        ("a" * 1023, {}, False),
        ("a" * 1024, {}, True),
        ("éé", {"min_size": 5}, False),
        ("éé", {"min_size": 4}, True),
    ],
)
def test_compress_threshold(text: str, options: dict[str, Any], compressed: bool) -> None:
    """applies the byte threshold at $options with $text.length characters"""
    original = r.post(URL).body_text(text)
    request = _run(original.compress_body("gzip", **options))
    if compressed:
        assert request.headers["content-encoding"] == "gzip"
        assert gzip.decompress(_bytes_body(request).body).decode() == text
    else:
        assert request is original
        assert "content-encoding" not in request.headers


def test_compress_unsupported() -> None:
    """leaves unsupported bodies and existing content encodings unchanged"""
    for body in (b.EMPTY, b.form_data(b.FormData()), b.raw(DATA)):
        original = r.post(URL).set_body(body)
        request = _run(original.compress_body("gzip", min_size=0))
        assert request is original
        assert "content-encoding" not in request.headers
    for encoding in ("identity", "deflate", "gzip"):
        original = r.post(URL).body_text(TEXT).set_header("Content-Encoding", encoding)
        assert _run(original.compress_body("gzip")) is original


@pytest.mark.parametrize(
    ("text", "content_length"),
    [
        pytest.param(TEXT, len(DATA), id="known length"),
        pytest.param("tiny", None, id="unknown length below minSize"),
    ],
)
def test_compress_stream(text: str, content_length: int | None) -> None:
    """compresses a stream with $name without a content length"""
    source = text.encode()
    original = r.post(URL).body_stream(
        stream_.make(source[:2], source[2:]),
        content_type="text/plain",
        content_length=content_length,
    )
    request = _run(original.compress_body("gzip"))
    assert isinstance(request.body, b.Stream)
    assert "content-length" not in request.headers
    assert request.headers["content-encoding"] == "gzip"
    assert request.headers["content-type"] == "text/plain"
    assert request.body.content_length is None
    compressed = b"".join(_run(request.body.stream.run_collect()))
    assert gzip.decompress(compressed).decode() == text


OVERSIZED = 9007199254740993


def _file_system(size: int) -> NoopFileSystem:
    info = FileInfo(
        type="File",
        mtime=None,
        atime=None,
        birthtime=None,
        dev=0,
        ino=None,
        mode=0o644,
        nlink=None,
        uid=None,
        gid=None,
        rdev=None,
        size=ByteSize(size),
        blksize=None,
        blocks=None,
    )

    class Fs(NoopFileSystem):
        def stat(self, path: str) -> fx.Effect[FileInfo, PlatformError]:
            return fx.succeed(info)

        def stream(
            self,
            path: str,
            *,
            offset: int = 0,
            bytes_to_read: int | None = None,
            chunk_size: int = 65536,
        ) -> Stream[bytes, PlatformError]:
            return stream_.empty

    return Fs()


@pytest.mark.parametrize(
    ("size", "options", "expected"),
    [
        pytest.param(OVERSIZED + 3, {"offset": OVERSIZED}, 3, id="unsafe bigint offset"),
        pytest.param(6, {"offset": 7}, 0, id="range past EOF"),
    ],
)
def test_body_file_content_length(size: int, options: dict[str, Any], expected: int) -> None:
    """sets the exact outgoing Content-Length for $name"""
    request = _run(
        r.post(URL)
        .body_text("stale")
        .body_file("x", content_type="application/octet-stream", **options)
        .pipe(fx.provide_service(FileSystem, _file_system(size)))
    )
    assert isinstance(request.body, b.Stream)
    assert request.body.content_length == expected
    assert request.headers["content-length"] == str(expected)
    assert request.headers["content-type"] == "application/octet-stream"


def test_body_file_bad_argument() -> None:
    """propagates typed BadArgument from file range validation"""
    error = _run(
        r.post(URL)
        .body_file("x", bytes_to_read="garbage")
        .pipe(fx.provide_service(FileSystem, _file_system(6)))
        .flip()
    )
    assert error.reason.tag == "BadArgument"


def test_append_url_joins() -> None:
    """joins segments without slashes"""
    assert r.get("base").append_url("users").url == "base/users"


def test_append_url_double_slash() -> None:
    """avoids double slashes"""
    assert r.get("base/").append_url("/users").url == "base/users"


def test_append_url_existing_slash() -> None:
    """preserves existing slash"""
    assert r.get("base/").append_url("users").url == "base/users"


def test_append_url_leading_slash() -> None:
    """preserves leading slash"""
    assert r.get("base").append_url("/users").url == "base/users"


def test_append_url_empty() -> None:
    """no-ops on empty path"""
    assert r.get("base").append_url("").url == "base"


def test_form_data_record() -> None:
    """creates a form data body from a record"""
    request = r.post("/").body_form_data_record(
        {"a": "a", "b": 1, "c": True, "d": None, "f": ["x", 2, False, None]}
    )
    assert isinstance(request.body, b.FormData)
    form = request.body
    assert form.get_all("a") == ["a"]
    assert form.get_all("b") == ["1"]
    assert form.get_all("c") == ["true"]
    assert form.get_all("d") == []
    assert form.get_all("f") == ["x", "2", "false"]


def test_form_data_removes_content_headers() -> None:
    """removes content headers when switching to form data"""
    request = r.post("/").body_text("hello").body_form_data_record({"a": "a"})
    assert "content-type" not in request.headers
    assert "content-length" not in request.headers


def test_set_body_stale_length() -> None:
    """removes stale content length when the replacement body has no known length"""
    request = r.post(URL).body_text("abc").set_body(b.stream(stream_.empty))
    assert "content-length" not in request.headers


def test_remove_header() -> None:
    """removes an existing header"""
    request = r.get("/").set_header("X-Test", "ok").remove_header("X-Test")
    assert "x-test" not in request.headers


def test_remove_missing_header() -> None:
    """no-ops on a missing header"""
    request = r.get("/").set_header("X-Test", "ok")
    assert request.remove_header("X-Missing").headers == request.headers


def test_update_headers() -> None:
    """transforms the header collection"""
    request = (
        r.get("/")
        .set_headers({"X-A": "a", "X-B": "b"})
        .update_headers(lambda headers: headers.remove("X-A").set("X-C", "c"))
    )
    assert request.headers == h.from_input({"x-b": "b", "x-c": "c"})


def test_hash_stored() -> None:
    """stores hash as Option"""
    request = r.get(u.parse("http://example.com/path?x=1#section"))
    assert request.hash == "section"
    url = request.to_url()
    assert url is not None
    assert u.href(url) == "http://example.com/path?x=1#section"


def test_remove_hash() -> None:
    """removes hash"""
    assert r.get("http://example.com").set_hash("section").remove_hash().hash is None


def test_invalid_url() -> None:
    """returns none for invalid url"""
    assert r.get("http://example.com").set_url("http://[::1").to_url() is None


def test_to_json_redacts() -> None:
    """redacts sensitive query params in url and urlParams"""
    request = r.get(
        "https://api.test/path?Signature=url-secret&page=1",
        url_params={"sig": "param-secret", "q": "visible"},
    )
    assert request.to_json()["url"] == "https://api.test/path?Signature=REDACTED&page=1"
    output = repr(request)
    assert "url-secret" not in output
    assert "param-secret" not in output
    assert "visible" in output


def test_hides_redacted_params() -> None:
    """hides Redacted url params from inspection"""
    request = (
        r.get("https://api.test/path")
        .set_url_param("remote", Redacted("param-secret"))
        .append_url_param("q", "visible")
    )
    for output in (str(request.to_json()), str(request), repr(request)):
        assert "param-secret" not in output
        assert "visible" in output
