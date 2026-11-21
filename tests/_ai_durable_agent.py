"""The agent ``test_ai_durable`` runs: a workflow that talks with a fake model for
``turns`` turns, each answered with one call of the ``Lookup`` tool, then ends with
"done". The model and the tool count their runs in ``Calls``."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, TypedDict

import pyfect as fx
from pyfect import reactivity
from pyfect import schema as S
from pyfect.ai import durable, prompt
from pyfect.ai import language_model as lm
from pyfect.ai import tool as T
from pyfect.ai import toolkit as K
from pyfect.cluster import cluster_workflow_engine, single_runner
from pyfect.sql import sqlite
from pyfect.sql.client import SqlClient
from pyfect.stream import _constructors as streams
from pyfect.testing import explore
from pyfect.workflow import workflow, workflow_engine


class LookupParams(TypedDict):
    n: int


Lookup = T.make("Lookup", parameters=S.Struct(LookupParams), success=S.String)
KIT = K.make(Lookup)


class AgentPayload(TypedDict):
    turns: int
    prompt: str


Agent = workflow.make(
    "Agent",
    payload=S.Struct(AgentPayload),
    success=S.String,
    idempotency_key=lambda p: f"{p['turns']}/{p['prompt']}",
)


class Calls:
    """How many times each model turn and each tool call ran."""

    def __init__(self) -> None:
        self.model: Counter[int] = Counter()
        self.tool: Counter[int] = Counter()


class CallsService(fx.Tag[Calls], key="test/ai_durable/Calls"): ...


def _turn(options: lm.ProviderOptions) -> int:
    return sum(1 for message in options.prompt.content if message.role == "tool")


def _wanted(options: lm.ProviderOptions) -> int:
    found = re.search(r"turns=(\d+)", repr(options.prompt.content[0]))
    assert found is not None
    return int(found.group(1))


def reply(options: lm.ProviderOptions) -> list[lm.EncodedPart]:
    """A call of ``Lookup`` until the prompt has the wanted number of tool results."""
    turn = _turn(options)
    usage = {"inputTokens": {"total": 10}, "outputTokens": {"total": 5}}
    if turn >= _wanted(options):
        return [
            {"type": "text", "text": "done"},
            {"type": "finish", "reason": "stop", "usage": usage},
        ]
    call = {"type": "tool-call", "id": f"call-{turn}", "name": "Lookup", "params": {"n": turn}}
    return [call, {"type": "finish", "reason": "tool-calls", "usage": usage}]


def stream_reply(options: lm.ProviderOptions) -> fx.Stream[lm.EncodedPart]:
    """``reply``'s parts as stream parts, one per chunk."""
    parts = reply(options)
    if parts[0]["type"] == "text":
        text: list[lm.EncodedPart] = [
            {"type": "text-start", "id": "t"},
            {"type": "text-delta", "id": "t", "delta": "do"},
            {"type": "text-delta", "id": "t", "delta": "ne"},
            {"type": "text-end", "id": "t"},
        ]
        parts = [*text, parts[1]]
    return streams.from_iterable(parts, chunk_size=1)


def model_layer() -> fx.Layer[lm.LanguageModel, Any, CallsService]:
    def make(calls: Calls) -> fx.Effect[lm.Service]:
        def generate(options: lm.ProviderOptions) -> fx.Effect[Any, Any, Any]:
            def run() -> list[lm.EncodedPart]:
                calls.model[_turn(options)] += 1
                return reply(options)

            return fx.sync(run)

        def stream(options: lm.ProviderOptions) -> fx.Stream[Any, Any, Any]:
            counted = streams.from_effect(fx.sync(lambda: calls.model.update([_turn(options)])))
            return counted.drain().concat(stream_reply(options))

        return lm.make(generate_text=generate, stream_text=stream)

    return fx.layer.effect(lm.LanguageModel, CallsService().flat_map(make))


def handlers_layer() -> fx.Layer[Any, Any, CallsService]:
    def make(calls: Calls) -> fx.Layer[Any]:
        def lookup(params: LookupParams, _: Any) -> fx.Effect[str]:
            def run() -> str:
                calls.tool[params["n"]] += 1
                return f"result {params['n']}"

            return fx.sync(run)

        return KIT.to_layer(Lookup.handler(lookup))

    return fx.layer.unwrap(CallsService().map(make))


class Chunks(fx.Tag[list[int]], key="test/ai_durable/Chunks"): ...


