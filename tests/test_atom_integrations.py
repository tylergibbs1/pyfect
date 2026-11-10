"""What ``atom_rpc``, ``atom_http_api`` and ``hydration`` do beyond
Effect's own tests: reactivity keys, headers, which atoms are
serializable, transport errors as defects, and the streamed hydration
paths. Expected values were checked against Effect's source under Node.
"""

import json
import types
from typing import Any, Never, TypedDict, cast

import pytest
from oracle._atom_timers import FakeTimers, timers

import pyfect as fx
from pyfect import layer, testing
from pyfect import schema as S
from pyfect.context import Tag
from pyfect.deferred import Deferred
from pyfect.exit import Success as ExitSuccess
from pyfect.http import response
from pyfect.http.client import HttpClient, HttpClientService
from pyfect.http.client import make as make_http_client
from pyfect.http.error import HttpClientError, TransportError
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse
from pyfect.http_api import endpoint as ep
from pyfect.http_api.api import HttpApi
from pyfect.http_api.group import HttpApiGroup
from pyfect.reactivity import async_result, atom, atom_http_api, atom_registry, atom_rpc, hydration
from pyfect.reactivity.async_result import AsyncResult, Failure, Initial, Success
from pyfect.rpc import RpcGroup, RpcMiddleware, make
from pyfect.rpc import test as rpc_test

__all__ = ["timers"]


def _tag(id: str) -> type[Tag[Any]]:
    return types.new_class(id, (Tag,), {"key": id})


# --- atom_rpc ----------------------------------------------------------------


class _Id(TypedDict):
    id: float


class Denied(S.TaggedError):
    pass


class Guard(RpcMiddleware[Never, Denied]):
    error = Denied


class Users(RpcGroup):
    get_user = make("getUser", payload=S.Struct(_Id, id=S.Number), success=S.String)
    rename = make("rename", payload=S.Struct(_Id, id=S.Number), success=S.String)
    guarded = make("guarded", success=S.String).middleware(Guard)
    events = make("events", success=S.String, stream=True)


class _Calls:
    def __init__(self) -> None:
        self.reads = 0
        self.headers: list[object] = []


def _users_client(calls: _Calls) -> atom_rpc.AtomRpcClient[Users, Any]:
    def get_user(request: Any) -> fx.Effect[str]:
        def run() -> str:
            calls.reads += 1
            calls.headers.append(request.headers.get("x-id"))
            return f"user-{calls.reads}"

        return fx.sync(run)

    def rename(request: Any) -> fx.Effect[str]:
        def run() -> str:
            calls.headers.append(request.headers.get("x-id"))
            return "renamed"

        return fx.sync(run)

    handlers = (
        Users.handlers()
        .handle(Users.get_user)(get_user)
        .handle(Users.rename)(rename)
        .handle(Users.guarded)(lambda _: fx.fail(Denied()))
        .handle(Users.events)(lambda _: fx.stream.make("a"))
    )

    def guard(effect: Any, _options: Any) -> Any:
        return effect

    return atom_rpc.make(
        _tag("Users"),
        group=Users,
        protocol=layer.merge(Users.to_layer(handlers), layer.succeed(Guard, guard)),
        make_effect=rpc_test.make_client(Users),
    )


@testing.effect
def test_rpc_mutation_reactivity_keys_refresh_queries_with_those_keys():
    calls = _Calls()
    client = _users_client(calls)
    user = client.query(Users.get_user, {"id": 1}, reactivity_keys=["users"])
    rename = client.mutation(Users.rename)
    registry = atom_registry.make()
    yield from fx.add_finalizer(lambda _: fx.sync(registry.dispose))
    yield from atom_registry.mount(registry, user)
    yield from atom_registry.mount(registry, rename)
    assert (yield from atom_registry.get_result(registry, user)) == "user-1"

    registry.set(rename, {"payload": {"id": 1}})
    yield from atom_registry.get_result(registry, rename, suspend_on_waiting=True)
    assert (yield from atom_registry.get_result(registry, user)) == "user-1"

    registry.set(rename, {"payload": {"id": 1}, "reactivity_keys": ["users"]})
    yield from atom_registry.get_result(registry, rename, suspend_on_waiting=True)
    yield from fx.yield_now()
    assert (yield from atom_registry.get_result(registry, user)) == "user-2"


