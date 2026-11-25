"""``pyfect.ai.durable``: an agent loop in a workflow whose model requests and tool calls
are activities, so a run killed at any step resumes without making a call twice.

The problems other frameworks have with durable agents, as tests: history that grows with
the turns and not with the conversation so far (model inputs were 99.8% of Temporal #1890's
history), and a replay with a changed prompt, which must fail instead of reusing the stored
answer (PydanticAI #13832, #13942). The 100-turn run killed at every step is
``test_ai_durable_sweep_memory`` and ``test_ai_durable_sweep_sqlite``."""

from __future__ import annotations

import gc
import sqlite3
from collections.abc import Callable
from contextlib import closing
from pathlib import Path
from typing import Any

import pytest
from _ai_durable_agent import (
    KIT,
    Agent,
    AgentPayload,
    Calls,
    CallsService,
    Chunks,
    Seen,
    agent,
    agent_layer,
    memory_engine,
    model_layer,
    run_agent,
    sqlite_engine,
    step_of,
)

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.ai import budget, durable, tool_ledger
from pyfect.ai import language_model as lm
from pyfect.ai import prompt as P
from pyfect.exit import Failure, Success
from pyfect.testing import explore
from pyfect.workflow import activity, workflow
from pyfect.workflow._activity_hook import ActivityHook
from pyfect.workflow._result import Suspended

# Outside a workflow -------------------------------------------------------------------


@testing.effect
def test_outside_a_workflow_the_layer_changes_nothing():
    @fx.gen
    def body():
        calls = yield from CallsService()
        response = yield from lm.generate_text("turns=1", toolkit=KIT)
        assert [part.name for part in response.tool_results] == ["Lookup"]
        assert (dict(calls.model), dict(calls.tool)) == ({0: 1}, {0: 1})

    from _ai_durable_agent import handlers_layer

    services = durable.layer.pipe(fx.layer.provide_merge(model_layer()))
    services = services.pipe(fx.layer.provide_merge(handlers_layer()))
    services = services.pipe(fx.layer.provide_merge(fx.layer.sync(CallsService, Calls)))
    yield from body.pipe(fx.provide(services))


# History size ----------------------------------------------------------------------------


def _stored_bytes(copy: Path) -> int:
    """The bytes the cluster engine had stored in the database ``copy``: its messages (the
    run, each activity's request) and their replies."""
    with closing(sqlite3.connect(copy)) as db:
        (stored,) = db.execute(
            "SELECT (SELECT coalesce(sum(length(payload)), 0) FROM cluster_messages)"
            " + (SELECT coalesce(sum(length(payload)), 0) FROM cluster_replies)"
        ).fetchone()
    return stored


def test_stored_bytes_grow_linearly_with_the_turns(ai_durable_crashes: list[Path]):
    """Each turn stores its outputs and two hashes, never the prompt so far: the bytes a
    turn adds are the same at turn 10 as at turn 100 (storing each request's prompt,
    they would grow with it, and the total with the square of the turns). Measured in the
    copies of a 100-turn run's database (``ai_durable_crashes``): copy ``2t`` is the
    database after ``t`` turns."""
    stored = {turns: _stored_bytes(ai_durable_crashes[2 * turns]) for turns in (10, 50, 100)}
    early = (stored[50] - stored[10]) / 40
    late = (stored[100] - stored[50]) / 50
    assert abs(late - early) <= 0.05 * early, stored


# Divergence ------------------------------------------------------------------------------


