"""``pyfect.http.asgi``: apps driven as ASGI applications in memory (as a
server or a host framework calls them), and ASGI applications mounted in
apps."""

from __future__ import annotations

import asyncio
from collections.abc import Sequence
from typing import Any

import pytest

import pyfect as fx
from pyfect import effect, layer, stream
from pyfect.context import Tag
from pyfect.deferred import Deferred
from pyfect.exit import fail as exit_fail
from pyfect.http import asgi, router, server_response
from pyfect.http.asgi import Message, Receive, Scope, Send
from pyfect.http.asgi._http import InvalidResponseHeaderError
from pyfect.http.server_request import HttpServerRequest, ServerRequest
from pyfect.http.server_response import HttpServerResponse
from pyfect.scope import acquire_release


def _scope(
    path: str = "/",
    *,
    method: str = "GET",
    headers: Sequence[tuple[str, str]] = (),
    root_path: str = "",
    query: bytes = b"",
    type: str = "http",
    extensions: dict[str, Any] | None = None,
) -> Scope:
    return {
        "type": type,
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": method,
        "scheme": "http",
        "path": path,
        "raw_path": path.encode(),
        "root_path": root_path,
        "query_string": query,
        "headers": [(k.encode(), v.encode()) for k, v in [("host", "test"), *headers]],
        "client": ("10.0.0.1", 1234),
        "server": ("test", 80),
        "extensions": extensions or {},
    }


class _Peer:
    """The server side of one ASGI call: queued messages in, sent ones
    recorded."""

    def __init__(self, *messages: Message) -> None:
        self.inbox: asyncio.Queue[Message] = asyncio.Queue()
        for message in messages:
            self.inbox.put_nowait(message)
        self.sent: list[Message] = []
        self.on_send = asyncio.Event()

    async def receive(self) -> Message:
        return await self.inbox.get()

    async def send(self, message: Message) -> None:
        self.sent.append(message)
        self.on_send.set()

    def status(self) -> int:
        return next(m["status"] for m in self.sent if m["type"].endswith("response.start"))

    def body(self) -> bytes:
        return b"".join(m.get("body", b"") for m in self.sent if m["type"].endswith("body"))


async def _request(app: Any, scope: Scope, *body: bytes) -> _Peer:
    chunks = body or (b"",)
    peer = _Peer(
        *(
            {"type": "http.request", "body": chunk, "more_body": i < len(chunks) - 1}
            for i, chunk in enumerate(chunks)
        )
    )
    await app(scope, peer.receive, peer.send)
    return peer


def _app(
    f: Any,
) -> fx.Effect[HttpServerResponse, Any, Any]:
    return HttpServerRequest().flat_map(f)


class Greeting(Tag[str], key="test/asgi/Greeting"):
    pass


def _greeting_layer(events: list[str]) -> fx.Layer[Greeting]:
    acquired = acquire_release(
        effect.sync(lambda: events.append("acquired")).as_("hello"),
        lambda _value, _exit: effect.sync(lambda: events.append("released")),
    )
    return layer.effect(Greeting, acquired)


def _greet(_request: ServerRequest) -> fx.Effect[HttpServerResponse, Any, Greeting]:
    return Greeting().map(server_response.text)


def test_lifespan_builds_the_layer_once_and_releases_it_at_shutdown() -> None:
    events: list[str] = []
    app = asgi.to_asgi(_app(_greet), _greeting_layer(events))

    async def main() -> list[bytes]:
        lifespan = _Peer({"type": "lifespan.startup"})
        running = asyncio.ensure_future(
            app({"type": "lifespan", "asgi": {"version": "3.0"}}, lifespan.receive, lifespan.send)
        )
        await lifespan.on_send.wait()
        assert lifespan.sent == [{"type": "lifespan.startup.complete"}]
        assert events == ["acquired"]
        bodies = [(await _request(app, _scope())).body() for _ in range(2)]
        lifespan.inbox.put_nowait({"type": "lifespan.shutdown"})
        await running
        assert lifespan.sent[-1] == {"type": "lifespan.shutdown.complete"}
        return bodies

    assert asyncio.run(main()) == [b"hello", b"hello"]
    assert events == ["acquired", "released"]


