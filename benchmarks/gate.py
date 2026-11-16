"""Fail when a stream or fiber pipeline gets much slower: ``uv run python benchmarks/gate.py``.

Machines differ, so each pipeline's time is divided by a pure-Python calibration timed next
to it, and that ratio is compared with ``benchmarks/baseline.json``. A process can run fast
or slow as a whole, so ``PROCESSES`` fresh processes each measure every case once and the
median of their ratios is the case's ratio: a fixed set of measurements, all taken before the
gate looks at any. A ratio more than ``TOLERANCE`` times its baseline fails. ``--update``
rewrites the baseline for this interpreter (do it after a deliberate speed change, from a CI
run's printed ratios).
"""

import json
import statistics
import subprocess
import sys
import sysconfig
from collections.abc import Sequence
from pathlib import Path

from streams import CASES, best_of

BASELINE = Path(__file__).with_name("baseline.json")
PROCESSES = 5
# The median of 5 processes, each case over a calibration next to it, on 8 CI runners
# running one commit (noise run 43854358958, 18 processes each, Python 3.13): the slowest
# runner's ratio over the fastest's was at most x1.41 (group_by_key + grouped_within, 1-item
# chunks), so a baseline recorded on one runner and checked on another can read x1.41 with
# no change. One process's ratio over one calibration, which the gate used before, spread
# x1.75 across those runners, past this limit.
TOLERANCE = 1.6


class _Box:
    __slots__ = ("value",)

    def __init__(self, value: int) -> None:
        self.value = value


def calibrate() -> int:
    """Interpreter work of the same kind as a fiber step: generators, objects, dicts, calls."""

    def boxes(n: int):
        for i in range(n):
            yield _Box(i)

    slots: dict[int, _Box] = {}
    total = 0
    for box in boxes(300_000):
        slots[box.value & 63] = box
        total += slots[box.value & 63].value
    return total


def _flavour() -> str:
    gil = "free-threaded" if sysconfig.get_config_var("Py_GIL_DISABLED") else "gil"
    return f"{sys.version_info.major}.{sys.version_info.minor}-{gil}"


def measure(names: Sequence[str]) -> dict[str, float]:
    """Each case's time in this process over the faster of the calibrations either side of it."""
    runs = {name: run for name, _, run in CASES}
    ratios: dict[str, float] = {}
    for name in names:
        before = best_of(calibrate)
        seconds = best_of(runs[name])
        ratios[name] = seconds / min(before, best_of(calibrate))
    return ratios


def _in_fresh_process(names: Sequence[str]) -> dict[str, float]:
    out = subprocess.run(
        [sys.executable, __file__, "--measure", *names],
        check=True,
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent,
    ).stdout
    found: dict[str, float] = json.loads(out)
    return found


def _read_baseline() -> dict[str, dict[str, float]]:
    return json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else {}


def main() -> int:
    update = "--update" in sys.argv[1:]
    baseline = _read_baseline()
    flavour = _flavour()
    expected = baseline.get(flavour, {})
    names = [name for name, _, _ in CASES]
    samples = [_in_fresh_process(names) for _ in range(PROCESSES)]
    ratios: dict[str, float] = {}
    slower: list[str] = []
    print(f"{flavour}: the median of {PROCESSES} processes")
    for name in names:
        each = [sample[name] for sample in samples]
        ratio = statistics.median(each)
        ratios[name] = round(ratio, 3)
        was = expected.get(name)
        verdict = "" if was is None else f" (baseline {was:.3f}, x{ratio / was:.2f})"
        print(f"  {name}: {ratio:.3f}{verdict} from {' '.join(f'{r:.3f}' for r in each)}")
        if was is not None and ratio > was * TOLERANCE:
            slower.append(name)
    if update:
        baseline[flavour] = ratios
        BASELINE.write_text(json.dumps(baseline, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"wrote {BASELINE.name} for {flavour}")
        return 0
    if not expected:
        print(f"no baseline for {flavour}; run with --update to record one", file=sys.stderr)
        return 1
    if slower:
        print(
            f"more than x{TOLERANCE} slower than the baseline: {', '.join(slower)}", file=sys.stderr
        )
        return 1
    return 0


if __name__ == "__main__":
    if sys.argv[1:2] == ["--measure"]:
        print(json.dumps(measure(sys.argv[2:])))
    else:
        raise SystemExit(main())
