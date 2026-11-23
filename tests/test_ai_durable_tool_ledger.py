"""``pyfect.ai.durable`` with ``tool_ledger.guard``: whatever a guarded call gives its
caller, a tool activity stores and reads back, and a ledger shared by several executions
keeps their calls apart.

A crash while a handler runs leaves the ledger an intent without a result, so the call
that runs again gets ``ToolOutcomeUnknown``: as a failed tool result for the model
(``"tell_model"``) or as the call's typed failure (``"fail"``). A ledger store that fails
gives ``ToolLedgerError``. Each must reach the agent as it does without the durable layer,
on the memory engine and on SQLite with the SQL ledger."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
from _ai_durable_agent import (
    KIT,
    Agent,
    AgentPayload,
    Calls,
    CallsService,
    agent,
    agent_layer,
    handlers_layer,
    memory_engine,
    model_layer,
    sqlite_engine,
)

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.ai import durable as durable_ai
from pyfect.ai import language_model as lm
from pyfect.ai import tool_ledger
from pyfect.ai._tool_outcomes import Outcome
from pyfect.exit import Failure
from pyfect.result import Ok
from pyfect.workflow import workflow

type Engines = Callable[[], tuple[fx.Layer[Any, Any, Any], fx.Layer[Any, Any, Any]]]

ENGINES: dict[str, Engines] = {
    "memory": lambda: (memory_engine(), tool_ledger.layer_memory),
    "sqlite": lambda: (sqlite_engine(), tool_ledger.layer_sql()),
}

PAYLOAD = AgentPayload(turns=1, prompt="go")
"""One call of ``Lookup``, ``call-0``, then "done"."""


def _reported(
    run: Callable[[AgentPayload, str], fx.Effect[str, Any, Any]],
) -> Callable[[AgentPayload, str], fx.Effect[str, Any, Any]]:
    """The agent with a typed failure as its answer, so the workflow's success schema holds
    it; a defect stays one."""

    def reporting(payload: AgentPayload, execution_id: str) -> fx.Effect[str, Any, Any]:
        return run(payload, execution_id).catch_all(
            lambda error: fx.succeed(f"failed: {type(error).__name__} {error.tool_call_id}")
        )

    return reporting


def _scoped(tool_call_id: str) -> fx.Effect[str]:
    """The ledger's key for ``tool_call_id`` inside ``PAYLOAD``'s execution."""
    return Agent.execution_id(PAYLOAD).map(lambda execution_id: f"{execution_id}/{tool_call_id}")


def _run_after(
    seed: Callable[[tool_ledger.ToolLedgerService], fx.Effect[Any, Any, Any]],
    on_unknown: tool_ledger.OnUnknown,
    engines: Engines,
) -> fx.Effect[tuple[str, dict[int, int]], Any, Any]:
    """Run ``PAYLOAD`` once ``seed`` has written to the ledger: the answer, and how often
    each tool call's handler ran."""
    engine, ledger = engines()
    guarded = tool_ledger.guard(KIT, on_unknown=on_unknown)
    layer = agent_layer(engine, run=_reported(agent(toolkit=guarded)), extra=ledger)

    @fx.gen
    def body():
        yield from seed((yield from tool_ledger.ToolLedger()))
        answer = yield from Agent.execute(PAYLOAD)
        return answer, dict((yield from CallsService()).tool)

    return body.pipe(fx.provide(layer))


def _started(
    key: fx.Effect[str],
) -> Callable[[tool_ledger.ToolLedgerService], fx.Effect[Any, Any]]:
    """An intent without a result under ``key``, as a crash mid-handler leaves it."""

    def claimed(begun: tool_ledger.Begun) -> None:
        assert isinstance(begun, tool_ledger.Claimed), begun

    return lambda ledger: key.flat_map(lambda k: ledger.begin(k, "Lookup")).map(claimed)


EXPECTED = {
    "tell_model": "done",
    "fail": "failed: ToolOutcomeUnknown call-0",
}
"""``"tell_model"``: the model gets the failed result and answers; ``"fail"``: the call
fails with ``ToolOutcomeUnknown``."""


@pytest.mark.parametrize("on_unknown", ["tell_model", "fail"])
@pytest.mark.parametrize("engine", ENGINES)
@testing.live
def test_a_call_cut_off_mid_handler_reaches_the_agent_as_an_unknown_outcome(
    engine: str, on_unknown: tool_ledger.OnUnknown
):
    found = yield from _run_after(_started(_scoped("call-0")), on_unknown, ENGINES[engine])
    assert found == (EXPECTED[on_unknown], {})


@pytest.mark.parametrize("on_unknown", ["tell_model", "fail"])
@pytest.mark.parametrize("engine", ENGINES)
@testing.live
def test_an_intent_an_earlier_release_stored_under_the_bare_id_still_counts(
    engine: str, on_unknown: tool_ledger.OnUnknown
):
    """Releases up to 0.6.22 keyed a call by its bare ``tool_call_id`` inside a workflow
    too: an execution in flight across the upgrade still finds its call's record."""
    found = yield from _run_after(_started(fx.succeed("call-0")), on_unknown, ENGINES[engine])
    assert found == (EXPECTED[on_unknown], {})


