"""CI splits the suite across runners (tests/_shards.py) and its ``check`` job fails unless the
shards together ran every test exactly once (scripts/test_shards.py verify)."""

import importlib.util
import json
import sys
from pathlib import Path
from types import ModuleType

import pytest
from _shards import DURATIONS, Plan, assign, load_durations, shard_of
from _subprocess import SUBPROCESS_TIMEOUT

ROOT = Path(__file__).resolve().parent.parent


def _script() -> ModuleType:
    spec = importlib.util.spec_from_file_location(
        "test_shards", ROOT / "scripts" / "test_shards.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["test_shards"] = module
    spec.loader.exec_module(module)
    return module


def test_longest_files_first_keeps_the_shards_level():
    durations = {"a.py": 10.0, "b.py": 9.0, "c.py": 6.0, "d.py": 5.0, "e.py": 4.0, "f.py": 2.0}
    plan = assign(durations, 3)
    assert plan.shards.keys() == durations.keys() and not plan.spread
    loads = [sum(s for path, s in durations.items() if plan.shards[path] == k) for k in (1, 2, 3)]
    assert tuple(loads) == plan.loads
    # Longest-first packing is within 4/3 of the best split, whatever the durations.
    assert max(loads) <= 4 / 3 * sum(durations.values()) / 3
    assert assign(dict(reversed(durations.items())), 3) == plan


def test_a_file_longer_than_a_shards_share_is_spread_over_every_shard():
    durations = {"big.py": 60.0, "a.py": 10.0, "b.py": 10.0, "c.py": 10.0}
    plan = assign(durations, 3)
    assert plan.spread == {"big.py"} and "big.py" not in plan.shards
    assert shard_of("big.py", plan, 3) is None
    assert max(plan.loads) == min(plan.loads) == 30.0


def test_the_recorded_durations_keep_every_shard_near_the_mean():
    """A heavy new file packed whole once left one CI shard at 47 minutes and the rest at 8."""
    loads = assign(load_durations(DURATIONS), 5).loads
    assert max(loads) <= 1.15 * sum(loads) / 5, [round(load) for load in loads]


def test_a_file_with_no_recorded_duration_still_lands_in_one_shard():
    empty = Plan({}, frozenset(), (0.0,) * 4)
    for path in ("tests/test_new.py", "tests/oracle/test_other.py"):
        assert shard_of(path, empty, 4) in (1, 2, 3, 4)
        assert shard_of(path, empty, 4) == shard_of(path, empty, 4)
    assert shard_of("tests/test_new.py", Plan({"tests/test_new.py": 3}, frozenset(), ()), 4) == 3


def test_the_shards_together_collect_every_test_once(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parent))
    for n in range(7):
        pytester.makepyfile(**{f"test_f{n}": "\n".join(f"def test_{t}(): pass" for t in range(n))})
    pytester.mkpydir("sub").joinpath("test_nested.py").write_text("def test_x(): pass\n")

    def collect(*shard: str) -> list[str]:
        manifest = pytester.path / f"manifest{''.join(shard).replace('/', 'of')}.txt"
        result = pytester.runpytest_subprocess(
            "-p", "_shards", "--collect-only", "--shard-manifest", str(manifest),
            *(["--shard", *shard] if shard else []), timeout=SUBPROCESS_TIMEOUT,
        )  # fmt: skip
        assert result.ret == 0, result.stdout.str()
        return manifest.read_text().splitlines()

    full = collect()
    shards = [collect(f"{k}/3") for k in (1, 2, 3)]
    assert len(full) == sum(range(7)) + 1
    assert sorted(test for shard in shards for test in shard) == sorted(full)
    assert all(shards), "a shard collected nothing; pick files so each gets one"


def test_a_spread_files_tests_run_once_across_the_shards(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parent))
    pytester.makepyfile(test_big="\n".join(f"def test_{t}(): pass" for t in range(60)))
    pytester.makepyfile(test_small="def test_x(): pass\n")
    recorded = pytester.path / "durations.json"
    recorded.write_text('{"test_big.py": 100.0, "test_small.py": 1.0}')

    def collect(*shard: str) -> list[str]:
        manifest = pytester.path / f"manifest{''.join(shard).replace('/', 'of')}.txt"
        result = pytester.runpytest_subprocess(
            "-p", "_shards", "--collect-only", "--shard-manifest", str(manifest),
            "--shard-recorded", str(recorded),
            *(["--shard", *shard] if shard else []), timeout=SUBPROCESS_TIMEOUT,
        )  # fmt: skip
        assert result.ret == 0, result.stdout.str()
        return manifest.read_text().splitlines()

    full = collect()
    shards = [collect(f"{k}/3") for k in (1, 2, 3)]
    assert sorted(test for shard in shards for test in shard) == sorted(full)
    assert all(sum(test.startswith("test_big.py") for test in shard) > 5 for shard in shards)


def test_verify_names_the_missing_and_the_repeated(tmp_path: Path):
    verify = _script().verify
    full = tmp_path / "full.txt"
    full.write_text("a::1\na::2\nb::1\n")
    one, two = tmp_path / "1.txt", tmp_path / "2.txt"
    one.write_text("a::1\na::2\n")
    two.write_text("b::1\n")
    assert verify(full, [one, two]) == []
    two.write_text("a::2\n")
    assert verify(full, [one, two]) == ["run 2 times: a::2", "in no shard: b::1"]
    full.write_text("")
    one.write_text("")
    two.write_text("")
    assert verify(full, [one, two]) == [f"{full} lists no tests"]


def test_update_keeps_the_slower_pythons_time(tmp_path: Path):
    update = _script().update
    (tmp_path / "313.json").write_text('{"tests/test_a.py": 2.0, "tests/test_b.py": 5.0}')
    (tmp_path / "314.json").write_text('{"tests/test_a.py": 3.0}')
    assert update([tmp_path / "313.json", tmp_path / "314.json"]) == {
        "tests/test_a.py": 3.0,
        "tests/test_b.py": 5.0,
    }


def test_a_parallel_shard_records_every_test_and_every_files_time(
    pytester: pytest.Pytester, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Under xdist the controller writes the manifest and the durations from all workers'
    reports; a worker writing its own share would leave tests out."""
    monkeypatch.setenv("PYTHONPATH", str(Path(__file__).parent))
    for n in range(1, 7):
        pytester.makepyfile(**{f"test_f{n}": "\n".join(f"def test_{t}(): pass" for t in range(n))})
    manifest = pytester.path / "manifest.txt"
    durations = pytester.path / "durations.json"
    result = pytester.runpytest_subprocess(
        "-p", "_shards", "-n", "3", "--shard-manifest", str(manifest),
        "--shard-durations", str(durations), timeout=SUBPROCESS_TIMEOUT,
    )  # fmt: skip
    result.assert_outcomes(passed=sum(range(1, 7)))
    assert len(manifest.read_text().splitlines()) == sum(range(1, 7))
    assert sorted(json.loads(durations.read_text())) == [f"test_f{n}.py" for n in range(1, 7)]
