"""``router.in_memory_client``: routes answered in memory, with response
bodies streamed to the client as the handler writes them."""

from __future__ import annotations

from typing import Any, Never, TypedDict

import pyfect as fx
from pyfect import layer, stream, testing
from pyfect import schema as S
from pyfect.deferred import Deferred
from pyfect.errors import Done
from pyfect.http import body, router, server_response
from pyfect.http.client import HttpClient
from pyfect.http.server_error import HttpServerError, RouteNotFound
from pyfect.http_api import HttpApi, HttpApiGroup, HttpApiRequest, builder, endpoint
from pyfect.http_api.error import HttpApiSchemaError
from pyfect.queue import Queue
from pyfect.scope import add_finalizer


def _streaming(body: stream.Stream[bytes, Any]) -> layer.Layer[Never, Never, router.HttpRouter]:
    return router.add(
        "GET", "/events", fx.succeed(server_response.stream(body, content_type="text/plain"))
    )


@testing.effect
def test_a_chunk_reaches_the_client_while_the_handler_still_writes():
    chunks = Queue[bytes, Done]()
    client = yield from router.in_memory_client(_streaming(stream.from_queue(chunks)))
    response = yield from client.get("http://localhost/events")
    pull = yield from response.stream.to_pull()
    yield from chunks.offer(b"one")
    assert (yield from pull) == (b"one",)
    yield from chunks.offer(b"two")
    assert (yield from pull) == (b"two",)


@testing.effect
def test_the_handler_writes_only_what_the_client_pulls():
    produced: list[int] = []
    counting = stream.iterate(0, lambda n: n + 1).tap(lambda n: fx.sync(lambda: produced.append(n)))
    body = counting.map(lambda n: str(n).encode()).rechunk(1)
    client = yield from router.in_memory_client(_streaming(body))
    response = yield from client.get("http://localhost/events")
    assert (yield from response.stream.take(3).run_collect()) == [b"0", b"1", b"2"]
    assert len(produced) <= 4


@testing.effect
def test_a_reader_that_stops_closes_the_request_scope():
    closed = Deferred[None]()

    @fx.gen
    def handler():
        yield from add_finalizer(lambda _exit: closed.succeed(None).as_void())
        body = stream.make(b"first").concat(stream.never)
        return server_response.stream(body, content_type="text/plain")

    client = yield from router.in_memory_client(router.add("GET", "/events", handler))
    response = yield from client.get("http://localhost/events")
    assert not (yield from closed.is_done())
    assert (yield from response.stream.take(1).run_collect()) == [b"first"]
    yield from closed.wait().timeout("1 second")


@testing.effect
def test_an_unread_body_closes_with_the_clients_scope():
    closed = Deferred[None]()

    @fx.gen
    def handler():
        yield from add_finalizer(lambda _exit: closed.succeed(None).as_void())
        return server_response.stream(stream.never, content_type="text/plain")

    @fx.gen
    def request():
        client = yield from router.in_memory_client(router.add("GET", "/events", handler))
        yield from client.get("http://localhost/events")

    yield from request.pipe(fx.scoped)
    assert (yield from closed.is_done())


@testing.effect
def test_an_unhandled_handler_error_is_a_defect_of_the_request():
    client = yield from router.in_memory_client(
        router.add("GET", "/fails", fx.fail(ValueError("boom")))
    )
    exit_ = yield from client.get("http://localhost/fails").exit()
    assert isinstance(exit_, fx.exit.Failure)
    assert isinstance(exit_.cause.squash(), ValueError)


def _defect_of(exit_: fx.exit.Exit[object, object]) -> object:
    assert isinstance(exit_, fx.exit.Failure)
    return exit_.cause.squash()


@testing.effect
def test_a_route_not_found_is_a_defect_of_the_request():
    # Effect's HttpApiTest client pipes the router through `Effect.orDie`, so a
    # route not found dies with its HttpServerError where a server answers 404.
    routes = router.add("GET", "/hello", server_response.text("hello"))
    client = yield from router.in_memory_client(routes)
    defect = _defect_of((yield from client.get("http://localhost/nope").exit()))
    assert isinstance(defect, HttpServerError) and isinstance(defect.reason, RouteNotFound)


class _Payload(TypedDict):
    n: int


class _Params(TypedDict):
    id: int


class _Things(HttpApiGroup, identifier="things"):
    create = endpoint.post("create", "/things", payload=S.Struct(_Payload), success=S.Int)


_api = HttpApi.make("in-memory").add(_Things)


def _create(request: HttpApiRequest[None, None, _Payload, None]) -> fx.Effect[int]:
    return fx.succeed(request.payload["n"])


@testing.effect
def test_a_payload_failing_its_schema_is_a_defect_of_the_request():
    # HttpApiBuilder dies with the HttpApiSchemaError (a server answers it with
    # 400); in memory it stays a defect, as in Effect's HttpApiTest.
    routes = builder.layer(_api).pipe(
        layer.provide(builder.group(_api, _Things, lambda h: h.handle(_Things.create)(_create)))
    )
    client = yield from router.in_memory_client(routes)
    request = client.post("http://localhost/things", body=body.json_unsafe({"n": "x"}))
    assert isinstance(_defect_of((yield from request.exit())), HttpApiSchemaError)


@testing.effect
def test_path_params_failing_their_schema_are_a_defect_of_the_request():
    @fx.gen
    def plain():
        params = yield from router.schema_path_params(S.Struct(_Params))
        return server_response.text(str(params["id"]))

    client = yield from router.in_memory_client(router.add("GET", "/plain/:id", plain))
    defect = _defect_of((yield from client.get("http://localhost/plain/abc").exit()))
    assert isinstance(defect, S.SchemaError)


@testing.effect
def test_layer_in_memory_client_is_the_http_client():
    routes = router.add("GET", "/hello", server_response.text("hello"))

    @fx.gen
    def get():
        response = yield from (yield from HttpClient()).get("http://localhost/hello")
        return response.status, (yield from response.text)

    assert (yield from get.pipe(fx.provide(router.layer_in_memory_client(routes)))) == (
        200,
        "hello",
    )


class Greeting(fx.Tag[str]): ...


@testing.effect
def test_a_routes_services_come_from_the_requests_context():
    routes = router.add("GET", "/hello", Greeting().map(server_response.text))
    client = yield from router.in_memory_client(routes)
    response = yield from client.get("http://localhost/hello").pipe(
        fx.provide_service(Greeting, "hi")
    )
    assert (yield from response.text) == "hi"


@testing.effect
def test_layer_in_memory_client_gives_routes_the_services_of_its_layer():
    routes = router.add("GET", "/hello", Greeting().map(server_response.text))
    client = router.layer_in_memory_client(routes).pipe(
        layer.provide(layer.succeed(Greeting, "from the layer"))
    )

    @fx.gen
    def get():
        response = yield from (yield from HttpClient()).get("http://localhost/hello")
        return (yield from response.text)

    assert (yield from get.pipe(fx.provide(client))) == "from the layer"
    # A service the request itself provides comes first, as before.
    overridden = get.pipe(fx.provide_service(Greeting, "from the request"))
    assert (yield from overridden.pipe(fx.provide(client))) == "from the request"
