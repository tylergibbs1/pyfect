"""Ports of Effect's ``http/HttpEffect.test.ts``.

Each test's docstring is the Effect test title. A Web ``Request`` /
``Response`` is a ``WebRequest`` / ``WebResponse`` and a Web handler an
asyncio handler (``web_handler``); each handler test runs its own loop.

Omitted, with the reason:

- ``an abort while the unread body is full releases the request scope
  owned by a streamed body``: a Python body is pulled only when read, so
  there is no buffered unread state; the abort of an unread body is
  covered by ``an abort before the body is read ...`` below.
- ``a failing layer rejects every request without an unhandled
  rejection``: ported without the unhandled-rejection listener, which
  asyncio has no equivalent of (an unretrieved task exception is logged,
  not raised).
"""

# pyright: reportPrivateUsage=false

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Never

import pytest

import pyfect as fx
from pyfect import effect, layer, scope, stream
from pyfect._core import _WithFiber
from pyfect.cause import Cause
from pyfect.context import Context, Reference
from pyfect.exit import Exit, Failure
from pyfect.http import http_effect, server_response
from pyfect.http.abort import AbortController
from pyfect.http.server_request import HttpServerRequest
from pyfect.http.server_response import HttpServerResponse
from pyfect.http.web import WebRequest, WebResponse
from pyfect.http.web_handler import (
    from_web_handler,
    request_from_web,
    to_web_handler,
    to_web_handler_layer,
    to_web_handler_with,
)
from pyfect.scope import Scope
from pyfect.tracer import CurrentTracer, ParentSpan, Tracer, TracerEnabled, native_tracer


class Value420(Reference[int]):
    @classmethod
    def default(cls) -> int:
        return 0


def _aio[A](make: Callable[[], Awaitable[A]]) -> A:
    async def main() -> A:
        return await make()

    return asyncio.run(main())


def _request(url: str = "http://localhost:3000/", **options: Any) -> WebRequest:
    return WebRequest(url, **options)


def _in_request[A, E](eff: fx.Effect[A, E, Any]) -> A:
    provided = eff.pipe(effect.provide_service(HttpServerRequest, request_from_web(_request())))
    return fx.run_blocking(provided.pipe(effect.provide_service(TracerEnabled, False)).or_die())


def _write_nothing(_request: object, _response: HttpServerResponse) -> fx.Effect[None]:
    return effect.void


def test_restores_the_request_scope_context_identity() -> None:
    """restores the request Scope context identity"""
    seen: list[Context[Any]] = []

    def app(fiber: Any) -> fx.Effect[HttpServerResponse]:
        seen.append(fiber._context)
        assert fiber._context.lookup(Scope)[0]
        return effect.succeed(server_response.empty())

    def program(fiber: Any) -> fx.Effect[tuple[Context[Any], Context[Any]], Never, Any]:
        before = fiber._context
        handled: fx.Effect[None, Never, Any] = http_effect.to_handled(
            _WithFiber[HttpServerResponse, Never, Any](app), _write_nothing
        )
        return handled.and_then(_WithFiber(lambda after: effect.succeed((before, after._context))))

    before, after = _in_request(_WithFiber(program))
    assert seen[0] is not before
    assert after is before


def test_propagates_a_handler_failure_through_middleware_to_request_and_forked_scopes() -> None:
    """propagates a handler failure through middleware to request and forked scopes"""
    error = ValueError("handler failed")
    exits: dict[str, Exit[Any, Any]] = {}

    def record(name: str) -> Callable[[Exit[Any, Any]], fx.Effect[None]]:
        return lambda exit: effect.sync(lambda: exits.__setitem__(name, exit))

    @fx.fn
    def app():
        current = yield from Scope()
        child = yield from current.fork()
        yield from child.add_finalizer(record("child"))
        yield from current.add_finalizer(record("request"))
        return (yield from effect.fail(error))

    _in_request(http_effect.to_handled(app(), _write_nothing, lambda handler: handler))
    for name in ("request", "child"):
        exit = exits[name]
        assert isinstance(exit, Failure)
        cause: Cause[Any] = exit.cause
        assert len(cause.reasons) == 1
        assert cause.squash() is error


# --- toWebHandler -------------------------------------------------------------


def _has_parent_span(found: list[bool]) -> fx.Effect[HttpServerResponse]:
    return ParentSpan().map(
        lambda span: (found.append(span is not None), server_response.empty())[1]
    )


