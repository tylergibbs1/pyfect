"""(pyfect) ``tool_ledger.guard``: a replayed tool call runs its handler at most once, or the
caller is told the outcome is unknown.

Other agent frameworks run a non-idempotent tool again after a crash, a retry or a resume
(PydanticAI #10926: "the tool runs again, so 2 payments"). ``_tool_ledger_scenario`` has the
payment tool; the turn is crashed at every step boundary, by an interrupt at each yield and
by ending the process (a fresh runtime then replays it over the same SQLite ledger).
"""

from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Never

import pytest
from _subprocess import SUBPROCESS_TIMEOUT
from _tool_ledger_scenario import (
    CALL_ID,
    CRASH_POINTS,
    Model,
    Pay,
    Payment,
    Receipt,
    Tools,
    pay,
    payments,
    sqlite_ledger,
    turn,
)

import pyfect as fx
from pyfect import schema as S
from pyfect import stream
from pyfect.ai import chat, language_model, response, tool, tool_ledger, toolkit
from pyfect.ai import prompt as P
from pyfect.ai.language_model import LanguageModel, ProviderOptions
from pyfect.duration import Duration
from pyfect.exit import Failure, Success
from pyfect.result import Ok
from pyfect.scheduler import Cancel, Scheduler, Task

_SCENARIO = Path(__file__).parent / "_tool_ledger_scenario.py"
_USAGE = {"inputTokens": {"total": 1}, "outputTokens": {"total": 1}}


def _blocking[A](eff: fx.Effect[A, Any, Never]) -> A:
    return fx.run_blocking(eff.or_die())


def _run[A](
    eff: fx.Effect[A, Any, Any],
    ledger: tool_ledger.ToolLedgerService,
    bank: Path,
    run: str = "replay",
) -> A:
    return _blocking(
        eff.pipe(fx.provide_service(tool_ledger.ToolLedger, ledger))
        .pipe(fx.provide(pay(bank, run)))
        .pipe(fx.provide(Model))
    )


def _is_receipt(part: object) -> bool:
    value: object = getattr(part, "result", None)
    return isinstance(part, response.ToolResultSuccess) and value == {"receipt": "r-5"}


def _is_unknown(part: object) -> bool:
    value: object = getattr(part, "result", None)
    return isinstance(part, response.ToolResultFailure) and isinstance(
        value, tool_ledger.ToolOutcomeUnknown
    )


def test_an_unguarded_replay_pays_again(tmp_path: Path):
    """The hole: without the ledger, replaying the turn runs the payment again."""
    bank = tmp_path / "bank"
    unguarded = language_model.generate_text("Pay 5", toolkit=Tools)
    program = unguarded.pipe(fx.provide(pay(bank, "run"))).pipe(fx.provide(Model))
    _blocking(program)
    _blocking(program)
    assert len(payments(bank)) == 2


def test_a_replayed_call_returns_the_recorded_result_without_running(tmp_path: Path):
    bank = tmp_path / "bank"
    ledger = tool_ledger.memory()
    first = _run(turn(), ledger, bank)
    second = _run(turn(), ledger, bank)
    assert payments(bank) == ["replay 5"]
    assert [_is_receipt(r) for r in first + second] == [True, True]
    assert second[0].encoded_result == first[0].encoded_result


# Interrupted at every yield ------------------------------------------------------------


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


def _interrupted_at(at: int, budget: int, ledger: tool_ledger.ToolLedgerService, bank: Path):
    """Run the turn, interrupted before the ``at``-th task the run schedules; whether the
    interrupt fired (it does not once ``at`` is past the run's last task)."""

    def under(inner: Scheduler) -> fx.Effect[bool, Any, Any]:
        sched = _InterruptAt(inner, at)

        @fx.gen
        def program():
            target = (
                yield from turn()
                .pipe(fx.provide_service(fx.MaxOpsBeforeYield, budget))
                .pipe(fx.provide_service(fx.CurrentScheduler, sched))
                .fork()
            )
            sched.target = target
            yield from target.await_exit()
            return sched.fired

        return fx.scoped(program)

    return _run(fx.CurrentScheduler().flat_map(under), ledger, bank, "interrupted")


