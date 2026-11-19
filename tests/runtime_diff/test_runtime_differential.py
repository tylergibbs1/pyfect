"""pyfect's runtime answers the checked-in programs as the pinned Effect (4.1.4) does.

``corpus.json`` holds generated cases (program.py: a program and the
``MaxOpsBeforeYield`` it runs under) with what effect_interpreter.ts answered for
each under Node: the exit, its cause's shape and every event in order. Each
replays here without Node. Grow or refresh it
with ``python -m runtime_diff --write N`` / ``--refresh`` (from ``tests/``);
the fuzz workflow compares freshly generated programs against Node.
"""

import json
import re
import shutil
from pathlib import Path

import pytest

from . import generate, oracle, program

_CORPUS = oracle.read_corpus()


@pytest.mark.parametrize(
    ("case", "effect"), _CORPUS, ids=[f"program-{i}" for i in range(len(_CORPUS))]
)
def test_pyfect_answers_as_effect_does(case: program.Case, effect: program.Json):
    found = oracle.difference(case, effect)
    assert found is None, found


def test_the_corpus_runs_out_of_budget():
    """Most cases run under a budget small enough to make fibers yield."""
    small = [budget for (_, budget), _ in _CORPUS if budget <= 200]
    assert len(small) * 2 > len(_CORPUS), "add cases (--write)"


def test_the_corpus_uses_every_node():
    """A node added to the language is compared with Effect in every run."""
    used = generate.features([program.to_json(expr) for (expr, _), _ in _CORPUS])
    assert set(program.NODES) - used == set(), "regenerate corpus.json (--write)"


def test_the_corpus_runs_every_node_and_mode_at_every_swept_budget():
    """An op count one off from Effect's shows at the one budget where that op is the
    last before a yield, which fresh programs at random budgets hit by luck: every node,
    and every value of a field choosing how one runs (``generate.MODES``, such as a
    ``FlatMapStream``'s concurrency), runs in a probed program (generate.probe) at each
    of ``SWEEP_BUDGETS``."""
    swept: dict[str, set[int]] = {name: set() for name in generate.FEATURES}
    for (expr, budget), _ in _CORPUS:
        for name in generate.features(program.to_json(expr)):
            swept[name].add(budget)
    wanted = set(generate.SWEEP_BUDGETS)
    missing = {
        name: sorted(wanted - budgets) for name, budgets in swept.items() if wanted - budgets
    }
    assert missing == {}, "add the sweep to corpus.json (--sweep)"


@pytest.mark.skipif(shutil.which("node") is None, reason="needs node")
def test_the_effect_interpreter_runs_on_the_pinned_effect(effect_checkout: Path):
    """effect_interpreter.ts patches the pinned Effect's source as it loads it: a patch whose
    text the pin no longer has stops the interpreter, so a new pin fails here, in every pytest
    run, rather than in the fuzz job's run on main."""
    case, effect = _CORPUS[0]
    with oracle.EffectOracle() as node:
        assert node.answer(case) == effect


def test_the_effect_interpreter_handles_every_node():
    """The two interpreters cover the same language."""
    source = oracle.INTERPRETER.read_text(encoding="utf-8")
    handled = set(re.findall(r'case "([A-Z]\w*)"', source))
    assert set(program.NODES) - {"Resource"} == handled


def test_a_nested_program_strategy_has_a_short_repr():
    """Hypothesis prints a strategy's repr when it re-encodes a drawn value, and
    ``st.recursive`` nests ``_extend`` once per doubling of ``max_leaves``: a level
    that repeated its children's repr made the fuzz job's reports grow to gigabytes."""
    nested = generate._extend(generate._extend(generate._extend(generate._LEAVES)))  # pyright: ignore[reportPrivateUsage]
    assert len(repr(nested)) < 20_000


def _answer(
    *reasons: str, log: list[program.Json] | None = None, stuck: bool = True
) -> program.Json:
    """An answer whose cause has ``reasons``: "interrupt", "die:d1" or "fail:e1"."""
    cause: list[program.Json] = [reason.split(":") for reason in reasons]  # pyright: ignore[reportAssignmentType]
    return {"exit": {"cause": cause}, "log": log or [], "stuck": stuck}


# A starved fiber interrupted after a race decided on a defect: Effect auto-yields holding
# the defect and the interrupt drops it; pyfect keeps it beside the interrupt.
_DECIDED_DEFECT = (
    '{"op": "Seq", "id": 1, "items": [{"op": "Exited", "id": 2, "body": {"op": "Fork", "id": 3, '
    '"child": {"op": "Log", "id": 4}, "body": {"op": "Seq", "id": 5, "items": [{"op": "Seq", '
    '"id": 6, "items": [{"op": "Exited", "id": 7, "body": {"op": "RaceAll", "id": 8, "items": '
    '[{"op": "Die", "id": 10}]}}, {"op": "Succeed", "id": 11, "value": 0}]}, {"op": "Log", '
    '"id": 16}]}, "end": "join", "start_immediately": false, "daemon": false, '
    '"uninterruptible": false}}]}'
)


def test_parity_149_accepts_a_defect_pyfect_keeps_beside_effects_interrupt():
    """pyfect never pauses between a decided result and its continuation (docs/PARITY.md, "A
    decided result lost at a step-budget pause"), so it reports a defect Effect drops."""
    case = oracle.case_from_json({"program": json.loads(_DECIDED_DEFECT), "budget": 10})
    recorded = dict(_CORPUS)
    assert recorded[case] == _answer("interrupt", log=[[3600000, "", 4, "log", None]])
    oracle.PARITY_149.clear()
    assert oracle.difference(case, recorded[case]) is None
    assert {json.dumps(oracle.case_json(case))} == oracle.PARITY_149


def test_parity_149_accepts_nothing_else():
    accepted = oracle.parity_149
    assert accepted(_answer("die:d1", "interrupt"), _answer("interrupt"))
    assert not accepted(_answer("die:d1"), {"exit": {"ok": 1}, "log": [], "stuck": True})
    assert not accepted(_answer("die:d1"), _answer())
    assert not accepted(_answer("die:d1", "fail:e1"), _answer("fail:e1"))
    assert not accepted(_answer("die:d1", "die:d2", "interrupt"), _answer("die:d1", "interrupt"))
    assert not accepted(_answer("fail:e1", "interrupt"), _answer("interrupt"))
    assert not accepted(_answer("die:d1", "interrupt", stuck=False), _answer("interrupt"))
    log: list[program.Json] = [[0, "", 1, "log", None]]
    assert not accepted(_answer("die:d1", "interrupt", log=log), _answer("interrupt"))