def test_a_failed_build_fails_the_lifespan_startup() -> None:
    failing: fx.Layer[Greeting, str] = layer.effect(Greeting, effect.fail("no greeting"))
    app = asgi.to_asgi(_app(_greet), failing)

    async def main() -> list[Message]:
        peer = _Peer({"type": "lifespan.startup"})
        await app({"type": "lifespan"}, peer.receive, peer.send)
        return peer.sent

    [message] = asyncio.run(main())
    assert message["type"] == "lifespan.startup.failed"
    assert "no greeting" in message["message"]


def test_without_a_lifespan_the_first_request_builds_the_layer() -> None:
    events: list[str] = []
    app = asgi.to_asgi(_app(_greet), _greeting_layer(events))

    async def main() -> bytes:
        peer = await _request(app, _scope())
        await app.runtime.dispose_async()
        return peer.body()

    assert asyncio.run(main()) == b"hello"
    assert events == ["acquired", "released"]


def test_the_host_lifespan_context_manager_builds_and_releases_the_layer() -> None:
    events: list[str] = []
    app = asgi.to_asgi(_app(_greet), _greeting_layer(events))

    async def main() -> None:
        async with app.lifespan():
            assert events == ["acquired"]
            assert (await _request(app, _scope())).body() == b"hello"

    asyncio.run(main())
    assert events == ["acquired", "released"]


def test_reads_the_request_from_the_scope() -> None:
    def describe(request: ServerRequest) -> fx.Effect[HttpServerResponse, Any]:
        return request.text.map(
            lambda text: server_response.json_unsafe(
                {
                    "method": request.method,
                    "url": request.url,
                    "host": request.headers.get("host"),
                    "remote": request.remote_address,
                    "body": text,
                }
            )
        )

    app = asgi.to_asgi(_app(describe))
    scope = _scope(
        "/api/items",
        method="POST",
        root_path="/api",
        query=b"page=2",
        headers=[("content-length", "6")],
    )
    peer = asyncio.run(_request(app, scope, b"ab", b"cd", b"ef"))
    assert peer.status() == 200
    import json

    assert json.loads(peer.body()) == {
        "method": "POST",
        "url": "/items?page=2",
        "host": "test",
        "remote": "10.0.0.1",
        "body": "abcdef",
    }


def test_streams_the_response_body() -> None:
    body = stream.from_iterable([b"a", b"b", b"c"])
    app = asgi.to_asgi(effect.succeed(server_response.stream(body)))
    peer = asyncio.run(_request(app, _scope()))
    chunks = [m for m in peer.sent if m["type"] == "http.response.body"]
    assert [(m["body"], m.get("more_body", False)) for m in chunks] == [
        (b"a", True),
        (b"b", True),
        (b"c", True),
        (b"", False),
    ]


def test_head_responses_have_no_body() -> None:
    app = asgi.to_asgi(effect.succeed(server_response.text("hello")))
    peer = asyncio.run(_request(app, _scope(method="HEAD")))
    assert peer.status() == 200
    assert peer.body() == b""
    start = peer.sent[0]
    assert (b"content-length", b"5") in start["headers"]


def test_a_client_disconnect_interrupts_the_request() -> None:
    started: Deferred[None] = Deferred()
    interrupted: Deferred[None] = Deferred()
    waiting = started.succeed(None).and_then(effect.never).interruptible()
    app = asgi.to_asgi(waiting.on_interrupt(interrupted.succeed(None)).as_(server_response.empty()))

    async def main() -> tuple[int, bool]:
        peer = _Peer({"type": "http.request", "body": b""})
        call = asyncio.ensure_future(app(_scope(), peer.receive, peer.send))
        await fx.run_async(started.wait())
        peer.inbox.put_nowait({"type": "http.disconnect"})
        await asyncio.wait_for(call, 5)
        await fx.run_async(interrupted.wait().timeout("5 seconds").or_die())
        return peer.status(), True

    status, was_interrupted = asyncio.run(main())
    assert status == 499
    assert was_interrupted


