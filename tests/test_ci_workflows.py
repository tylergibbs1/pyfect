"""CI runs the project's full check, and a release publishes only after CI and the docs pass.

The check line in CLAUDE.md is what "done" means locally; CI's `lint` and `test` jobs must run
the same four tools, or a commit green on one machine is red on the other.
"""

import json
import re
from pathlib import Path

from pyfect.date_time._icu_zones import NODE_VERSION

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
    lint, test = _job("ci.yml", "lint"), _job("ci.yml", "test")
    for command in ("ruff format --check .", "ruff check .", "uv run pyright"):
        assert command in lint, f"ci.yml's lint job does not run `{command}`"
    assert "uv run pytest" in test, "ci.yml's test job does not run the tests"
    for job in (lint, test):
        assert "PYFECT_EFFECT_REF" in job, "the oracle tests need Effect's checkout"
        assert "uses: ./.github/actions/check-setup" in job


def test_the_shards_run_every_test_once_and_the_check_says_so():
    """The tests run split across runners; `check (3.x)`, the name branch protection requires,
    passes only if lint and every shard passed and the shards' tests are a full collection's."""
    test = _job("ci.yml", "test")
    shards = re.search(r"(?m)^\s+shard: \[(.*)\]$", test)
    assert shards, "ci.yml's test job has no shard matrix"
    count = len(shards.group(1).split(","))
    assert shards.group(1) == ", ".join(str(k) for k in range(1, count + 1))
    assert f"name: test (${{{{ matrix.python }}}}, ${{{{ matrix.shard }}}}/{count})" in test
    run = re.search(r"(?ms)- name: Tests\n\s+run: \|\n(.*?)\n\n", test)
    assert run, "ci.yml's test job has no Tests step"
    assert f"--shard ${{{{ matrix.shard }}}}/{count} " in run.group(1)
    for narrowing in (" -k ", " -m ", "--deselect", "--ignore", " -x", "--maxfail", "--lf"):
        assert narrowing not in run.group(1), f"the shards must run every test: {narrowing}"
    assert "--shard-manifest .shards/shard-${{ matrix.shard }}.txt" in run.group(1)
    assert "name: manifest-${{ matrix.python }}-${{ matrix.shard }}" in test

    lint = _job("ci.yml", "lint")
    assert "--collect-only -p no:randomly --shard-manifest .shards/full.txt" in lint
    assert "name: manifest-${{ matrix.python }}-full" in lint

    check = _job("ci.yml", "check")
    assert "needs: [lint, test]" in check
    # A required check that is skipped counts as passed, so it must run when a shard failed.
    assert "if: always()" in check
    assert '[ "$LINT" = success ] && [ "$TEST" = success ]' in check
    assert "LINT: ${{ needs.lint.result }}" in check and "TEST: ${{ needs.test.result }}" in check
    assert "pattern: manifest-${{ matrix.python }}-*" in check
    assert "scripts/test_shards.py verify .shards/full.txt .shards/shard-*.txt" in check


def test_the_docs_build_check_passes_only_if_every_docs_job_did():
    """`build` is the docs check branch protection requires; the work runs in parallel jobs."""
    text = (WORKFLOWS / "docs.yml").read_text(encoding="utf-8")
    jobs = re.findall(r"(?m)^  ([\w-]+):\n", text.split("\njobs:\n", 1)[1])
    others = [job for job in jobs if job != "build"]
    build = _job("docs.yml", "build")
    assert f"needs: [{', '.join(others)}]" in build
    assert "if: always()" in build
    for job in others:
        assert f"${{{{ needs.{job}.result }}}}" in build, job
        assert re.search(r"(?m)^    timeout-minutes: \d+$", _job("docs.yml", job)), job
    assert build.count("= success ]") == len(others)


def test_only_a_pull_request_may_skip_the_site_build():
    """The merge queue, pushes and releases build the site; a pull request whose diff touches
    nothing the site reads may skip it, and `build` passes a skipped site only then."""
    text = (WORKFLOWS / "docs.yml").read_text(encoding="utf-8")
    triggers = text.split("\njobs:\n", 1)[0]
    for trigger in ("push:", "pull_request:", "merge_group:", "workflow_call:"):
        assert f"\n  {trigger}" in triggers, trigger
    assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in triggers

    changes = _job("docs.yml", "changes")
    assert "site=true\n" in changes
    narrowing = changes.split('if [ "$EVENT" = pull_request ]; then', 1)
    assert len(narrowing) == 2 and "site=false" not in narrowing[0], "only a PR may skip"
    assert "EVENT: ${{ github.event_name }}" in changes

    assert "if: needs.changes.outputs.site == 'true'" in _job("docs.yml", "site")
    build = _job("docs.yml", "build")
    assert "SITE_NEEDED: ${{ needs.changes.outputs.site }}" in build
    assert '{ [ "$SITE" = skipped ] && [ "$SITE_NEEDED" = false ]; }' in build


