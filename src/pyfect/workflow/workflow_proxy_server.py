"""Serving the operations of ``workflow_proxy`` (Effect's
``effect/workflow/WorkflowProxyServer``)::

    ApiLive = builder.layer(api).pipe(
        fx.layer.provide(workflow_proxy_server.layer_http_api(api, "workflows", [EmailWorkflow]))
    )
    RpcLive = rpc_server.layer(WorkflowRpcs).pipe(
        fx.layer.provide(workflow_proxy_server.layer_rpc_handlers([EmailWorkflow]))
    )

Execute runs the workflow, discard starts it and answers with its
execution id, resume resumes it; the engine and the workflows' handlers
stay on the server. A defect is logged.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Never, overload

from pyfect._core import Effect
from pyfect.context import Context
from pyfect.effect import context
from pyfect.http_api._handlers import GroupHandlers, Handlers, HttpApiRequest
from pyfect.http_api.api import HttpApi
from pyfect.http_api.builder import group as builder_group
from pyfect.layer import Layer
from pyfect.layer import effect_context as layer_effect_context
from pyfect.logger import log_error
from pyfect.rpc import make as make_rpc
from pyfect.rpc._rpc import HandlerEntry, RpcRequest, handler_tag
from pyfect.rpc.group import HandlersFor
from pyfect.scope import Scope
from pyfect.workflow._services import WorkflowEngine
from pyfect.workflow.workflow import Workflow

type AnyWorkflow = Workflow[Any, Any, Any]
type Request = HttpApiRequest[Any, Any, Any, Any]


def _logged[A, E, R](effect: Effect[A, E, R], method: str) -> Effect[A, E, R]:
    return effect.tap_defect(log_error).annotate_logs(
        {"module": "WorkflowProxyServer", "method": method}
    )


@overload
def handle_http(
    handlers: GroupHandlers[Any], workflows: Sequence[AnyWorkflow]
) -> Handlers[Any, Any, WorkflowEngine]: ...
@overload
def handle_http[GP, GE, R](
    handlers: Handlers[GP, GE, R], workflows: Sequence[AnyWorkflow]
) -> Handlers[GP, GE, R | WorkflowEngine]: ...
def handle_http(
    handlers: Handlers[Any, Any, Any] | GroupHandlers[Any], workflows: Sequence[AnyWorkflow]
) -> Handlers[Any, Any, Any]:
    """``handlers`` with the execute, discard and resume endpoints of each
    workflow handled: those ``workflow_proxy.http_endpoints(workflow)``
    declares in the handlers' group, next to its other endpoints::

        builder.group(api, Expenses, lambda h: workflow_proxy_server.handle_http(
            h.handle(Expenses.health)(health), [SubmitExpense]))
    """
    group = handlers.group
    tags = [t for w in workflows for t in (w.tag, f"{w.tag}Discard", f"{w.tag}Resume")]
    missing = [t for t in tags if t not in group.endpoints]
    if missing:
        raise ValueError(
            f'HttpApiGroup "{group.identifier}" has no endpoint {", ".join(missing)}: declare '
            "workflow_proxy.http_endpoints(workflow) in it"
        )
    found: Handlers[Any, Any, Any] = (
        Handlers(group) if isinstance(handlers, GroupHandlers) else handlers
    )
    for workflow in workflows:
        tag = workflow.tag

        def execute(request: Request, w: AnyWorkflow = workflow) -> Effect[Any, Any, Any]:
            return _logged(w.execute(request.payload), w.tag)

        def discard(request: Request, w: AnyWorkflow = workflow) -> Effect[Any, Any, Any]:
            return _logged(w.execute(request.payload, discard=True), f"{w.tag}Discard")

        def resume(request: Request, w: AnyWorkflow = workflow) -> Effect[Any, Any, Any]:
            return _logged(w.resume(request.payload["executionId"]), f"{w.tag}Resume")

        found = (
            found.handle(group.endpoints[tag])(execute)
            .handle(group.endpoints[f"{tag}Discard"])(discard)
            .handle(group.endpoints[f"{tag}Resume"])(resume)
        )
    return found


def layer_http_api(
    api: HttpApi[Any], identifier: str, workflows: Sequence[AnyWorkflow]
) -> Layer[Any, Never, WorkflowEngine]:
    """The handlers of the group ``identifier`` of ``api``, made by
    ``workflow_proxy.to_http_api_group(identifier, workflows)`` (or one
    declaring only ``workflow_proxy.http_endpoints`` of ``workflows``)."""
    group = api.groups.get(identifier)
    if group is None:
        raise ValueError(f'HttpApiGroup "{identifier}" not found in HttpApi "{api.identifier}"')
    return builder_group(api, group, lambda handlers: handle_http(handlers, workflows))


def layer_rpc_handlers(
    workflows: Sequence[AnyWorkflow], *, prefix: str = ""
) -> Layer[HandlersFor[Any], Never, WorkflowEngine]:
    """The handlers of the RPCs ``workflow_proxy.to_rpc_group(workflows,
    prefix=prefix)`` declares."""

    def entries(services: Context[Any]) -> Context[Any]:
        kept = Context({t: s for t, s in services.map_unsafe.items() if t is not Scope})
        found: dict[Any, HandlerEntry] = {}
        for workflow in workflows:
            tag = f"{prefix}{workflow.tag}"

            def execute(
                request: RpcRequest[Any], w: AnyWorkflow = workflow
            ) -> Effect[Any, Any, Any]:
                return w.execute(request.payload)

            def discard(
                request: RpcRequest[Any], w: AnyWorkflow = workflow
            ) -> Effect[Any, Any, Any]:
                return w.execute(request.payload, discard=True)

            def resume(
                request: RpcRequest[Any], w: AnyWorkflow = workflow
            ) -> Effect[Any, Any, Any]:
                return w.resume(request.payload["executionId"])

            for name, handler in (
                (tag, execute),
                (f"{tag}Discard", discard),
                (f"{tag}Resume", resume),
            ):
                found[handler_tag(make_rpc(name))] = HandlerEntry(name, handler, kept)
        return Context(found)

    return layer_effect_context(context().map(entries))


__all__ = ["AnyWorkflow", "Request", "handle_http", "layer_http_api", "layer_rpc_handlers"]
