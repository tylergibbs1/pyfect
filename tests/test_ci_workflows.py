"""CI runs the project's full check, and a release publishes only after CI and the docs pass.

The check line in CLAUDE.md is what "done" means locally; CI's `check` job must run the same
four tools, or a commit green on one machine is red on the other.
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WORKFLOWS = ROOT / ".github" / "workflows"


def _job(workflow: str, name: str) -> str:
    text = (WORKFLOWS / workflow).read_text(encoding="utf-8")
    match = re.search(rf"(?ms)^  {re.escape(name)}:\n(.*?)(?=^  [\w-]+:\n|\Z)", text)
    assert match, f"{workflow} has no job {name!r}"
    return match.group(1)


def test_ci_runs_the_check_in_claude_md():
    claude = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    line = next(ln for ln in claude.splitlines() if "uv run ruff format" in ln)
    tools = [part.split()[2] for part in line.strip().split("&&")]
    assert tools == ["ruff", "ruff", "pyright", "pytest"], line
    job = _job("ci.yml", "check")
    for command in ("ruff format --check .", "ruff check .", "uv run pyright", "uv run pytest"):
        assert command in job, f"ci.yml's check job does not run `{command}`"
    assert "PYFECT_EFFECT_REF" in job, "the oracle tests need Effect's checkout"


def test_ci_gates_benchmarks_and_free_threaded():
    assert "gate.py" in _job("ci.yml", "benchmarks")
    assert "3.14t" in _job("ci.yml", "free-threaded")


def test_a_release_needs_ci_and_the_docs():
    release = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    assert "uses: ./.github/workflows/ci.yml" in _job("release.yml", "ci")
    assert "uses: ./.github/workflows/docs.yml" in _job("release.yml", "docs")
    assert re.search(r"needs: \[ci, docs\]", _job("release.yml", "build")), release
    for workflow in ("ci.yml", "docs.yml"):
        assert "workflow_call:" in (WORKFLOWS / workflow).read_text(encoding="utf-8")
