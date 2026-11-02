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

The groups above are built at run time, so a client reads their
operations by name (``.method("<Tag>")``, untyped). To type a client,
declare the operations in your own group (Effect types its groups by the
workflows' tags, which Python cannot)::

    class Expenses(HttpApiGroup, identifier="expenses"):
        submit, submit_discard, submit_resume = workflow_proxy.http_endpoints(SubmitExpense)

    class ExpenseRpcs(RpcGroup):
        submit, submit_discard, submit_resume = workflow_proxy.rpcs(SubmitExpense)
"""

from __future__ import annotations

import types
from collections.abc import Sequence
from typing import Any, NamedTuple, Never, TypedDict

from pyfect.http_api import endpoint as http_endpoint
from pyfect.http_api.endpoint import HttpApiEndpoint
from pyfect.http_api.group import HttpApiGroup
from pyfect.rpc import Rpc
from pyfect.rpc import make as make_rpc
from pyfect.rpc.group import RpcGroup
from pyfect.schema import String, Struct
from pyfect.workflow.workflow import Workflow


class ResumePayload(TypedDict):
    executionId: str


"""The payload of a ``<Tag>Resume`` operation."""

RESUME_PAYLOAD = Struct(ResumePayload)

type AnyWorkflow = Workflow[Any, Any, Any]


class WorkflowRpcs[P, A, E](NamedTuple):
    """The three RPCs of one workflow (``rpcs``)."""

    execute: Rpc[P, A, E]
    discard: Rpc[P, str, Never]
    resume: Rpc[ResumePayload, None, Never]


class WorkflowEndpoints[P, A, E](NamedTuple):
    """The three HTTP endpoints of one workflow (``http_endpoints``)."""

    execute: HttpApiEndpoint[None, None, P, P, None, A, A, E]
    discard: HttpApiEndpoint[None, None, P, P, None, str, str, Never]
    resume: HttpApiEndpoint[None, None, ResumePayload, ResumePayload, None, None, None, Never]


def rpcs[P, A, E](workflow: Workflow[P, A, E], *, prefix: str = "") -> WorkflowRpcs[P, A, E]:
    """The execute, discard and resume RPCs of ``workflow`` (tags
    ``<prefix><Tag>``, ``...Discard``, ``...Resume``), typed, to declare in
    an ``RpcGroup``; ``workflow_proxy_server.layer_rpc_handlers`` serves
    them."""
    tag = f"{prefix}{workflow.tag}"
    return WorkflowRpcs(
        make_rpc(
            tag,
            payload=workflow.payload_schema,
            success=workflow.success_schema,
            error=workflow.error_schema,
        ).annotate_merge(workflow.annotations),
        make_rpc(f"{tag}Discard", payload=workflow.payload_schema, success=String).annotate_merge(
            workflow.annotations
        ),
        make_rpc(f"{tag}Resume", payload=RESUME_PAYLOAD).annotate_merge(workflow.annotations),
    )


def http_endpoints[P, A, E](workflow: Workflow[P, A, E]) -> WorkflowEndpoints[P, A, E]:
    """The execute, discard and resume endpoints of ``workflow`` (``POST
    /<tag>``, ``/<tag>/discard``, ``/<tag>/resume``), typed, to declare in
    an ``HttpApiGroup``; ``workflow_proxy_server.handle_http`` serves
    them."""
    path = f"/{tag_to_path(workflow.tag)}"
    return WorkflowEndpoints(
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


def to_rpc_group(workflows: Sequence[AnyWorkflow], *, prefix: str = "") -> type[RpcGroup]:
    """An ``RpcGroup`` with the execute, discard and resume RPCs of each
    workflow, their tags prefixed by ``prefix``. Subclass it to name it::

        class WorkflowRpcs(workflow_proxy.to_rpc_group([EmailWorkflow])): ...

    Its client reads them by tag; declare ``rpcs(workflow)`` in a group
    of your own to type them."""
    if not workflows:
        raise ValueError("to_rpc_group needs at least one workflow")
    found: dict[str, Any] = {}
    for workflow in workflows:
        for rpc in rpcs(workflow, prefix=prefix):
            found[rpc.tag] = rpc
    return types.new_class("WorkflowRpcs", (RpcGroup,), {}, lambda ns: ns.update(found))


def tag_to_path(tag: str) -> str:
    return tag.lower()


def to_http_api_group(name: str, workflows: Sequence[AnyWorkflow]) -> type[HttpApiGroup[Never]]:
    """An ``HttpApiGroup`` with identifier ``name`` holding the execute,
    discard and resume endpoints of each workflow (``POST /<tag>``,
    ``/<tag>/discard``, ``/<tag>/resume``). A client calls them with
    ``get_group(client, Group).method("<Tag>")``; declare
    ``http_endpoints(workflow)`` in a group of your own to type them."""
    if not workflows:
        raise ValueError("to_http_api_group needs at least one workflow")
    group: type[HttpApiGroup[Never]] = types.new_class(name, (HttpApiGroup,), {"identifier": name})
    for workflow in workflows:
        group = group.add(*http_endpoints(workflow))
    return group


__all__ = [
    "RESUME_PAYLOAD",
    "AnyWorkflow",
    "ResumePayload",
    "WorkflowEndpoints",
    "WorkflowRpcs",
    "http_endpoints",
    "rpcs",
    "tag_to_path",
    "to_http_api_group",
    "to_rpc_group",
]