@testing.effect
def test_rpc_query_and_mutation_send_their_headers():
    calls = _Calls()
    client = _users_client(calls)
    user = client.query(Users.get_user, {"id": 1}, headers={"x-id": "q"})
    rename = client.mutation(Users.rename)
    registry = atom_registry.make()
    yield from fx.add_finalizer(lambda _: fx.sync(registry.dispose))
    yield from atom_registry.mount(registry, rename)
    yield from atom_registry.get_result(registry, user)
    registry.set(rename, {"payload": {"id": 1}, "headers": {"x-id": "m"}})
    yield from atom_registry.get_result(registry, rename, suspend_on_waiting=True)
    assert calls.headers == ["q", "m"]


def test_rpc_serializable_atoms() -> None:
    client = _users_client(_Calls())
    # A streaming query, and an empty key (falsy, as in Effect), are not serializable.
    assert not atom.is_serializable(client.query(Users.events, None, serialization_key="s"))
    assert not atom.is_serializable(client.query(Users.get_user, {"id": 1}, serialization_key=""))
    assert atom.is_serializable(client.query(Users.get_user, {"id": 1}, serialization_key="k"))


@testing.effect
def test_rpc_middleware_errors_with_a_schema_are_dehydrated():
    client = _users_client(_Calls())
    guarded = client.query(Users.guarded, None, serialization_key="g")
    registry = atom_registry.make()
    yield from fx.add_finalizer(lambda _: fx.sync(registry.dispose))
    yield from atom_registry.mount(registry, guarded)
    yield from atom_registry.get_result(registry, guarded).exit()

    [entry] = hydration.dehydrate(registry)
    assert entry.key == "AtomRpc:guarded:g"
    assert json.loads(json.dumps(entry.value)) == {
        "_tag": "Failure",
        "cause": [{"_tag": "Fail", "error": {"_tag": "Denied"}}],
        "previousSuccess": {"_tag": "None"},
        "waiting": False,
    }


# --- atom_http_api -----------------------------------------------------------


_GET = ep.get("get", "/users", success=S.String)
_CREATE = ep.post("create", "/users", success=S.String)
_GROUP: Any = HttpApiGroup.make("users").add(_GET, _CREATE)


def _api_client(answer: Any) -> atom_http_api.AtomHttpApiClient[Any]:
    def send(request: HttpClientRequest, *_: Any) -> fx.Effect[HttpClientResponse, Any]:
        return fx.suspend(lambda: answer(request))

    service: HttpClientService[Any] = make_http_client(send)
    return atom_http_api.make(
        _tag("Api"),
        api=HttpApi.make("api").add(_GROUP),
        base_url="http://test",
        http_client=layer.succeed(HttpClient, service),
    )


def _json(request: HttpClientRequest, value: str) -> fx.Effect[HttpClientResponse]:
    return fx.succeed(
        response.make(request, f'"{value}"', headers={"content-type": "application/json"})
    )


@pytest.mark.parametrize("failure", ["transport", "schema"])
@testing.effect
def test_http_api_transport_and_schema_errors_are_defects(failure: str):
    def answer(request: HttpClientRequest) -> fx.Effect[HttpClientResponse, Any]:
        if failure == "transport":
            return fx.fail(HttpClientError(TransportError(request)))
        return fx.succeed(response.make(request, "not json", status=200))

    client = _api_client(answer)
    query = client.query(_GROUP, _GET)
    registry = atom_registry.make()
    yield from fx.add_finalizer(lambda _: fx.sync(registry.dispose))
    yield from atom_registry.mount(registry, query)
    yield from atom_registry.get_result(registry, query).exit()
    result = registry.get(query)
    assert isinstance(result, Failure)
    [defect] = result.cause.defects
    assert isinstance(defect, HttpClientError if failure == "transport" else S.SchemaError)


@testing.effect
def test_http_api_mutation_reactivity_keys_refresh_queries_with_those_keys():
    gets = [0]

    def answer(request: HttpClientRequest) -> fx.Effect[HttpClientResponse]:
        if request.method == "GET":
            gets[0] += 1
            return _json(request, f"get-{gets[0]}")
        return _json(request, "created")

    client = _api_client(answer)
    query = client.query(_GROUP, _GET, reactivity_keys=["users"])
    create = client.mutation(_GROUP, _CREATE)
    registry = atom_registry.make()
    yield from fx.add_finalizer(lambda _: fx.sync(registry.dispose))
    yield from atom_registry.mount(registry, query)
    yield from atom_registry.mount(registry, create)
    assert (yield from atom_registry.get_result(registry, query)) == "get-1"

    registry.set(create, {})
    yield from atom_registry.get_result(registry, create, suspend_on_waiting=True)
    assert (yield from atom_registry.get_result(registry, query)) == "get-1"

    registry.set(create, {"reactivity_keys": ["users"]})
    yield from atom_registry.get_result(registry, create, suspend_on_waiting=True)
    yield from fx.yield_now()
    assert (yield from atom_registry.get_result(registry, query)) == "get-2"


