"""The benchmark gate decides from a fixed set of measurements, taken before it looks at any.

A shared CI runner can be slow for a few seconds: one case measured x1.98 its baseline
while every other case stayed within x1.15, and a rerun measured x1.05. The gate once
measured a case again while it was over the limit and kept the fastest, so a real slowdown
got more chances to look fast. It now takes the median of a fixed number of processes.
"""

import importlib
import sys
from collections.abc import Callable, Iterator, Sequence
from pathlib import Path
from types import ModuleType

import pytest

BENCHMARKS = Path(__file__).resolve().parents[1] / "benchmarks"


@pytest.fixture
def gate(monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    monkeypatch.setattr(sys, "path", [str(BENCHMARKS), *sys.path])
    module = importlib.import_module("gate")
    monkeypatch.setitem(sys.modules, "gate", module)
    return module


def _timings(gate: ModuleType, monkeypatch: pytest.MonkeyPatch, case: list[float]) -> list[int]:
    """Calibration always takes 1 s; the case takes each of `case` in turn, then the last.
    Every process runs in this one, so a test sees each measurement. The returned list
    counts the case's measurements."""
    times: Iterator[float] = iter(case)
    last = [case[-1]]
    measured = [0]

    def run() -> int:
        return 0

    def best_of(fn: Callable[[], object]) -> float:
        if fn is run:
            measured[0] += 1
            last[0] = next(times, last[0])
            return last[0]
        return 1.0

    def in_this_process(names: Sequence[str]) -> dict[str, float]:
        measure: Callable[[Sequence[str]], dict[str, float]] = gate.measure
        return measure(names)

    monkeypatch.setattr(gate, "CASES", (("case", 1, run),))
    monkeypatch.setattr(gate, "best_of", best_of)
    monkeypatch.setattr(gate, "_in_fresh_process", in_this_process, raising=False)
    monkeypatch.setattr(gate, "_flavour", lambda: "test")
    monkeypatch.setattr(gate, "_read_baseline", lambda: {"test": {"case": 1.0}})
    return measured


def test_one_slow_process_passes(gate: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    _timings(gate, monkeypatch, [2.0, 1.05])
    assert gate.main() == 0


def test_a_lasting_slowdown_fails(gate: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    _timings(gate, monkeypatch, [2.0, 2.0, 2.0])
    assert gate.main() == 1


def test_one_fast_measurement_does_not_pass_a_slow_case(
    gate: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Four of five measurements are x2 the baseline. Measuring again while over the limit
    and keeping the fastest passed it on the second measurement."""
    _timings(gate, monkeypatch, [2.0, 1.0, 2.0, 2.0, 2.0])
    assert gate.main() == 1


@pytest.mark.parametrize("seconds", [1.0, 2.0], ids=["fast", "slow"])
def test_a_case_is_measured_as_often_whatever_it_measures(
    gate: ModuleType, monkeypatch: pytest.MonkeyPatch, seconds: float
) -> None:
    """How often a case is measured cannot depend on its result, or a retry is back."""
    measured = _timings(gate, monkeypatch, [seconds])
    gate.main()
    assert measured[0] == 5
