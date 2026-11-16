"""Compare this checkout's speed with its branch base: ``uv run python benchmarks/compare.py``.

The base is the commit this branch grew from: the merge base with ``origin/main``, or on
``main`` itself the first parent. Comparing with any other commit (a later one, another
branch's) can hide a regression or invent one, so it is the default, and naming another
commit takes ``--base``. Both sides run the same benchmarks (this checkout's
``streams.py``) against their own ``src/``, alternating in fresh processes, each case's time
over the gate's calibration. Each round compares a case with the base run next to it, and the
median of those ratios is the case's slowdown, so one round that ran fast or slow on either
side (a busy neighbour, a slowed calibration) does not decide it. A case slower than its base
by more than its tolerance fails.

Tolerances come from CI's spread comparing a commit with itself (``--base HEAD``), with
room (see ``TOLERANCE``). ``gate.py`` still catches slow drift against ``baseline.json``,
but runners differ from each other by up to 1.6x on fork-heavy, so only a comparison on one
runner can catch one change's regression, which the gate's 1.6 let through.
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MEASURE = Path(__file__).with_name("_measure.py")

# A case slower than its base by more than this fails. Twelve CI runners comparing a commit
# with itself (bench-noise runs 43357391286 and 43358456044, 5 rounds each, Python 3.13) put
# every case within x0.93 to x1.04 of itself: fork-heavy x0.96-1.03, queue x0.94-1.03, map +
# filter x0.93-1.04. x1.10 is more than twice the largest of those; the per-fiber dispatchers'
# x1.37 fork-heavy regression, which the gate's 1.6 let through, fails it by far. map +
# filter keeps the default: run 43363222313 put it at x1.098 of a base whose code path it
# shares, so its spread is wider than those twelve runs showed.
TOLERANCE: dict[str, float] = {
    "fork-heavy": 1.10,
    "queue offer/take": 1.10,
}
# The other cases' spread is wider or not measured; they get the room of x1.25.
DEFAULT_TOLERANCE = 1.25


def _git(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, check=True, capture_output=True, text=True
    ).stdout.strip()


def branch_base(repo: Path = ROOT, main: str = "origin/main") -> str:
    """The commit this branch grew from: the merge base with ``main``, or the first
    parent when ``HEAD`` is on ``main`` already."""
    head = _git("rev-parse", "HEAD", cwd=repo)
    base = _git("merge-base", "HEAD", main, cwd=repo)
    return _git("rev-parse", "HEAD^1", cwd=repo) if base == head else base


def _measure(src: Path, cases: list[str]) -> dict[str, float]:
    env = {**os.environ, "PYTHONPATH": str(src)}
    out = subprocess.run(
        [sys.executable, str(MEASURE), str(src), *cases],
        env=env,
        check=True,
        capture_output=True,
        text=True,
        cwd=MEASURE.parent,
    ).stdout
    found: dict[str, float] = json.loads(out)
    return found


def slowdown(rounds: list[tuple[float, float]]) -> float:
    """The median over rounds of this checkout's time against the base run next to it."""
    return statistics.median(head / base for head, base in rounds)


def compare(base: str, rounds: int, cases: list[str]) -> dict[str, list[tuple[float, float]]]:
    """Each case's ratio over the calibration per round: (this checkout, ``base``)."""
    found: dict[str, list[list[float]]] = {case: [] for case in cases}
    with tempfile.TemporaryDirectory() as tmp:
        tree = Path(tmp) / "base"
        _git("worktree", "add", "--detach", "-q", str(tree), base)
        try:
            sides = (ROOT / "src", tree / "src")
            for i in range(rounds):
                # Alternate which side goes first, so a machine warming up or slowing down
                # costs both alike.
                order = (0, 1) if i % 2 == 0 else (1, 0)
                for case in cases:
                    found[case].append([0.0, 0.0])
                for side in order:
                    for case, ratio in _measure(sides[side], cases).items():
                        found[case][-1][side] = ratio
                        print(f"round {i + 1} {('head', 'base')[side]} {case}: {ratio:.3f}")
        finally:
            _git("worktree", "remove", "--force", str(tree))
    return {case: [(now, was) for now, was in pairs] for case, pairs in found.items()}


def main() -> int:
    from streams import CASES

    parser = argparse.ArgumentParser(prog="benchmarks/compare.py")
    parser.add_argument("--base", help="commit to compare with (default: the branch base)")
    parser.add_argument("--rounds", type=int, default=5)
    parser.add_argument("--case", action="append", help="only these cases (default: all)")
    args = parser.parse_args()
    base: str = args.base or branch_base()
    cases: list[str] = args.case or [name for name, _, _ in CASES]
    print(f"comparing HEAD {_git('rev-parse', '--short', 'HEAD')} with base {base[:12]}")
    slower: list[str] = []
    for case, pairs in compare(base, args.rounds, cases).items():
        limit = TOLERANCE.get(case, DEFAULT_TOLERANCE)
        ratio = slowdown(pairs)
        verdict = "slower" if ratio > limit else "ok"
        print(
            f"  {case}: x{ratio:.3f}, the median of {len(pairs)} rounds (limit x{limit}) {verdict}"
        )
        if verdict == "slower":
            slower.append(case)
    if slower:
        print(f"slower than the branch base: {', '.join(slower)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
