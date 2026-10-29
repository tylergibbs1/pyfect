"""``workflow_proxy`` / ``workflow_proxy_server``: the execute, discard and
resume operations of workflows over RPC and over an HTTP API, served in
memory. (Effect has no tests of these modules.)"""

from __future__ import annotations

from typing import Any, TypedDict, cast

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.http_api import test as api_test
from pyfect.http_api.api import HttpApi
from pyfect.rpc import test as rpc_test
from pyfect.workflow import (
    Complete,
    Suspended,
    durable_deferred,
    workflow,
    workflow_engine,
    workflow_proxy,
    workflow_proxy_server,
)


class Value(TypedDict):
    value: float


Increment = workflow.make(
    "Increment",
    payload=S.Struct(Value),
    success=S.Number,
    error=S.String,
    idempotency_key=lambda p: str(p["value"]),
)
Gate = durable_deferred.make("gate")
calls: list[float] = []


def _increment(p: Value, _id: str) -> fx.Effect[float, str, Any]:
    def body():
        calls.append(p["value"])
        if p["value"] < 0:
            return (yield from fx.fail("negative"))
        if p["value"] == 0:
            yield from Gate.wait()
        return p["value"] + 1

    return fx.gen(body)


WORKFLOWS = Increment.to_layer(_increment).pipe(
    fx.layer.provide_merge(workflow_engine.layer_memory)
)


def _poll_until_suspended(execution_id: str):
    result = yield from Increment.poll(execution_id)
    while not isinstance(result, Suspended):
        yield from fx.yield_now()
        result = yield from Increment.poll(execution_id)


def test_rpc_group_declares_execute_discard_and_resume_per_workflow():
    group = workflow_proxy.to_rpc_group([Increment], prefix="Wf")
    assert sorted(group.rpcs) == ["WfIncrement", "WfIncrementDiscard", "WfIncrementResume"]
    assert group.rpcs["WfIncrementDiscard"].success_schema is S.String


def test_http_api_group_posts_to_the_lowercased_tag():
    group = workflow_proxy.to_http_api_group("workflows", [Increment])
    paths = {k: (e.method, e.path) for k, e in group.endpoints.items()}
    assert paths == {
        "Increment": ("POST", "/increment"),
        "IncrementDiscard": ("POST", "/increment/discard"),
        "IncrementResume": ("POST", "/increment/resume"),
    }


def test_proxies_need_a_workflow():
    for make in (
        lambda: workflow_proxy.to_rpc_group([]),
        lambda: workflow_proxy.to_http_api_group("none", []),
    ):
        try:
            make()
        except ValueError:
            continue
        raise AssertionError("an empty proxy must be rejected")


@testing.effect
def test_rpc_handlers_execute_discard_and_resume():
    group = workflow_proxy.to_rpc_group([Increment])
    handlers = workflow_proxy_server.layer_rpc_handlers([Increment])

    def program():
        client: Any = yield from rpc_test.make_client(group)
        assert (yield from client.Increment({"value": 1})) == 2
        assert (yield from client.Increment({"value": -1}).flip()) == "negative"

        execution_id = cast("str", (yield from client.IncrementDiscard({"value": 0})))
        assert execution_id == (yield from Increment.execution_id({"value": 0}))
        yield from _poll_until_suspended(execution_id)
        runs = len(calls)
        yield from client.IncrementResume({"executionId": execution_id})
        while len(calls) == runs:
            yield from fx.yield_now()
        assert isinstance((yield from Increment.poll(execution_id)), Suspended | None)

    yield from fx.gen(program).pipe(fx.provide(handlers.pipe(fx.layer.provide_merge(WORKFLOWS))))


@testing.effect
def test_http_api_handlers_execute_discard_and_resume():
    group = workflow_proxy.to_http_api_group("workflows", [Increment])
    api = HttpApi.make("api").add(group)
    handlers = workflow_proxy_server.layer_http_api(api, "workflows", [Increment])

    def program():
        client = yield from api_test.groups(api, [group])
        methods = client[group]
        assert (yield from methods.method("Increment")(payload={"value": 2})) == 3
        assert (yield from methods.method("Increment")(payload={"value": -2}).flip()) == "negative"

        execution_id = cast(
            "str", (yield from methods.method("IncrementDiscard")(payload={"value": 0}))
        )
        assert execution_id == (yield from Increment.execution_id({"value": 0}))
        yield from _poll_until_suspended(execution_id)
        token = Gate.token_from_execution_id(workflow=Increment, execution_id=execution_id)
        yield from Gate.succeed(token=token, value=None)
        yield from methods.method("IncrementResume")(payload={"executionId": execution_id})
        result = yield from Increment.poll(execution_id)
        while not isinstance(result, Complete):
            yield from fx.yield_now()
            result = yield from Increment.poll(execution_id)
        assert result == Complete(fx.Success(1))

    yield from fx.gen(program).pipe(fx.provide(handlers.pipe(fx.layer.provide_merge(WORKFLOWS))))


def test_importing_pyfect_loads_neither_rpc_nor_http_api():
    """The proxies are submodules imported on demand, so ``fx.workflow``
    does not add the RPC and HTTP API packages to pyfect's import time."""
    import subprocess
    import sys

    loaded = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            "import sys, pyfect; "
            "print(sorted(m for m in ('pyfect.rpc', 'pyfect.http_api') if m in sys.modules))",
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()
    assert loaded == "[]"