def test_skips_the_server_span_with_the_default_tracer() -> None:
    """skips the server span with the default tracer"""
    found: list[bool] = []
    handler = to_web_handler(_has_parent_span(found))
    _aio(lambda: handler(_request()))
    assert found == [False]


def test_provides_a_parent_span_with_a_configured_tracer() -> None:
    """provides a parent span with a configured tracer"""
    found: list[bool] = []
    tracer = Tracer.make(native_tracer.span)
    handler = to_web_handler(_has_parent_span(found))
    _aio(lambda: handler(_request(), Context.make(CurrentTracer, tracer)))
    assert found == [True]


def test_json() -> None:
    """json"""
    handler = to_web_handler(server_response.json({"foo": "bar"}))

    async def main() -> object:
        return await (await handler(_request())).json()

    assert _aio(main) == {"foo": "bar"}


def test_cookies() -> None:
    """cookies"""
    response = (
        server_response.json_unsafe({"foo": "bar"})
        .set_cookie_unsafe("foo", "bar")
        .set_cookie_unsafe("test", "123", secure=True, http_only=True, same_site="strict")
    )
    handler = to_web_handler(effect.succeed(response))

    async def main() -> tuple[list[str], object]:
        web = await handler(_request())
        return web.get_set_cookie(), await web.json()

    cookies, body = _aio(main)
    assert cookies == ["foo=bar", "test=123; HttpOnly; Secure; SameSite=Strict"]
    assert body == {"foo": "bar"}


def test_expire_cookie() -> None:
    """expireCookie"""
    app = (
        server_response.empty()
        .expire_cookie("foo", path="/")
        .map(lambda response: response.expire_cookie_unsafe("bar"))
    )
    handler = to_web_handler(app)
    web = _aio(lambda: handler(_request()))
    assert web.get_set_cookie() == [
        "foo=; Max-Age=0; Path=/; Expires=Thu, 01 Jan 1970 00:00:00 GMT",
        "bar=; Max-Age=0; Expires=Thu, 01 Jan 1970 00:00:00 GMT",
    ]


def test_stream() -> None:
    """stream"""
    body = stream.from_iterable(["foo", "bar"]).encode_text()
    handler = to_web_handler(effect.succeed(server_response.stream(body)))

    async def main() -> str:
        return await (await handler(_request())).text()

    assert _aio(main) == "foobar"


def test_preserves_explicit_stream_headers() -> None:
    """preserves explicit stream headers"""
    response = server_response.stream(stream.empty).set_headers(
        {"Content-Type": "text/javascript", "Content-Length": "9007199254740993"}
    )
    handler = to_web_handler(effect.succeed(response))

    async def main() -> WebResponse:
        web = await handler(_request("http://localhost/script.js"))
        await web.read()
        return web

    web = _aio(main)
    assert web.get("content-type") == "text/javascript"
    assert web.get("content-length") == "9007199254740993"


@pytest.mark.parametrize("when", ["before the request", "while the handler starts"])
def test_an_abort_interrupts_the_handler_as_a_client_abort(when: str) -> None:
    """an abort %s interrupts the handler as a client abort"""
    controller = AbortController()
    if when == "before the request":
        controller.abort()
    interrupted: list[bool] = []

    def start() -> None:
        if when == "while the handler starts":
            controller.abort()

    app: fx.Effect[HttpServerResponse] = (
        effect.sync(start)
        .and_then(effect.never)
        .on_interrupt(effect.sync(lambda: interrupted.append(True)))
        # Handlers are uninterruptible unless they opt in, as router routes do.
        .interruptible()
    )
    handler = to_web_handler(app)
    web = _aio(lambda: handler(_request(signal=controller.signal)))
    assert web.status == 499
    assert interrupted == [True]


def _stream_owning_scope(
    finalized: list[bool], pulled_second: list[bool]
) -> fx.Effect[HttpServerResponse, Any, Any]:
    def second() -> str:
        pulled_second.append(True)
        return "second"

    body = (
        stream.from_iterable(["first"])
        .concat(stream.from_effect(effect.sync(second)))
        .concat(stream.never)
        .encode_text()
    )
    return scope.add_finalizer(lambda _: effect.sync(lambda: finalized.append(True))).as_(
        server_response.stream(body)
    )


async def _wait_for(predicate: Callable[[], bool]) -> None:
    for _ in range(1000):
        if predicate():
            return
        await asyncio.sleep(0.001)