def agent(
    *, toolkit: Any = KIT, streamed: bool = False, extra_prompt: Callable[[], str] = lambda: ""
) -> Callable[[AgentPayload, str], fx.Effect[str, Any, Any]]:
    """The agent loop: ``generate_text`` (or ``stream_text``, recording the size of each
    chunk in ``Chunks``) until a response makes no tool call.
    ``extra_prompt`` is read on every run, to change the code under a running workflow."""

    def turn(history: prompt.Prompt) -> fx.Effect[tuple[list[Any], str], Any, Any]:
        if not streamed:
            return lm.generate_text(history, toolkit=toolkit).map(
                lambda r: (list(r.content), r.text)
            )

        def run(chunks: list[int]) -> fx.Effect[tuple[list[Any], str], Any, Any]:
            def seen(chunk: tuple[Any, ...]) -> tuple[Any, ...]:
                chunks.append(len(chunk))
                return chunk

            parts = lm.stream_text(history, toolkit=toolkit).map_array(seen).run_collect()
            return parts.map(
                lambda found: (
                    list(found),
                    "".join(p.delta for p in found if p.type == "text-delta"),
                )
            )

        return Chunks().flat_map(run)

    def run_agent(payload: AgentPayload, _execution_id: str) -> fx.Effect[str, Any, Any]:
        @fx.gen
        def body():
            text = f"turns={payload['turns']} {payload['prompt']}{extra_prompt()}"
            history = prompt.make(text)
            while True:
                content, answer = yield from turn(history)
                history = history.concat(prompt.from_response_parts(content))
                if not any(part.type == "tool-call" for part in content):
                    return answer

        return body

    return run_agent


run_agent = agent()


def agent_layer(
    engine: fx.Layer[Any, Any, Any],
    *,
    run: Callable[[AgentPayload, str], fx.Effect[str, Any, Any]] = run_agent,
    durable_layer: fx.Layer[Any, Any, Any] | None = durable.layer,
    extra: fx.Layer[Any, Any, Any] | None = None,
    registered: workflow.Workflow[AgentPayload, str, Any] = Agent,
) -> fx.Layer[Any, Any, Any]:
    """The workflow registered on ``engine``, with the durable layer over the model."""
    services = model_layer()
    if durable_layer is not None:
        services = durable_layer.pipe(fx.layer.provide_merge(services))
    services = services.pipe(fx.layer.provide_merge(handlers_layer()))
    if extra is not None:
        services = services.pipe(fx.layer.provide_merge(extra))
    return (
        registered.to_layer(run)
        .pipe(fx.layer.provide_merge(services))
        .pipe(fx.layer.provide_merge(engine))
        .pipe(fx.layer.provide_merge(fx.layer.sync(CallsService, Calls)))
        .pipe(fx.layer.provide_merge(fx.layer.sync(Chunks, list)))
    )


def memory_engine() -> fx.Layer[Any, Any, Any]:
    return workflow_engine.layer_memory


def sqlite_engine() -> fx.Layer[Any, Any, Any]:
    """``single_runner`` on a fresh SQLite ``:memory:`` database each build."""
    client = sqlite.make(sqlite.SqliteClientConfig(filename=":memory:"))
    sql = fx.layer.effect(SqlClient, client).pipe(fx.layer.provide(reactivity.layer))
    return cluster_workflow_engine.layer.pipe(
        fx.layer.provide_merge(single_runner.layer(runner_storage_kind="memory"))
    ).pipe(fx.layer.provide_merge(sql))


# The crash sweep -------------------------------------------------------------------------

TURNS = 100
STEPS = 2 * TURNS + 1
"""A model request a turn, a tool call a turn, and the request that ends with "done"."""


@dataclass(frozen=True)
class Seen:
    """What one run of a sweep left: its exit, and how often each step ran."""

    exit: fx.Exit[str, Any]
    model: dict[int, int]
    tool: dict[int, int]

    def repeated(self) -> list[str]:
        return [f"model {t}" for t, n in self.model.items() if n > 1] + [
            f"tool {t}" for t, n in self.tool.items() if n > 1
        ]


def step_of(activity: str) -> str:
    """``pyfect/ai/3/model`` is model turn 2 (two tool results before it); ``.../tool/1``
    the tool call of turn 2."""
    parts = activity.split("/")
    turn = int(parts[2]) - 1
    return f"model {turn}" if parts[3] == "model" else f"tool {turn}"


def sweep(
    engine: fx.Layer[Any, Any, Any], step: int, stored: bool | None = None
) -> fx.Effect[None, Any, Any]:
    """Run ``TURNS`` turns, crash after activity ``step`` (before its result is stored,
    after, or both when ``stored`` is ``None``), resume, and check: the run ends with
    "done", every step ran, and only a step cut off before its result was stored ran
    again, once."""
    seen: list[Seen] = []

    def check(ex: fx.Exit[str, Any]) -> fx.Effect[str | None, Any, CallsService]:
        def judge(calls: Calls) -> str | None:
            seen.append(Seen(ex, dict(calls.model), dict(calls.tool)))
            if ex != fx.exit.Success("done"):
                return f"the run ended with {ex}"
            ran = (sorted(calls.model), sorted(calls.tool))
            if ran != (list(range(TURNS + 1)), list(range(TURNS))):
                return "a step never ran"
            return None

        return CallsService().map(judge)

    @fx.gen
    def body():
        report = yield from explore.activity_crashes(
            Agent,
            AgentPayload(turns=TURNS, prompt="go"),
            layer=agent_layer(engine),
            check=check,
            at=[step],
            stored=stored,
        )
        assert len(seen) == len(report.points) == (2 if stored is None else 1)
        for point, run in zip(report.points, seen, strict=True):
            assert run.repeated() == ([] if point.stored else [step_of(point.activity)]), point

    return body