class _ItemId(TypedDict):
    id: int


_RENAME = ep.patch(
    "rename", "/items/:id", params=S.Struct(_ItemId, id=S.Int), payload=S.String, success=S.String
)
_LIST = ep.get("list", "/items", success=S.String)
_ITEMS: Any = HttpApiGroup.make("items").add(_RENAME, _LIST)


@testing.effect
def test_http_api_mutate_sends_its_parts_and_waits_for_the_result():
    """``mutate(group, endpoint)(**parts)`` writes the parts to the mutation
    atom and waits for its result (DOGFOOD pulse #1); its reactivity keys
    refresh the queries with those keys."""
    sent: list[tuple[str, str, bytes]] = []
    lists = [0]

    def send(request: HttpClientRequest, *_: Any) -> fx.Effect[HttpClientResponse, Any]:
        if request.method == "GET":
            lists[0] += 1
            return _json(request, f"list-{lists[0]}")
        body = request.body
        sent.append((request.method, request.url, getattr(body, "body", b"")))
        # answered later, so the call waits for the result
        return fx.sleep("10 millis").and_then(_json(request, "renamed"))

    client = atom_http_api.make(
        _tag("Items"),
        api=HttpApi.make("items").add(_ITEMS),
        base_url="http://test",
        http_client=layer.succeed(HttpClient, make_http_client(send)),
    )
    listing = client.query(_ITEMS, _LIST, reactivity_keys=["items"])
    registry = atom_registry.make()
    yield from fx.add_finalizer(lambda _: fx.sync(registry.dispose))
    yield from atom_registry.mount(registry, listing)
    assert (yield from atom_registry.get_result(registry, listing)) == "list-1"

    rename = client.mutate(_ITEMS, _RENAME)
    result = yield from rename(params={"id": 7}, payload="new", reactivity_keys=["items"]).pipe(
        fx.provide_service(atom_registry.AtomRegistry, registry)
    )
    assert result == "renamed"
    assert sent == [("PATCH", "http://test/items/7", b'"new"')]
    yield from fx.yield_now()
    assert (yield from atom_registry.get_result(registry, listing)) == "list-2"
    assert registry.get(client.mutation(_ITEMS, _RENAME)) == async_result.success("renamed")


@testing.effect
def test_http_api_query_of_is_query_with_its_parts_checked_by_the_endpoint():
    """``query_of(group, endpoint)(**parts)`` is ``query(group, endpoint, **parts)``:
    the same atom for the same arguments, sending the parts (DOGFOOD atom_http_api
    query: the curried form fixes the parts' types before they are checked)."""
    sent: list[str] = []

    def send(request: HttpClientRequest, *_: Any) -> fx.Effect[HttpClientResponse, Any]:
        sent.append(request.url)
        return _json(request, "item")

    client = atom_http_api.make(
        _tag("ItemsQueryOf"),
        api=HttpApi.make("items").add(_ITEMS),
        base_url="http://test",
        http_client=layer.succeed(HttpClient, make_http_client(send)),
    )
    get = client.query_of(_ITEMS, _RENAME)
    item = get(params={"id": 3}, payload="p", reactivity_keys=["items"], time_to_live="1 minute")
    assert item is client.query(
        _ITEMS,
        _RENAME,
        params={"id": 3},
        payload="p",
        reactivity_keys=["items"],
        time_to_live="1 minute",
    )
    assert item.idle_ttl == fx.duration.minutes(1)
    response_only = client.query_of(_ITEMS, _RENAME, response_mode="response-only")
    assert response_only(params={"id": 3}, payload="p") is client.query(
        _ITEMS, _RENAME, params={"id": 3}, payload="p", response_mode="response-only"
    )
    registry = atom_registry.make()
    yield from fx.add_finalizer(lambda _: fx.sync(registry.dispose))
    yield from atom_registry.mount(registry, item)
    assert (yield from atom_registry.get_result(registry, item)) == "item"
    assert sent == ["http://test/items/3"]


