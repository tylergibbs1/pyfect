"""Ports of Effect's ``test/reactivity/AtomHttpApi.test.ts``, every title.

``AtomHttpApi.Service()(id, {...})`` is ``atom_http_api.make(Tag, ...)``
with ``Tag`` a tag keyed ``id``; ``Client.query("group", "get", ...)`` is
``client.query(Group, endpoint, ...)`` (the group class and the endpoint
value). Path and query parameters use ``S.Finite`` (the endpoint
derives their string codec). ``timeToLive: "1 minute"`` is ``60``;
``0n`` (a bigint) is ``0.0``. ``Effect.yieldNow`` is ``fx.yield_now()``.
"""

import json
import types
from collections.abc import Callable
from typing import Any, TypedDict

import pytest

import pyfect as fx
from pyfect import layer, stream, testing
from pyfect import schema as S
from pyfect._core import Effect
from pyfect.context import Tag
from pyfect.duration import millis
from pyfect.encoding import sse
from pyfect.exit import Exit
from pyfect.exit import succeed as exit_succeed
from pyfect.http import body as http_body
from pyfect.http import response
from pyfect.http.client import HttpClient, HttpClientService, make_with
from pyfect.http.client import make as make_http_client
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse
from pyfect.http_api import client as api_client
from pyfect.http_api import endpoint as ep
from pyfect.http_api import schema as api_schema
from pyfect.http_api.api import HttpApi
from pyfect.http_api.group import HttpApiGroup
from pyfect.reactivity import _time, async_result, atom, atom_http_api, atom_registry, hydration
from pyfect.stream import Stream

from ._http_api import struct


class _Name(TypedDict):
    name: str


_SSE = {"content-type": "text/event-stream"}


def _tag(id: str) -> type[Tag[api_client.Client[Any]]]:
    """``class <id>(Tag[Client[...]], key=id)``."""
    return types.new_class(id, (Tag,), {"key": id})


def _raw_http_layer(answer: Any) -> layer.Layer[HttpClient]:
    """``HttpClient.makeWith``: requests reach ``answer`` as built, without
    URL validation."""

    def postprocess(requests: Effect[HttpClientRequest, Any, Any]) -> Any:
        return requests.map(answer)

    return layer.succeed(HttpClient, make_with(postprocess, fx.succeed))


def _http_layer(
    answer: Any,
) -> layer.Layer[HttpClient]:
    def send(request: HttpClientRequest, *_: Any) -> Effect[HttpClientResponse, Any]:
        return fx.sync(lambda: answer(request))

    service: HttpClientService[Any] = make_http_client(send)
    return layer.succeed(HttpClient, service)


_FRESH_GET = ep.get("get", "/value", success=S.Number)
_FRESH_GROUP: Any = HttpApiGroup.make("group").add(_FRESH_GET)


def _make_counting_client(next: Callable[[], int]) -> Any:
    def answer(request: HttpClientRequest) -> HttpClientResponse:
        return response.make(
            request, json.dumps(next()), headers={"content-type": "application/json"}
        )

    return atom_http_api.make(
        _tag("FreshClient"),
        api=HttpApi.make("FreshApi").add(_FRESH_GROUP),
        base_url="https://example.test",
        http_client=_http_layer(answer),
    )


def _counter() -> tuple[list[int], Callable[[], int]]:
    requests = [0]

    def next() -> int:
        requests[0] += 1
        return requests[0]

    return requests, next


