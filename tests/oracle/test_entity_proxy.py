"""Ports of Effect's ``test/cluster/EntityProxy.test.ts``. Each test's
docstring is the Effect test title."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pyfect as fx
from pyfect import primary_key, testing
from pyfect import schema as S
from pyfect.cluster import entity_proxy, entity_proxy_server
from pyfect.cluster.entity import Entity
from pyfect.cluster.entity_proxy import to_rpc_group
from pyfect.http import server as http_server
from pyfect.http_api import get_group
from pyfect.http_api import test as api_test
from pyfect.http_api.api import HttpApi
from pyfect.rpc import AnyRpc, RpcGroup
from pyfect.rpc import make as make_rpc
from pyfect.rpc import test as rpc_test

from ._cluster_entities import TestEntity, User
from .test_sharding import test_sharding


class RequestKey(S.Class):
    key: str

    def primary_key(self) -> str:
        return self.key


class ProxiedEntity(Entity, type="Entity"):
    request = make_rpc("Request", payload=RequestKey)


def test_constructs_the_original_rpc_payload() -> None:
    """constructs the original RPC payload"""
    group = to_rpc_group(ProxiedEntity)
    rpc = group.rpcs["Entity.Request"]
    schema: Any = rpc.payload_schema
    payload: Any = S.decode_unknown_sync(schema)(
        {"entityId": "entity-id", "payload": {"key": "request-id"}}
    )
    original = payload["payload"]
    assert primary_key.is_primary_key(original)
    assert primary_key.value(original) == "request-id"


def test_derives_a_request_and_a_discard_rpc_per_entity_rpc() -> None:
    group = to_rpc_group(ProxiedEntity)
    assert sorted(group.rpcs) == ["Entity.Request", "Entity.RequestDiscard"]


def _method(client: Any, group: type[RpcGroup], tag: str) -> Any:
    for name, value in vars(group).items():
        if isinstance(value, AnyRpc) and value.tag == tag:
            return getattr(client, name)
    raise KeyError(tag)


@testing.effect
def test_serves_the_proxy_rpcs_through_the_entity_client():
    group = to_rpc_group(TestEntity)
    handlers = entity_proxy_server.layer_rpc_handlers(TestEntity).pipe(
        fx.layer.provide_merge(test_sharding)
    )

    @fx.gen
    def body():
        yield from testing.adjust(0.001)
        client = yield from rpc_test.make_client(group)
        get_user: Callable[[object], fx.Effect[User, Any]] = _method(
            client, group, "TestEntity.GetUser"
        )
        user = yield from get_user({"entityId": "1", "payload": {"id": 7}})
        assert user == User(id=7, name="User 7")
        discard = _method(client, group, "TestEntity.GetUserDiscard")
        assert (yield from discard({"entityId": "1", "payload": {"id": 8}})) is None

    yield from fx.scoped(body).pipe(fx.provide(handlers))


def test_derives_a_post_endpoint_and_a_discard_endpoint_per_entity_rpc() -> None:
    group = entity_proxy.to_http_api_group("proxied", ProxiedEntity)
    assert group.identifier == "proxied"
    found = {(e.identifier, e.method, e.path) for e in group.endpoints.values()}
    assert found == {
        ("Request", "POST", "/request/:entityId"),
        ("RequestDiscard", "POST", "/request/:entityId/discard"),
    }


@testing.effect
def test_serves_the_proxy_http_api_through_the_entity_client():
    group = entity_proxy.to_http_api_group("test-entity", TestEntity)
    api = HttpApi.make("Proxy").add(group)
    handlers = entity_proxy_server.layer_http_api(api, group, TestEntity).pipe(
        fx.layer.provide_merge(test_sharding)
    )

    @fx.gen
    def body():
        yield from testing.adjust(0.001)
        client = yield from api_test.groups(api, [group])
        methods: Any = get_group(client, group)
        get_user: Callable[..., fx.Effect[Any, Any]] = methods.method("GetUser")
        user = yield from get_user(params={"entityId": "1"}, payload={"id": 7})
        assert user == User(id=7, name="User 7")
        discard: Callable[..., fx.Effect[Any, Any]] = methods.method("GetUserDiscard")
        sent = yield from discard(params={"entityId": "1"}, payload={"id": 8})
        assert sent is None

    yield from (
        fx.scoped(body).pipe(fx.provide(handlers)).pipe(fx.provide(http_server.layer_services))
    )