def test_http_api_query_of_rejects_a_foreign_endpoint() -> None:
    client = atom_http_api.make(
        _tag("ItemsQueryOfForeign"),
        api=HttpApi.make("items").add(_ITEMS),
        http_client=layer.succeed(HttpClient, make_http_client(lambda r, *_: _json(r, "x"))),  # pyright: ignore[reportUnknownLambdaType, reportUnknownArgumentType]
    )
    with pytest.raises(ValueError, match="is not an endpoint of items"):
        client.query_of(_ITEMS, _GET)


def test_http_api_only_decoded_only_atoms_are_serializable() -> None:
    client = _api_client(lambda request: _json(request, "x"))  # pyright: ignore[reportUnknownLambdaType, reportUnknownArgumentType]
    assert atom.is_serializable(client.mutation(_GROUP, _CREATE))
    assert not atom.is_serializable(client.mutation(_GROUP, _CREATE, response_mode="response-only"))
    assert not atom.is_serializable(
        client.mutation(_GROUP, _CREATE, response_mode="decoded-and-response")
    )
    assert atom.is_serializable(client.query(_GROUP, _GET, serialization_key="k"))
    assert not atom.is_serializable(client.query(_GROUP, _GET, serialization_key=""))
    assert not atom.is_serializable(
        client.query(_GROUP, _GET, response_mode="response-only", serialization_key="k")
    )


def test_http_api_rejects_a_group_or_endpoint_of_another_api() -> None:
    client = _api_client(lambda request: _json(request, "x"))  # pyright: ignore[reportUnknownLambdaType, reportUnknownArgumentType]
    other: Any = HttpApiGroup.make("users").add(_GET)
    with pytest.raises(ValueError, match="not a group"):
        client.query(other, _GET)
    with pytest.raises(ValueError, match="not an endpoint"):
        client.query(_GROUP, ep.get("missing", "/missing"))


# --- hydration ---------------------------------------------------------------


def _result_atom(key: str) -> atom.Writable[AsyncResult[str], AsyncResult[str]]:
    seed = cast("AsyncResult[str]", async_result.initial())
    return atom.make(seed).serializable(key=key, schema=async_result.Schema(success=S.String))


def test_dehydrate_leaves_out_initial_results_unless_asked(timers: FakeTimers) -> None:
    pending = _result_atom("pending")
    registry = timers.registry()
    try:
        registry.mount(pending)
        assert hydration.dehydrate(registry) == []
        [entry] = hydration.dehydrate(registry, encode_initial_as="value-only")
        assert (entry.key, entry.value, entry.result_deferred) == (
            "pending",
            {"_tag": "Initial", "waiting": False},
            None,
        )
    finally:
        registry.dispose()


def test_a_streamed_result_preloads_an_atom_the_target_has_not_read(timers: FakeTimers) -> None:
    profile = _result_atom("profile")
    server = timers.registry()
    client = timers.registry()
    try:
        server.mount(profile)
        state = hydration.dehydrate(server, encode_initial_as="deferred")
        hydration.hydrate(client, state)
        server.set(profile, async_result.success("server", timestamp=1000))
        timers.flush()

        result = client.get(profile)
        assert isinstance(result, Success)
        assert (result.value, result.timestamp) == ("server", 1000)
    finally:
        server.dispose()
        client.dispose()


def test_an_unusable_streamed_result_drops_the_preloaded_initial(timers: FakeTimers) -> None:
    resolved: Deferred[float] = Deferred()
    # 0.5 is not an Int, so the server's result cannot be encoded.
    server_atom = atom.make(resolved.wait()).serializable(
        key="count", schema=async_result.Schema(success=S.Int)
    )
    seeded = atom.state[AsyncResult[int]](async_result.success(7, timestamp=1))
    client_atom = seeded.serializable(key="count", schema=async_result.Schema(success=S.Int))
    server = timers.registry()
    client = timers.registry()
    try:
        server.mount(server_atom)
        state = hydration.dehydrate(server, encode_initial_as="deferred")
        hydration.hydrate(client, state)
        resolved.done_unsafe(ExitSuccess(0.5))
        timers.flush()
        assert "count" not in client.preloaded_serializable

        result = client.get(client_atom)
        assert isinstance(result, Success)
        assert (result.value, result.timestamp) == (7, 1)
    finally:
        server.dispose()
        client.dispose()