_OUTCOMES = {
    # (payments, what the replay got): what the interrupt landed before
    ((), "receipt"): "the call began: the replay runs it",
    ((), "unknown"): "the handler ran: the replay may not run it, and says so",
    (("interrupted 5",), "unknown"): "the result was recorded: the replay says so",
    (("interrupted 5",), "receipt"): "nothing: the replay returns the recorded result",
}


@pytest.mark.parametrize("budget", [1, 7, 64])
def test_a_turn_interrupted_at_every_yield_pays_at_most_once(tmp_path: Path, budget: int):
    """Each point: interrupt the turn there, then replay it over the same ledger. The
    payment runs at most once, and a replay that cannot know gets ``ToolOutcomeUnknown``."""
    seen: dict[int, tuple[tuple[str, ...], str]] = {}
    at = 0
    while True:
        at += 1
        bank = tmp_path / f"bank-{at}"
        ledger = tool_ledger.memory()
        fired = _interrupted_at(at, budget, ledger, bank)
        [result] = _run(turn(), ledger, bank)
        paid = tuple(p for p in payments(bank) if p != "replay 5")
        got = "receipt" if _is_receipt(result) else "unknown" if _is_unknown(result) else "?"
        seen[at] = (paid, got)
        if payments(bank) == [*paid, "replay 5"]:
            seen[at] = (paid, "ran on replay" if got == "receipt" else got)
        if not fired:
            break
    allowed = {((), "ran on replay"), *(k for k in _OUTCOMES if k != ((), "receipt"))}
    assert {at: s for at, s in seen.items() if s not in allowed} == {}
    # The sweep reached every stage: before the claim, between the claim and the payment,
    # after the payment, and after the record.
    assert set(seen.values()) == allowed


# The process dies at every step boundary -----------------------------------------------


@pytest.mark.parametrize("point", CRASH_POINTS)
def test_a_turn_whose_process_dies_at_every_step_pays_at_most_once(tmp_path: Path, point: str):
    db, bank = tmp_path / "ledger.db", tmp_path / "bank"
    died = subprocess.run(
        [sys.executable, str(_SCENARIO), str(db), str(bank), point],
        capture_output=True,
        text=True,
        check=False,
        timeout=SUBPROCESS_TIMEOUT,
    )
    assert died.returncode == 3, died.stderr
    # A fresh runtime over the same store.
    program = turn().pipe(fx.provide(sqlite_ledger(db)))
    [result] = _blocking(program.pipe(fx.provide(pay(bank, "replay"))).pipe(fx.provide(Model)))
    outcomes: dict[str, tuple[list[str], str]] = {
        "before_begin": (["replay 5"], "receipt"),
        "after_begin": ([], "unknown"),
        "after_payment": (["crashed 5"], "unknown"),
        "before_complete": (["crashed 5"], "unknown"),
        "after_complete": (["crashed 5"], "receipt"),
        "end": (["crashed 5"], "receipt"),
    }
    assert (payments(bank), "receipt" if _is_receipt(result) else "unknown") == outcomes[point]
    assert _is_receipt(result) or _is_unknown(result)


# Idempotent and read-only tools run again ------------------------------------------------


def _started(ledger: tool_ledger.ToolLedgerService, name: str) -> None:
    """``CALL_ID`` was started by a run that died before recording a result."""
    assert isinstance(_blocking(ledger.begin(CALL_ID, name)), tool_ledger.Claimed)