def test_routes_are_served_by_router_to_asgi() -> None:
    events: list[str] = []
    # Handlers read the services the served layer builds.
    routes = router.add("GET", "/hello", _app(_greet)).pipe(
        layer.provide_merge(_greeting_layer(events))
    )
    app = router.to_asgi(routes, disable_logger=True)

    async def main() -> tuple[int, int]:
        async with app.lifespan():
            found = await _request(app, _scope("/hello"))
            missing = await _request(app, _scope("/nope"))
        return found.status(), missing.status()

    assert asyncio.run(main()) == (200, 404)
    assert events == ["acquired", "released"]


# --- WebSocket scopes ----------------------------------------------------------------


def _echo(request: ServerRequest) -> fx.Effect[HttpServerResponse, Any, Any]:
    @fx.fn
    def body():
        sock = yield from request.upgrade
        reader = yield from sock.reader
        writer = yield from sock.writer
        chunks = yield from reader.pull
        yield from writer.write_all([c.upper() if isinstance(c, str) else c for c in chunks])
        return server_response.empty()

    from pyfect.scope import scoped

    return scoped(body())


def test_a_websocket_is_accepted_when_the_app_upgrades() -> None:
    app = asgi.to_asgi(_app(_echo))

    async def main() -> list[Message]:
        peer = _Peer(
            {"type": "websocket.connect"},
            {"type": "websocket.receive", "text": "hello"},
        )
        scope = _scope("/ws", type="websocket")
        scope["subprotocols"] = ["chat", "other"]
        await asyncio.wait_for(app(scope, peer.receive, peer.send), 5)
        return peer.sent

    sent = asyncio.run(main())
    assert sent == [
        {"type": "websocket.accept", "subprotocol": "chat"},
        {"type": "websocket.send", "text": "HELLO"},
        {"type": "websocket.close", "code": 1000, "reason": ""},
    ]


def test_an_app_that_does_not_upgrade_answers_over_http() -> None:
    app = asgi.to_asgi(effect.succeed(server_response.text("no", status=426)))

    async def main(extensions: dict[str, Any]) -> list[Message]:
        peer = _Peer({"type": "websocket.connect"})
        scope = _scope("/ws", type="websocket", extensions=extensions)
        await asyncio.wait_for(app(scope, peer.receive, peer.send), 5)
        return peer.sent

    start, body = asyncio.run(main({"websocket.http.response": {}}))
    assert start["type"] == "websocket.http.response.start"
    assert start["status"] == 426
    assert body == {"type": "websocket.http.response.body", "body": b"no"}
    # Without the extension the server refuses the handshake (403).
    assert asyncio.run(main({})) == [{"type": "websocket.close", "code": 1008}]


def test_a_lost_websocket_connection_interrupts_the_app() -> None:
    reading: Deferred[None] = Deferred()
    interrupted: Deferred[None] = Deferred()

    def hold(request: ServerRequest) -> fx.Effect[HttpServerResponse, Any, Any]:
        # The reader stays open in the request's scope.
        upgraded = (
            request.upgrade.flat_map(lambda sock: sock.reader)
            .and_then(reading.succeed(None))
            .and_then(effect.never)
        )
        return upgraded.interruptible().on_interrupt(interrupted.succeed(None))

    app = asgi.to_asgi(_app(hold))

    async def main() -> list[Message]:
        peer = _Peer({"type": "websocket.connect"})
        call = asyncio.ensure_future(app(_scope("/ws", type="websocket"), peer.receive, peer.send))
        await fx.run_async(reading.wait().timeout("5 seconds").or_die())
        peer.inbox.put_nowait({"type": "websocket.disconnect", "code": 1006})
        await asyncio.wait_for(call, 5)
        await fx.run_async(interrupted.wait().timeout("5 seconds").or_die())
        return peer.sent

    assert asyncio.run(main()) == [{"type": "websocket.accept", "subprotocol": None}]


# --- ASGI applications in apps ---------------------------------------------------------


