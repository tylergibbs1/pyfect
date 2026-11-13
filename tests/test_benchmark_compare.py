"""benchmarks/compare.py compares a commit with its branch base by default: a report
that compared with a later commit once hid a 30% fork-heavy regression."""

import importlib.util
import subprocess
from pathlib import Path
from types import ModuleType

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