def test_a_settled_deferred_stops_listening_to_the_server_atom(timers: FakeTimers) -> None:
    profile = _result_atom("profile")
    server = timers.registry()
    try:
        unmount = server.mount(profile)
        [entry] = hydration.dehydrate(server, encode_initial_as="deferred")
        server.set(profile, async_result.success("first"))
        assert entry.result_deferred is not None and entry.result_deferred.is_done_unsafe()
        unmount()
        timers.flush()
        assert "profile" not in server.get_nodes()
    finally:
        server.dispose()


def test_an_initial_result_with_waiting_survives_the_wire(timers: FakeTimers) -> None:
    profile = _result_atom("profile")
    server = timers.registry()
    client = timers.registry()
    try:
        server.set(profile, async_result.initial(waiting=True))
        state = [
            hydration.DehydratedAtom.from_json(e.to_json())
            for e in hydration.dehydrate(server, encode_initial_as="value-only")
        ]
        hydration.hydrate(client, state)
        assert client.get(profile) == Initial(waiting=True)
    finally:
        server.dispose()
        client.dispose()


# --- hydrated effect atoms reload (DOGFOOD pulse #2) -------------------------
#
# A hydrated effect atom without skip_initial_run runs its effect once built.
# What it shows, printed by Effect 4.0.6 under Node for each way the reload
# ends: the build keeps the hydrated value, so a reload that settles during the
# build is dropped and one that settles later replaces it, without the hydrated
# value ever reading as waiting; a refresh then shows its results as usual.

_SETTLES = {
    "succeeds at once": fx.succeed(2),
    "succeeds later": fx.sleep("50 millis").and_then(fx.succeed(2)),
    "fails at once": fx.fail("down"),
    "fails later": fx.sleep("50 millis").and_then(fx.fail("down")),
}


def _shown(result: AsyncResult[int, str]) -> tuple[object, ...]:
    match result:
        case Success(value=value, waiting=waiting, timestamp=timestamp):
            return ("Success", value, waiting, "hydrated" if timestamp == 1000 else "new")
        case Failure(previous_success=previous, waiting=waiting):
            return ("Failure", waiting, None if previous is None else previous.value.value)
        case _:
            return ("Initial", result.waiting)


@pytest.mark.parametrize(
    ("reload", "later", "refreshed", "refreshed_later"),
    [
        (
            "succeeds at once",
            ("Success", 1, False, "hydrated"),
            ("Success", 2, False, "new"),
            ("Success", 2, False, "new"),
        ),
        (
            "succeeds later",
            ("Success", 2, False, "new"),
            ("Success", 2, True, "new"),
            ("Success", 2, False, "new"),
        ),
        (
            "fails at once",
            ("Success", 1, False, "hydrated"),
            ("Failure", False, 1),
            ("Failure", False, 1),
        ),
        (
            "fails later",
            ("Failure", False, 1),
            ("Failure", True, 1),
            ("Failure", False, 1),
        ),
    ],
)
def test_a_hydrated_effect_atom_reloads_once_built(
    timers: FakeTimers,
    reload: str,
    later: tuple[object, ...],
    refreshed: tuple[object, ...],
    refreshed_later: tuple[object, ...],
) -> None:
    schema = async_result.Schema(success=S.Int, error=S.String)
    runs = [0]

    def run() -> None:
        runs[0] += 1

    count = atom.make(fx.sync(run).and_then(_SETTLES[reload])).serializable(key="n", schema=schema)
    saved = [
        hydration.DehydratedAtom(
            key="n",
            value={"_tag": "Success", "value": 1, "waiting": False, "timestamp": 1000},
            dehydrated_at=1000,
        )
    ]
    registry = timers.registry()
    try:
        hydration.hydrate(registry, saved)
        assert _shown(registry.get(count)) == ("Success", 1, False, "hydrated")
        registry.mount(count)
        assert runs[0] == 1
        assert _shown(registry.get(count)) == ("Success", 1, False, "hydrated")
        timers.advance(300)
        assert _shown(registry.get(count)) == later
        registry.refresh(count)
        assert runs[0] == 2
        assert _shown(registry.get(count)) == refreshed
        timers.advance(300)
        assert _shown(registry.get(count)) == refreshed_later
    finally:
        registry.dispose()


def test_a_subscripted_state_is_the_same_writable_atom(timers: FakeTimers) -> None:
    """``atom.state[T](value)`` only states the type (DOGFOOD pulse #3)."""
    log = atom.state[tuple[str, ...]](()).keep_alive()
    registry = timers.registry()
    try:
        assert registry.get(log) == ()
        registry.update(log, lambda lines: (*lines, "started"))
        assert registry.get(log) == ("started",)
    finally:
        registry.dispose()
