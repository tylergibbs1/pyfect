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


def test_ci_runs_the_batch_file_tests_on_windows():
    job = _job("ci.yml", "windows")
    assert "runs-on: windows-latest" in job
    assert "tests/test_process_batch_files.py" in job


def test_a_release_needs_ci_and_the_docs():
    release = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    assert "uses: ./.github/workflows/ci.yml" in _job("release.yml", "ci")
    assert "uses: ./.github/workflows/docs.yml" in _job("release.yml", "docs")
    assert re.search(r"needs: \[ci, docs\]", _job("release.yml", "build")), release
    for workflow in ("ci.yml", "docs.yml"):
        assert "workflow_call:" in (WORKFLOWS / workflow).read_text(encoding="utf-8")


def test_the_check_runs_on_every_python_pyproject_lists():
    """CI once ran only the Python uv picked (3.14, from .python-version), so a 3.13-only
    failure could pass it."""
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    listed = re.findall(r'"Programming Language :: Python :: (3\.\d+)"', pyproject)
    minimum = re.search(r'requires-python = ">=(3\.\d+)"', pyproject)
    assert minimum and listed and listed[0] == minimum.group(1), "classifiers start at the minimum"
    job = _job("ci.yml", "check")
    matrix = re.search(r"(?m)^\s+python: \[(.*)\]$", job)
    assert matrix, "ci.yml's check job has no python matrix"
    assert re.findall(r'"(3\.\d+)"', matrix.group(1)) == listed
    assert "UV_PYTHON: ${{ matrix.python }}" in job
    assert "uv sync --locked --python ${{ matrix.python }}" in job
