"""Ports of Effect's ``test/reactivity/AtomRpc.test.ts``, every title.

``AtomRpc.Service()(id, {...})`` is ``atom_rpc.make(Tag, group=..., ...)``
with ``Tag`` a tag keyed ``id``. Effect's tests hand ``makeEffect`` a raw
function as the flat client; here the client is ``RpcTest.makeClient`` of
the group over a layer of handlers doing the same. The type test of
"includes client middleware errors in atom failure types" is pinned in
``tests/type_checks.py`` (``atom_rpc_types``); the port checks the atoms'
kinds. ``Effect.yieldNow`` is ``fx.yield_now``; awaiting the result
promise is waiting on the ``result_deferred``.
"""

import types
from typing import Any, Never, TypedDict

import pytest

import pyfect as fx
from pyfect import layer, testing
from pyfect import schema as S
from pyfect.context import Tag
from pyfect.deferred import Deferred
from pyfect.reactivity import async_result, atom, atom_registry, atom_rpc, hydration
from pyfect.result import Ok
from pyfect.rpc import RpcGroup, RpcMiddleware, make
from pyfect.rpc import test as rpc_test
from pyfect.rpc.client import ClientProtocol, ClientProtocolService
from pyfect.rpc.client_error import RpcClientError
from pyfect.rpc.middleware import ClientMiddlewareOptions, layer_client
from pyfect.socket import SocketCloseError


class _Name(TypedDict):
    name: str


class _Id(TypedDict):
    id: float


class _User(TypedDict):
    id: float
    name: str


class Users(RpcGroup):
    get_user = make(
        "getUser",
        payload=S.Struct(_Id, id=S.FiniteFromString),
        success=S.Struct(_User, id=S.Number, name=S.String),
    )


class ClientFailure(fx.TaggedError):
    pass


class ClientMiddleware(RpcMiddleware[Never, ClientFailure], required_for_client=True):
    """Effect's ``clientError``: it has no error schema."""


class ClientMiddlewareGroup(RpcGroup):
    get_user = make("getUser", success=S.String).middleware(ClientMiddleware)
    stream = make("stream", success=S.String, stream=True).middleware(ClientMiddleware)


def _never_send(_client_id: int, _message: object) -> fx.Effect[None, Any]:
    return fx.die(RuntimeError("unexpected request"))


def _client_middleware_protocol(
    middleware: Any,
) -> layer.Layer[Any, Any, Any]:
    protocol = ClientProtocolService(
        run=lambda _id, _write: fx.never,
        send=_never_send,
        supports_ack=False,
        codec_for=S.to_codec_json,
    )
    return layer.merge(
        layer.succeed(ClientProtocol, protocol), layer_client(ClientMiddleware, middleware)
    )


def _tag[G](id: str, _group: type[G]) -> type[Tag[G]]:
    """``class <id>(Tag[G], key=id)``."""
    return types.new_class(id, (Tag,), {"key": id})


@pytest.mark.parametrize(
    ("id_a", "tag_a", "id_b", "tag_b"),
    [("RpcA", "create", "RpcB", "create"), ("Tenant:User", "create", "Tenant", "User:create")],
)
@testing.effect
def test_isolates_mutations_across_services(id_a: str, tag_a: str, id_b: str, tag_b: str):
    """isolates mutations across services ($idA / $idB)"""
    requests: list[dict[str, str]] = []

    def make_client(id: str, tag: str) -> tuple[Any, Any]:
        create = make(tag, payload=S.Struct(_Name, name=S.String), success=S.String)
        group: Any = types.new_class(
            "Group", (RpcGroup,), exec_body=lambda ns: ns.update(create=create)
        )

        def handle(request: Any) -> fx.Effect[str]:
            def record() -> str:
                requests.append({"service": id, "name": request.payload["name"]})
                return f"{id} ok"

            return fx.sync(record)

        client = atom_rpc.make(
            _tag(id, group),
            group=group,
            protocol=group.to_layer(group.handlers().handle(create)(handle)),
            make_effect=rpc_test.make_client(group),
        )
        return client, create

    rpc_a, create_rpc_a = make_client(id_a, tag_a)
    rpc_b, create_rpc_b = make_client(id_b, tag_b)
    create_a = rpc_a.mutation(create_rpc_a)
    create_b = rpc_b.mutation(create_rpc_b)
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
        "requests": [{"service": id_a, "name": "alice"}, {"service": id_b, "name": "bob"}],
    }