def test_ci_gates_benchmarks_and_free_threaded():
    job = _job("ci.yml", "benchmarks")
    assert "gate.py" in job
    # The comparison with the branch base needs the history to find it.
    assert "python compare.py\n" in job and "fetch-depth: 0" in job
    assert "3.14t" in _job("ci.yml", "free-threaded")


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
    for name in ("lint", "test", "check"):
        job = _job("ci.yml", name)
        matrix = re.search(r"(?m)^\s+python: \[(.*)\]$", job)
        assert matrix, f"ci.yml's {name} job has no python matrix"
        assert re.findall(r'"(3\.\d+)"', matrix.group(1)) == listed, name
    for name in ("lint", "test"):
        job = _job("ci.yml", name)
        assert "UV_PYTHON: ${{ matrix.python }}" in job
        assert "python: ${{ matrix.python }}" in job
    setup = (ROOT / ".github" / "actions" / "check-setup" / "action.yml").read_text("utf-8")
    assert "PYTHON: ${{ inputs.python }}" in setup
    assert 'uv sync --locked --python "$PYTHON"' in setup


def test_workflows_pin_one_effect_commit():
    """The oracle tests, mutation runs and the runtime differential job compare
    against one Effect."""
    pins = {
        path.name: re.findall(r"EFFECT_COMMIT: ([0-9a-f]{40})", path.read_text(encoding="utf-8"))
        for path in sorted(WORKFLOWS.glob("*.yml"))
    }
    assert {"ci.yml", "fuzz.yml"} <= {name for name, commits in pins.items() if commits}
    assert len({commit for commits in pins.values() for commit in commits}) == 1, pins


def test_the_fuzz_workflow_compares_fresh_programs_with_node():
    job = _job("fuzz.yml", "runtime-differential")
    assert "python -m runtime_diff --fresh" in job
    assert "PYFECT_EFFECT_REF" in job and "setup-node" in job


def test_ci_runs_the_node_the_recorded_answers_came_from():
    """The Intl, ICU zone and node:path answers were recorded under one Node; under another the
    tests that compare with it skip, which CI fails (tests/_skips.py)."""
    pinned = (ROOT / ".node-version").read_text(encoding="utf-8").strip()
    fixtures = ROOT / "tests" / "oracle"
    recorded = {
        "pyfect.date_time._icu_zones.NODE_VERSION": NODE_VERSION,
        "intl_answers.json": json.loads((fixtures / "intl_answers.json").read_text())["node"],
        "node_path_cases.json": json.loads(
            (fixtures / "fixtures" / "node_path_cases.json").read_text()
        )["node"],
    }
    assert recorded == dict.fromkeys(recorded, pinned)
    for path in (".github/actions/check-setup/action.yml", ".github/workflows/fuzz.yml"):
        text = (ROOT / path).read_text(encoding="utf-8")
        assert "node-version-file: .node-version" in text, path


_DRIVER_EXTRAS = ("pg", "mysql", "mssql", "redis")
"""The extras that install a database or server driver."""


def test_each_driver_runs_its_tests_at_its_newest_and_lowest_versions():
    """asyncmy 0.2.18 failed every MySQL query of a fresh install of 0.6.5-0.6.9, while CI
    installed uv.lock's 0.2.17. drivers.yml re-resolves each driver extra's packages without
    the lock, at the newest and the lowest allowed release, on every change to the code using
    them and daily."""
    text = (WORKFLOWS / "drivers.yml").read_text(encoding="utf-8")
    triggers = text.split("\njobs:\n", 1)[0]
    for path in ('"src/pyfect/sql/**"', '"pyproject.toml"', '"uv.lock"'):
        assert path in triggers, path
    assert "schedule:" in triggers and "pull_request_target" not in triggers
    job = _job("drivers.yml", "driver")
    assert "resolution: [highest, lowest-direct]" in job
    assert 'uv pip install --python .venv/bin/python --resolution "$RESOLUTION"' in job
    assert 'PYFECT_REQUIRE_ALL_TESTS: "1"' in job

    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    rows = re.findall(r"(?m)^\s+- extra: (\w+)\n\s+packages: (.+)\n\s+tests: (.+)$", job)
    assert sorted(extra for extra, _, _ in rows) == sorted(_DRIVER_EXTRAS)
    for extra, packages, tests in rows:
        listed = re.search(rf"(?ms)^{extra} = \[\n(.*?)^\]", pyproject)
        assert listed, extra
        names = re.findall(r'"([\w-]+)', listed.group(1))
        assert sorted(packages.split()) == sorted(names), extra
        for pattern in tests.split():
            assert list(ROOT.glob(pattern)), f"{extra}: {pattern} matches no test"