@pytest.mark.parametrize("annotation", [tool.Idempotent, tool.Readonly])
def test_an_idempotent_or_readonly_tool_runs_again(tmp_path: Path, annotation: Any):
    bank = tmp_path / "bank"
    safe = Pay.annotate(annotation, True)
    kit = toolkit.make(safe)
    handlers = kit.to_layer(
        safe.handler(lambda params, _ctx: fx.sync(lambda: _paid(bank, params["amount"])))
    )
    ledger = tool_ledger.memory()
    _started(ledger, "Pay")
    guarded = tool_ledger.guard(kit, on_unknown="fail")
    reply = _blocking(
        language_model.generate_text("Pay 5", toolkit=guarded)
        .pipe(fx.provide_service(tool_ledger.ToolLedger, ledger))
        .pipe(fx.provide(handlers))
        .pipe(fx.provide(Model))
    )
    assert payments(bank) == ["rerun 5"]
    assert [_is_receipt(r) for r in reply.tool_results] == [True]
    recorded = _blocking(ledger.lookup(CALL_ID))
    assert isinstance(recorded, tool_ledger.Completed)


def _paid(bank: Path, amount: int) -> Any:
    with bank.open("a") as out:
        out.write(f"rerun {amount}\n")
    return {"receipt": f"r-{amount}"}


# The unknown outcome -------------------------------------------------------------------


def test_fail_makes_an_unknown_outcome_a_typed_error(tmp_path: Path):
    bank = tmp_path / "bank"
    ledger = tool_ledger.memory()
    _started(ledger, "Pay")
    guarded = tool_ledger.guard(Tools, on_unknown="fail")
    exit = _run(language_model.generate_text("Pay 5", toolkit=guarded).exit(), ledger, bank)
    assert isinstance(exit, Failure)
    unknown = tool_ledger.ToolOutcomeUnknown(tool_call_id=CALL_ID, tool_name="Pay")
    assert exit.cause.find_error() == Ok(unknown)
    assert payments(bank) == []


def test_an_unknown_outcome_reaches_the_model_as_a_valid_tool_result(tmp_path: Path):
    """The model gets a failed result for the call; the next request's history pairs it
    with the call, and the chat's history still encodes."""
    bank = tmp_path / "bank"
    ledger = tool_ledger.memory()
    _started(ledger, "Pay")
    prompts: list[P.Prompt] = []
    replies: list[list[dict[str, object]]] = [
        [{"type": "tool-call", "id": CALL_ID, "name": "Pay", "params": {"amount": 5}}],
        [{"type": "text", "text": "I could not confirm the payment."}],
    ]

    def answer(options: ProviderOptions) -> fx.Effect[list[dict[str, object]]]:
        prompts.append(options.prompt)
        finish: dict[str, object] = {"type": "finish", "reason": "stop", "usage": _USAGE}
        return fx.succeed([*replies[len(prompts) - 1], finish])

    model = fx.layer.effect(
        LanguageModel, language_model.make(generate_text=answer, stream_text=lambda _: stream.empty)
    )
    guarded = tool_ledger.guard(Tools, on_unknown="tell_model")

    @fx.gen
    def program():
        session = yield from chat.empty
        first = yield from session.generate_text("Pay 5", toolkit=guarded)
        yield from session.generate_text("Did it go through?", toolkit=guarded)
        return first, (yield from session.export)

    first, exported = _blocking(
        program.pipe(fx.provide_service(tool_ledger.ToolLedger, ledger))
        .pipe(fx.provide(pay(bank, "run")))
        .pipe(fx.provide(model))
    )
    [result] = first.tool_results
    assert _is_unknown(result)
    assert result.encoded_result == {
        "_tag": "ToolOutcomeUnknown",
        "toolCallId": CALL_ID,
        "toolName": "Pay",
        "description": tool_ledger.ToolOutcomeUnknown(
            tool_call_id=CALL_ID, tool_name="Pay"
        ).description,
    }
    # The next request sends the call, then its result: a history providers accept.
    sent = [(type(part).__name__, part.id) for part in _tool_parts(prompts[1])]
    assert sent == [("ToolCallPart", CALL_ID), ("ToolResultPart", CALL_ID)]
    # The history encodes (the chat's export) and decodes again.
    again = _blocking(chat.from_export(exported).flat_map(lambda c: c.history.get()))
    assert _tool_parts(again) == _tool_parts(prompts[1])
    assert payments(bank) == []