def test_an_abort_after_reading_a_chunk_releases_the_request_scope_owned_by_a_streamed_body() -> (
    None
):
    """an abort %s releases the request scope owned by a streamed body (after reading a chunk)"""
    controller = AbortController()
    finalized: list[bool] = []
    handler = to_web_handler(_stream_owning_scope(finalized, []))

    async def main() -> None:
        web = await handler(_request(signal=controller.signal))
        chunks = web.chunks()
        assert await anext(chunks) == b"first"
        reading = asyncio.ensure_future(anext(chunks, None))
        await asyncio.sleep(0.01)
        controller.abort()
        await _wait_for(lambda: bool(finalized))
        reading.cancel()

    _aio(main)
    assert finalized == [True]


def test_an_abort_before_the_body_is_read_releases_the_request_scope_owned_by_a_streamed_body() -> (
    None
):
    """an abort %s releases the request scope owned by a streamed body (body never read)"""
    controller = AbortController()
    finalized: list[bool] = []
    handler = to_web_handler(_stream_owning_scope(finalized, []))

    async def main() -> None:
        await handler(_request(signal=controller.signal))
        controller.abort()
        await _wait_for(lambda: bool(finalized))

    _aio(main)
    assert finalized == [True]


def test_stream_scope() -> None:
    """stream scope"""
    order: list[str] = []

    @fx.fn
    def app():
        yield from scope.add_finalizer(lambda _: effect.sync(lambda: order.append("handler")))
        body = (
            stream.from_iterable(["foo", "bar"])
            .encode_text()
            .ensuring(effect.sync(lambda: order.append("stream")))
        )
        return server_response.stream(body)

    handler = to_web_handler(app())

    async def main() -> str:
        return await (await handler(_request())).text()

    assert _aio(main) == "foobar"
    assert order == ["stream", "handler"]


def test_streaming_head_closes_the_request_scope() -> None:
    """streaming HEAD closes the request scope"""
    finalized: list[bool] = []

    @fx.fn
    def app():
        yield from scope.add_finalizer(lambda _: effect.sync(lambda: finalized.append(True)))
        return server_response.stream(stream.from_iterable(["body"]).encode_text())

    handler = to_web_handler(app())
    _aio(lambda: handler(_request(method="HEAD")))
    assert finalized == [True]


@pytest.mark.parametrize("status", [204, 205, 304])
def test_status_closes_the_request_scope_without_starting_the_stream(status: int) -> None:
    """status %i closes the request scope without starting the stream"""
    finalized: list[bool] = []
    started: list[bool] = []

    def start() -> bytes:
        started.append(True)
        return b"\x01"

    @fx.fn
    def app():
        yield from scope.add_finalizer(lambda _: effect.sync(lambda: finalized.append(True)))
        return server_response.stream(stream.from_effect(effect.sync(start)), status=status)

    handler = to_web_handler(app())
    web = _aio(lambda: handler(_request()))
    assert web.status == status
    assert web.body is None
    assert started == []
    assert finalized == [True]


def test_stream_runtime() -> None:
    """stream runtime"""
    body = stream.from_effect(Value420()).map(str).encode_text()
    handler = to_web_handler_with(Context.make(Value420, 420))(
        effect.succeed(server_response.stream(body)), None
    )

    async def main() -> str:
        return await (await handler(_request())).text()

    assert _aio(main) == "420"


def test_stream_layer() -> None:
    """stream layer"""
    body = stream.from_effect(Value420()).map(str).encode_text()

    async def main() -> str:
        made = to_web_handler_layer(
            effect.succeed(server_response.stream(body)), layer.succeed(Value420, 420)
        )
        return await (await made.handler(_request())).text()

    assert _aio(main) == "420"


def test_custom_context() -> None:
    """custom context"""

    class Env(Reference[dict[str, str]]):
        @classmethod
        def default(cls) -> dict[str, str]:
            return {"foo": "bar"}

    handler = to_web_handler(Env().flat_map(server_response.json))

    async def main() -> object:
        return await (await handler(_request(), Context.make(Env, {"foo": "baz"}))).json()

    assert _aio(main) == {"foo": "baz"}


# --- toWebHandlerLayer ----------------------------------------------------------


def test_builds_the_layer_when_the_handler_is_created() -> None:
    """builds the layer when the handler is created"""
    builds: list[int] = []

    def build() -> int:
        builds.append(1)
        return 420

    async def main() -> str:
        made = to_web_handler_layer(
            Value420().map(lambda value: server_response.text(str(value))),
            layer.effect(Value420, effect.sync(build)),
        )
        await asyncio.sleep(0)
        assert len(builds) == 1
        text = await (await made.handler(_request())).text()
        assert len(builds) == 1
        await made.dispose()
        return text

    assert _aio(main) == "420"