async def _echo_asgi(scope: Scope, receive: Receive, send: Send) -> None:
    body = b""
    while True:
        message = await receive()
        body += message.get("body", b"")
        if not message.get("more_body", False):
            break
    await send(
        {
            "type": "http.response.start",
            "status": 201,
            "headers": [
                (b"x-root", scope["root_path"].encode()),
                (b"x-path", scope["path"].encode()),
            ],
        }
    )
    await send({"type": "http.response.body", "body": b"echo:", "more_body": True})
    await send({"type": "http.response.body", "body": body})


def test_from_asgi_mounts_an_asgi_application_under_a_prefix() -> None:
    mounted = router.add_all(
        [router.route("*", "*", asgi.from_asgi(_echo_asgi)).pipe(router.prefix_route("/legacy"))]
    )
    app = router.to_asgi(mounted, disable_logger=True)

    async def main() -> _Peer:
        async with app.lifespan():
            return await _request(
                app,
                _scope("/legacy/items", method="POST", headers=[("content-length", "4")]),
                b"da",
                b"ta",
            )

    peer = asyncio.run(main())
    assert peer.status() == 201
    assert peer.body() == b"echo:data"
    headers = dict(peer.sent[0]["headers"])
    assert headers[b"x-root"] == b"/legacy"
    assert headers[b"x-path"] == b"/legacy/items"


def test_from_asgi_fails_with_a_500_when_the_application_raises() -> None:
    async def broken(scope: Scope, receive: Receive, send: Send) -> None:
        raise RuntimeError("broken")

    app = asgi.to_asgi(asgi.from_asgi(broken))
    assert asyncio.run(_request(app, _scope())).status() == 500


