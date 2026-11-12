"""The benchmark gate fails on a lasting slowdown, not on one slow measurement.

A shared CI runner can be slow for a few seconds: one case measured x1.98 its baseline
while every other case stayed within x1.15, and a rerun measured x1.05.
"""

import importlib
import sys
from collections.abc import Callable, Iterator
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


def _timings(gate: ModuleType, monkeypatch: pytest.MonkeyPatch, case: list[float]) -> None:
    """Calibration always takes 1 s; the case takes each of `case` in turn, then the last."""
    times: Iterator[float] = iter(case)
    last = [case[-1]]

    def run() -> int:
        return 0

    def best_of(fn: Callable[[], object]) -> float:
        if fn is run:
            last[0] = next(times, last[0])
            return last[0]
        return 1.0

    monkeypatch.setattr(gate, "CASES", (("case", 1, run),))
    monkeypatch.setattr(gate, "best_of", best_of)
    monkeypatch.setattr(gate, "_flavour", lambda: "test")
    monkeypatch.setattr(gate, "_read_baseline", lambda: {"test": {"case": 1.0}})


def test_one_slow_measurement_passes(gate: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    _timings(gate, monkeypatch, [2.0, 1.05])
    assert gate.main() == 0


def test_a_lasting_slowdown_fails(gate: ModuleType, monkeypatch: pytest.MonkeyPatch) -> None:
    _timings(gate, monkeypatch, [2.0, 2.0, 2.0])
    assert gate.main() == 1
