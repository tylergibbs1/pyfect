"""Ports of platform-node's ``HttpStaticServer.test.ts``, against the live
file system and ``platform.layer_strong`` (``NodeHttpPlatform.layer``).

Each test's docstring is the Effect test title. The fixtures are copied
from the Effect tests. The mocked ``fs.createReadStream`` is a
``LiveFileSystem`` recording each stream it opens as ``(path, start,
end)`` (Node's inclusive ``end``).
"""

import asyncio
import os
import shutil
from collections.abc import Callable, Coroutine, Iterator
from pathlib import Path
from typing import Any
from urllib.parse import quote, urljoin

import pytest

from pyfect import effect, layer, stream
from pyfect.file_system import FileSystem
from pyfect.file_system._live import LiveFileSystem
from pyfect.http import router
from pyfect.http import static_server as static
from pyfect.http.platform import layer_strong as platform_layer
from pyfect.http.web import WebRequest
from pyfect.http.web_handler import WebHandler
from pyfect.path import layer as path_layer
from pyfect.platform_error import PlatformError

FIXTURES = Path(__file__).parent / "fixtures"
UNSAFE_RANGE_INTEGER = str(2**53)

Opened = tuple[str, int, int | None]


class RecordingFileSystem(LiveFileSystem):
    __slots__ = ("opened",)

    def __init__(self) -> None:
        super().__init__()
        self.opened: list[Opened] = []

    def stream(
        self, path: str, *, offset: int = 0, bytes_to_read: int | None = None, **options: Any
    ) -> stream.Stream[bytes, PlatformError]:
        end = None if bytes_to_read is None else offset + bytes_to_read - 1
        inner = super().stream(path, offset=offset, bytes_to_read=bytes_to_read, **options)

        def open_() -> stream.Stream[bytes, PlatformError]:
            self.opened.append((path, offset, end))
            return inner

        return stream.unwrap(effect.sync(open_))


class Context:
    def __init__(self, root: Path, outside_file: Path, file_system: RecordingFileSystem) -> None:
        self.root = root
        self.outside_file = outside_file
        self.file_system = file_system
        self.handler: WebHandler


type Run = Callable[[Context], Coroutine[Any, Any, None]]


@pytest.fixture
def temporary_root(tmp_path: Path) -> Iterator[tuple[Path, Path]]:
    root = tmp_path / "root"
    shutil.copytree(FIXTURES / "http-static-server", root)
    outside = tmp_path / "http-static-server-outside.txt"
    shutil.copyfile(FIXTURES / "http-static-server-outside.txt", outside)
    yield root, outside


def with_static_files(paths: tuple[Path, Path], run: Run, **options: Any) -> None:
    root, outside = paths
    file_system = RecordingFileSystem()
    fs_layer = layer.succeed(FileSystem, file_system)
    services = layer.merge(path_layer, fs_layer).pipe(
        layer.provide_merge(platform_layer.pipe(layer.provide(fs_layer)))
    )
    app = static.layer(root=str(root), **options).pipe(layer.provide_merge(services))
    context = Context(root, outside, file_system)

    async def main() -> None:
        made = router.to_web_handler(app, disable_logger=True)
        context.handler = made.handler
        try:
            await run(context)
        finally:
            await made.dispose()

    asyncio.run(main())


def get(url: str, headers: dict[str, str] | None = None) -> WebRequest:
    return WebRequest(f"http://localhost{url}", headers=headers)


def test_serves_files_with_expected_content_type_and_body(temporary_root: tuple[Path, Path]):
    """serves files with expected content type and body"""

    async def run(ctx: Context) -> None:
        response = await ctx.handler(get("/hello.txt"))
        assert response.status == 200
        assert response.get("content-type") == "text/plain; charset=utf-8"
        assert (await response.text()).rstrip() == "hello static file"

    with_static_files(temporary_root, run)


def test_serves_default_index_file_for_directory_paths(temporary_root: tuple[Path, Path]):
    """serves default index file for directory paths"""

    async def run(ctx: Context) -> None:
        response = await ctx.handler(get("/guide/"))
        assert response.status == 200
        assert response.get("content-type") == "text/html; charset=utf-8"
        assert (await response.text()).rstrip() == "<html><body>guide index</body></html>"

    with_static_files(temporary_root, run)