@testing.effect
def test_a_replay_with_a_changed_prompt_dies_with_request_diverged():
    """The run stops after its first turn was stored; the prompt is changed and the run
    resumed. Reusing the stored answer would answer a different prompt, so the replay of
    the first request dies with ``RequestDiverged`` and the model is not called again."""
    extra = [""]
    stops: list[str] = []

    def stop_after_turn_one(activity: Any, run: Any) -> Any:
        stops.append(activity.name)
        return run.and_then(fx.succeed(Suspended())) if len(stops) == 2 else run

    payload = AgentPayload(turns=3, prompt="go")
    layer = agent_layer(memory_engine(), run=agent(extra_prompt=lambda: extra[0]))

    @fx.gen
    def body():
        calls = yield from CallsService()
        execution_id = yield from Agent.execution_id(payload)
        waiter = yield from Agent.execute(payload).exit().fork()
        while not isinstance((yield from Agent.poll(execution_id)), Suspended):
            yield from fx.yield_now()
        extra[0] = " (now in French)"
        yield from Agent.resume(execution_id)
        ex = yield from waiter.join()
        assert isinstance(ex, Failure)
        diverged = ex.cause.squash()
        assert isinstance(diverged, durable.RequestDiverged)
        assert diverged.step == "pyfect/ai/1/model"
        assert diverged.recorded != diverged.requested
        assert (dict(calls.model), dict(calls.tool)) == ({0: 1}, {0: 1})

    yield from body.pipe(fx.provide(layer)).pipe(
        fx.provide_service(ActivityHook, stop_after_turn_one)
    )


@testing.live
def test_on_the_cluster_engine_a_caller_outside_gets_request_diverged_as_an_error_instance():
    """The cluster engine stores the run's result, its defect through ``Schema.Defect()``
    as Effect does: a caller outside the workflow reads it back as an ``ErrorInstance``
    named after ``RequestDiverged``, not as the class."""
    extra = [""]
    stops: list[str] = []

    def stop_after_turn_one(activity: Any, run: Any) -> Any:
        stops.append(activity.name)
        return run.and_then(fx.succeed(Suspended())) if len(stops) == 2 else run

    payload = AgentPayload(turns=3, prompt="go")
    layer = agent_layer(sqlite_engine(), run=agent(extra_prompt=lambda: extra[0]))

    @fx.gen
    def body():
        execution_id = yield from Agent.execution_id(payload)
        waiter = yield from Agent.execute(payload).exit().fork()
        while not isinstance((yield from Agent.poll(execution_id)), Suspended):
            yield from fx.yield_now()
        extra[0] = " (now in French)"
        yield from Agent.resume(execution_id)
        ex = yield from waiter.join()
        assert isinstance(ex, Failure)
        defect = ex.cause.squash()
        assert isinstance(defect, S.ErrorInstance), defect
        assert defect.name == "pyfect/ai/Durable/RequestDiverged"
        assert defect.message.startswith("pyfect/ai/1/model: the replayed request")

    yield from body.pipe(fx.provide(layer)).pipe(
        fx.provide_service(ActivityHook, stop_after_turn_one)
    )


@testing.effect
def test_with_suspend_on_failure_a_diverged_run_suspends_and_resumes_once_the_prompt_is_back():
    extra = [""]
    stops: list[str] = []

    def stop_after_turn_one(activity: Any, run: Any) -> Any:
        stops.append(activity.name)
        return run.and_then(fx.succeed(Suspended())) if len(stops) == 2 else run

    payload = AgentPayload(turns=3, prompt="go")
    suspending = Agent.annotate(workflow.SuspendOnFailure, True)
    layer = agent_layer(
        memory_engine(), run=agent(extra_prompt=lambda: extra[0]), registered=suspending
    )

    @fx.gen
    def body():
        calls = yield from CallsService()
        execution_id = yield from suspending.execution_id(payload)
        waiter = yield from suspending.execute(payload).exit().fork()

        @fx.gen
        def suspended():
            while not isinstance(found := (yield from suspending.poll(execution_id)), Suspended):
                yield from fx.yield_now()
            return found

        yield from suspended
        extra[0] = " (now in French)"
        yield from suspending.resume(execution_id)
        assert (yield from suspended).failed
        extra[0] = ""
        yield from suspending.resume(execution_id)
        assert (yield from waiter.join()) == Success("done")
        assert all(n == 1 for n in (*calls.model.values(), *calls.tool.values()))

    yield from body.pipe(fx.provide(layer)).pipe(
        fx.provide_service(ActivityHook, stop_after_turn_one)
    )


