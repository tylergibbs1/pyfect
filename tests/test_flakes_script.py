"""The nightly flake hunt (flakes-nightly.yml) reruns the suite in new random orders and lists
every test that failed with the seed that repeats its order (scripts/flakes.py)."""

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Stands in for pytest: prints the seed it was given and fails one test when told to.
_FAKE_PYTEST = """
import sys
seed = sys.argv[sys.argv.index("-p") + 2].removeprefix("--randomly-seed=")
print("seed", seed)
if sys.argv[1] == "fail":
    print("= short test summary info =")
    print("FAILED test_inner.py::test_inner - assert False")
    print("= short test summary info =")
    print("FAILED tests/test_pool.py::test_grows[ttl] - AssertionError: the pool never grew")
    print("ERROR tests/test_db.py::test_query - TimeoutError")
    sys.exit(1)
if sys.argv[1] == "crash":
    sys.exit(3)
"""


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("flakes", ROOT / "scripts" / "flakes.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["flakes"] = module
    spec.loader.exec_module(module)
    return module


flakes = _script()


def _round(tmp_path: Path, job: str, outcome: str) -> Path:
    out = tmp_path / "artifacts" / f"flakes-{job}" / job
    flakes.rounds(job, 0, 0, out, [sys.executable, "-c", _FAKE_PYTEST, outcome])
    return out


def test_a_round_records_its_seed_and_the_tests_that_failed(tmp_path: Path):
    """An inner pytest run's summary (pytester, in a failed test's captured output) is not the
    suite's: only the last summary names the suite's failures."""
    out = _round(tmp_path, "suite-3.14.10-2", "fail")
    (record,) = [json.loads(line) for line in (out / "rounds.jsonl").read_text().splitlines()]
    log = (out / "round-1.log").read_text()
    assert f"seed {record['seed']}\n" in log, "the recorded seed is the one pytest was given"
    assert record["exit_code"] == 1 and record["hogs"] == 0
    assert record["failed"] == [
        "tests/test_pool.py::test_grows[ttl]",
        "tests/test_db.py::test_query",
    ]


def test_the_report_names_each_failed_test_with_its_job_seed_and_log(tmp_path: Path):
    _round(tmp_path, "suite-3.13.18-1", "pass")
    failed = _round(tmp_path, "free-threaded-3.14.10t-1", "fail")
    seed = json.loads((failed / "rounds.jsonl").read_text())["seed"]
    report = tmp_path / "report"
    assert not flakes.report(report, [tmp_path / "artifacts"])
    summary = (report / "summary.md").read_text()
    assert "2 rounds in 2 jobs; 1 failed, 2 distinct tests failed." in summary
    assert "| `tests/test_pool.py::test_grows[ttl]` | 1 | free-threaded-3.14.10t-1: 1 |" in summary
    assert f"free-threaded-3.14.10t-1, round 1, seed {seed}, 0 busy processes" in summary
    assert f"-p randomly --randomly-seed={seed}`" in summary
    assert (report / "free-threaded-3.14.10t-1" / "round-1.log").exists()
    assert not (report / "suite-3.13.18-1").exists(), "only failed rounds' logs are kept"


def test_a_round_that_fails_without_naming_a_test_fails_the_report(tmp_path: Path):
    _round(tmp_path, "suite-3.14.0-5", "crash")
    report = tmp_path / "report"
    assert not flakes.report(report, [tmp_path / "artifacts"])
    assert "(no test named: pytest exited with 3)" in (report / "summary.md").read_text()


def test_the_report_passes_only_with_rounds_that_all_passed(tmp_path: Path):
    assert not flakes.report(tmp_path / "empty", [tmp_path / "artifacts"]), "no rounds ran"
    _round(tmp_path, "suite-3.13.18-1", "pass")
    assert flakes.report(tmp_path / "report", [tmp_path / "artifacts"])


@pytest.mark.parametrize("minutes", ["0", "51"])
def test_rounds_refuse_minutes_past_the_jobs_budget(tmp_path: Path, minutes: str):
    args = ["rounds", "--job", "j", "--minutes", minutes, "--hogs", "2", "--out", str(tmp_path)]
    with pytest.raises(SystemExit) as refused:
        flakes.main([*args, "--", sys.executable, "-c", ""])
    assert refused.value.code == 2
