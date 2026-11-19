"""Effect's answers for programs, from effect_interpreter.ts under Node, and the
checked-in corpus of them (``corpus.json``) that every pytest run replays.

Needs Node 24 and the pinned Effect checkout (``tests/_effect_ref.py``) for anything
that asks Node; replaying the corpus needs neither.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from types import TracebackType
from typing import IO, Self, cast

import _effect_ref

from .interpret import answer
from .program import Case, Json, from_json, to_json

INTERPRETER = Path(__file__).with_name("effect_interpreter.ts")
CORPUS = Path(__file__).with_name("corpus.json")
# The budget of corpus rows written before cases had one: none in effect.
UNLIMITED = 2**53 - 1


class EffectOracle:
    """A Node process answering programs one at a time (``--serve``), started with Effect
    loaded."""

    def __init__(self) -> None:
        effect = _effect_ref.checkout()
        self._node = subprocess.Popen(
            ["node", str(INTERPRETER), "--serve"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            env={**os.environ, _effect_ref.ENV: str(effect)},
        )
        # Node says it is ready once Effect has loaded, so a source patch that no longer
        # applies stops the run here, before any program is generated, with Node's error above.
        if cast("IO[str]", self._node.stdout).readline() != "ready\n":
            raise RuntimeError(f"the Effect interpreter did not start ({self._node.wait()})")

    def answer(self, case: Case) -> Json:
        stdin, stdout = cast("IO[str]", self._node.stdin), cast("IO[str]", self._node.stdout)
        stdin.write(json.dumps(case_json(case)) + "\n")
        stdin.flush()
        line = stdout.readline()
        if not line:
            raise RuntimeError(f"the Effect interpreter exited ({self._node.wait()})")
        found: Json = json.loads(line)
        return found

    def close(self) -> None:
        cast("IO[str]", self._node.stdin).close()
        self._node.wait()
        cast("IO[str]", self._node.stdout).close()

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        kind: type[BaseException] | None,
        error: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


def case_json(case: Case) -> Json:
    program, budget = case
    return {"program": to_json(program), "budget": budget}


def case_from_json(row: dict[str, Json]) -> Case:
    budget = row.get("budget", UNLIMITED)
    assert isinstance(budget, int)
    return from_json(row["program"]), budget


# The cases accepted through ``parity_149`` (as case_json), which the runs report.
PARITY_149: set[str] = set()


def parity_149(mine: Json, effect: Json) -> bool:
    """Whether the answers differ only as docs/PARITY.md's "A decided result lost at a
    step-budget pause" says they may: Effect can auto-yield holding a decided defect and an
    interrupt drops it, while pyfect never pauses there. So Effect's cause has an interrupt
    and no defect, pyfect's is the same with one or more defects added, and nothing else
    differs."""
    if not (isinstance(mine, dict) and isinstance(effect, dict)):
        return False
    mine_exit, effect_exit = mine.get("exit"), effect.get("exit")
    if not (isinstance(mine_exit, dict) and isinstance(effect_exit, dict)):
        return False
    mine_cause, effect_cause = mine_exit.get("cause"), effect_exit.get("cause")
    if not (isinstance(mine_cause, list) and isinstance(effect_cause, list)):
        return False
    if {**mine, "exit": None} != {**effect, "exit": None}:
        return False

    def died(reason: Json) -> bool:
        return isinstance(reason, list) and reason[:1] == ["die"]

    kept = [reason for reason in mine_cause if not died(reason)]
    return (
        ["interrupt"] in effect_cause
        and not any(died(reason) for reason in effect_cause)
        and len(kept) < len(mine_cause)
        and kept == effect_cause
    )


def difference(case: Case, effect: Json) -> str | None:
    """How pyfect's answer for ``case`` differs from Effect's, if it does, apart from the
    difference ``parity_149`` accepts (counted in ``PARITY_149``)."""
    program, budget = case
    mine = answer(program, budget)
    if mine == effect:
        return None
    if parity_149(mine, effect):
        PARITY_149.add(json.dumps(case_json(case)))
        return None
    return (
        f"case:    {json.dumps(case_json(case))}\n"
        f"pyfect:  {json.dumps(mine)}\n"
        f"Effect:  {json.dumps(effect)}"
    )


def read_corpus() -> list[tuple[Case, Json]]:
    rows: list[dict[str, Json]] = json.loads(CORPUS.read_text(encoding="utf-8"))
    return [(case_from_json(row), row["effect"]) for row in rows]


def write_corpus(rows: list[tuple[Case, Json]]) -> None:
    data = [
        {"program": to_json(program), "budget": budget, "effect": effect}
        for (program, budget), effect in rows
    ]
    CORPUS.write_text(
        json.dumps(data, indent=None, separators=(",", ":")).replace(
            '},{"program"', '},\n{"program"'
        )
        + "\n",
        encoding="utf-8",
    )
