"""benchmarks/compare.py compares a commit with its branch base by default: a report
that compared with a later commit once hid a 30% fork-heavy regression."""

import importlib.util
import json
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from types import ModuleType

import pytest

_COMPARE = Path(__file__).resolve().parent.parent / "benchmarks" / "compare.py"


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("benchmark_compare", _COMPARE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def _commit(repo: Path, name: str) -> str:
    (repo / name).write_text(name)
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", name)
    return _git(repo, "rev-parse", "HEAD")


def test_a_branch_compares_with_where_it_left_main(tmp_path: Path):
    _git(tmp_path, "init", "-q", "-b", "main")
    _commit(tmp_path, "a")
    fork_point = _commit(tmp_path, "b")
    _git(tmp_path, "checkout", "-q", "-b", "topic")
    _commit(tmp_path, "c")
    _commit(tmp_path, "d")
    _git(tmp_path, "checkout", "-q", "main")
    _commit(tmp_path, "later on main")
    _git(tmp_path, "checkout", "-q", "topic")
    assert _module().branch_base(tmp_path, "main") == fork_point


def test_main_compares_with_its_first_parent(tmp_path: Path):
    _git(tmp_path, "init", "-q", "-b", "main")
    before = _commit(tmp_path, "a")
    _commit(tmp_path, "b")
    assert _module().branch_base(tmp_path, "main") == before


def test_fork_heavy_has_its_own_tolerance():
    """The gate's 1.6 let a x1.37 fork-heavy regression through."""
    tolerance = _module().TOLERANCE
    assert tolerance["fork-heavy"] < 1.37
    assert tolerance["queue offer/take"] < 1.37


# queue offer/take, (head, base) per round, from CI run 43820738478 (a test-only change):
# the base's round 2 ran 11% faster than its other four rounds.
_ONE_FAST_BASE_ROUND = [
    (12.582, 12.263),
    (12.601, 10.936),
    (12.653, 12.708),
    (13.214, 12.387),
    (12.704, 12.671),
]


def _best_of_each_side(rounds: list[tuple[float, float]]) -> float:
    """How compare.py used to judge: each side's best round, divided."""
    return min(head for head, _ in rounds) / min(base for _, base in rounds)


def test_one_fast_round_on_one_side_does_not_decide_the_verdict():
    """The best of each side read x1.151 for a change that touched no source, over the
    limit of x1.10; each round against the base run next to it reads x1.026."""
    limit = _module().TOLERANCE["queue offer/take"]
    assert _best_of_each_side(_ONE_FAST_BASE_ROUND) > limit
    assert _module().slowdown(_ONE_FAST_BASE_ROUND) < 1.03


def test_a_regression_in_most_rounds_fails_despite_one_fast_round():
    """x1.2 slower in four rounds of five; one fast head round hid it from the best of each
    side."""
    rounds = [(12.0, 10.0), (12.1, 10.0), (9.0, 10.0), (12.2, 10.1), (12.0, 9.9)]
    limit = _module().TOLERANCE["queue offer/take"]
    assert _best_of_each_side(rounds) < limit
    assert _module().slowdown(rounds) > limit


# queue offer/take on one runner comparing a commit with itself, 5 rounds of
# (head time, head calibration, base time, base calibration) in ms, from the noise run
# 43854358958 (runner 6). The calibration swung 25% between processes; the case did not.
_SWINGING_CALIBRATION = [
    (657.55, 43.98, 662.34, 39.52),
    (653.08, 40.83, 643.58, 41.42),
    (648.38, 41.11, 722.89, 41.45),
    (663.14, 49.42, 652.98, 40.21),
    (643.36, 39.65, 660.58, 41.77),
]


def test_a_commit_compared_with_itself_reads_even_from_raw_times():
    """Both sides run back to back on one runner, so there is nothing for a calibration to
    cancel: dividing by each process's calibration read x0.904 here (and x1.111 in release
    run 43850829053, failing 0.6.9), while the raw times read x0.993."""
    calibrated = [(h / hc, b / bc) for h, hc, b, bc in _SWINGING_CALIBRATION]
    raw = [(h, b) for h, _, b, _ in _SWINGING_CALIBRATION]
    assert abs(_module().slowdown(calibrated) - 1) > 0.09
    assert abs(_module().slowdown(raw) - 1) < 0.01


def test_each_side_reports_raw_times(monkeypatch: pytest.MonkeyPatch):
    """compare.py's measuring process must not divide by the gate's calibration."""
    benchmarks = _COMPARE.parent
    monkeypatch.setattr(sys, "path", [str(benchmarks), *sys.path])
    spec = importlib.util.spec_from_file_location("benchmark_measure", benchmarks / "_measure.py")
    assert spec is not None and spec.loader is not None
    measure = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(measure)

    def no_calibration() -> int:
        raise AssertionError("compare.py measured the calibration")

    monkeypatch.setattr(measure, "calibrate", no_calibration, raising=False)

    def once(run: Callable[[], float]) -> float:
        return run()

    monkeypatch.setattr(measure, "best_of", once)
    monkeypatch.setattr(measure, "CASES", [("a case", None, lambda: 7.5)])
    monkeypatch.setattr(
        "sys.argv", ["_measure.py", str(Path(measure.pyfect.__file__).parent.parent), "a case"]
    )
    printed: list[str] = []
    monkeypatch.setattr("builtins.print", printed.append)
    measure.main()
    assert json.loads(printed[0]) == {"a case": 7.5}