@testing.effect
def test_the_request_hash_covers_the_prompt_and_the_tools_but_not_the_span():
    options = lm.ProviderOptions(P.make("hi"))
    same = lm.ProviderOptions(P.make("hi"), previous_response_id="resp-1")
    assert durable.request_hash(options, streamed=False) == durable.request_hash(
        same, streamed=False
    )
    for other in (
        lm.ProviderOptions(P.make("hello")),
        lm.ProviderOptions(P.make("hi"), tool_choice="required"),
    ):
        assert durable.request_hash(other, streamed=False) != durable.request_hash(
            options, streamed=False
        )
    assert durable.request_hash(options, streamed=True) != durable.request_hash(
        options, streamed=False
    )
    assert durable.call_hash("Lookup", {"n": 1}) != durable.call_hash("Lookup", {"n": 2})
    yield from fx.void


def test_a_grown_prompt_digests_only_its_new_messages_and_hashes_as_one_built_afresh(
    monkeypatch: pytest.MonkeyPatch,
):
    """A turn's request hash costs the same at turn 100 as at turn 1: the messages the
    prompt kept are not digested again, and the hash is the one the whole prompt has."""
    encoded: list[object] = []
    encode = durable._encode_message  # pyright: ignore[reportPrivateUsage]

    def counting(message: P.Message) -> object:
        encoded.append(message)
        return encode(message)

    monkeypatch.setattr(durable, "_encode_message", counting)
    prompt = P.make(f"turn {0} of a long run")
    for turn in range(1, 50):
        prompt = prompt.concat(f"turn {turn}")
        durable.request_hash(lm.ProviderOptions(prompt), streamed=False)
    assert len(encoded) == 50
    afresh = P.make(f"turn {0} of a long run")
    for turn in range(1, 50):
        afresh = afresh.concat(f"turn {turn}")
    assert not any(a is b for a, b in zip(afresh.content, prompt.content, strict=True))
    assert durable.request_hash(lm.ProviderOptions(afresh), streamed=False) == (
        durable.request_hash(lm.ProviderOptions(prompt), streamed=False)
    )
    reordered = P.from_messages(reversed(prompt.content))
    assert durable.request_hash(lm.ProviderOptions(reordered), streamed=False) != (
        durable.request_hash(lm.ProviderOptions(prompt), streamed=False)
    )


# Budgets and the tool ledger -------------------------------------------------------------


def _small_sweep(
    layer: fx.Layer[Any, Any, Any], check: Callable[[fx.Exit[str, Any], Calls], str | None]
) -> fx.Effect[explore.CrashReport, Any, Any]:
    def checked(ex: fx.Exit[str, Any]) -> fx.Effect[str | None, Any, CallsService]:
        return CallsService().map(lambda calls: check(ex, calls))

    return explore.activity_crashes(
        Agent, AgentPayload(turns=5, prompt="go"), layer=layer, check=checked
    )


def _budgeted(limits: budget.Limits) -> Callable[[AgentPayload, str], fx.Effect[str, Any, Any]]:
    """The agent under a budget made in its body: each run, and each replay, starts it
    anew and spends it again on every step, replayed or not."""

    def run(payload: AgentPayload, execution_id: str) -> fx.Effect[str, Any, Any]:
        return (
            run_agent(payload, execution_id)
            .pipe(budget.limit(limits))
            .catch_all(lambda error: fx.succeed(f"stopped: {error}"))
        )

    return run


@testing.effect
def test_a_budget_that_fits_the_run_exactly_holds_at_every_crash_point():
    """6 requests and 5 tool calls are exactly what the run makes. A replayed step spends
    the budget as it did the first time (its stored usage), once: counting it twice would
    exceed the budget after a crash."""
    layer = agent_layer(memory_engine(), run=_budgeted(budget.Limits(requests=6, tool_calls=5)))
    report = yield from _small_sweep(
        layer, lambda ex, _: None if ex == Success("done") else f"ended with {ex}"
    )
    assert len(report.points) == 22


@testing.effect
def test_a_budget_one_request_short_stops_every_crashed_run_at_the_same_request():
    """Not spending replayed steps would let a resumed run go past its budget; spending
    them, every crashed run stops where the run without a crash stops."""
    layer = agent_layer(memory_engine(), run=_budgeted(budget.Limits(requests=5)))
    stopped = Success("stopped: Budget exceeded: requests needs 1, 0 of 5 left")
    report = yield from _small_sweep(
        layer,
        lambda ex, calls: (
            None if ex == stopped and max(calls.model) == 4 else f"{ex}, {dict(calls.model)}"
        ),
    )
    assert len(report.points) == 20