@testing.effect
def test_reuses_fresh_hydration_and_revalidates_stale_hydration_once(
    monkeypatch: pytest.MonkeyPatch,
):
    """reuses fresh hydration and revalidates stale hydration once"""
    requests, next = _counter()
    client_api = _make_counting_client(next)
    query = client_api.query(
        _FRESH_GROUP,
        _FRESH_GET,
        serialization_key="value",
        stale_time="1 second",
        reactivity_keys=["value"],
    )
    clock = [10_000]
    monkeypatch.setattr(_time, "time", types.SimpleNamespace(time_ns=lambda: clock[0] * 1_000_000))
    server = atom_registry.make()
    yield from fx.add_finalizer(lambda _: fx.sync(server.dispose))
    yield from atom_registry.mount(server, query)
    assert (yield from atom_registry.get_result(server, query)) == 1
    state = hydration.dehydrate(server)

    for age, refresh, expected in [(500, False, 1), (1_500, False, 2), (500, True, 3)]:
        clock[0] = 10_000 + age
        client = atom_registry.make()
        yield from fx.add_finalizer(lambda _, client=client: fx.sync(client.dispose))
        hydration.hydrate(client, state)
        if refresh:
            client.refresh(query)
        yield from atom_registry.mount(client, query)
        if not refresh:
            seed = client.get(query)
            assert isinstance(seed, async_result.Success)
            assert seed.value == 1  # pyright: ignore[reportUnknownMemberType]
        yield from fx.yield_now()
        result = yield from atom_registry.get_result(client, query, suspend_on_waiting=True)
        assert result == expected
        assert requests[0] == expected


@pytest.mark.parametrize("legacy_first", [False, True])
@testing.effect
def test_refreshes_a_shared_key_for_both_readers(legacy_first: bool):
    """refreshes a shared key for both readers (legacy first: %s)"""
    requests, next = _counter()
    client_api = _make_counting_client(next)
    legacy = client_api.query(
        _FRESH_GROUP, _FRESH_GET, serialization_key="value", reactivity_keys=["value"]
    )
    stale = client_api.query(
        _FRESH_GROUP,
        _FRESH_GET,
        serialization_key="value",
        reactivity_keys=["value"],
        stale_time=0,
    )
    registry = atom_registry.make()
    yield from fx.add_finalizer(lambda _: fx.sync(registry.dispose))
    first, second = (legacy, stale) if legacy_first else (stale, legacy)
    yield from atom_registry.mount(registry, first)
    yield from atom_registry.get_result(registry, first, suspend_on_waiting=True)
    yield from atom_registry.mount(registry, second)
    yield from fx.yield_now()

    def read(query: Any) -> Effect[float, Any, Any]:
        return atom_registry.get_result(registry, query, suspend_on_waiting=True)

    before = yield from read(stale)
    if legacy_first:
        assert before == 2
    registry.refresh(second)
    assert (yield from read(first)) == before + 1
    assert requests[0] == before + 1


@pytest.mark.parametrize(
    ("id_a", "group_a", "id_b", "group_b"),
    [("ApiA", "users", "ApiB", "users"), ("Api:users", "users", "Api", "users:users")],
)
@testing.effect
def test_isolates_mutations_across_services(id_a: str, group_a: str, id_b: str, group_b: str):
    """isolates mutations across services ($idA / $idB)"""
    requests: list[dict[str, object]] = []

    def make_client(id: str, group_id: str, base_url: str) -> tuple[Any, Any, Any]:
        create = ep.post(
            "create", "/users", payload=S.Struct(_Name, name=S.String), success=S.String
        )
        group: Any = HttpApiGroup.make(group_id).add(create)

        def answer(request: HttpClientRequest) -> HttpClientResponse:
            body = request.body
            assert isinstance(body, http_body.Bytes)
            requests.append({"url": request.url, "payload": json.loads(body.body)})
            return response.make(
                request, json.dumps(f"{id} ok"), headers={"content-type": "application/json"}
            )

        client = atom_http_api.make(
            _tag(id),
            api=HttpApi.make(id).add(group),
            base_url=base_url,
            http_client=_http_layer(answer),
        )
        return client, group, create

    api_a, users_a, create_endpoint_a = make_client(id_a, group_a, "https://a.test")
    api_b, users_b, create_endpoint_b = make_client(id_b, group_b, "https://b.test")
    create_a = api_a.mutation(users_a, create_endpoint_a)
    create_b = api_b.mutation(users_b, create_endpoint_b)
    registry = atom_registry.make()
    yield from fx.add_finalizer(lambda _: fx.sync(registry.dispose))
    yield from atom_registry.mount(registry, create_a)
    yield from atom_registry.mount(registry, create_b)

    registry.set(create_a, {"payload": {"name": "alice"}})
    result_a = yield from atom_registry.get_result(registry, create_a, suspend_on_waiting=True)
    registry.set(create_b, {"payload": {"name": "bob"}})
    result_b = yield from atom_registry.get_result(registry, create_b, suspend_on_waiting=True)

    assert {"results": [result_a, result_b], "requests": requests} == {
        "results": [f"{id_a} ok", f"{id_b} ok"],
        "requests": [
            {"url": "https://a.test/users", "payload": {"name": "alice"}},
            {"url": "https://b.test/users", "payload": {"name": "bob"}},
        ],
    }


