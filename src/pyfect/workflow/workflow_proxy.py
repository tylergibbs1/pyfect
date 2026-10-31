"""RPC and HTTP API definitions for workflows (Effect's
``effect/workflow/WorkflowProxy``)::

    WorkflowRpcs = workflow_proxy.to_rpc_group([EmailWorkflow])
    Workflows = workflow_proxy.to_http_api_group("workflows", [EmailWorkflow])

Each workflow gets three operations: ``<Tag>`` executes it (its payload,
success and error), ``<Tag>Discard`` starts it and answers with the
execution id, and ``<Tag>Resume`` resumes a suspended execution by
``executionId``. Over HTTP they are ``POST /<tag>``, ``/<tag>/discard``
and ``/<tag>/resume`` (the tag lowercased). ``workflow_proxy_server``
serves them.
"""

from __future__ import annotations

import types
from collections.abc import Sequence
from typing import Any, Never, TypedDict

from pyfect.http_api import endpoint as http_endpoint
from pyfect.http_api.group import HttpApiGroup
from pyfect.rpc import make as make_rpc
from pyfect.rpc.group import RpcGroup
from pyfect.schema import String, Struct
from pyfect.workflow.workflow import Workflow


class ResumePayload(TypedDict):
    executionId: str


"""The payload of a ``<Tag>Resume`` operation."""

RESUME_PAYLOAD = Struct(ResumePayload)

type AnyWorkflow = Workflow[Any, Any, Any]


def to_rpc_group(workflows: Sequence[AnyWorkflow], *, prefix: str = "") -> type[RpcGroup]:
    """An ``RpcGroup`` with the execute, discard and resume RPCs of each
    workflow, their tags prefixed by ``prefix``. Subclass it to name it::

        class WorkflowRpcs(workflow_proxy.to_rpc_group([EmailWorkflow])): ...
    """
    if not workflows:
        raise ValueError("to_rpc_group needs at least one workflow")
    rpcs: dict[str, Any] = {}
    for workflow in workflows:
        tag = f"{prefix}{workflow.tag}"
        rpcs[tag] = make_rpc(
            tag,
            payload=workflow.payload_schema,
            success=workflow.success_schema,
            error=workflow.error_schema,
        ).annotate_merge(workflow.annotations)
        rpcs[f"{tag}Discard"] = make_rpc(
            f"{tag}Discard", payload=workflow.payload_schema, success=String
        ).annotate_merge(workflow.annotations)
        rpcs[f"{tag}Resume"] = make_rpc(f"{tag}Resume", payload=RESUME_PAYLOAD).annotate_merge(
            workflow.annotations
        )
    return types.new_class("WorkflowRpcs", (RpcGroup,), {}, lambda ns: ns.update(rpcs))


def tag_to_path(tag: str) -> str:
    return tag.lower()


def to_http_api_group(name: str, workflows: Sequence[AnyWorkflow]) -> type[HttpApiGroup[Never]]:
    """An ``HttpApiGroup`` with identifier ``name`` holding the execute,
    discard and resume endpoints of each workflow (``POST /<tag>``,
    ``/<tag>/discard``, ``/<tag>/resume``). A client calls them with
    ``get_group(client, Group).method("<Tag>")``."""
    if not workflows:
        raise ValueError("to_http_api_group needs at least one workflow")
    group: type[HttpApiGroup[Never]] = types.new_class(name, (HttpApiGroup,), {"identifier": name})
    for workflow in workflows:
        path = f"/{tag_to_path(workflow.tag)}"
        group = group.add(
            http_endpoint.post(
                workflow.tag,
                path,
                payload=workflow.payload_schema,
                success=workflow.success_schema,
                error=workflow.error_schema,
            ).annotate_merge(workflow.annotations),
            http_endpoint.post(
                f"{workflow.tag}Discard",
                f"{path}/discard",
                payload=workflow.payload_schema,
                success=String,
            ).annotate_merge(workflow.annotations),
            http_endpoint.post(
                f"{workflow.tag}Resume", f"{path}/resume", payload=RESUME_PAYLOAD
            ).annotate_merge(workflow.annotations),
        )
    return group


__all__ = [
    "RESUME_PAYLOAD",
    "AnyWorkflow",
    "ResumePayload",
    "tag_to_path",
    "to_http_api_group",
    "to_rpc_group",
]
