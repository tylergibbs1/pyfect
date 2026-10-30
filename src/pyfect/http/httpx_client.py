"""An ``HttpClient`` backed by httpx (the ``pyfect[httpx]`` extra).

``layer`` provides the client; ``layer_with(**options)`` passes options to
``httpx.AsyncClient`` (``verify``, ``proxy``, ``limits``, ...). The httpx
client runs on an asyncio loop of its own, on a background thread, so the
layer works under ``run_sync`` and ``run_async`` alike, and closes with the
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
import threading
from collections.abc import AsyncIterator, Callable, Coroutine
from concurrent.futures import Future
from typing import TYPE_CHECKING, Any, Never
from urllib.parse import SplitResult

from pyfect._fiber import Fiber
from pyfect.effect import Effect, callback, fail, succeed, sync
from pyfect.errors import Done
from pyfect.http import body as _body
from pyfect.http import url as _url
from pyfect.http._httpx_options import RequestDefaults, split_options
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
from pyfect.stream import Stream, from_effect_repeat

if TYPE_CHECKING:
    import httpx

_NO_BODY_STATUSES = frozenset((204, 205, 304))
_EMPTY_FORM_BOUNDARY = "pyfect-empty-form"


def _form_content(form: _body.FormData) -> dict[str, Any]:
    if not form.entries:
        # httpx sends an empty ``files`` list as no body at all.
        return {"content": f"--{_EMPTY_FORM_BOUNDARY}--\r\n".encode()}
    files = [
        (
            name,
            (None, value.encode())
            if isinstance(value, str)
            else (value.name, value.content, value.content_type),
        )
        for name, value in form.entries
    ]
    return {"files": files}


def _future[A](
    signal: AbortSignal | None, start: Callable[[], Future[A]]
) -> Effect[A, BaseException]:
    """Wait for the future ``start()`` gives; interrupting (or aborting
    ``signal``) cancels it."""

    def register(resume: Callable[[Effect[A, BaseException]], None]) -> Effect[None]:
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
        return sync(future.cancel).as_void()

    return callback(register)


class _Backend:
    """An ``httpx.AsyncClient`` on an asyncio loop running on a thread of
    its own."""

    def __init__(self, options: dict[str, Any]) -> None:
        import httpx

        options.setdefault("timeout", None)
        self.client = httpx.AsyncClient(**options)
        self.loop = asyncio.new_event_loop()
        threading.Thread(target=self._run, name="pyfect-httpx", daemon=True).start()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()
        self.loop.close()

    def submit[A](self, make: Callable[[], Coroutine[Any, Any, A]]) -> Future[A]:
        return asyncio.run_coroutine_threadsafe(make(), self.loop)

    def _call_soon(self, f: Callable[[], object]) -> None:
        """Run ``f`` on the loop; once the backend has closed (and with it
        every response), there is nothing left to do."""
        try:
            self.loop.call_soon_threadsafe(f)
        except RuntimeError:
            if not self.loop.is_closed():
                raise

    def close(self) -> Effect[None]:
        """Close the httpx client, then stop the loop."""
        closing = _future(None, lambda: self.submit(self.client.aclose)).ignore()
        return closing.flat_map(
            lambda _: sync(lambda: self.loop.call_soon_threadsafe(self.loop.stop)).as_void()
        )

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
                return _form_content(body)
            case _body.Stream():
                chunks = body.stream.tap_error(lambda error: sync(lambda: failures.append(error)))
                iterable = chunks.to_async_iterable_with(fiber._context)

                async def content() -> AsyncIterator[bytes]:
                    async for chunk in iterable:
                        yield chunk

                return {"content": content()}
            case _body.Empty():
                return {}

    def send(
        self,
        request: HttpClientRequest,
        url: SplitResult,
        signal: AbortSignal,
        fiber: Fiber[Any, Any],
    ) -> Effect[HttpClientResponse, HttpClientError]:
        if "upgrade" in request.headers:
            return fail(
                HttpClientError(
                    TransportError(request, None, "httpx cannot send an HTTP upgrade request")
                )
            )
        failures: list[object] = []
        content = self._content(request, fiber, failures)
        headers = request.headers
        if isinstance(request.body, _body.FormData):
            headers = headers.remove("content-type")
            if not request.body.entries:
                content_type = f"multipart/form-data; boundary={_EMPTY_FORM_BOUNDARY}"
                headers = headers.set("content-type", content_type)

        async def send() -> httpx.Response:
            built = self.client.build_request(
                request.method, _url.href(url), headers=list(headers.items()), **content
            )
            return await self.client.send(built, stream=True)

        def on_error(error: BaseException) -> Effect[Never, HttpClientError]:
            if failures:
                return fail(HttpClientError(EncodeError(request, failures[0])))
            return fail(HttpClientError(TransportError(request, error)))

        return (
            _future(signal, lambda: self.submit(send))
            .catch_all(on_error)
            .map(lambda response: self._response(request, response, signal))
        )

    def _response(
        self, request: HttpClientRequest, response: httpx.Response, signal: AbortSignal
    ) -> HttpClientResponse:
        def close() -> None:
            self._call_soon(lambda: self.loop.create_task(response.aclose()))

        signal.add_listener(close)
        headers = Headers(
            {name: ", ".join(response.headers.get_list(name)) for name in response.headers}
        )
        body: Stream[bytes, object] | None = None
        if request.method != "HEAD" and response.status_code not in _NO_BODY_STATUSES:
            body = self._body(response)
        else:
            close()
        return HttpClientResponse(
            request,
            response.status_code,
            headers,
            body,
            url=str(response.url),
            set_cookie=response.headers.get_list("set-cookie"),
        )

    def _body(self, response: httpx.Response) -> Stream[bytes, object]:
        chunks = response.aiter_bytes()

        async def next_chunk() -> bytes:
            return await anext(chunks)

        def end_or_fail(error: BaseException) -> Effect[Never, BaseException | Done]:
            return fail(Done() if isinstance(error, StopAsyncIteration) else error)

        pull = _future(None, lambda: self.submit(next_chunk)).catch_all(end_or_fail)
        closing = _future(None, lambda: self.submit(response.aclose)).ignore()
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
