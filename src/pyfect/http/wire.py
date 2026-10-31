"""Responses as a server writes them (Effect's ``HttpServerResponse.toWeb``
and ``fromWeb``, with a ``WireResponse`` in the place of a Web
``Response``): a status, a reason, header lines (``set-cookie`` once per
cookie) and the body's bytes.

A ``raw`` body that is a ``WebResponse`` is sent as that response, with
the outer response's headers merged over its own.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterable, Callable, Coroutine, Iterable, Sequence
from dataclasses import dataclass, field, replace
from typing import cast

from pyfect._js import text_encode
from pyfect.http import _form_data
from pyfect.http import body as _body
from pyfect.http.cookies import from_set_cookie
from pyfect.http.headers import Headers
from pyfect.http.server_response import (
    HttpServerResponse,
    omits_body,
    omits_content_length,
    parse_content_length,
)
from pyfect.http.web import WebResponse
from pyfect.stream import Stream, from_async_iterable
from pyfect.stream import succeed as stream_succeed

type WireBody = bytes | Stream[bytes, object] | None
"""The bytes, a stream of them, or no body."""


@dataclass(frozen=True, slots=True)
class WireResponse:
    """A response as written: header names are lowercase, and only
    ``set-cookie`` repeats."""

    status: int = 200
    status_text: str = ""
    headers: tuple[tuple[str, str], ...] = ()
    body: WireBody = field(default=None, compare=False)

    def get(self, name: str) -> str | None:
        """The value of header ``name`` (repeated values joined by ``, ``)."""
        name = name.lower()
        values = [value for key, value in self.headers if key == name]
        return ", ".join(values) if values else None

    def get_set_cookie(self) -> list[str]:
        return [value for key, value in self.headers if key == "set-cookie"]

    def has(self, name: str) -> bool:
        name = name.lower()
        return any(key == name for key, _ in self.headers)


def _header_lines(headers: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    return [(key.lower(), value) for key, value in headers]


def _merge(
    target: list[tuple[str, str]], headers: Sequence[tuple[str, str]]
) -> list[tuple[str, str]]:
    """``headers`` over ``target``: a ``set-cookie`` is added, any other
    replaces the header."""
    out = list(target)
    for key, value in headers:
        if key != "set-cookie":
            out = [(k, v) for k, v in out if k != key]
        out.append((key, value))
    return out


def _without(headers: list[tuple[str, str]], name: str) -> list[tuple[str, str]]:
    return [(key, value) for key, value in headers if key != name]


def _response_headers(response: HttpServerResponse) -> list[tuple[str, str]]:
    lines = list(response.headers.items())
    lines.extend(("set-cookie", header) for header in response.cookies.to_set_cookie_headers())
    return lines


def _web_body(raw: WebResponse) -> WireBody:
    body = raw.body
    if body is None or isinstance(body, bytes):
        return body
    return from_async_iterable(body, lambda error: error)


def _raw_body(value: object) -> WireBody:
    """A raw body: bytes, text, or an async iterable of bytes."""
    if isinstance(value, AsyncIterable):
        chunks = cast("AsyncIterable[bytes]", value)
        return from_async_iterable(chunks, lambda error: error)
    return raw_bytes(value)


_closing: set[asyncio.Task[None]] = set()


def cancel_body(body: _body.HttpBody) -> None:
    """Close the async iterable of a raw body left unsent (Effect's
    ``cancelResponseBody``, Web ``ReadableStream.cancel``)."""
    if isinstance(body, _body.Raw):
        _cancel(body.body)


def _cancel(value: object) -> None:
    close = getattr(value, "aclose", None)
    if not isinstance(value, AsyncIterable) or close is None:
        return
    closed = cast("Callable[[], Coroutine[object, object, None]]", close)
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(closed())
        return
    task = loop.create_task(closed())
    _closing.add(task)
    task.add_done_callback(_closing.discard)


def raw_bytes(value: object) -> bytes:
    """The bytes of a raw body that is ``bytes`` or ``str``."""
    if isinstance(value, bytes | bytearray):
        return bytes(value)
    if isinstance(value, str):
        return text_encode(value)
    raise TypeError(f"a raw body of type {type(value).__name__} cannot be written")


def to_wire(response: HttpServerResponse, *, without_body: bool = False) -> WireResponse:
    """``response`` as written; ``without_body`` (a ``HEAD`` request) and
    the 204, 205 and 304 statuses leave out its body, and 204 and 205 its
    ``content-length``."""
    headers = _response_headers(response)
    body = response.body
    outer_omits_body = omits_body(response)
    no_body = outer_omits_body or without_body
    if isinstance(body, _body.Raw) and isinstance(body.body, WebResponse):
        raw = body.body
        # HEAD keeps the raw status; an explicit bodyless status replaces it.
        status, status_text = (
            (response.status, response.status_text or "")
            if outer_omits_body
            else (raw.status, raw.status_text)
        )
        merged = _merge(list(raw.header_lines), headers)
        if omits_content_length(status):
            merged = _without(merged, "content-length")
        return WireResponse(status, status_text, tuple(merged), None if no_body else _web_body(raw))
    status_text = response.status_text or ""
    if no_body:
        cancel_body(body)
        if omits_content_length(response.status):
            headers = _without(headers, "content-length")
        return WireResponse(response.status, status_text, tuple(headers), None)
    wire_body: WireBody
    match body:
        case _body.Empty():
            wire_body = None
        case _body.Bytes():
            wire_body = body.body
        case _body.Raw():
            wire_body = _raw_body(body.body)
        case _body.FormData():
            wire_body, content_type = _form_data.encode(body)
            headers = _merge(headers, [("content-type", content_type)])
        case _body.Stream():
            wire_body = body.stream
    return WireResponse(response.status, status_text, tuple(headers), wire_body)


def from_wire(wire: WireResponse) -> HttpServerResponse:
    """A server response of ``wire``: its cookies parsed from
    ``set-cookie``, its body streamed."""
    headers = Headers(dict(_without(_header_lines(wire.headers), "set-cookie")))
    response = HttpServerResponse(
        wire.status,
        wire.status_text or None,
        headers,
        from_set_cookie(wire.get_set_cookie()),
    )
    if wire.body is None:
        return response
    chunks: Stream[bytes, object]
    chunks = stream_succeed(wire.body) if isinstance(wire.body, bytes) else wire.body
    return response.set_body(
        _body.stream(
            chunks,
            wire.get("content-type"),
            parse_content_length(wire.get("content-length")),
        )
    )


def with_body(wire: WireResponse, body: WireBody) -> WireResponse:
    return replace(wire, body=body)


__all__ = [
    "WireBody",
    "WireResponse",
    "cancel_body",
    "from_wire",
    "raw_bytes",
    "to_wire",
    "with_body",
]
