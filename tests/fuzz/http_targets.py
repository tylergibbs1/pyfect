"""The live server's HTTP/1 and WebSocket parsing, and the request-level
parsers a handler reaches (URLs, query strings, cookies, multipart bodies)."""

from __future__ import annotations

from typing import Any, cast

from pyfect import effect
from pyfect._url import Url
from pyfect.effect import fail, succeed, void
from pyfect.http import cookies, origin, trace_context, url_params
from pyfect.http import multipart_parser as mp
from pyfect.http._authority import parse_authority, parse_origin_form
from pyfect.http.headers import from_input, parse_http_date
from pyfect.http.live_server._body import BodyError, BodyReader
from pyfect.http.live_server._head import HeadError, parse_head
from pyfect.http.live_server._inbound import BareLineFeed, HeadTooLarge, Inbound
from pyfect.http.live_server._serve import MAX_HEAD_SIZE
from pyfect.http.live_server._ws_deflate import PerMessageDeflate, negotiate
from pyfect.http.live_server._ws_frames import FrameParser, Message, ProtocolError
from pyfect.http.multipart_parser import _content_type as content_type
from pyfect.socket._connection import Connection
from pyfect.socket._errors import SocketError, close_error

from ._harness import Crash, chunks, raises_only, settle, target

_MAX_REQUESTS = 32


class _Received:
    """The part of a ``Connection`` ``Inbound`` reads: ``chunks``, then a clean end."""

    def __init__(self, pieces: list[bytes]) -> None:
        self._pieces = pieces

    def pull_into(self, take: Any, limit: int | None = None) -> Any:
        if self._pieces:
            return succeed(take((self._pieces.pop(0),)))
        return fail(close_error(1000))


def _request_parsers(head: Any) -> None:
    """What a handler reads from a request's head."""
    headers = head.headers
    if isinstance(head.target, str) and head.target != "*":
        url = Url.parse("http://localhost" + head.target)
        if url is not None:
            url_params.parse(url.search).to_record()
    cookies.parse_header(headers.get("cookie", ""))
    origin.parse_origin(headers.get("origin", ""))
    trace_context.from_headers(headers)
    parse_http_date(headers.get("if-modified-since", ""))


@target("http_request")
def http_request(data: bytes) -> None:
    """A connection's bytes read as the live server does: heads, bodies
    (``Content-Length`` or chunked, with trailers), one request after another."""
    inbound = Inbound(cast(Connection, _Received(chunks(data))))

    def serve() -> Any:
        for _ in range(_MAX_REQUESTS):
            raw = yield from inbound.read_head(MAX_HEAD_SIZE)
            if raw is None:
                return
            try:
                head = parse_head(raw)
            except HeadError:
                return
            _request_parsers(head)
            body = BodyReader(inbound, head.framing, lambda: void)
            yield from body.stream().run_drain()
            if not body.complete:
                raise Crash("a drained body is complete")

    settle(effect.gen(serve), HeadTooLarge, BareLineFeed, BodyError, SocketError)


@target("http_head")
def http_head(data: bytes) -> None:
    raises_only(lambda: parse_head(data), HeadError)


@target("http_text")
def http_text(data: bytes) -> None:
    """Header values a handler parses: the first byte picks which."""
    if not data:
        return
    value = data[1:].decode("latin-1")
    match data[0] % 8:
        case 0:
            cookies.parse_header(value)
        case 1:
            cookies.from_set_cookie(value.split("\n"))
        case 2:
            url_params.parse(value).to_record()
        case 3:
            parse_http_date(value)
        case 4:
            origin.parse_origin(value)
        case 5:
            parse_authority(value)
            parse_origin_form(value)
        case 6:
            content_type.parse(value)
            content_type.parse_disposition(value)
        case _:
            trace_context.from_headers(
                from_input({"traceparent": value, "b3": value, "x-b3-traceid": value})
            )


@target("url")
def url(data: bytes) -> None:
    """WHATWG URL parsing; a parsed URL's ``href`` parses to itself."""
    text = data.decode("utf-8", "replace")
    parsed = Url.parse(text)
    if parsed is None:
        return
    again = Url.parse(parsed.href)
    if again is None or again.href != parsed.href:
        raise Crash(f"href does not round-trip: {parsed.href!r} -> {again and again.href!r}")


def _frames(data: bytes, compressed: bool) -> None:
    limit = 64 * 1024
    inflate = None
    if compressed:
        negotiated = negotiate(PerMessageDeflate(), "permessage-deflate", limit)
        assert negotiated is not None
        inflate = negotiated.inflater()
    parser = FrameParser(limit, inflate)
    for piece in chunks(data):
        for event in raises_only(lambda piece=piece: parser.feed(piece), ProtocolError) or []:
            if isinstance(event, Message) and len(event.data) > limit:
                raise Crash(f"a message of {len(event.data)} bytes passed the limit")


@target("ws_frames")
def ws_frames(data: bytes) -> None:
    """Client frames, plain and with ``permessage-deflate`` (messages stay
    within the size limit however well they inflate)."""
    _frames(data, compressed=bool(data) and data[0] & 1 == 1)


@target("ws_extensions")
def ws_extensions(data: bytes) -> None:
    raises_only(lambda: negotiate(PerMessageDeflate(), data.decode("latin-1"), 1024), ValueError)


@target("multipart")
def multipart(data: bytes) -> None:
    """A multipart body: the first line is the ``Content-Type``, the rest the body,
    parsed with small limits so every limit is reachable."""
    first, _, body = data.partition(b"\n")
    total = [0]

    def on_file(info: mp.PartInfo) -> mp.OnChunk:
        def on_chunk(chunk: bytes | None) -> None:
            if chunk is not None:
                total[0] += len(chunk)

        return on_chunk

    def on_field(info: mp.PartInfo, value: bytes) -> None:
        total[0] += len(value)
        mp.decode_field(info, value)

    parser = mp.make(
        headers={"content-type": first.decode("latin-1")},
        on_file=on_file,
        on_field=on_field,
        on_error=lambda error: None,
        on_done=lambda: None,
        max_parts=8,
        max_total_size=4096,
        max_part_size=2048,
        max_field_size=1024,
    )
    for piece in chunks(body):
        parser.write(piece)
    parser.end()
    if total[0] > 4096:
        raise Crash(f"{total[0]} bytes of parts passed the 4096-byte limit")