@pytest.mark.parametrize("engine", ENGINES)
@testing.live
def test_a_result_an_earlier_release_stored_under_the_bare_id_is_replayed(engine: str):
    def completed(ledger: tool_ledger.ToolLedgerService) -> fx.Effect[Any, Any]:
        return ledger.begin("call-0", "Lookup").and_then(
            ledger.complete("call-0", Outcome(False, "result 0"))
        )

    found = yield from _run_after(completed, "tell_model", ENGINES[engine])
    assert found == ("done", {})


class _Broken(tool_ledger.ToolLedgerService):
    """A ledger store that is down: ``begin`` fails with ``ToolLedgerError``."""

    def begin(self, tool_call_id: str, tool_name: str) -> fx.Effect[Any, Any]:
        return fx.fail(tool_ledger.ToolLedgerError("down", "begin", tool_call_id, OSError()))

    def complete(self, tool_call_id: str, outcome: Outcome) -> fx.Effect[None, Any]:
        raise AssertionError("not reached")

    def lookup(self, tool_call_id: str) -> fx.Effect[Any, Any]:
        return fx.succeed(None)


def _broken_ledger() -> fx.Layer[tool_ledger.ToolLedger]:
    return fx.layer.succeed(tool_ledger.ToolLedger, _Broken())


@pytest.mark.parametrize("engine", ENGINES)
@testing.live
def test_a_failing_ledger_store_reaches_the_agent_as_a_typed_tool_ledger_error(engine: str):
    database, _ = ENGINES[engine]()
    guarded = tool_ledger.guard(KIT, on_unknown="fail")
    layer = agent_layer(database, run=_reported(agent(toolkit=guarded)), extra=_broken_ledger())
    scoped = yield from _scoped("call-0")
    answer = yield from Agent.execute(PAYLOAD).pipe(fx.provide(layer))
    assert answer == f"failed: ToolLedgerError {scoped}"


TypedAgent = workflow.make(
    "TypedAgent",
    payload=S.Struct(AgentPayload),
    success=S.String,
    error=S.Union(tool_ledger.ToolOutcomeUnknown, tool_ledger.ToolLedgerError),
    idempotency_key=lambda p: f"{p['turns']}/{p['prompt']}",
)
"""The agent with the guard's errors in ``error=``, so its caller gets them typed."""


@pytest.mark.parametrize("engine", ENGINES)
@testing.live
def test_a_workflow_listing_tool_ledger_error_gives_its_caller_the_typed_error(engine: str):
    database, _ = ENGINES[engine]()
    guarded = tool_ledger.guard(KIT, on_unknown="fail")
    layer = agent_layer(
        database, run=agent(toolkit=guarded), extra=_broken_ledger(), registered=TypedAgent
    )
    scoped = yield from TypedAgent.execution_id(PAYLOAD).map(lambda e: f"{e}/call-0")
    exit = yield from TypedAgent.execute(PAYLOAD).pipe(fx.provide(layer)).exit()
    assert isinstance(exit, Failure), exit
    found = exit.cause.find_error()
    assert isinstance(found, Ok), exit.cause
    error = found.value
    assert isinstance(error, tool_ledger.ToolLedgerError), error
    assert (error.message, error.method, error.tool_call_id) == ("down", "begin", scoped)
    # The store's exception was stored as JSON: it comes back as an ErrorInstance.
    assert isinstance(error.cause, S.ErrorInstance), error.cause
    assert error.cause.name == "OSError"


@pytest.mark.parametrize("durable", [True, False])
@pytest.mark.parametrize("engine", ENGINES)
@testing.live
def test_two_executions_reusing_a_tool_call_id_each_run_their_tool(engine: str, durable: bool):
    """Both executions' model calls its tool ``call-0`` (fakes and examples reuse ids); the
    second must run its own handler, not get the first one's result."""
    database, ledger = ENGINES[engine]()
    guarded = tool_ledger.guard(KIT, on_unknown="fail")
    layer = agent_layer(
        database,
        run=_reported(agent(toolkit=guarded)),
        extra=ledger,
        durable_layer=durable_ai.layer if durable else None,
    )

    @fx.gen
    def body():
        first = yield from Agent.execute(AgentPayload(turns=1, prompt="first"))
        second = yield from Agent.execute(AgentPayload(turns=1, prompt="second"))
        return first, second, dict((yield from CallsService()).tool)

    assert (yield from body.pipe(fx.provide(layer))) == ("done", "done", {0: 2})


@testing.live
def test_outside_a_workflow_a_call_is_keyed_by_its_bare_id():
    ledger = tool_ledger.memory()
    guarded = tool_ledger.guard(KIT, on_unknown="fail")

    @fx.gen
    def body():
        yield from lm.generate_text("turns=1", toolkit=guarded)
        return (yield from ledger.lookup("call-0"))

    services = model_layer().pipe(fx.layer.provide_merge(handlers_layer()))
    services = services.pipe(fx.layer.provide_merge(fx.layer.sync(CallsService, Calls)))
    entry = yield from body.pipe(fx.provide_service(tool_ledger.ToolLedger, ledger)).pipe(
        fx.provide(services)
    )
    assert isinstance(entry, tool_ledger.Completed)
    assert entry.outcome == Outcome(False, "result 0")