def test_includes_client_middleware_errors_in_atom_failure_types() -> None:
    """includes client middleware errors in atom failure types"""
    client = atom_rpc.make(
        _tag("MiddlewareClient", ClientMiddlewareGroup),
        group=ClientMiddlewareGroup,
        protocol=layer.empty,
        make_effect=fx.die(RuntimeError("unused")),
    )
    mutation = client.mutation(ClientMiddlewareGroup.get_user)
    query = client.query(ClientMiddlewareGroup.get_user, None)
    stream = client.query(ClientMiddlewareGroup.stream, None)
    assert atom.is_writable(mutation)
    assert atom.is_atom(query) and not atom.is_writable(query)
    assert atom.is_writable(stream)


def _users_protocol() -> layer.Layer[Any, Any, Any]:
    def get_user(request: Any) -> fx.Effect[_User]:
        id = request.payload["id"]
        return fx.succeed(_User(id=id, name=f"user-{id:g}"))

    return Users.to_layer(Users.handlers().handle(Users.get_user)(get_user))


@testing.effect
def test_query_creates_a_serializable_atom_with_reactivity_and_retention():
    """query creates a serializable atom with reactivity and retention"""
    client = atom_rpc.make(
        _tag("Client", Users),
        group=Users,
        protocol=_users_protocol(),
        make_effect=rpc_test.make_client(Users),
    )
    query = client.query(
        Users.get_user,
        {"id": 1},
        headers={"x-id": "abc"},
        reactivity_keys=["users"],
        time_to_live="1 minute",
        serialization_key="1",
    )
    assert (query.idle_ttl, atom.is_serializable(query)) == (fx.duration.minutes(1), True)
    assert client.query(Users.get_user, {"id": 2}, time_to_live=0).idle_ttl == fx.duration.zero
    assert client.query(Users.get_user, {"id": 3}, time_to_live=0.0).idle_ttl == fx.duration.zero
    keep_alive = client.query(
        Users.get_user,
        {"id": 2},
        reactivity_keys=["users"],
        time_to_live=float("inf"),
        serialization_key="keep-alive",
    )
    assert (keep_alive.kept_alive, atom.is_serializable(keep_alive)) == (True, True)
    info = query.serializable_info
    assert info is not None

    from_encoded_payload = client.query(
        Users.get_user,
        {"id": 1},
        headers={"x-id": "abc"},
        reactivity_keys=["users"],
        time_to_live="1 minute",
        serialization_key="1",
    )
    assert from_encoded_payload is query
    assert from_encoded_payload.serializable_info is not None
    assert from_encoded_payload.serializable_info.key == info.key

    registry = atom_registry.make()
    unmount = registry.mount(query)
    yield from fx.yield_now()
    yield from fx.yield_now()

    dehydrated = hydration.to_values(hydration.dehydrate(registry))
    assert len(dehydrated) == 1
    assert dehydrated[0].key == info.key
    unmount()


