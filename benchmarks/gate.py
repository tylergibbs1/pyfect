"""Fail when a stream or fiber pipeline gets much slower: ``uv run python benchmarks/gate.py``.

Machines differ, so each pipeline's time is divided by a pure-Python calibration timed in
the same process, and that ratio is compared with ``benchmarks/baseline.json``. A ratio more
than ``TOLERANCE`` times its baseline fails. ``--update`` rewrites the baseline for this
interpreter (do it after a deliberate speed change, from a CI run's printed ratios).
"""

import json
import sys
import sysconfig
from pathlib import Path

from streams import CASES, best_of

BASELINE = Path(__file__).with_name("baseline.json")
TOLERANCE = 1.6


class _Box:
    __slots__ = ("value",)

    def __init__(self, value: int) -> None:
        self.value = value


def _calibration() -> int:
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


def main() -> int:
    update = "--update" in sys.argv[1:]
    baseline: dict[str, dict[str, float]] = (
        json.loads(BASELINE.read_text(encoding="utf-8")) if BASELINE.exists() else {}
    )
    flavour = _flavour()
    expected = baseline.get(flavour, {})
    calibration = best_of(_calibration)
    ratios: dict[str, float] = {}
    slower: list[str] = []
    print(f"{flavour}: calibration {calibration * 1e3:.1f} ms")
    for name, _items, run in CASES:
        ratio = best_of(run) / calibration
        ratios[name] = round(ratio, 3)
        was = expected.get(name)
        verdict = "" if was is None else f" (baseline {was:.3f}, x{ratio / was:.2f})"
        print(f"  {name}: {ratio:.3f}{verdict}")
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
    raise SystemExit(main())