_EVENTS = ep.get("events", "/events", success=api_schema.StreamSse(data=S.String))
_STREAMING_GROUP: Any = HttpApiGroup.make("group").add(_EVENTS)


def _streaming_client() -> atom_http_api.AtomHttpApiClient[Any]:
    def answer(request: HttpClientRequest) -> HttpClientResponse:
        chunks: Stream[bytes] = stream.from_iterable([b"data: ", b'"hello"\n\n'])
        return response.make(request, chunks, headers=_SSE)

    return atom_http_api.make(
        _tag("StreamingClient"),
        base_url="http://test",
        api=HttpApi.make("StreamingApi").add(_STREAMING_GROUP),
        http_client=_http_layer(answer),
    )


def _assert_event_too_large(error: object) -> None:
    assert isinstance(error, sse.SseError)
    assert isinstance(error.reason, sse.EventTooLarge)
    assert error.reason.max_event_size == 4


@testing.effect
def test_query_keeps_sse_decode_options_in_the_cache_key_and_forwards_them():
    """query keeps SSE decode options in the cache key and forwards them"""
    client = _streaming_client()
    registry = atom_registry.make()
    yield from fx.add_finalizer(lambda _: fx.sync(registry.dispose))
    limited = client.query(_STREAMING_GROUP, _EVENTS, sse_options={"max_event_size": 4})
    defaults = client.query(_STREAMING_GROUP, _EVENTS)
    assert limited is not defaults
    assert limited is client.query(_STREAMING_GROUP, _EVENTS, sse_options={"max_event_size": 4})

    limited_stream = yield from atom_registry.get_result(registry, limited)
    default_stream = yield from atom_registry.get_result(registry, defaults)
    error, values = yield from fx.all(
        limited_stream.run_collect().flip(), default_stream.run_collect(), concurrency="unbounded"
    )

    _assert_event_too_large(error)
    assert list(values) == ["hello"]


@testing.effect
def test_mutation_forwards_sse_decode_options_independently_for_each_call():
    """mutation forwards SSE decode options independently for each call"""
    client = _streaming_client()
    registry = atom_registry.make()
    yield from fx.add_finalizer(lambda _: fx.sync(registry.dispose))
    mutation = client.mutation(_STREAMING_GROUP, _EVENTS, response_mode="decoded-only")
    yield from atom_registry.mount(registry, mutation)

    registry.set(mutation, {"sse_options": {"max_event_size": 4}})
    limited = yield from atom_registry.get_result(registry, mutation, suspend_on_waiting=True)
    _assert_event_too_large((yield from limited.run_collect().flip()))

    registry.set(mutation, {})
    defaults = yield from atom_registry.get_result(registry, mutation, suspend_on_waiting=True)
    assert list((yield from defaults.run_collect())) == ["hello"]


_QUERY = ep.get("query", "/query")
_MUTATION = ep.post("mutation", "/mutation")
_TOP_LEVEL_GROUP: Any = HttpApiGroup.make("group", top_level=True).add(_QUERY, _MUTATION)


@testing.effect
def test_dispatches_queries_and_mutations_for_top_level_groups():
    """dispatches queries and mutations for top-level groups"""
    requests: list[str] = []

    def answer(request: HttpClientRequest) -> HttpClientResponse:
        requests.append(request.url)
        return response.make(request, status=204)

    client = atom_http_api.make(
        _tag("TopLevelClient"),
        api=HttpApi.make("top-level-api").add(_TOP_LEVEL_GROUP),
        http_client=_raw_http_layer(answer),
    )
    registry = atom_registry.make()
    query = client.query(_TOP_LEVEL_GROUP, _QUERY)
    mutation = client.mutation(_TOP_LEVEL_GROUP, _MUTATION)

    yield from atom_registry.mount(registry, query)
    yield from atom_registry.mount(registry, mutation)
    registry.set(mutation, {})

    query_exit: Exit[Any, Any] = yield from atom_registry.get_result(
        registry, query, suspend_on_waiting=True
    ).exit()
    mutation_exit: Exit[Any, Any] = yield from atom_registry.get_result(
        registry, mutation, suspend_on_waiting=True
    ).exit()

    assert {"mutation": mutation_exit, "query": query_exit, "requests": requests} == {
        "mutation": exit_succeed(None),
        "query": exit_succeed(None),
        "requests": ["/query", "/mutation"],
    }


