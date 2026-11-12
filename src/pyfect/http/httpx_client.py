"""An ``HttpClient`` backed by httpx (the ``pyfect-dev[httpx]`` extra).

``layer`` provides the client; ``layer_with(**options)`` passes options to
``httpx.AsyncClient`` (``verify``, ``proxy``, ``limits``, ...). The httpx
client runs on an asyncio loop of its own, on a background thread, so the
layer works under ``run_blocking`` and ``run_async`` alike, and closes with the
layer::

    program.pipe(fx.provide(httpx_client.layer))

Interrupting a request cancels it in httpx (closing its connection);
response bodies stream chunk by chunk, and a request body ``Stream`` is
pulled as httpx sends it. httpx applies no timeout by default here, as
``fetch`` applies none: use ``Effect.timeout``.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
import contextlib
import socket
from collections.abc import AsyncIterator, Callable, Coroutine, Sequence
from concurrent.futures import Future
from typing import TYPE_CHECKING, Any, Never

from pyfect._fiber import Fiber
from pyfect._js import text_encode
from pyfect._loop_thread import LoopThread
from pyfect._os_wait import WaitsFor, os_wait
from pyfect._released import Lifetime
from pyfect.effect import Effect, fail, succeed, suspend, sync
from pyfect.errors import Done
from pyfect.http import _form_data
from pyfect.http import body as _body
from pyfect.http import url as _url
from pyfect.http._httpx_options import RequestDefaults, import_httpx, split_options
from pyfect.http.abort import AbortSignal
from pyfect.http.client import HttpClient, HttpClientService
from pyfect.http.client import make as make_client
from pyfect.http.error import EncodeError, HttpClientError, TransportError
from pyfect.http.headers import Headers
from pyfect.http.method import has_body
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.scope import Scope, acquire_release
from pyfect.socket import SocketService
from pyfect.socket._errors import CloseEvent, SocketError, close_error, read_error, write_error
from pyfect.socket._socket import Chunk, Reader, Writer, encode_chunk
from pyfect.socket._socket import make as make_socket
from pyfect.stream import Stream, from_effect_repeat
from pyfect.stream._async_iterable import StreamAsyncIterator

if TYPE_CHECKING:
    import httpx

_NO_BODY_STATUSES = frozenset((204, 205, 304))
_EMPTY_FORM_BOUNDARY = "pyfect-empty-form"
_READ_SIZE = 65536
"""The most an upgraded connection's reader takes per pull."""


_FORM_CONTENT_TYPE = "pyfect_form_content_type"
_BODY_READER = "pyfect_body_reader"
_BODY_DONE = "pyfect_body_done"
"""The keys ``_content`` returns a streamed form's content type, a streamed body's
reader, and what to call once that body is done, under (taken out before the rest
goes to httpx)."""


def _stream_content(
    stream: Stream[bytes, object], fiber: Fiber[Any, Any], failures: list[object]
) -> dict[str, Any]:
    chunks = stream.tap_error(lambda error: sync(lambda: failures.append(error)))
    reader = aiter(chunks.to_async_iterable_with(fiber._context))
    done: list[Callable[[], object]] = []

    async def content() -> AsyncIterator[bytes]:
        try:
            async with contextlib.aclosing(reader):
                async for chunk in reader:
                    yield chunk
        finally:
            for then in done:
                then()

    return {"content": content(), _BODY_READER: reader, _BODY_DONE: done}


def _form_body(
    form: _body.FormData, fiber: Fiber[Any, Any], failures: list[object]
) -> dict[str, Any]:
    if not _form_data.has_file_source(form):
        return _form_content(form)
    # Encoded by pyfect, so each file source is read as the connection takes it.
    encoded, content_type = _form_data.encode(form)
    assert not isinstance(encoded, bytes)
    return {**_stream_content(encoded, fiber, failures), _FORM_CONTENT_TYPE: content_type}


def _form_content(form: _body.FormData) -> dict[str, Any]:
    if not form.entries:
        # httpx sends an empty ``files`` list as no body at all.
        return {"content": text_encode(f"--{_EMPTY_FORM_BOUNDARY}--\r\n")}
    files = [
        (
            name,
            (None, text_encode(value))
            if isinstance(value, str)
            else (value.name, value.content, value.content_type),
        )
        for name, value in form.entries
    ]
    return {"files": files}


def _future[A](
    signal: AbortSignal | None, start: Callable[[], Future[A]], *, waits_for: WaitsFor
) -> Effect[A, BaseException]:
    """Wait for the future ``start()`` gives; interrupting (or aborting
    ``signal``) cancels it. A body's next chunk is an ``"event"``: the
    server may hold it back indefinitely, so the test clock must not wait
    for it."""

    def register(resume: Callable[[Effect[A, BaseException]], None]) -> Callable[[], bool]:
        future = start()
        remove = (lambda: None) if signal is None else signal.add_listener(future.cancel)

        def done(finished: Future[A]) -> None:
            remove()
            if finished.cancelled():
                resume(fail(asyncio.CancelledError()))
                return
            error = finished.exception()
            resume(succeed(finished.result()) if error is None else fail(error))

        future.add_done_callback(done)
        return future.cancel

    return os_wait(register, waits_for=waits_for)


