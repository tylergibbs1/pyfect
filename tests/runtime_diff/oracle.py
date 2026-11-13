"""Effect's answers for programs, from effect_interpreter.ts under Node, and the
checked-in corpus of them (``corpus.json``) that every pytest run replays.

Needs Node 24 and ``PYFECT_EFFECT_REF`` (an Effect 4.1.2 checkout) for anything
that asks Node; replaying the corpus needs neither.
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from types import TracebackType
from typing import IO, Self, cast

from .interpret import answer
from .program import Case, Json, from_json, to_json

INTERPRETER = Path(__file__).with_name("effect_interpreter.ts")
CORPUS = Path(__file__).with_name("corpus.json")
# The budget of corpus rows written before cases had one: none in effect.
UNLIMITED = 2**53 - 1


class EffectOracle:
    """A Node process answering programs one at a time (``--serve``)."""

    def __init__(self) -> None:
        if not os.environ.get("PYFECT_EFFECT_REF"):
            raise RuntimeError("set PYFECT_EFFECT_REF to an Effect 4.1.2 checkout")
        self._node = subprocess.Popen(
            ["node", str(INTERPRETER), "--serve"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )

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


def difference(case: Case, effect: Json) -> str | None:
    """How pyfect's answer for ``case`` differs from Effect's, if it does."""
    program, budget = case
    mine = answer(program, budget)
    if mine == effect:
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
