"""Serves the RPCs and HTTP endpoints ``entity_proxy`` derives (Effect's
``EntityProxyServer``): each call goes to the entity through its sharding
client."""

# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Never

from pyfect._core import Effect
from pyfect.cluster.entity import Entity
from pyfect.cluster.entity_proxy import to_rpc_group
from pyfect.cluster.sharding import Sharding
from pyfect.effect import gen
from pyfect.http_api import builder
from pyfect.http_api._handlers import GroupHandlers, HttpApiRequest
from pyfect.http_api.api import HttpApi
from pyfect.http_api.group import HttpApiGroup
from pyfect.layer import Layer
from pyfect.logger import log_error
from pyfect.rpc import AnyRpc, RpcRequest
from pyfect.rpc.group import Handlers, HandlersFor


def _call(client: Callable[[str], Any], parent: AnyRpc, *, discard: bool) -> Any:
    def handle(request: RpcRequest[Any]) -> Effect[Any, Any]:
        payload = request.payload
        call = client(payload["entityId"])._rpc_methods[parent.tag]
        return call.discard(payload["payload"]) if discard else call(payload["payload"])

    return handle


def layer_rpc_handlers(entity: type[Entity]) -> Layer[HandlersFor[Any], Never, Sharding]:
    """The handlers of ``to_rpc_group(entity)``: ``"<type>.<Tag>"`` calls
    the entity and ``"<type>.<Tag>Discard"`` sends without waiting for the
    reply."""
    group = to_rpc_group(entity)

    @gen
    def make():
        client = yield from entity.client()
        by_tag: dict[str, Any] = {}
        for parent in entity.rpcs.values():
            by_tag[f"{entity.type}.{parent.tag}"] = _call(client, parent, discard=False)
            by_tag[f"{entity.type}.{parent.tag}Discard"] = _call(client, parent, discard=True)
        return Handlers[Any, Never](group, by_tag)

    return group.to_layer_effect(make)


def _endpoint_handler(
    client: Callable[[str], Any], entity: type[Entity], parent: AnyRpc, *, discard: bool
) -> Callable[[HttpApiRequest[Any, Any, Any, Any]], Effect[Any, Any]]:
    method = f"{parent.tag}Discard" if discard else parent.tag

    def handle(request: HttpApiRequest[Any, Any, Any, Any]) -> Effect[Any, Any]:
        entity_id: str = request.params["entityId"]
        call = client(entity_id)._rpc_methods[parent.tag]
        sent: Effect[Any, Any] = call.discard(request.payload) if discard else call(request.payload)
        return sent.tap_defect(log_error).annotate_logs(
            {
                "module": "EntityProxyServer",
                "entity": entity.type,
                "entityId": entity_id,
                "method": method,
            }
        )

    return handle


def layer_http_api[G: HttpApiGroup[Any, Any]](
    api: HttpApi[G], group: type[G], entity: type[Entity]
) -> Layer[G, Never, Sharding]:
    """The handlers of ``group`` in ``api``, a group made by
    ``entity_proxy.to_http_api_group(..., entity)`` (Effect's
    ``EntityProxyServer.layerHttpApi``). Defects are logged."""

    def build(handlers: GroupHandlers[Any]) -> Effect[Any, Never, Sharding]:
        @gen
        def make():
            client = yield from entity.client()
            built: Any = handlers
            for parent in entity.rpcs.values():
                for discard in (False, True):
                    identifier = f"{parent.tag}Discard" if discard else parent.tag
                    built = built.handle(group.endpoints[identifier])(
                        _endpoint_handler(client, entity, parent, discard=discard)
                    )
            return built

        return make

    return builder.group(api, group, build)


__all__ = ["layer_http_api", "layer_rpc_handlers"]