@pytest.mark.parametrize("prefix", ["", "/static"])
def test_redirects_directory_urls_with_their_query_string(
    temporary_root: tuple[Path, Path], prefix: str
):
    """redirects directory URLs with their query string under ${prefix || "/"}"""

    async def run(ctx: Context) -> None:
        response = await ctx.handler(get(f"{prefix}/guide?x=1&next=%2Fdocs"))
        assert response.status == 301
        location = response.get("location")
        assert location == f"{prefix}/guide/?x=1&next=%2Fdocs"
        index = await ctx.handler(WebRequest(urljoin("http://localhost", location)))
        assert index.status == 200
        assert index.get("location") is None
        assert (await index.text()).rstrip() == "<html><body>guide index</body></html>"

    with_static_files(temporary_root, run, **({"prefix": prefix} if prefix else {}))


def test_supports_custom_index_file_and_disabled_index_fallback(
    temporary_root: tuple[Path, Path],
):
    """supports custom index file and disabled index fallback"""

    async def custom(ctx: Context) -> None:
        response = await ctx.handler(get("/custom/"))
        assert response.status == 200
        assert (await response.text()).rstrip() == "<html><body>custom home</body></html>"

    async def disabled(ctx: Context) -> None:
        assert (await ctx.handler(get("/custom"))).status == 404

    with_static_files(temporary_root, custom, index="home.html")
    with_static_files(temporary_root, disabled, index=None)


def test_returns_304_for_if_none_match_exact_weak_and_wildcard(
    temporary_root: tuple[Path, Path],
):
    """returns 304 for If-None-Match exact, weak, and wildcard"""

    async def run(ctx: Context) -> None:
        etag = (await ctx.handler(get("/conditional.txt"))).get("etag")
        assert etag is not None
        weak_comparable = etag[2:] if etag.startswith("W/") else f"W/{etag}"
        exact = await ctx.handler(get("/conditional.txt", {"If-None-Match": etag}))
        weak = await ctx.handler(get("/conditional.txt", {"If-None-Match": weak_comparable}))
        any_ = await ctx.handler(get("/conditional.txt", {"If-None-Match": "*"}))
        assert [exact.status, weak.status, any_.status] == [304, 304, 304]
        assert exact.get("etag") == etag
        assert exact.get("cache-control") == "public, max-age=60"
        assert exact.get("content-type") is None
        assert exact.get("content-length") is None

    with_static_files(temporary_root, run, cache_control="public, max-age=60")


def test_returns_304_for_if_modified_since_and_200_when_file_changed(
    temporary_root: tuple[Path, Path],
):
    """returns 304 for If-Modified-Since and 200 when file changed"""

    async def run(ctx: Context) -> None:
        last_modified = (await ctx.handler(get("/conditional.txt"))).get("last-modified")
        assert last_modified is not None
        headers = {"If-Modified-Since": last_modified}
        assert (await ctx.handler(get("/conditional.txt", headers))).status == 304
        conditional_file = ctx.root / "conditional.txt"
        conditional_file.write_text("updated conditional body")
        updated = conditional_file.stat().st_mtime + 10
        os.utime(conditional_file, (updated, updated))
        modified = await ctx.handler(get("/conditional.txt", headers))
        assert modified.status == 200
        assert await modified.text() == "updated conditional body"

    with_static_files(temporary_root, run)


def test_honors_range_only_for_a_matching_strong_if_range_etag(
    temporary_root: tuple[Path, Path],
):
    """honors Range only for a matching strong If-Range ETag"""

    async def run(ctx: Context) -> None:
        first = await ctx.handler(get("/range.txt"))
        etag = first.get("etag")
        assert etag is not None
        assert not etag.startswith("W/")
        full_body = await first.text()
        ctx.file_system.opened.clear()

        matching = await ctx.handler(get("/range.txt", {"Range": "bytes=0-10", "If-Range": etag}))
        assert matching.status == 206
        assert matching.get("content-range") == f"bytes 0-10/{len(full_body)}"
        assert await matching.text() == "0123456789a"
        # Only the selected range opens the file, not the discarded full response.
        assert ctx.file_system.opened == [(str(ctx.root / "range.txt"), 0, 10)]

        # Weak tags and Last-Modified dates never match.
        last_modified = first.get("last-modified")
        assert last_modified is not None
        for if_range in (f"W/{etag}", last_modified):
            response = await ctx.handler(
                get("/range.txt", {"Range": "bytes=0-10", "If-Range": if_range})
            )
            assert response.status == 200
            assert response.get("content-range") is None
            assert await response.text() == full_body

    with_static_files(temporary_root, run)


