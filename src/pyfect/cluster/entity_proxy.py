"""RPCs and HTTP endpoints that reach an entity from outside the cluster
(Effect's ``EntityProxy``): ``to_rpc_group`` derives an RPC group whose
requests carry the entity id and the entity RPC's payload;
``to_http_api_group`` derives an HTTP API group with the entity id in the
path."""

from __future__ import annotations

from typing import Any, TypedDict

from pyfect import schema as S
from pyfect.cluster.cluster_error import (
    AlreadyProcessingMessage,
    EntityNotAssignedToRunner,
    MailboxFull,
    PersistenceError,
)
from pyfect.cluster.entity import Entity
from pyfect.http_api import endpoint as http_endpoint
from pyfect.http_api.group import HttpApiGroup
from pyfect.rpc import AnyRpc, RpcGroup
from pyfect.rpc import make as make_rpc


class ProxyPayload(TypedDict):
    """The payload of a proxy RPC: the entity id and the entity RPC's own
    payload."""

    entityId: str
    payload: Any


CLIENT_ERRORS: tuple[Any, ...] = (MailboxFull, AlreadyProcessingMessage, PersistenceError)
"""The errors a discarding call can fail with."""

REQUEST_ERRORS: tuple[Any, ...] = (*CLIENT_ERRORS, EntityNotAssignedToRunner)
"""The cluster errors a call can fail with, besides the RPC's own."""


def _payload(rpc: AnyRpc) -> Any:
    return S.Struct(ProxyPayload, payload=rpc.payload_schema)


def proxy_rpcs(entity: type[Entity]) -> list[AnyRpc]:
    """For each entity RPC ``Tag``: ``"<type>.<Tag>"``, answered with the
    RPC's success, and ``"<type>.<Tag>Discard"``, answered once the message
    is sent."""
    rpcs: list[AnyRpc] = []
    for parent in entity.rpcs.values():
        payload = _payload(parent)
        success: Any = parent.success_schema
        error: Any = S.Union(parent.error_schema, *REQUEST_ERRORS)
        make: Any = make_rpc
        made: AnyRpc = make(
            f"{entity.type}.{parent.tag}", payload=payload, success=success, error=error
        )
        rpc = made.annotate_merge(parent.annotations)
        discard: AnyRpc = make_rpc(
            f"{entity.type}.{parent.tag}Discard",
            payload=payload,
            error=S.Union(*CLIENT_ERRORS),
        ).annotate_merge(parent.annotations)
        rpcs.extend((rpc, discard))
    return rpcs


def to_rpc_group(entity: type[Entity]) -> type[RpcGroup]:
    """The RPC group of ``proxy_rpcs(entity)`` (Effect's
    ``EntityProxy.toRpcGroup``); its RPCs are looked up by tag in
    ``rpcs``."""
    members = {f"rpc_{index}": rpc for index, rpc in enumerate(proxy_rpcs(entity))}
    return type(f"{entity.__name__}Proxy", (RpcGroup,), members)


class EntityIdParams(TypedDict):
    """The path parameters of a proxy endpoint."""

    entityId: str


_ENTITY_ID_PARAMS: Any = S.Struct(EntityIdParams)


def to_http_api_group(name: str, entity: type[Entity]) -> type[HttpApiGroup[Any]]:
    """The HTTP API group ``name`` with, for each entity RPC ``Tag``, a
    ``POST /<tag lowercased>/:entityId`` endpoint ``Tag`` answered with the
    RPC's success, and ``POST /<tag lowercased>/:entityId/discard``
    ``TagDiscard`` answered once the message is sent (Effect's
    ``EntityProxy.toHttpApiGroup``)."""
    group: type[HttpApiGroup[Any]] = HttpApiGroup.make(name)
    post: Any = http_endpoint.post
    for parent in entity.rpcs.values():
        path = f"/{parent.tag.lower()}/:entityId"
        call: Any = post(
            parent.tag,
            path,
            params=_ENTITY_ID_PARAMS,
            payload=parent.payload_schema,
            success=parent.success_schema,
            error=(parent.error_schema, *REQUEST_ERRORS),
        )
        discard: Any = post(
            f"{parent.tag}Discard",
            f"{path}/discard",
            params=_ENTITY_ID_PARAMS,
            payload=parent.payload_schema,
            error=CLIENT_ERRORS,
        )
        group = group.add(
            call.annotate_merge(parent.annotations), discard.annotate_merge(parent.annotations)
        )
    return group


__all__ = [
    "CLIENT_ERRORS",
    "REQUEST_ERRORS",
    "EntityIdParams",
    "ProxyPayload",
    "proxy_rpcs",
    "to_http_api_group",
    "to_rpc_group",
]