def test_a_failing_layer_rejects_every_request() -> None:
    """a failing layer rejects every request without an unhandled rejection"""
    error = ValueError("boom")

    async def main() -> list[BaseException]:
        made = to_web_handler_layer(
            effect.succeed(server_response.empty()), layer.effect_discard(effect.fail(error))
        )
        await asyncio.sleep(0)
        rejected: list[BaseException] = []
        for _ in range(2):
            try:
                await made.handler(_request())
            except ValueError as raised:
                rejected.append(raised)
        return rejected

    assert _aio(main) == [error, error]


# --- fromWebHandler -------------------------------------------------------------


def _read(make: Callable[[], Awaitable[WebResponse]]) -> tuple[WebResponse, bytes]:
    async def main() -> tuple[WebResponse, bytes]:
        web = await make()
        return web, await web.read()

    return _aio(main)


def test_basic_get_request() -> None:
    """basic GET request"""

    async def web_handler(request: WebRequest) -> WebResponse:
        return WebResponse(f"Hello from {request.url}", headers={"Content-Type": "text/plain"})

    handler = to_web_handler(from_web_handler(web_handler))
    web, body = _read(lambda: handler(_request("http://localhost:3000/hello")))
    assert web.status == 200
    assert body == b"Hello from http://localhost:3000/hello"


def test_post_with_json_body() -> None:
    """POST with JSON body"""

    async def web_handler(request: WebRequest) -> WebResponse:
        return WebResponse.json_of({"received": await request.json()})

    handler = to_web_handler(from_web_handler(web_handler))
    request = _request(
        method="POST", body='{"message":"hello"}', headers={"Content-Type": "application/json"}
    )

    async def main() -> object:
        return await (await handler(request)).json()

    assert _aio(main) == {"received": {"message": "hello"}}


def test_preserves_request_headers() -> None:
    """preserves request headers"""

    async def web_handler(request: WebRequest) -> WebResponse:
        return WebResponse.json_of(
            {
                "authorization": request.get("Authorization"),
                "custom": request.get("X-Custom-Header"),
            }
        )

    handler = to_web_handler(from_web_handler(web_handler))
    request = _request(
        headers={"Authorization": "Bearer token123", "X-Custom-Header": "custom-value"}
    )

    async def main() -> object:
        return await (await handler(request)).json()

    assert _aio(main) == {"authorization": "Bearer token123", "custom": "custom-value"}


def test_preserves_response_status_and_headers() -> None:
    """preserves response status and headers"""

    async def web_handler(_request: WebRequest) -> WebResponse:
        return WebResponse(
            "Not Found",
            status=404,
            status_text="Not Found",
            headers={"X-Error-Code": "RESOURCE_NOT_FOUND", "Content-Type": "text/plain"},
        )

    handler = to_web_handler(from_web_handler(web_handler))
    web, body = _read(lambda: handler(_request("http://localhost:3000/missing")))
    assert web.status == 404
    assert web.get("X-Error-Code") == "RESOURCE_NOT_FOUND"
    assert body == b"Not Found"


def test_round_trip_with_to_web_handler() -> None:
    """round-trip with toWebHandler"""
    web_handler = to_web_handler(server_response.json({"source": "effect"}))
    final = to_web_handler(from_web_handler(web_handler))

    async def main() -> object:
        return await (await final(_request())).json()

    assert _aio(main) == {"source": "effect"}


def test_json_preserves_content_type() -> None:
    """json preserves content-type"""
    handler = to_web_handler(server_response.json({"foo": "bar"}))
    web = _aio(lambda: handler(_request()))
    assert web.get("Content-Type") == "application/json"


def test_preserves_response_content_type_header() -> None:
    """preserves response content-type header"""

    async def web_handler(_request: WebRequest) -> WebResponse:
        return WebResponse.json_of({"message": "hello"})

    handler = to_web_handler(from_web_handler(web_handler))

    async def main() -> tuple[str | None, object]:
        web = await handler(_request())
        return web.get("Content-Type"), await web.json()

    assert _aio(main) == ("application/json", {"message": "hello"})


def test_preserves_custom_content_type_header() -> None:
    """preserves custom content-type header"""

    async def web_handler(_request: WebRequest) -> WebResponse:
        return WebResponse("<html></html>", headers={"Content-Type": "text/html; charset=utf-8"})

    handler = to_web_handler(from_web_handler(web_handler))
    web = _aio(lambda: handler(_request()))
    assert web.get("Content-Type") == "text/html; charset=utf-8"