@pytest.mark.parametrize("range_", ["bytes=10-", "bytes=100-200"])
def test_returns_the_full_changed_file_for_a_stale_if_range_etag(
    temporary_root: tuple[Path, Path], range_: str
):
    """returns the full changed file for a stale If-Range ETag with Range %s"""

    async def run(ctx: Context) -> None:
        first = await ctx.handler(get("/range.txt"))
        etag = first.get("etag")
        await first.text()
        updated_body = "NEW-NEW-NEW-NEW-NEW-NEW-"
        (ctx.root / "range.txt").write_text(updated_body)
        assert etag is not None
        resumed = await ctx.handler(get("/range.txt", {"Range": range_, "If-Range": etag}))
        assert resumed.status == 200
        assert resumed.get("content-range") is None
        assert resumed.get("content-length") == str(len(updated_body))
        assert resumed.get("etag") != etag
        assert await resumed.text() == updated_body

    with_static_files(temporary_root, run)


def test_handles_range_requests_for_valid_invalid_and_malformed_headers(
    temporary_root: tuple[Path, Path],
):
    """handles range requests for valid, invalid, and malformed headers"""

    async def run(ctx: Context) -> None:
        full = await ctx.handler(get("/range.txt"))
        etag = full.get("etag")
        assert etag is not None
        full_body = await full.text()
        size = len(full_body)

        first = await ctx.handler(get("/range.txt", {"Range": "bytes=0-10"}))
        assert first.status == 206
        assert first.get("content-range") == f"bytes 0-10/{size}"
        assert await first.text() == "0123456789a"

        open_ended = await ctx.handler(get("/range.txt", {"Range": "bytes=5-"}))
        assert open_ended.status == 206
        assert open_ended.get("content-range") == f"bytes 5-{size - 1}/{size}"
        assert await open_ended.text() == full_body[5:]

        suffix = await ctx.handler(get("/range.txt", {"Range": "bytes=-10"}))
        assert suffix.status == 206
        assert suffix.get("content-range") == f"bytes {size - 10}-{size - 1}/{size}"
        assert await suffix.text() == full_body[-10:]

        ctx.file_system.opened.clear()
        invalid = await ctx.handler(get("/range.txt", {"Range": "bytes=100-200", "If-Range": etag}))
        assert invalid.status == 416
        assert invalid.get("content-range") == f"bytes */{size}"
        assert await invalid.text() == ""
        assert ctx.file_system.opened == []

        malformed = await ctx.handler(get("/range.txt", {"Range": "bytes=abc"}))
        assert malformed.status == 200
        assert await malformed.text() == full_body

    with_static_files(temporary_root, run)


@pytest.mark.parametrize(
    "range_",
    [f"bytes={UNSAFE_RANGE_INTEGER}-", f"bytes={UNSAFE_RANGE_INTEGER}-{UNSAFE_RANGE_INTEGER}"],
)
def test_returns_416_for_a_range_start_above_max_safe_integer(
    temporary_root: tuple[Path, Path], range_: str
):
    """returns 416 for a range start above Number.MAX_SAFE_INTEGER: %s"""

    async def run(ctx: Context) -> None:
        full_body = await (await ctx.handler(get("/range.txt"))).text()
        response = await ctx.handler(get("/range.txt", {"Range": range_}))
        assert response.status == 416
        assert response.get("content-range") == f"bytes */{len(full_body)}"
        assert await response.text() == ""

    with_static_files(temporary_root, run)


