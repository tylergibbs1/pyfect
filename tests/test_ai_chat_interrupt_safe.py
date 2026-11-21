"""(pyfect) ``chat.interrupt_safe``: a turn cut short still leaves a history the providers
take, keeps the tool results that finished, and ``resume`` finishes it.

Other frameworks leave a tool call without its result after a cancel, or throw finished
results away, and every later request is rejected (LangGraph #5672, #6726; OpenAI Agents
SDK #5642, #1061). Effect's ``Chat`` records a turn only when the call succeeds, so the
results of tools that finished are lost; it stays that way (``tests/oracle/test_ai_chat.py``).

The model asks for two ``Lookup`` calls; ``a`` finishes after a few yields, ``b`` after
more. Each turn is interrupted at every point it gives the scheduler a turn (as
``test_decided_results.py`` does), and the history left is checked by building the next
request through the Anthropic, OpenAI Responses and Chat Completions encodings
(``_provider_history``).
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from functools import partial
from typing import Any, TypedDict

import pytest
from _provider_history import problems

import pyfect as fx
from pyfect import layer
from pyfect import schema as S
from pyfect.ai import chat as C
from pyfect.ai import language_model as lm
from pyfect.ai import prompt as P
from pyfect.ai import response as R
from pyfect.ai import tool, tool_ledger, toolkit
from pyfect.duration import Duration
from pyfect.persistence import persistence
from pyfect.scheduler import Cancel, Scheduler, Task
from pyfect.stream import _constructors as streams


class Key(TypedDict):
    key: str


Lookup = tool.make("Lookup", parameters=S.Struct(Key), success=S.String, failure=S.String)
Tools = toolkit.make(Lookup)

_STEPS = {"a": 1, "b": 3}
_USAGE = {"inputTokens": {"total": 1}, "outputTokens": {"total": 1}}
_PARTS: list[dict[str, object]] = [
    {"type": "text", "text": "Looking both up."},
    {"type": "tool-call", "id": "a", "name": "Lookup", "params": {"key": "a"}},
    {"type": "tool-call", "id": "b", "name": "Lookup", "params": {"key": "b"}},
    {"type": "finish", "reason": "tool-calls", "usage": _USAGE},
]
_STREAMED: list[dict[str, object]] = [
    {"type": "text-start", "id": "t"},
    {"type": "text-delta", "id": "t", "delta": "Looking "},
    {"type": "text-delta", "id": "t", "delta": "both up."},
    {"type": "text-end", "id": "t"},
    *_PARTS[1:],
]


def _value(key: str) -> str:
    return f"value of {key}"


@dataclass
class Handlers:
    """The ``Lookup`` handler: each call yields its key's steps, then returns. ``started``
    and ``finished`` count the runs; a key in ``blocked`` never finishes, a key in
    ``failing`` fails."""

    blocked: set[str] = field(default_factory=set[str])
    failing: set[str] = field(default_factory=set[str])
    started: Counter[str] = field(default_factory=Counter[str])
    finished: Counter[str] = field(default_factory=Counter[str])

    def run(self, key: str) -> fx.Effect[str, str]:
        def start() -> None:
            self.started[key] += 1

        def finish() -> str:
            self.finished[key] += 1
            return _value(key)

        steps = fx.for_each(range(_STEPS[key]), lambda _: fx.yield_now())
        body = fx.sync(start).and_then(steps)
        if key in self.blocked:
            return body.and_then(fx.never)
        if key in self.failing:
            return body.and_then(fx.fail(f"{key} failed"))
        return body.and_then(fx.sync(finish))

    @property
    def layer(self) -> fx.Layer[Any]:
        return Tools.to_layer(Lookup.handler(lambda params, _ctx: self.run(params["key"])))


Model = fx.layer.effect(
    lm.LanguageModel,
    lm.make(
        generate_text=lambda _: fx.succeed(_PARTS),
        stream_text=lambda _: streams.from_iterable(_STREAMED).rechunk(1),
    ),
)

type Turn = Callable[[C.Service], fx.Effect[Any, Any, Any]]


def _generate(chat: C.Service) -> fx.Effect[Any, Any, Any]:
    return chat.generate_text("Look up a and b", toolkit=Tools)


def _stream(chat: C.Service) -> fx.Effect[Any, Any, Any]:
    return chat.stream_text("Look up a and b", toolkit=Tools).run_drain()


def _guarded(chat: C.Service) -> fx.Effect[Any, Any, Any]:
    return chat.generate_text(
        "Look up a and b", toolkit=tool_ledger.guard(Tools, on_unknown="tell_model")
    )


def _run[A](eff: fx.Effect[A, Any, Any], handlers: Handlers, ledger: Any = None) -> A:
    provided = eff.pipe(fx.provide(handlers.layer)).pipe(fx.provide(Model))
    if ledger is not None:
        provided = provided.pipe(fx.provide_service(tool_ledger.ToolLedger, ledger))
    return fx.run_blocking(provided.or_die())


# What a history holds --------------------------------------------------------------------


def _results(history: P.Prompt) -> dict[str, object]:
    """Each tool result by call id: its value, ``"unfinished"`` for a stand-in, or the
    ``_tag`` of a failure."""
    found: dict[str, object] = {}
    for message in history.content:
        if not isinstance(message, P.ToolMessage):
            continue
        for part in message.content:
            if not isinstance(part, P.ToolResultPart):
                continue
            result: Any = part.result
            match result:
                case {"type": "execution-interrupted"}:
                    found[part.id] = "unfinished"
                case {"_tag": tag}:
                    found[part.id] = tag
                case _:
                    found[part.id] = result
    return found


def _stage(history: P.Prompt) -> str:
    """How far the turn got before the interrupt."""
    if not history.content:
        return "not started"
    results = _results(history)
    if not any(isinstance(m, P.AssistantMessage) for m in history.content):
        return "prompt only"
    return " ".join(f"{id}={results.get(id, '-')}" for id in ("a", "b"))


# Interrupted at every yield ----------------------------------------------------------------


class _InterruptAt:
    """The run's scheduler, except that the ``at``-th task it schedules is preceded by an
    interrupt of ``target`` (as in ``test_decided_results.py``)."""

    def __init__(self, inner: Scheduler, at: int) -> None:
        self.inner = inner
        self.at = at
        self.seen = 0
        self.target: fx.Fiber[Any, Any] | None = None
        self.fired = False

    def schedule(self, task: Task, priority: int = 0) -> None:
        self.seen += 1
        target = self.target
        if self.seen == self.at and target is not None:
            self.fired = True
            self.inner.schedule(lambda: target.interrupt_as_unsafe(None))
        self.inner.schedule(task)

    def call_later(self, delay: Duration, task: Task, *, daemon: bool = False) -> Cancel:
        return self.inner.call_later(delay, task, daemon=daemon)

    def track(self, tracker: Any, f: Callable[[], None]) -> None:
        self.inner.track(tracker, f)

    def outside_work(self) -> Any:
        return self.inner.outside_work()


def _interrupted(chat: C.Service, turn: Turn, at: int, budget: int) -> fx.Effect[bool, Any, Any]:
    """Run ``turn`` on ``chat``, interrupted before the ``at``-th task the run schedules;
    whether the interrupt fired (it does not once ``at`` is past the turn's last task)."""

    def under(inner: Scheduler) -> fx.Effect[bool, Any, Any]:
        sched = _InterruptAt(inner, at)

        @fx.gen
        def program():
            target = (
                yield from turn(chat)
                .pipe(fx.provide_service(fx.MaxOpsBeforeYield, budget))
                .pipe(fx.provide_service(fx.CurrentScheduler, sched))
                .fork()
            )
            sched.target = target
            yield from target.await_exit()
            return sched.fired

        return fx.scoped(program)

    return fx.CurrentScheduler().flat_map(under)


@dataclass
class _Point:
    history: P.Prompt
    handlers: Handlers
    ledger: tool_ledger.ToolLedgerService
    chat: C.InterruptSafe


def _attempt(turn: Turn, at: int, budget: int) -> Any:
    chat = C.interrupt_safe((yield from C.empty))
    fired = yield from _interrupted(chat, turn, at, budget)
    return chat, fired, (yield from chat.history.get())


def _sweep(turn: Turn, budget: int, half: int | None = None) -> list[_Point]:
    """``turn`` on a new interrupt-safe chat, interrupted at each point in turn (with
    ``half``, at every other point, starting from the first or the second)."""
    points: list[_Point] = []
    step = 1 if half is None else 2
    at = 0 if half is None else half - step
    while True:
        at += step
        handlers, ledger = Handlers(), tool_ledger.memory()

        attempt = fx.gen(partial(_attempt, turn, at, budget))
        chat, fired, history = _run(attempt, handlers, ledger)
        points.append(_Point(history, handlers, ledger, chat))
        if not fired:
            return points


_BUDGETS = [1, 7, 64]
# (budget, half): the sweep with a budget of one step has the most points, so it runs in
# two halves, to keep each test well inside the time limit.
_SWEEPS = [(1, 1), (1, 2), (7, None), (64, None)]


@pytest.mark.parametrize(("budget", "half"), _SWEEPS)
@pytest.mark.parametrize("turn", [_generate, _stream], ids=["generate_text", "stream_text"])
def test_a_turn_interrupted_at_every_yield_leaves_a_valid_history(
    turn: Turn, budget: int, half: int | None
):
    points = _sweep(turn, budget, half)
    found = {at: problems(p.history) for at, p in enumerate(points, 1)}
    assert {at: problem for at, problem in found.items() if problem} == {}
    # Every result kept is the handler's own value, and a handler that never finished
    # has none: a stand-in only says the call did not finish.
    for point in points:
        for id, result in _results(point.history).items():
            assert result in (_value(id), "unfinished")
            if point.handlers.finished[id] == 0:
                assert result == "unfinished"
    # The sweep reached every stage of the turn (with a budget of one step, also those
    # before the response is in).
    stages = {_stage(p.history) for p in points}
    early = {"not started", "prompt only"} if budget == 1 else set[str]()
    assert (
        early
        | {
            "a=unfinished b=unfinished",
            f"a={_value('a')} b=unfinished",
            f"a={_value('a')} b={_value('b')}",
        }
        <= stages
    )


# Finished results survive ------------------------------------------------------------------


def _cut_after_a(chat: C.Service, turn: Turn) -> fx.Effect[None, Any, Any]:
    """Run ``turn`` until ``a``'s result is in, then interrupt it (``b`` never finishes)."""

    @fx.gen
    def program():
        fiber = yield from turn(chat).fork()
        for _ in range(50):
            yield from fx.yield_now()
        yield from fiber.interrupt()

    return program


@pytest.mark.parametrize("turn", [_generate, _stream], ids=["generate_text", "stream_text"])
def test_an_interrupted_turn_keeps_the_results_that_finished(turn: Turn):
    handlers = Handlers(blocked={"b"})

    @fx.gen
    def program():
        chat = C.interrupt_safe((yield from C.empty))
        yield from _cut_after_a(chat, turn)
        return (yield from chat.history.get())

    history = _run(program, handlers)
    assert handlers.finished == Counter({"a": 1})
    assert problems(history) == []
    assert _results(history) == {"a": _value("a"), "b": "unfinished"}
    user, assistant, results = history.content
    assert user == P.make("Look up a and b").content[0]
    assert isinstance(assistant, P.AssistantMessage)
    assert [type(p).__name__ for p in assistant.content] == [
        "TextPart",
        "ToolCallPart",
        "ToolCallPart",
    ]
    assert isinstance(results, P.ToolMessage)


@pytest.mark.parametrize("turn", [_generate, _stream], ids=["generate_text", "stream_text"])
def test_effects_chat_still_records_only_a_finished_turn(turn: Turn):
    """The hole interrupt_safe closes: Effect's chat drops ``a``'s finished result (and,
    streaming, keeps ``b``'s call without one)."""
    handlers = Handlers(blocked={"b"})

    @fx.gen
    def program():
        chat = yield from C.empty
        yield from _cut_after_a(chat, turn)
        return (yield from chat.history.get())

    history = _run(program, handlers)
    assert handlers.finished == Counter({"a": 1})
    assert problems(history) != [] or "a" not in _results(history)


def test_a_failed_turn_commits_too():
    handlers = Handlers(failing={"b"})

    @fx.gen
    def program():
        chat = C.interrupt_safe((yield from C.empty))
        failed = yield from _generate(chat).flip()
        return failed, (yield from chat.history.get())

    failed, history = _run(program, handlers)
    assert failed == "b failed"
    assert problems(history) == []
    assert _results(history) == {"a": _value("a"), "b": "unfinished"}


def test_a_finished_turn_is_recorded_as_effects_chat_records_it():
    @fx.gen
    def program():
        safe = C.interrupt_safe((yield from C.empty))
        plain = yield from C.empty
        yield from _generate(safe)
        yield from _generate(plain)
        return (yield from safe.history.get()), (yield from plain.history.get())

    safe, plain = _run(program, Handlers())
    assert safe == plain
    assert problems(safe) == []


# Resuming ------------------------------------------------------------------------------------


def test_resume_runs_the_unfinished_calls_and_keeps_the_finished_ones():
    handlers = Handlers(blocked={"b"})

    @fx.gen
    def program():
        chat = C.interrupt_safe((yield from C.empty))
        yield from _cut_after_a(chat, _generate)
        handlers.blocked.clear()
        resumed = yield from chat.resume(toolkit=Tools)
        again = yield from chat.resume(toolkit=Tools)
        return resumed, again, (yield from chat.history.get())

    resumed, again, history = _run(program, handlers)
    assert [(r.id, r.result) for r in resumed if not isinstance(r, R.ToolApprovalRequestPart)] == [
        ("b", _value("b"))
    ]
    assert again == ()
    assert handlers.started == Counter({"a": 1, "b": 2})
    assert handlers.finished == Counter({"a": 1, "b": 1})
    assert _results(history) == {"a": _value("a"), "b": _value("b")}
    assert problems(history) == []


@pytest.mark.parametrize("budget", _BUDGETS)
def test_with_the_ledger_a_resumed_turn_runs_no_tool_twice(budget: int):
    """Each point: interrupt the guarded turn there, then resume it with the guarded
    toolkit over the same ledger. No handler starts twice, no finished result is lost,
    and every call ends with its value or ``ToolOutcomeUnknown``."""
    guarded = tool_ledger.guard(Tools, on_unknown="tell_model")
    outcomes: Counter[str] = Counter()
    for point in _sweep(_guarded, budget):
        before = _results(point.history)
        _run(point.chat.resume(toolkit=guarded), point.handlers, point.ledger)
        history = _run(point.chat.history.get(), point.handlers)
        after = _results(history)
        assert problems(history) == []
        assert max(point.handlers.started.values(), default=0) <= 1
        for id, result in before.items():
            if result != "unfinished":
                assert after[id] == result
        assert set(after.values()) <= {_value("a"), _value("b"), "ToolOutcomeUnknown"}
        outcomes.update(f"{id}={result}" for id, result in after.items())
    # The resume both ran calls that had not started and reported ones cut short.
    assert outcomes[f"b={_value('b')}"] > 0
    assert outcomes["b=ToolOutcomeUnknown"] > 0


# Persistence, export and import ---------------------------------------------------------------


def test_an_interrupted_turn_is_saved_and_resumes_after_reopening():
    handlers = Handlers(blocked={"b"})
    chats_layer = C.layer_persisted(store_id="chat").pipe(
        layer.provide_merge(persistence.layer_backing_memory)
    )

    @fx.gen
    def program():
        chats = yield from C.Persistence()
        chat = C.interrupt_safe((yield from chats.get_or_create("1")))
        yield from _cut_after_a(chat, _generate)
        saved = (yield from chats.get("1")).history
        stored = yield from saved.get()
        assert stored == (yield from chat.history.get())
        handlers.blocked.clear()
        reopened = C.interrupt_safe((yield from chats.get("1")))
        yield from reopened.resume(toolkit=Tools)
        return stored, (yield from (yield from chats.get("1")).history.get())

    stored, resumed = _run(program.pipe(fx.provide(chats_layer)), handlers)
    assert problems(stored) == []
    assert _results(stored) == {"a": _value("a"), "b": "unfinished"}
    assert _results(resumed) == {"a": _value("a"), "b": _value("b")}
    assert problems(resumed) == []


def test_an_interrupted_turn_round_trips_through_export_json():
    handlers = Handlers(blocked={"b"})

    @fx.gen
    def program():
        chat = C.interrupt_safe((yield from C.empty))
        yield from _cut_after_a(chat, _generate)
        text = yield from chat.export_json
        handlers.blocked.clear()
        restored = C.interrupt_safe((yield from C.from_json(json.dumps(json.loads(text)))))
        assert (yield from restored.history.get()) == (yield from chat.history.get())
        yield from restored.resume(toolkit=Tools)
        return (yield from restored.history.get())

    history = _run(program, handlers)
    assert _results(history) == {"a": _value("a"), "b": _value("b")}


def test_stream_parts_still_reach_the_caller():
    @fx.gen
    def program():
        chat = C.interrupt_safe((yield from C.empty))
        parts = yield from chat.stream_text("Look up a and b", toolkit=Tools).run_collect()
        return [p.type for p in parts]

    assert _run(program, Handlers()).count("tool-result") == 2
