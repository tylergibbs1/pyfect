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
from typing import Any, Never

from pyfect._core import Effect
from pyfect.context import Context
from pyfect.effect import context
from pyfect.http_api._handlers import Handlers, HttpApiRequest
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


def layer_http_api(
    api: HttpApi[Any], identifier: str, workflows: Sequence[AnyWorkflow]
) -> Layer[Any, Never, WorkflowEngine]:
    """The handlers of the group ``identifier`` of ``api``, made by
    ``workflow_proxy.to_http_api_group(identifier, workflows)``."""
    group = api.groups.get(identifier)
    if group is None:
        raise ValueError(f'HttpApiGroup "{identifier}" not found in HttpApi "{api.identifier}"')

    def build(handlers: Any) -> Handlers[Any, Any, Any]:
        for workflow in workflows:
            tag = workflow.tag

            def execute(request: Request, w: AnyWorkflow = workflow) -> Effect[Any, Any, Any]:
                return _logged(w.execute(request.payload), w.tag)

            def discard(request: Request, w: AnyWorkflow = workflow) -> Effect[Any, Any, Any]:
                return _logged(w.execute(request.payload, discard=True), f"{w.tag}Discard")

            def resume(request: Request, w: AnyWorkflow = workflow) -> Effect[Any, Any, Any]:
                return _logged(w.resume(request.payload["executionId"]), f"{w.tag}Resume")

            handlers = (
                handlers.handle(group.endpoints[tag])(execute)
                .handle(group.endpoints[f"{tag}Discard"])(discard)
                .handle(group.endpoints[f"{tag}Resume"])(resume)
            )
        return handlers

    return builder_group(api, group, build)


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


__all__ = ["AnyWorkflow", "Request", "layer_http_api", "layer_rpc_handlers"]