_GET = ep.get(
    "get",
    "/users/:id",
    params=struct({"id": S.Finite}),
    query=struct({"page": S.Finite}),
)
_API_GROUP: Any = HttpApiGroup.make("group").add(_GET)


@testing.effect
def test_query_creates_a_serializable_atom_with_reactivity_and_retention_that_encodes_the_request():
    """query creates a serializable atom with reactivity and retention that encodes the request"""
    sent: list[HttpClientRequest] = []

    def answer(request: HttpClientRequest) -> HttpClientResponse:
        sent.append(request)
        return response.make(request, status=204)

    client = atom_http_api.make(
        _tag("Client"),
        api=HttpApi.make("api").add(_API_GROUP),
        http_client=_raw_http_layer(answer),
    )
    query = client.query(
        _API_GROUP,
        _GET,
        params={"id": 1},
        query={"page": 2},
        reactivity_keys=["users"],
        time_to_live="1 minute",
        serialization_key="1:2",
    )
    assert (query.idle_ttl, atom.is_serializable(query)) == (fx.duration.minutes(1), True)
    assert (
        client.query(_API_GROUP, _GET, params={"id": 2}, query={"page": 3}, time_to_live=0).idle_ttl
        == fx.duration.zero
    )
    assert (
        client.query(
            _API_GROUP, _GET, params={"id": 3}, query={"page": 4}, time_to_live=0.0
        ).idle_ttl
        == fx.duration.zero
    )
    keep_alive = client.query(
        _API_GROUP,
        _GET,
        params={"id": 2},
        query={"page": 3},
        reactivity_keys=["users"],
        time_to_live=float("inf"),
        serialization_key="keep-alive",
    )
    assert (keep_alive.kept_alive, atom.is_serializable(keep_alive)) == (True, True)
    info = query.serializable_info
    assert info is not None

    from_encoded_input = client.query(
        _API_GROUP,
        _GET,
        params={"id": 1},
        query={"page": 2},
        reactivity_keys=["users"],
        time_to_live="1 minute",
        serialization_key="1:2",
    )
    assert from_encoded_input.serializable_info is not None
    assert from_encoded_input.serializable_info.key == info.key

    registry = atom_registry.make()
    unmount = registry.mount(query)
    yield from fx.yield_now()
    yield from fx.yield_now()
    yield from fx.yield_now()

    [request] = sent
    assert request.url == "/users/1"
    assert list(request.url_params) == [("page", "2")]

    dehydrated = hydration.to_values(hydration.dehydrate(registry))
    assert len(dehydrated) == 1
    assert dehydrated[0].key == info.key
    unmount()


@testing.effect
def test_returns_generated_sse_stream_failures_from_queries():
    """returns generated SSE stream failures from queries"""
    watch = ep.get("watch", "/watch", success=api_schema.StreamSse(data=S.String))
    events: Any = HttpApiGroup.make("events").add(watch)

    def answer(request: HttpClientRequest) -> HttpClientResponse:
        return response.make(request, "retry: 1000\n\n", headers=_SSE)

    client = atom_http_api.make(
        _tag("StreamClient"),
        api=HttpApi.make("StreamApi").add(events),
        base_url="https://example.test",
        http_client=_http_layer(answer),
    )
    registry = atom_registry.make()
    query = client.query(events, watch)
    yield from atom_registry.mount(registry, query)
    events_stream = yield from atom_registry.get_result(registry, query)
    error = yield from events_stream.run_collect().flip()

    assert error == sse.Retry(duration=millis(1000), last_event_id=None)