@testing.effect
def test_with_the_tool_ledger_no_tool_runs_twice_even_cut_off_before_its_result_was_stored():
    """The ledger runs inside the tool's activity: a call whose activity ran but was not
    stored is answered from the ledger when it runs again, so its handler does not."""
    guarded = tool_ledger.guard(KIT, on_unknown="tell_model")
    layer = agent_layer(memory_engine(), run=agent(toolkit=guarded), extra=tool_ledger.layer_memory)

    def check(ex: fx.Exit[str, Any], calls: Calls) -> str | None:
        if ex != Success("done"):
            return f"ended with {ex}"
        if any(n != 1 for n in calls.tool.values()) or sorted(calls.tool) != list(range(5)):
            return f"tool runs {dict(calls.tool)}"
        return None

    report = yield from _small_sweep(layer, check)
    assert len(report.points) == 22


# Streaming -------------------------------------------------------------------------------


@testing.effect
def test_a_streamed_run_killed_at_every_step_repeats_nothing():
    """A streamed request is one activity: its parts are stored once the provider's
    stream ends, and a replay gives them back without calling the model."""
    layer = agent_layer(memory_engine(), run=agent(streamed=True))
    seen: list[Seen] = []

    def check(ex: fx.Exit[str, Any], calls: Calls) -> str | None:
        seen.append(Seen(ex, dict(calls.model), dict(calls.tool)))
        return None if ex == Success("done") else f"ended with {ex}"

    report = yield from _small_sweep(layer, check)
    for point, run in zip(report.points, seen[1:], strict=True):
        assert run.repeated() == ([] if point.stored else [step_of(point.activity)]), point


def _streamed_chunks(durable_layer: fx.Layer[Any, Any, Any] | None) -> fx.Effect[list[int]]:
    layer = agent_layer(
        memory_engine(), run=agent(streamed=True, toolkit=None), durable_layer=durable_layer
    )

    @fx.gen
    def body():
        assert (yield from Agent.execute(AgentPayload(turns=0, prompt="go"))) == "done"
        return (yield from Chunks())

    return body.pipe(fx.provide(layer))


@testing.effect
def test_inside_a_durable_run_a_streamed_response_comes_as_one_chunk():
    """The provider streams five parts, one a chunk. In a durable run the caller gets them
    as one chunk, on the first run as on a replay, so a crash mid-stream never shows a
    consumer the same part twice."""
    assert (yield from _streamed_chunks(None)) == [1, 1, 1, 1, 1]
    assert (yield from _streamed_chunks(durable.layer)) == [5]


# Inside an activity ----------------------------------------------------------------------


@testing.effect
def test_a_request_inside_an_activity_is_not_made_an_activity_again():
    """The activity around a request stores what it does; a step of its own would count
    from 1 again inside it and take the name of the run's first request."""
    names: list[str] = []

    def record(activity: Any, run: Any) -> Any:
        names.append(activity.name)
        return run

    def research(payload: AgentPayload, execution_id: str) -> fx.Effect[str, Any, Any]:
        inner = run_agent(payload, execution_id)
        return activity.make(name="research", success=S.String, execute=inner)

    layer = agent_layer(memory_engine(), run=research)
    found = yield from (
        Agent.execute(AgentPayload(turns=2, prompt="go"))
        .pipe(fx.provide(layer))
        .pipe(fx.provide_service(ActivityHook, record))
    )
    assert (found, names) == ("done", ["research"])


def test_a_finished_run_leaves_no_step_counters_behind():
    """The counters are keyed weakly by the run's instance and hold only ints and names, so
    they go with it once the run's effect is done (a plain run: a test effect's runtime keeps
    its fibers until the test ends). Only this run's counters count: an earlier test on the
    same worker may still hold a run of its own."""
    earlier = list(durable._runs)  # pyright: ignore[reportPrivateUsage]
    run = Agent.execute(AgentPayload(turns=2, prompt="go")).pipe(
        fx.provide(agent_layer(memory_engine()))
    )
    found = fx.run_blocking(run)
    gc.collect()
    runs = durable._runs  # pyright: ignore[reportPrivateUsage]
    left = [instance for instance in runs if all(instance is not e for e in earlier)]
    assert (found, left) == ("done", [])
