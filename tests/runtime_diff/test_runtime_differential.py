"""pyfect's runtime answers the checked-in programs as Effect 4.1.2 does.

``corpus.json`` holds generated programs (program.py) with what
effect_interpreter.ts answered for each under Node: the exit, its cause's shape
and every event in order. Each replays here without Node. Grow or refresh it
with ``python -m runtime_diff --write N`` / ``--refresh`` (from ``tests/``);
the fuzz workflow compares freshly generated programs against Node.
"""

import re

import pytest

from . import oracle, program

_CORPUS = oracle.read_corpus()


@pytest.mark.parametrize(
    ("expr", "effect"), _CORPUS, ids=[f"program-{i}" for i in range(len(_CORPUS))]
)
def test_pyfect_answers_as_effect_does(expr: program.Expr, effect: program.Json):
    found = oracle.difference(expr, effect)
    assert found is None, found


def _ops(value: program.Json) -> set[str]:
    if isinstance(value, list):
        return set[str]().union(*(_ops(item) for item in value))
    if isinstance(value, dict):
        ops = {str(value["op"])} if "op" in value else set[str]()
        return ops.union(*(_ops(item) for item in value.values()))
    return set()


def test_the_corpus_uses_every_node():
    """A node added to the language is compared with Effect in every run."""
    used = _ops([program.to_json(expr) for expr, _ in _CORPUS])
    assert set(program.NODES) - used == set(), "regenerate corpus.json (--write)"


def test_the_effect_interpreter_handles_every_node():
    """The two interpreters cover the same language."""
    source = oracle.INTERPRETER.read_text(encoding="utf-8")
    handled = set(re.findall(r'case "([A-Z]\w*)"', source))
    assert set(program.NODES) - {"Resource"} == handled