def _tool_parts(prompt: P.Prompt) -> list[P.ToolCallPart | P.ToolResultPart]:
    return [
        part
        for message in prompt.content
        if isinstance(message, P.AssistantMessage | P.ToolMessage)
        for part in message.content
        if isinstance(part, P.ToolCallPart | P.ToolResultPart)
    ]


# Failures are outcomes too ---------------------------------------------------------------


@pytest.mark.parametrize("mode", ["error", "return"])
def test_a_recorded_failure_is_replayed_without_running(tmp_path: Path, mode: Any):
    runs: list[int] = []
    failing = tool.make(
        "Pay",
        parameters=S.Struct(Payment),
        success=S.Struct(Receipt),
        failure=S.String,
        failure_mode=mode,
    )
    kit = toolkit.make(failing)
    handlers = kit.to_layer(
        failing.handler(
            lambda _params, _ctx: fx.sync(lambda: runs.append(1)).and_then(fx.fail("declined"))
        )
    )
    ledger = tool_ledger.memory()
    guarded = tool_ledger.guard(kit, on_unknown="fail")
    program = (
        language_model.generate_text("Pay 5", toolkit=guarded)
        .exit()
        .pipe(fx.provide_service(tool_ledger.ToolLedger, ledger))
        .pipe(fx.provide(handlers))
        .pipe(fx.provide(Model))
    )
    first, second = _blocking(program), _blocking(program)
    assert runs == [1]
    if mode == "error":
        assert isinstance(first, Failure) and isinstance(second, Failure)
        assert [e.cause.find_error() for e in (first, second)] == [Ok("declined")] * 2
    else:
        assert isinstance(first, Success) and isinstance(second, Success)
        results = [r.result for e in (first, second) for r in e.value.tool_results]
        assert results == ["declined", "declined"]


def test_invalid_parameters_leave_no_record(tmp_path: Path):
    ledger = tool_ledger.memory()
    kit = _blocking(
        tool_ledger.guard(Tools, on_unknown="fail")
        .pipe(fx.provide_service(tool_ledger.ToolLedger, ledger))
        .pipe(fx.provide(pay(tmp_path / "bank", "run")))
    )
    handled = _blocking(
        fx.scoped(
            kit.handle("Pay", {"amount": "five"}, CALL_ID).flat_map(lambda s: s.run_collect())
        )
    )
    assert [r.failure_origin for r in handled] == ["parameters"]
    assert _blocking(ledger.lookup(CALL_ID)) is None


def test_a_streamed_turn_is_guarded_too(tmp_path: Path):
    bank = tmp_path / "bank"
    ledger = tool_ledger.memory()
    _started(ledger, "Pay")

    def parts(_options: ProviderOptions) -> stream.Stream[dict[str, object]]:
        call: dict[str, object] = {
            "type": "tool-call",
            "id": CALL_ID,
            "name": "Pay",
            "params": {"amount": 5},
        }
        finish: dict[str, object] = {"type": "finish", "reason": "tool-calls", "usage": _USAGE}
        return stream.make(call, finish)

    model = fx.layer.effect(
        LanguageModel,
        language_model.make(generate_text=lambda _: fx.succeed([]), stream_text=parts),
    )
    guarded = tool_ledger.guard(Tools, on_unknown="tell_model")
    seen = _blocking(
        language_model.stream_text("Pay 5", toolkit=guarded)
        .run_collect()
        .pipe(fx.provide_service(tool_ledger.ToolLedger, ledger))
        .pipe(fx.provide(pay(bank, "run")))
        .pipe(fx.provide(model))
    )
    assert [_is_unknown(p) for p in seen if getattr(p, "type", None) == "tool-result"] == [True]
    assert payments(bank) == []