@pytest.mark.parametrize(
    "range_", [f"bytes=0-{UNSAFE_RANGE_INTEGER}", f"bytes=-{UNSAFE_RANGE_INTEGER}"]
)
def test_returns_the_whole_file_as_206_for_range_ends_and_suffixes_above_max_safe_integer(
    temporary_root: tuple[Path, Path], range_: str
):
    """returns the whole file as 206 for range ends and suffixes above Number.MAX_SAFE_INTEGER: %s"""  # noqa: E501

    async def run(ctx: Context) -> None:
        full_body = await (await ctx.handler(get("/range.txt"))).text()
        size = len(full_body)
        response = await ctx.handler(get("/range.txt", {"Range": range_}))
        assert response.status == 206
        assert response.get("content-range") == f"bytes 0-{size - 1}/{size}"
        assert response.get("content-length") == str(size)
        assert await response.text() == full_body

    with_static_files(temporary_root, run)


def test_clamps_a_range_end_above_max_safe_integer_while_preserving_a_nonzero_start(
    temporary_root: tuple[Path, Path],
):
    """clamps a range end above Number.MAX_SAFE_INTEGER while preserving a nonzero start"""

    async def run(ctx: Context) -> None:
        full_body = await (await ctx.handler(get("/range.txt"))).text()
        size = len(full_body)
        response = await ctx.handler(
            get("/range.txt", {"Range": f"bytes=5-{UNSAFE_RANGE_INTEGER}"})
        )
        assert response.status == 206
        assert response.get("content-range") == f"bytes 5-{size - 1}/{size}"
        assert response.get("content-length") == str(size - 5)
        assert await response.text() == full_body[5:]

    with_static_files(temporary_root, run)


def test_handles_spa_fallback_for_html_accept_and_missing_routes(
    temporary_root: tuple[Path, Path],
):
    """handles SPA fallback for html accept and missing routes"""

    async def run(ctx: Context) -> None:
        html = await ctx.handler(get("/missing", {"accept": "text/html"}))
        assert html.status == 200
        assert (await html.text()).rstrip() == "<html><body>root index</body></html>"
        assert (await ctx.handler(get("/missing.js", {"accept": "text/html"}))).status == 404
        assert (await ctx.handler(get("/missing", {"accept": "application/json"}))).status == 404

    with_static_files(temporary_root, run, spa=True, index="index.html")


def test_rejects_directory_traversal_attempts(temporary_root: tuple[Path, Path]):
    """rejects directory traversal attempts"""

    async def run(ctx: Context) -> None:
        urls = [
            "/../../../etc/passwd",
            "/..%2F..%2Fetc%2Fpasswd",
            f"/..%2F{quote(ctx.outside_file.name, safe='')}",
        ]
        statuses = [(await ctx.handler(get(url))).status for url in urls]
        assert statuses == [404, 404, 404]

    with_static_files(temporary_root, run)


def test_rejects_null_bytes_and_malformed_uri_encoding(temporary_root: tuple[Path, Path]):
    """rejects null bytes and malformed uri encoding"""

    async def run(ctx: Context) -> None:
        null_byte = await ctx.handler(get("/null%00byte.txt"))
        malformed = await ctx.handler(get("/%E0%A4%A"))
        assert [null_byte.status, malformed.status] == [404, 404]

    with_static_files(temporary_root, run)


def test_applies_custom_mime_types_and_cache_control(temporary_root: tuple[Path, Path]):
    """applies custom mime types and cache-control"""

    async def run(ctx: Context) -> None:
        response = await ctx.handler(get("/hello.txt"))
        assert response.status == 200
        assert response.get("content-type") == "application/x-custom-text"
        assert response.get("cache-control") == "public, max-age=120"

    with_static_files(
        temporary_root,
        run,
        cache_control="public, max-age=120",
        mime_types={"txt": "application/x-custom-text"},
    )


def test_uses_octet_stream_for_unknown_extension_and_404_for_missing_file(
    temporary_root: tuple[Path, Path],
):
    """uses application/octet-stream for unknown extension and 404 for missing file"""

    async def run(ctx: Context) -> None:
        unknown = await ctx.handler(get("/file.binx"))
        assert unknown.status == 200
        assert unknown.get("content-type") == "application/octet-stream"
        assert (await ctx.handler(get("/does-not-exist.txt"))).status == 404

    with_static_files(temporary_root, run)
