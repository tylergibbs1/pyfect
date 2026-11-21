"""``pyfect.ai.budget``: run-wide limits that hold when calls run in parallel or nest.

The two scenarios other agent frameworks overshoot on, ported: PydanticAI #9255 (a limit
of 9 tool calls, 8 parallel delegations, "COMPLETED tool_calls=16") and #11918 (a nested
agent escapes its parent's limits)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from decimal import Decimal
from typing import Any, Never, TypedDict, cast

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.ai import budget, prompt
from pyfect.ai import language_model as lm
from pyfect.ai import tool as T
from pyfect.ai import toolkit as K
from pyfect.ai.ai_error import AiError, UnknownError
from pyfect.context import Reference, Tag
from pyfect.stream import _constructors as streams


class Task(TypedDict):
    task: str


Delegate = T.make("Delegate", parameters=S.Struct(Task), success=S.String)
Work = T.make("Work", parameters=S.Struct(Task), success=S.String)
PARENT_KIT = K.make(Delegate)
CHILD_KIT = K.make(Work)


def usage(input_tokens: int, output_tokens: int) -> dict[str, Any]:
    return {"inputTokens": {"total": input_tokens}, "outputTokens": {"total": output_tokens}}


def finish(input_tokens: int = 10, output_tokens: int = 5, reason: str = "stop") -> lm.EncodedPart:
    return {"type": "finish", "reason": reason, "usage": usage(input_tokens, output_tokens)}


def call(id: str, name: str) -> lm.EncodedPart:
    return {"type": "tool-call", "id": id, "name": name, "params": {"task": id}}


def answered(options: lm.ProviderOptions) -> bool:
    return any(message.role == "tool" for message in options.prompt.content)


def agents(options: lm.ProviderOptions) -> Sequence[lm.EncodedPart]:
    """The parent delegates to 8 agents in one response; each agent calls ``Work`` once."""
    if answered(options):
        return [{"type": "text", "text": "done"}, finish()]
    names = [tool.name for tool in options.tools]
    if "Delegate" in names:
        return [*(call(f"d{i}", "Delegate") for i in range(8)), finish(reason="tool-calls")]
    return [call("w", "Work"), finish(reason="tool-calls")]


def model(
    generate: Callable[[lm.ProviderOptions], Any],
    stream: Callable[[lm.ProviderOptions], Any] = lambda _: streams.empty,
) -> fx.Layer[lm.LanguageModel]:
    def generated(options: lm.ProviderOptions) -> fx.Effect[Any, Any, Any]:
        result: object = generate(options)
        if isinstance(result, fx.Effect):
            return cast("fx.Effect[Any, Any, Any]", result)
        return fx.succeed(result)

    return fx.layer.effect(lm.LanguageModel, lm.make(generate_text=generated, stream_text=stream))


FIXED = budget.Limits(total_tokens=1_000, max_output_tokens=100, estimate_input_tokens=lambda _: 50)
"""Each request reserves 50 input and 100 output tokens."""


# Inheritance ---------------------------------------------------------------------------


class Service(Tag[str], key="test/budget/Service"):
    pass


class Level(Reference[int], key="test/budget/Level"):
    @classmethod
    def default(cls) -> int:
        return 0


@testing.effect
def test_forked_fibers_inherit_services_and_references():
    """As in Effect v4, a fiber forks with its parent's context: services and References
    reach forked fibers, ``fx.all`` and ``for_each`` branches, and their own forks."""

    def nested() -> fx.Effect[tuple[str, int], Never, Service]:
        both = Service().zip(Level())
        return both.fork().flat_map(lambda f: f.join()).fork().flat_map(lambda f: f.join())

    seen = yield from (
        fx.all([nested(), nested()], concurrency="unbounded")
        .zip(fx.for_each(range(3), lambda _: nested(), concurrency=3))
        .pipe(fx.provide_service(Service, "s"))
        .pipe(fx.provide_service(Level, 7))
    )
    assert seen == ([("s", 7)] * 2, [("s", 7)] * 3)


# PydanticAI #9255 and #11918 -------------------------------------------------------------


@testing.effect
def test_parallel_delegations_never_run_more_tool_calls_than_the_limit():
    """PydanticAI #9255: ``tool_calls_limit=9`` with 8 parallel delegations, each agent
    making a call, completed with 16 tool calls. Each call reserves before its handler
    runs, so at most 9 handlers start and the run fails with ``BudgetExceeded``; the
    siblings still running are interrupted and their finalizers run. Run without a
    budget, the same agents make the 16 calls (next test)."""
    started: list[str] = []
    finalized: list[str] = []

    def delegate(params: Task, _: Any) -> fx.Effect[str, Any, Any]:
        sub_agent = lm.generate_text(params["task"], toolkit=CHILD_KIT).map(lambda r: r.text)
        return fx.sync(lambda: started.append("Delegate")).and_then(sub_agent)

    def work(params: Task, _: Any) -> fx.Effect[str]:
        return fx.sync(lambda: started.append("Work")).and_then(fx.never)

    def finalized_delegate(params: Task, context: Any) -> fx.Effect[str, Any, Any]:
        return delegate(params, context).ensuring(fx.sync(lambda: finalized.append("d")))

    handlers = fx.layer.merge(
        PARENT_KIT.to_layer(Delegate.handler(finalized_delegate)),
        CHILD_KIT.to_layer(Work.handler(work)),
    )
    shared = yield from budget.make(budget.Limits(tool_calls=9))
    error = yield from (
        lm.generate_text("split the work", toolkit=PARENT_KIT)
        .pipe(budget.provide(shared))
        .pipe(fx.provide(handlers))
        .pipe(fx.provide(model(agents)))
        .flip()
    )
    spent = yield from shared.spent()
    assert isinstance(error, budget.BudgetExceeded)
    assert (error.resource, error.limit, error.available) == ("tool_calls", 9, 0)
    # The ninth call is counted; a sibling's failure may interrupt it before its handler.
    assert spent.tool_calls == 9
    assert 8 <= len(started) <= 9
    assert started.count("Delegate") == 8
    assert finalized == ["d"] * 8


@testing.effect
def test_without_a_budget_the_delegations_make_sixteen_calls():
    """The same run without a budget: the 16 calls PydanticAI reported, all of them."""
    started: list[str] = []

    def run(name: str) -> Callable[[Task, Any], fx.Effect[str, Any, Any]]:
        def handler(params: Task, _: Any) -> fx.Effect[str, Any, Any]:
            record = fx.sync(lambda: started.append(name))
            if name == "Work":
                return record.as_("worked")
            return record.and_then(lm.generate_text(params["task"], toolkit=CHILD_KIT)).map(
                lambda r: r.text
            )

        return handler

    handlers = fx.layer.merge(
        PARENT_KIT.to_layer(Delegate.handler(run("Delegate"))),
        CHILD_KIT.to_layer(Work.handler(run("Work"))),
    )
    yield from (
        lm.generate_text("split the work", toolkit=PARENT_KIT)
        .pipe(fx.provide(handlers))
        .pipe(fx.provide(model(agents)))
    )
    assert len(started) == 16


@testing.effect
def test_a_nested_agent_draws_from_its_parents_budget():
    """PydanticAI #11918: an agent run inside a tool, with a limit and a model of its own,
    still draws from the budget around it: its requests count there, and the parent's
    limit stops it although its own has room."""
    inner = budget.Limits(requests=100)
    other_model = model(lambda _: [finish()])

    def delegate(params: Task, _: Any) -> fx.Effect[str, Any, Any]:
        sub_agent = lm.generate_text(params["task"]).map(lambda r: r.text)
        return sub_agent.pipe(budget.limit(inner)).pipe(fx.provide(other_model))

    handlers = PARENT_KIT.to_layer(Delegate.handler(delegate))
    parent = yield from budget.make(budget.Limits(requests=5))
    error = yield from (
        lm.generate_text("split the work", toolkit=PARENT_KIT, concurrency=1)
        .pipe(budget.provide(parent))
        .pipe(fx.provide(handlers))
        .pipe(fx.provide(model(agents)))
        .flip()
    )
    spent = yield from parent.spent()
    assert isinstance(error, budget.BudgetExceeded)
    assert error.resource == "requests"
    # The parent's own request, then four agents' before the fifth is refused.
    assert spent.requests == 5
    assert spent.tool_calls == 5


@testing.effect
def test_nested_limits_each_hold():
    """A request reserves in every budget around it, or in none: the inner limit refuses
    without charging the outer one."""
    outer = yield from budget.make(budget.Limits(requests=10))
    inner = yield from budget.make(budget.Limits(requests=2))
    one = lm.generate_text("hi")
    error = yield from (
        fx.for_each(range(3), lambda _: one)
        .pipe(budget.provide(inner))
        .pipe(budget.provide(outer))
        .pipe(fx.provide(model(lambda _: [finish()])))
        .flip()
    )
    assert isinstance(error, budget.BudgetExceeded)
    assert ((yield from inner.spent()).requests, (yield from outer.spent()).requests) == (2, 2)


# Reservations --------------------------------------------------------------------------


@testing.effect
def test_settling_refunds_the_unused_reservation():
    """A request holds its worst case while in flight, then spends the response's usage
    and gives back the rest."""
    shared = yield from budget.make(FIXED)
    during: list[budget.Spent] = []

    def generate(_: lm.ProviderOptions) -> fx.Effect[Sequence[lm.EncodedPart]]:
        return shared.held().map(lambda held: (during.append(held), [finish(20, 7)])[1])

    yield from lm.generate_text("hi").pipe(budget.provide(shared)).pipe(fx.provide(model(generate)))
    assert during == [budget.Spent(requests=1, input_tokens=50, output_tokens=100)]
    assert (yield from shared.held()) == budget.Spent()
    assert (yield from shared.spent()) == budget.Spent(requests=1, input_tokens=20, output_tokens=7)


@testing.effect
def test_a_response_without_usage_spends_what_it_reserved():
    shared = yield from budget.make(FIXED)
    yield from (
        lm.generate_text("hi")
        .pipe(budget.provide(shared))
        .pipe(fx.provide(model(lambda _: [{"type": "text", "text": "hi"}])))
    )
    assert (yield from shared.spent()) == budget.Spent(
        requests=1, input_tokens=50, output_tokens=100
    )


@testing.effect
def test_a_failed_call_releases_its_reservation():
    """A provider failure after the reservation gives back its tokens; the request it
    made still counts."""
    shared = yield from budget.make(FIXED)
    failure = AiError(module="Test", method="generate", reason=UnknownError())
    error = yield from (
        lm.generate_text("hi")
        .pipe(budget.provide(shared))
        .pipe(fx.provide(model(lambda _: fx.fail(failure))))
        .flip()
    )
    assert error is failure
    assert (yield from shared.held()) == budget.Spent()
    assert (yield from shared.spent()) == budget.Spent(requests=1)


@testing.effect
def test_an_interrupted_call_releases_its_reservation():
    shared = yield from budget.make(FIXED)
    called = yield from fx.Deferred[None].make()
    request = called.succeed(None).and_then(fx.never)
    fiber = yield from (
        lm.generate_text("hi")
        .pipe(budget.provide(shared))
        .pipe(fx.provide(model(lambda _: request)))
        .fork()
    )
    yield from called.wait()
    assert (yield from shared.held()).total_tokens == 150
    yield from fiber.interrupt()
    assert (yield from shared.held()) == budget.Spent()
    assert (yield from shared.spent()) == budget.Spent(requests=1)


@testing.effect
def test_a_reservation_that_does_not_fit_never_calls_the_provider():
    """The worst case is checked before the request: with 140 tokens left, a request
    reserving 150 fails with ``BudgetExceeded``, which ``catch_tag`` recovers."""
    called: list[str] = []
    limits = budget.Limits(
        total_tokens=140, max_output_tokens=100, estimate_input_tokens=lambda _: 50
    )

    def generate(_: lm.ProviderOptions) -> Sequence[lm.EncodedPart]:
        called.append("request")
        return [finish()]

    error = yield from (
        lm.generate_text("hi").pipe(budget.limit(limits)).pipe(fx.provide(model(generate))).flip()
    )
    assert called == []
    assert isinstance(error, budget.BudgetExceeded)
    assert (error.resource, error.limit, error.requested, error.available) == (
        "total_tokens",
        140,
        150,
        140,
    )
    assert str(error) == "Budget exceeded: total_tokens needs 150, 140 of 140 left"
    recovered = yield from (
        lm.generate_text("hi")
        .map(lambda r: r.text)
        .pipe(budget.limit(limits))
        .pipe(fx.catch_tag(budget.BudgetExceeded, lambda e: fx.succeed(e.resource)))
        .pipe(fx.provide(model(generate)))
    )
    assert recovered == "total_tokens"


@testing.effect
def test_concurrent_requests_never_hold_more_than_the_limit():
    """Eight requests at once against room for three worst cases: three run, and what is
    spent or held never passes the limit."""
    limits = budget.Limits(
        total_tokens=450, max_output_tokens=100, estimate_input_tokens=lambda _: 50
    )
    shared = yield from budget.make(limits)
    gate = yield from fx.Deferred[None].make()
    peak: list[int] = []

    def generate(_: lm.ProviderOptions) -> fx.Effect[Sequence[lm.EncodedPart]]:
        held = shared.held().zip(shared.spent())
        observe = held.map(lambda hs: peak.append(hs[0].total_tokens + hs[1].total_tokens))
        return observe.and_then(gate.wait()).as_([finish(50, 100)])

    one = lm.generate_text("hi").exit()
    fibers = yield from (
        fx.all([one] * 8, concurrency="unbounded")
        .pipe(budget.provide(shared))
        .pipe(fx.provide(model(generate)))
        .fork()
    )
    yield from fx.yield_now()
    yield from gate.succeed(None)
    exits = yield from fibers.join()
    assert sum(isinstance(ex, fx.Success) for ex in exits) == 3
    assert max(peak) <= 450
    assert (yield from shared.spent()).total_tokens == 450


@testing.effect
def test_a_cost_limit_reserves_the_worst_case_price():
    def price(tokens: budget.Tokens) -> Decimal:
        return tokens.input * Decimal("0.01") + tokens.output * Decimal("0.03")

    limits = budget.Limits(
        cost=budget.Cost(Decimal(4), price),
        max_output_tokens=100,
        estimate_input_tokens=lambda _: 50,
    )
    shared = yield from budget.make(limits)
    one = lm.generate_text("hi")
    error = yield from (
        fx.for_each(range(3), lambda _: one)
        .pipe(budget.provide(shared))
        .pipe(fx.provide(model(lambda _: [finish(10, 10)])))
        .flip()
    )
    # A request reserves 3.50 and spends 0.40: two fit, the third would hold 4.30.
    spent = yield from shared.spent()
    assert spent.cost == Decimal("0.80")
    assert isinstance(error, budget.BudgetExceeded)
    assert (error.resource, error.requested) == ("cost", Decimal("3.50"))


@testing.effect
def test_a_stream_settles_from_its_finish_part():
    shared = yield from budget.make(FIXED)
    held: list[budget.Spent] = []

    def stream(_: lm.ProviderOptions) -> Any:
        observe = streams.from_effect(shared.held().map(held.append)).drain()
        return observe.concat(
            streams.make({"type": "text-delta", "id": "t", "delta": "hi"}, finish(30, 3))
        )

    yield from (
        lm.stream_text("hi")
        .run_drain()
        .pipe(budget.provide(shared))
        .pipe(fx.provide(model(lambda _: [], stream)))
    )
    assert held == [budget.Spent(requests=1, input_tokens=50, output_tokens=100)]
    assert (yield from shared.held()) == budget.Spent()
    assert (yield from shared.spent()) == budget.Spent(requests=1, input_tokens=30, output_tokens=3)


@testing.effect
def test_a_failed_stream_releases_its_reservation():
    shared = yield from budget.make(FIXED)
    failure = AiError(module="Test", method="stream", reason=UnknownError())
    error = yield from (
        lm.stream_text("hi")
        .run_drain()
        .pipe(budget.provide(shared))
        .pipe(fx.provide(model(lambda _: [], lambda _: streams.fail(failure))))
        .flip()
    )
    assert error is failure
    assert (yield from shared.held()) == budget.Spent()
    assert (yield from shared.spent()) == budget.Spent(requests=1)


@pytest.mark.parametrize(
    ("limits", "message"),
    [
        (lambda: budget.Limits(tool_calls=-1), "Limits.tool_calls must not be negative, got -1"),
        (
            lambda: budget.Limits(output_tokens=10),
            (
                "Limits.max_output_tokens must be set (to the provider's max_tokens) with a "
                "limit on output tokens, total tokens or cost"
            ),
        ),
        (
            lambda: budget.Limits(cost=budget.Cost(Decimal(-1), lambda _: Decimal(0))),
            "Limits.cost.limit must not be negative, got -1",
        ),
    ],
)
def test_limits_are_checked_when_made(limits: Callable[[], budget.Limits], message: str):
    with pytest.raises(ValueError, match="^" + message.replace("(", r"\(").replace(")", r"\)")):
        limits()


def test_the_default_estimate_counts_a_token_per_four_characters():
    options = lm.ProviderOptions(prompt.make("x" * 9))
    assert budget.estimate_input_tokens(options) == 3