class _Backend:
    """An ``httpx.AsyncClient`` on an asyncio loop running on a thread of
    its own."""

    def __init__(self, options: dict[str, Any]) -> None:
        options.setdefault("timeout", None)
        self.client = import_httpx().AsyncClient(**options)
        self._thread = LoopThread("pyfect-httpx")
        self.loop = self._thread.loop
        self._lifetime = Lifetime("HTTP client")
        self._closing: set[asyncio.Task[None]] = set()
        """Responses being closed (touched on the loop only)."""

    def _close_response(self, response: httpx.Response) -> None:
        task = self.loop.create_task(response.aclose())
        self._closing.add(task)
        task.add_done_callback(self._closing.discard)

    async def _settle(self) -> None:
        """Wait for the responses being closed."""
        while self._closing:
            closing = list(self._closing)
            self._closing.clear()
            await asyncio.gather(*closing, return_exceptions=True)

    async def _shutdown(self) -> None:
        await self._settle()
        await self.client.aclose()

    def submit[A](self, make: Callable[[], Coroutine[Any, Any, A]]) -> Future[A]:
        """Run ``make()`` on the loop; once the client is closed, a future
        failed with ``Released``."""
        return self._lifetime.submit(lambda: self._thread.submit(make))

    def _close_reader(self, reader: StreamAsyncIterator[bytes]) -> None:
        task = self.loop.create_task(reader.aclose())
        self._closing.add(task)
        task.add_done_callback(self._closing.discard)

    def _call_soon(self, f: Callable[[], object]) -> None:
        """Run ``f`` on the loop; once the backend has closed (and with it
        every response), there is nothing left to do."""
        try:
            self.loop.call_soon_threadsafe(f)
        except RuntimeError:
            if not self.loop.is_closed():
                raise

    def close(self) -> Effect[None]:
        """Close the httpx client, then stop the loop and wait until it has
        closed (with it every response body httpx left open)."""

        def shutdown() -> Future[None]:
            future = self.submit(self._shutdown)
            self._lifetime.close()
            return future

        def stop() -> Future[None]:
            self._thread.stop()
            return self._thread.stopped

        closing = _future(None, shutdown, waits_for="work").ignore()
        return closing.and_then(_future(None, stop, waits_for="work").ignore())

    def _content(
        self, request: HttpClientRequest, fiber: Fiber[Any, Any], failures: list[object]
    ) -> dict[str, Any]:
        body = request.body
        if not has_body(request.method):
            return {}
        match body:
            case _body.Bytes():
                return {"content": body.body}
            case _body.Raw():
                return {"content": body.body}
            case _body.FormData():
                return _form_body(body, fiber, failures)
            case _body.Stream():
                return _stream_content(body.stream, fiber, failures)
            case _body.Empty():
                return {}

    def send(
        self,
        request: HttpClientRequest,
        url: _url.Url,
        signal: AbortSignal,
        fiber: Fiber[Any, Any],
    ) -> Effect[HttpClientResponse, HttpClientError]:
        failures: list[object] = []
        content = self._content(request, fiber, failures)
        reader: StreamAsyncIterator[bytes] | None = content.pop(_BODY_READER, None)
        done: list[Callable[[], object]] = content.pop(_BODY_DONE, [])
        if reader is not None:
            # An abort (interrupt, timeout) stops the body's stream at once: an
            # upload the server stopped reading must not hold it open.
            body_reader = reader
            # Once the body is done the listener goes: it holds the request's context,
            # which reaches the response, so it would keep an unread response (and the
            # finalizer that aborts it) alive.
            done.append(
                signal.add_listener(
                    lambda: self._call_soon(lambda: self._close_reader(body_reader))
                )
            )
        headers = request.headers
        if isinstance(request.body, _body.FormData):
            headers = headers.remove("content-type")
            streamed_type = content.pop(_FORM_CONTENT_TYPE, None)
            if streamed_type is not None:
                # A form pyfect encodes itself carries its own boundary.
                headers = headers.set("content-type", streamed_type)
            if not request.body.entries:
                content_type = f"multipart/form-data; boundary={_EMPTY_FORM_BOUNDARY}"
                headers = headers.set("content-type", content_type)

        async def send() -> httpx.Response:
            built = self.client.build_request(
                request.method, _url.href(url), headers=list(headers.items()), **content
            )
            response = await self.client.send(built, stream=True)
            # Tied to the signal as soon as it exists: an interrupt that wins
            # against its arrival (a lost race) drops it unseen, and aborts.
            signal.add_listener(lambda: self._call_soon(lambda: self._close_response(response)))
            return response

        def on_error(error: BaseException) -> Effect[Never, HttpClientError]:
            if failures and isinstance(failures[0], _body.FileSourceError):
                return fail(HttpClientError(TransportError(request, failures[0].cause)))
            if failures:
                return fail(HttpClientError(EncodeError(request, failures[0])))
            return fail(HttpClientError(TransportError(request, error)))

        return (
            _future(signal, lambda: self.submit(send), waits_for="work")
            .catch_all(on_error)
            .map(lambda response: self._response(request, response))
        )

    def _response(self, request: HttpClientRequest, response: httpx.Response) -> HttpClientResponse:
        headers = Headers(
            {name: ", ".join(response.headers.get_list(name)) for name in response.headers}
        )
        body: Stream[bytes, object] | None = None
        upgrade: Effect[SocketService, HttpClientError] | None = None
        if response.status_code == 101:
            # httpcore hands over the switched connection, the bytes it read
            # past the head first (as httpx-ws takes WebSockets).
            upgrade = succeed(self._upgraded(response))
        elif request.method != "HEAD" and response.status_code not in _NO_BODY_STATUSES:
            body = self._body(response)
        else:
            self._call_soon(lambda: self._close_response(response))
        return HttpClientResponse(
            request,
            response.status_code,
            headers,
            body,
            url=str(response.url),
            set_cookie=response.headers.get_list("set-cookie"),
            upgrade=upgrade,
        )

    def _upgraded(self, response: httpx.Response) -> SocketService:
        """The connection of a ``101`` response as a socket: releasing the
        reader's scope closes it, releasing the writer's half-closes it."""
        stream = response.extensions["network_stream"]

        async def close() -> None:
            try:
                await stream.aclose()
            finally:
                await response.aclose()

        async def half_close() -> None:
            sock = stream.get_extra_info("socket")
            with contextlib.suppress(OSError):
                sock.shutdown(socket.SHUT_WR)

        def run(
            make: Callable[[], Coroutine[Any, Any, Any]], waits_for: WaitsFor
        ) -> Effect[Any, BaseException]:
            return _future(None, lambda: self.submit(make), waits_for=waits_for)

        def read() -> Effect[tuple[bytes, ...], SocketError]:
            async def chunk() -> bytes:
                return await stream.read(_READ_SIZE)

            def got(data: bytes) -> Effect[tuple[bytes, ...], SocketError]:
                return succeed((data,)) if data else fail(close_error(1000))

            return run(chunk, "event").map_error(read_error).flat_map(got)

        def write(chunk: Chunk | CloseEvent) -> Effect[None, SocketError]:
            if isinstance(chunk, CloseEvent):
                return run(close, "work").ignore()
            return write_all((chunk,))

        def write_all(chunks: Sequence[Chunk]) -> Effect[None, SocketError]:
            data = b"".join(encode_chunk(chunk) for chunk in chunks)
            return run(lambda: stream.write(data), "work").map_error(write_error).as_(None)

        reader = acquire_release(
            succeed(Reader(suspend(read))), lambda _r, _e: run(close, "work").ignore()
        )
        writer = acquire_release(
            succeed(Writer(write, write_all)), lambda _w, _e: run(half_close, "work").ignore()
        )
        return make_socket(reader, writer)

    def _body(self, response: httpx.Response) -> Stream[bytes, object]:
        chunks = response.aiter_bytes()

        async def next_chunk() -> bytes:
            return await anext(chunks)

        def end_or_fail(error: BaseException) -> Effect[Never, BaseException | Done]:
            return fail(Done() if isinstance(error, StopAsyncIteration) else error)

        pull = _future(None, lambda: self.submit(next_chunk), waits_for="event").catch_all(
            end_or_fail
        )
        closing = _future(None, lambda: self.submit(response.aclose), waits_for="work").ignore()
        return from_effect_repeat(pull).ensuring(closing)