@testing.effect
def test_dehydrates_the_rest_of_the_registry_when_client_middleware_fails():
    """dehydrates the rest of the registry when client middleware fails"""

    def fail(_options: ClientMiddlewareOptions) -> fx.Effect[Never, ClientFailure]:
        return fx.fail(ClientFailure())

    client = atom_rpc.make(
        _tag("ClientWithMiddleware", ClientMiddlewareGroup),
        group=ClientMiddlewareGroup,
        protocol=_client_middleware_protocol(fail),
    )
    failed = client.query(ClientMiddlewareGroup.get_user, None, serialization_key="failed")
    unaffected = atom.make(42).serializable(key="unaffected", schema=S.Int)
    registry = atom_registry.make()
    unmount_failed = registry.mount(failed)
    unmount_unaffected = registry.mount(unaffected)
    yield from fx.yield_now()
    yield from fx.yield_now()

    assert async_result.is_failure(registry.get(failed))
    dehydrated = hydration.to_values(hydration.dehydrate(registry))
    assert [e for e in dehydrated if e.key == "AtomRpc:getUser:failed"] == []
    assert [e.value for e in dehydrated if e.key == "unaffected"] == [42]
    unmount_unaffected()
    unmount_failed()


@testing.effect
def test_dehydrates_a_query_that_failed_with_an_rpc_client_error():
    def fail(_options: ClientMiddlewareOptions) -> fx.Effect[Never, Any]:
        return fx.fail(RpcClientError(reason=SocketCloseError(code=1006)))

    client = atom_rpc.make(
        _tag("ClientWithClosedSocket", ClientMiddlewareGroup),
        group=ClientMiddlewareGroup,
        protocol=_client_middleware_protocol(fail),
    )
    failed = client.query(ClientMiddlewareGroup.get_user, None, serialization_key="closed")
    registry = atom_registry.make()
    unmount = registry.mount(failed)
    yield from fx.yield_now()
    yield from fx.yield_now()

    dehydrated = hydration.to_values(hydration.dehydrate(registry))
    [entry] = [e for e in dehydrated if e.key == "AtomRpc:getUser:closed"]
    value: Any = entry.value
    [fail_] = value["cause"]
    assert fail_["error"] == {
        "_tag": "RpcClientError",
        "reason": {"_tag": "SocketCloseError", "code": 1006},
    }
    hydrated = atom_registry.make()
    hydration.hydrate(hydrated, dehydrated)
    result = hydrated.get(failed)
    assert async_result.is_failure(result)
    assert result.cause.find_error() == Ok(RpcClientError(reason=SocketCloseError(code=1006)))
    unmount()


@testing.effect
def test_settles_promise_dehydration_when_client_middleware_later_fails():
    """settles promise dehydration when client middleware later fails"""
    fail_middleware: Deferred[None] = yield from Deferred[None].make()

    def fail_later(_options: ClientMiddlewareOptions) -> fx.Effect[Never, ClientFailure]:
        return fail_middleware.wait().and_then(fx.fail(ClientFailure()))

    client = atom_rpc.make(
        _tag("ClientWithDeferredMiddleware", ClientMiddlewareGroup),
        group=ClientMiddlewareGroup,
        protocol=_client_middleware_protocol(fail_later),
    )
    failed = client.query(
        ClientMiddlewareGroup.get_user, None, serialization_key="deferred-failure"
    )
    registry = atom_registry.make()
    unmount_failed = registry.mount(failed)

    assert async_result.is_initial(registry.get(failed))
    dehydrated = hydration.to_values(hydration.dehydrate(registry, encode_initial_as="deferred"))
    [result] = [
        e.result_deferred for e in dehydrated if e.key == "AtomRpc:getUser:deferred-failure"
    ]
    assert result is not None

    notifications = [0]

    def notify(_: object) -> None:
        notifications[0] += 1

    unsubscribe = registry.subscribe(failed, notify)
    hydrated = atom_registry.make()
    hydration.hydrate(hydrated, dehydrated)

    yield from fail_middleware.succeed(None)
    yield from result.wait().exit().timeout("1 second")

    assert notifications[0] == 1
    unmount_hydrated = hydrated.mount(failed)
    unmount_hydrated()
    unsubscribe()
    unmount_failed()