def test_lifespan_runs_the_applications_startup_and_shutdown() -> None:
    events: list[str] = []

    async def with_lifespan(scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "lifespan":
            while True:
                message = await receive()
                if message["type"] == "lifespan.startup":
                    scope["state"]["db"] = "connected"
                    events.append("startup")
                    await send({"type": "lifespan.startup.complete"})
                else:
                    events.append("shutdown")
                    await send({"type": "lifespan.shutdown.complete"})
                    return
        await _echo_asgi(scope, receive, send)

    @fx.fn
    def program():
        state = yield from asgi.lifespan(with_lifespan)
        events.append(f"running with {state['db']}")

    asyncio.run(fx.run_async(fx.scoped(program()).or_die()))
    assert events == ["startup", "running with connected", "shutdown"]


def test_lifespan_fails_when_the_startup_fails() -> None:
    async def failing(scope: Scope, receive: Receive, send: Send) -> None:
        await receive()
        await send({"type": "lifespan.startup.failed", "message": "no database"})

    exit = asyncio.run(fx.run_async(fx.scoped(asgi.lifespan(failing)).exit()))
    assert exit == exit_fail(asgi.AsgiLifespanError("no database"))


def test_lifespan_of_an_application_without_lifespan_support_starts_at_once() -> None:
    async def http_only(scope: Scope, receive: Receive, send: Send) -> None:
        raise RuntimeError("unsupported scope")

    state = asyncio.run(fx.run_async(fx.scoped(asgi.lifespan(http_only)).or_die()))
    assert state == {}


# --- review: edge cases ---------------------------------------------------------------


class _CountingPeer(_Peer):
    def __init__(self, *messages: Message) -> None:
        super().__init__(*messages)
        self.received = 0

    async def receive(self) -> Message:
        self.received += 1
        return await super().receive()


def test_an_unread_request_body_is_buffered_up_to_the_high_water_mark() -> None:
    release: Deferred[None] = Deferred()
    app = asgi.to_asgi(release.wait().as_(server_response.empty()))
    chunk = b"x" * (asgi.HIGH_WATER_MARK // 4)

    async def main() -> int:
        peer = _CountingPeer(
            *({"type": "http.request", "body": chunk, "more_body": True} for _ in range(16))
        )
        scope = _scope(method="POST", headers=[("transfer-encoding", "chunked")])
        call = asyncio.ensure_future(app(scope, peer.receive, peer.send))
        await asyncio.sleep(0.05)
        received = peer.received
        await fx.run_async(release.succeed(None))
        await asyncio.wait_for(call, 5)
        return received

    # Four chunks fill the buffer; nothing more is read while nobody reads.
    assert asyncio.run(main()) == 4


def _echo_text(request: ServerRequest) -> fx.Effect[HttpServerResponse, Any]:
    return request.text.map(server_response.text)


def test_a_chunked_request_has_a_body() -> None:
    app = asgi.to_asgi(_app(_echo_text))
    scope = _scope(method="POST", headers=[("transfer-encoding", "chunked")])
    assert asyncio.run(_request(app, scope, b"ab", b"cd")).body() == b"abcd"


def test_the_request_url_follows_the_scope_scheme() -> None:
    from pyfect.http.server_request import to_url

    def scheme(request: ServerRequest) -> fx.Effect[HttpServerResponse]:
        url = to_url(request)
        return effect.succeed(server_response.text("" if url is None else url.scheme))

    app = asgi.to_asgi(_app(scheme))
    scope = _scope()
    scope["scheme"] = "https"
    assert asyncio.run(_request(app, scope)).body() == b"https"


def test_a_failed_send_stops_the_streamed_body() -> None:
    events: list[str] = []
    body = (
        stream.iterate(0, lambda n: n + 1)
        .map(lambda n: str(n).encode())
        .ensuring(effect.sync(lambda: events.append("closed")))
    )
    app = asgi.to_asgi(effect.succeed(server_response.stream(body)))

    class _Gone(_Peer):
        async def send(self, message: Message) -> None:
            await super().send(message)
            if len(self.sent) > 3:
                raise ConnectionResetError("gone")

    async def main() -> None:
        peer = _Gone({"type": "http.request", "body": b""})
        await asyncio.wait_for(app(_scope(), peer.receive, peer.send), 5)
        await asyncio.sleep(0.05)

    # The server's send error ends the request quietly and closes the body.
    asyncio.run(main())
    assert events == ["closed"]


def test_a_server_error_while_streaming_closes_the_body_and_is_raised() -> None:
    events: list[str] = []
    body = (
        stream.iterate(0, lambda n: n + 1)
        .map(lambda n: str(n).encode())
        .ensuring(effect.sync(lambda: events.append("closed")))
    )
    app = asgi.to_asgi(effect.succeed(server_response.stream(body)))

    class _Broken(_Peer):
        async def send(self, message: Message) -> None:
            await super().send(message)
            if len(self.sent) > 3:
                raise RuntimeError("server bug")

    async def main() -> str:
        peer = _Broken({"type": "http.request", "body": b""})
        try:
            await asyncio.wait_for(app(_scope(), peer.receive, peer.send), 5)
        except RuntimeError as error:
            await asyncio.sleep(0.05)
            # Closed while the loop runs, not when it shuts down.
            return f"{error}: {events}"
        return "no error"

    assert asyncio.run(main()) == "server bug: ['closed']"


class _ClosingPeer(_Peer):
    """A client that drops the connection when the app closes it."""

    async def send(self, message: Message) -> None:
        await super().send(message)
        if message["type"] == "websocket.close":
            self.inbox.put_nowait({"type": "websocket.disconnect", "code": 1006})


def test_a_websocket_the_app_closed_is_not_a_lost_connection() -> None:
    from pyfect.scope import scoped
    from pyfect.socket import CloseEvent

    events: list[str] = []

    def close_then_work(request: ServerRequest) -> fx.Effect[HttpServerResponse, Any, Any]:
        @fx.fn
        def body():
            sock = yield from request.upgrade
            yield from sock.reader
            writer = yield from sock.writer
            yield from writer.write(CloseEvent(4400, "bye"))
            yield from fx.sleep("100 millis")
            yield from effect.sync(lambda: events.append("finished"))
            return server_response.empty()

        return (
            scoped(body())
            .interruptible()
            .on_interrupt(effect.sync(lambda: events.append("interrupted")))
        )

    app = asgi.to_asgi(_app(close_then_work))

    async def main() -> list[Message]:
        peer = _ClosingPeer({"type": "websocket.connect"})
        await asyncio.wait_for(app(_scope("/ws", type="websocket"), peer.receive, peer.send), 5)
        return peer.sent

    sent = asyncio.run(main())
    assert sent[-1] == {"type": "websocket.close", "code": 4400, "reason": "bye"}
    assert events == ["finished"]


def test_a_websocket_closed_before_the_upgrade_interrupts_the_app() -> None:
    waiting: Deferred[None] = Deferred()
    interrupted: Deferred[None] = Deferred()
    hold = waiting.succeed(None).and_then(effect.never).interruptible()
    app = asgi.to_asgi(hold.on_interrupt(interrupted.succeed(None)).as_(server_response.empty()))

    async def main() -> list[Message]:
        peer = _Peer({"type": "websocket.connect"})
        call = asyncio.ensure_future(app(_scope("/ws", type="websocket"), peer.receive, peer.send))
        await fx.run_async(waiting.wait().timeout("5 seconds").or_die())
        # A clean close code, but the handshake never finished.
        peer.inbox.put_nowait({"type": "websocket.disconnect", "code": 1000})
        await asyncio.wait_for(call, 5)
        await fx.run_async(interrupted.wait().timeout("5 seconds").or_die())
        return peer.sent

    assert asyncio.run(main()) == []


def test_websocket_upgrades_with_custom_headers_fail() -> None:
    def upgrade(request: ServerRequest) -> fx.Effect[HttpServerResponse, Any, Any]:
        return (
            request.upgrade_with(headers={"x-extra": "1"})
            .exit()
            .map(
                lambda exit: server_response.text(
                    "failed" if isinstance(exit, fx.Failure) else "upgraded", status=426
                )
            )
        )

    app = asgi.to_asgi(_app(upgrade))

    async def main() -> list[Message]:
        peer = _Peer({"type": "websocket.connect"})
        scope = _scope("/ws", type="websocket", extensions={"websocket.http.response": {}})
        await asyncio.wait_for(app(scope, peer.receive, peer.send), 5)
        return peer.sent

    _start, body = asyncio.run(main())
    assert body["body"] == b"failed"


def test_a_host_header_that_is_not_an_authority_does_not_change_the_routed_path() -> None:
    admin = effect.succeed(server_response.text("ADMIN"))

    def echo(request: ServerRequest) -> fx.Effect[HttpServerResponse]:
        return effect.succeed(server_response.text(f"{request.url} {request.original_url}"))

    routes = router.add("GET", "/admin", admin).pipe(
        layer.provide_merge(router.add("GET", "/public", _app(echo)))
    )
    app = router.to_asgi(routes, disable_logger=True)

    async def main() -> list[bytes]:
        bodies: list[bytes] = []
        async with app.lifespan():
            for host in ("x/admin?", "x?role=admin&", "u@x", "x#f"):
                scope = _scope("/public")
                scope["headers"] = [(b"host", host.encode())]
                bodies.append((await _request(app, scope)).body())
        return bodies

    assert asyncio.run(main()) == [b"/public http://test:80/public"] * 4


def test_a_host_header_that_is_not_an_authority_does_not_change_to_url() -> None:
    """``to_url`` (what a web handler and the tracer read) never resolves
    the request's path against a client-sent host."""
    from pyfect.http.server_request import to_url

    def full(request: ServerRequest) -> fx.Effect[HttpServerResponse]:
        url = to_url(request)
        return effect.succeed(server_response.text("None" if url is None else url.geturl()))

    app = asgi.to_asgi(_app(full))

    async def main() -> list[bytes]:
        bodies: list[bytes] = []
        for host in ("x/admin/", "x/a/b?", "u@x", "[1]"):
            scope = _scope("/public")
            scope["headers"] = [(b"host", host.encode())]
            bodies.append((await _request(app, scope)).body())
        return bodies

    assert asyncio.run(main()) == [b"None"] * 4


def test_a_path_that_is_not_origin_form_is_a_400() -> None:
    """A server may hand on a raw request-target without a leading ``/``
    (uvicorn's h11 protocol does); it must neither run into the host nor
    be routed as if it had one."""
    admin = effect.succeed(server_response.text("ADMIN"))
    routes = router.add("GET", "/admin", admin).pipe(
        layer.provide_merge(router.add("*", "*", effect.succeed(server_response.text("ANY"))))
    )
    app = router.to_asgi(routes, disable_logger=True)

    async def main() -> list[tuple[int, bytes]]:
        responses: list[tuple[int, bytes]] = []
        async with app.lifespan():
            for path in ("evil.com/admin", "admin", "http://evil/admin"):
                response = await _request(app, _scope(path))
                responses.append((response.status(), response.body()))
        return responses

    assert asyncio.run(main()) == [(400, b"")] * 3


def test_a_websocket_path_that_is_not_origin_form_is_refused() -> None:
    app = asgi.to_asgi(_app(_echo))

    async def main() -> list[Message]:
        peer = _Peer({"type": "websocket.connect"})
        await asyncio.wait_for(app(_scope("evil/ws", type="websocket"), peer.receive, peer.send), 5)
        return peer.sent

    assert asyncio.run(main()) == [{"type": "websocket.close", "code": 1008}]


def test_from_asgi_keeps_an_encoded_slash_the_router_did_not_split_on() -> None:
    """The mounted app routes on what pyfect routed on: ``%2F`` stayed
    inside one segment for the router, so it stays encoded in the scope's
    ``path`` (a guard on a more specific route cannot be bypassed)."""
    guarded = router.route(
        "*", "/admin/*", effect.succeed(server_response.text("denied", status=403))
    ).pipe(router.prefix_route("/legacy"))
    public = router.route("*", "*", asgi.from_asgi(_echo_asgi)).pipe(router.prefix_route("/legacy"))
    app = router.to_asgi(router.add_all([public, guarded]), disable_logger=True)

    async def main() -> list[tuple[int, bytes, bytes]]:
        seen: list[tuple[int, bytes, bytes]] = []
        async with app.lifespan():
            for path in ("/legacy/admin/users", "/legacy/admin%2Fusers", "/legacy/a%2fb%20c"):
                peer = await _request(app, _scope(path))
                headers = dict(peer.sent[0]["headers"])
                seen.append(
                    (peer.status(), headers.get(b"x-root", b""), headers.get(b"x-path", b""))
                )
        return seen

    assert asyncio.run(main()) == [
        (403, b"", b""),
        (201, b"/legacy", b"/legacy/admin%2Fusers"),
        (201, b"/legacy", b"/legacy/a%2fb c"),
    ]


def test_a_foreign_handler_never_sees_a_dot_segment_the_router_matched_literally() -> None:
    """The router matches ``..`` as a literal segment, while a mounted app
    (Starlette's ``StaticFiles``, a WHATWG ``URL``) resolves it: such a
    path is refused before either bridge, so ``/x/../admin`` cannot reach
    what a guard on ``/admin/*`` protects. Browsers never send one."""
    from pyfect.http.web import WebRequest, WebResponse
    from pyfect.http.web_handler import from_web_handler

    called: list[str] = []

    async def web(request: WebRequest) -> WebResponse:
        called.append(request.url)
        return WebResponse("ok")

    guarded = router.route(
        "*", "/admin/*", effect.succeed(server_response.text("denied", status=403))
    ).pipe(router.prefix_route("/legacy"))
    on_asgi = router.route("*", "/asgi/*", asgi.from_asgi(_echo_asgi))
    on_web = router.route("*", "/web/*", from_web_handler(web))
    mounted = [route.pipe(router.prefix_route("/legacy")) for route in (on_asgi, on_web)]
    app = router.to_asgi(router.add_all([*mounted, guarded]), disable_logger=True)
    paths = [
        f"/legacy/{bridge}/{dots}/admin/users"
        for bridge in ("asgi", "web")
        for dots in ("..", "%2E%2e", ".%2e/.", "x\\..\\..")
    ]

    async def main() -> list[int]:
        async with app.lifespan():
            return [(await _request(app, _scope(path))).status() for path in paths]

    assert asyncio.run(main()) == [400] * len(paths)
    assert called == []


def test_a_response_header_value_with_a_control_character_is_never_sent() -> None:
    # The same field-value grammar as the live server: tab, visible ASCII, obs-text.
    for value in ("a\x01b", "a\x0bb", "a\x0cb", "a\x7fb", "a\nb"):
        response = server_response.text("ok").set_header("x-value", value)
        app = asgi.to_asgi(effect.succeed(response))
        peer = _Peer({"type": "http.request", "body": b"", "more_body": False})
        with pytest.raises(InvalidResponseHeaderError):
            asyncio.run(app(_scope(), peer.receive, peer.send))
        starts = [m for m in peer.sent if m["type"] == "http.response.start"]
        assert [(m["status"], m["headers"]) for m in starts] == [(500, [])]


def test_a_websocket_lost_while_the_accept_is_sent_stays_closed() -> None:
    from pyfect.http.asgi._web_socket import AsgiWebSocket
    from pyfect.socket._web_socket import CLOSED

    events: list[str] = []

    async def main() -> tuple[int, str]:
        peer = _Peer()
        release = asyncio.Event()

        async def send(message: Message) -> None:
            await peer.send(message)
            await release.wait()

        ws = AsgiWebSocket(peer.receive, send)
        for kind in ("open", "close"):
            ws.add_event_listener(kind, lambda event: events.append(str(event.type)))
        accepting = asyncio.ensure_future(ws.accept(None))
        await asyncio.wait_for(peer.on_send.wait(), 5)
        peer.inbox.put_nowait({"type": "websocket.disconnect", "code": 1006})
        await asyncio.sleep(0.01)
        release.set()
        try:
            await accepting
            outcome = "accepted"
        except ConnectionError:
            outcome = "refused"
        await ws.finish()
        return ws.ready_state, outcome

    # The disconnect wins: the socket never opens after it closed.
    assert asyncio.run(main()) == (CLOSED, "refused")
    assert events == ["close"]


def _held_asgi(status: int, ended: asyncio.Event) -> Any:
    """An ASGI app that starts a streamed response, then waits for the
    disconnect (as Starlette's ``StreamingResponse`` does)."""

    async def app(scope: Scope, receive: Receive, send: Send) -> None:
        try:
            await send({"type": "http.response.start", "status": status, "headers": []})
            if status == 200:
                await send({"type": "http.response.body", "body": b"a", "more_body": True})
            while (await receive())["type"] != "http.disconnect":
                pass
            await asyncio.Event().wait()
        finally:
            ended.set()

    return app


def _drop_body(
    app: fx.Effect[HttpServerResponse, Any, Any],
) -> fx.Effect[HttpServerResponse, Any, Any]:
    return app.map(lambda _response: server_response.text("replaced"))


@pytest.mark.parametrize(
    ("method", "status", "drop"),
    [("HEAD", 200, False), ("GET", 204, False), ("GET", 304, False), ("GET", 200, True)],
    ids=["head", "204", "304", "dropped"],
)
def test_a_mounted_asgi_app_ends_with_its_response(method: str, status: int, drop: bool) -> None:
    async def main() -> tuple[int, bool]:
        ended = asyncio.Event()
        mounted = asgi.from_asgi(_held_asgi(status, ended))
        app = asgi.to_asgi(_drop_body(mounted) if drop else mounted)
        peer = await asyncio.wait_for(_request(app, _scope(method=method)), 5)
        await asyncio.wait_for(ended.wait(), 5)
        return peer.status(), ended.is_set()

    assert asyncio.run(main()) == (200 if drop else status, True)


def test_a_mounted_asgi_app_ends_when_the_client_goes_away() -> None:
    async def main() -> bool:
        ended = asyncio.Event()
        app = asgi.to_asgi(asgi.from_asgi(_held_asgi(200, ended)))
        peer = _Peer({"type": "http.request", "body": b""})
        call = asyncio.ensure_future(app(_scope(), peer.receive, peer.send))
        await asyncio.wait_for(peer.on_send.wait(), 5)
        peer.inbox.put_nowait({"type": "http.disconnect"})
        await asyncio.wait_for(call, 5)
        await asyncio.wait_for(ended.wait(), 5)
        return ended.is_set()

    assert asyncio.run(main())