def make(**options: Any) -> Effect[HttpClientService[HttpClientError], Never, Scope]:
    """A client on a new ``httpx.AsyncClient(**options)``, closed with the
    scope.

    The request defaults (``headers``, ``params``, ``cookies``, ``auth``)
    are added to each request by the pyfect client, not by httpx, so
    ``follow_redirects`` drops their credentials on a hop to another origin
    as it does a request's own. ``auth`` is a ``(username, password)`` pair
    and ``cookies`` a mapping; set any other credential per request."""
    defaults, transport = split_options(options)
    backend = acquire_release(
        sync(lambda: _Backend(dict(transport))), lambda backend, _exit: backend.close()
    )
    return backend.map(lambda backend: _with_defaults(make_client(backend.send), defaults))


def _with_defaults(
    client: HttpClientService[HttpClientError], defaults: RequestDefaults
) -> HttpClientService[HttpClientError]:
    return client if defaults.is_empty() else client.map_request(defaults.apply)


def layer_with(**options: Any) -> Layer[HttpClient]:
    """``layer`` with options for ``httpx.AsyncClient`` (see ``make``)."""
    split_options(options)
    return layer_effect(HttpClient, make(**options))


layer: Layer[HttpClient] = layer_with()
"""An ``HttpClient`` on httpx with its default options (and no timeout)."""


__all__ = ["layer", "layer_with", "make"]
