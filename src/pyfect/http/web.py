"""Requests and responses as asyncio code sees them (Effect's Web
``Request`` and ``Response``): what ``web_handler`` handlers take and
return, and what the ASGI adapter speaks.

A body is ``bytes``, an async iterable of ``bytes`` (read once) or
``None``. Header names are lowercase; repeated request headers are joined
with ``", "``, and only ``set-cookie`` repeats in a response.
"""

from __future__ import annotations

from collections.abc import AsyncIterable, AsyncIterator, Iterable, Mapping
from typing import Any, cast, final

from pyfect import _json_text
from pyfect._js import text_encode
from pyfect.http.abort import AbortSignal
from pyfect.http.headers import Headers

type WebBody = bytes | AsyncIterable[bytes] | None
type HeaderLines = Mapping[str, str] | Iterable[tuple[str, str]]


def _lines(headers: HeaderLines | None) -> tuple[tuple[str, str], ...]:
    if headers is None:
        return ()
    pairs: Iterable[tuple[str, str]] = (
        cast("Mapping[str, str]", headers).items() if isinstance(headers, Mapping) else headers
    )
    return tuple((key.lower(), value) for key, value in pairs)


def _body_of(body: bytes | str | AsyncIterable[bytes] | None) -> WebBody:
    return text_encode(body) if isinstance(body, str) else body


async def _read(body: WebBody) -> bytes:
    if body is None:
        return b""
    if isinstance(body, bytes):
        return body
    return b"".join([chunk async for chunk in body])


async def _once(body: bytes | None) -> AsyncIterator[bytes]:
    if body:
        yield body


class _Message:
    __slots__ = ("_used", "body", "header_lines")

    def __init__(
        self, headers: HeaderLines | None, body: bytes | str | AsyncIterable[bytes] | None
    ):
        self.header_lines = _lines(headers)
        self.body: WebBody = _body_of(body)
        self._used = False

    def get(self, name: str) -> str | None:
        """Header ``name``, repeated values joined with ``", "``."""
        name = name.lower()
        values = [value for key, value in self.header_lines if key == name]
        return ", ".join(values) if values else None

    def has(self, name: str) -> bool:
        name = name.lower()
        return any(key == name for key, _ in self.header_lines)

    async def read(self) -> bytes:
        """The whole body (it can be read once)."""
        if self._used:
            raise RuntimeError("body already read")
        self._used = True
        return await _read(self.body)

    async def buffer(self) -> bytes:
        """Read the body into memory, so it can be read again (what Web
        ``Response.clone`` allows)."""
        if self._used:
            raise RuntimeError("body already read")
        if not (self.body is None or isinstance(self.body, bytes)):
            self.body = await _read(self.body)
        return self.body or b""

    async def text(self) -> str:
        return (await self.read()).decode("utf-8", "replace")

    async def json(self) -> Any:
        return _json_text.parse(await self.read())

    def chunks(self) -> AsyncIterator[bytes]:
        """The body, chunk by chunk."""

        self._used = True
        body = self.body
        if body is None or isinstance(body, bytes):
            return _once(body)
        # The body itself, so closing the iterator closes it.
        return aiter(body)


@final
class WebRequest(_Message):
    """A request a server received: an absolute ``url``, and a ``signal``
    that fires when the client goes away."""

    __slots__ = ("method", "remote_address", "signal", "url")

    def __init__(
        self,
        url: str,
        *,
        method: str = "GET",
        headers: HeaderLines | None = None,
        body: bytes | str | AsyncIterable[bytes] | None = None,
        signal: AbortSignal | None = None,
        remote_address: str | None = None,
    ) -> None:
        super().__init__(headers, body)
        self.url = url
        self.method = method.upper()
        self.signal = signal
        self.remote_address = remote_address

    @property
    def headers(self) -> Headers:
        joined: dict[str, str] = {}
        for key, value in self.header_lines:
            joined[key] = f"{joined[key]}, {value}" if key in joined else value
        return Headers(joined)


@final
class WebResponse(_Message):
    """A response as sent."""

    __slots__ = ("status", "status_text")

    def __init__(
        self,
        body: bytes | str | AsyncIterable[bytes] | None = None,
        *,
        status: int = 200,
        status_text: str = "",
        headers: HeaderLines | None = None,
    ) -> None:
        lines = _lines(headers)
        if isinstance(body, str) and not any(key == "content-type" for key, _ in lines):
            lines = (*lines, ("content-type", "text/plain;charset=UTF-8"))
        super().__init__(lines, body)
        self.status = status
        self.status_text = status_text

    @classmethod
    def json_of(cls, value: object, *, status: int = 200) -> WebResponse:
        """A JSON response (Web ``Response.json``)."""
        return cls(
            text_encode(_json_text.stringify(value)),
            status=status,
            headers={"content-type": "application/json"},
        )

    def get_set_cookie(self) -> list[str]:
        return [value for key, value in self.header_lines if key == "set-cookie"]

    def __repr__(self) -> str:
        return f"WebResponse(status={self.status}, headers={self.header_lines!r})"


__all__ = ["HeaderLines", "WebBody", "WebRequest", "WebResponse"]
