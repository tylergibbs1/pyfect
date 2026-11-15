"""CI runs the project's full check, and a release publishes only after CI, its extras and the
docs pass.

The check line in CLAUDE.md is what "done" means locally; CI's `lint`, `types` and `test` jobs
must run the same four tools, or a commit green on one machine is red on the other.
"""

import ast
import json
import re
from pathlib import Path

import _container_images
import _source

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
    lint, types, test = _job("ci.yml", "lint"), _job("ci.yml", "types"), _job("ci.yml", "test")
    for command in ('uvx "$ruff" format --check .', 'uvx "$ruff" check .'):
        assert command in lint, f"ci.yml's lint job does not run `{command}`"
    assert 'p["name"] == "ruff"' in lint, "lint runs the ruff uv.lock pins"
    assert "uv run --no-sync pyright" in types, "ci.yml's types job does not run pyright"
    assert "uv run --no-sync pytest" in test, "ci.yml's test job does not run the tests"
    for job in (types, test, _job("ci.yml", "collect")):
        assert "uses: ./.github/actions/check-setup" in job
    for job in (test, _job("ci.yml", "collect")):
        assert "PYFECT_EFFECT_REF" in job, "the oracle tests need Effect's checkout"


def test_one_pyright_run_checks_every_python():
    """Pyright analyses for pyproject's pythonVersion whatever runs it; the types job syncs that
    Python."""
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    version = re.search(r'(?m)^pythonVersion = "(3\.\d+)"$', pyproject)
    assert version, "pyproject.toml pins pyright's pythonVersion"
    assert f'python: "{version.group(1)}"' in _job("ci.yml", "types")


def test_the_shards_run_every_test_once_and_the_check_says_so():
    """The tests run split across runners; `check (3.x)`, the name branch protection requires,
    passes only if every job passed and the shards' tests are a full collection's."""
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

    collect = _job("ci.yml", "collect")
    assert "--collect-only -p no:randomly --shard-manifest .shards/full.txt" in collect
    assert "name: manifest-${{ matrix.python }}-full" in collect

    check = _job("ci.yml", "check")
    jobs = ["lint", "types", "collect", "images", "test"]
    assert f"needs: [{', '.join(jobs)}]" in check
    # A required check that is skipped counts as passed, so it must run when a job failed.
    assert "if: always()" in check
    for job in jobs:
        assert f"${{{{ needs.{job}.result }}}}" in check, job
        assert f'[ "${job.upper()}" = success ]' in check, job
    assert "pattern: manifest-${{ matrix.python }}-*" in check
    assert "scripts/test_shards.py verify .shards/full.txt .shards/shard-*.txt" in check


def test_a_branch_push_checks_its_pull_request():
    """A pull request from this repository's own branch gets its checks from the push of that
    branch (the same commit); its pull_request run would only double the runners. A fork's runs
    here."""
    for workflow in ("ci.yml", "audit.yml"):
        text = (WORKFLOWS / workflow).read_text(encoding="utf-8")
        jobs = re.findall(r"(?m)^  ([\w-]+):\n", text.split("\njobs:\n", 1)[1])
        for job in jobs:
            condition = re.search(r"(?m)^    if: (.*)$", _job(workflow, job))
            assert condition, f"{workflow}'s {job} has no condition"
            assert (
                "github.event_name != 'pull_request' || github.event.pull_request.head.repo.fork"
                in condition.group(1)
            ), f"{workflow}'s {job}"


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


def test_extras_gate_benchmarks_and_free_threaded():
    job = _job("extras.yml", "benchmarks")
    assert "gate.py" in job
    # The comparison with the branch base needs the history to find it.
    assert "python compare.py\n" in job and "fetch-depth: 0" in job
    assert "3.14t" in _job("extras.yml", "free-threaded")


def test_the_extras_check_waits_for_every_extra_that_runs():
    """`extras` passes only if every extra passed, or none ran because this run doesn't run
    them; each extra and the check decide that with one condition."""
    text = (WORKFLOWS / "extras.yml").read_text(encoding="utf-8")
    runs = re.search(r"(?m)^  RUNS_EXTRAS: \$\{\{ (.*) \}\}$", text)
    assert runs, "extras.yml defines RUNS_EXTRAS"
    jobs = re.findall(r"(?m)^  ([\w-]+):\n", text.split("\njobs:\n", 1)[1])
    extras = [job for job in jobs if job != "extras"]
    for job in extras:
        assert f"    if: {runs.group(1)}\n" in _job("extras.yml", job), job
    check = _job("extras.yml", "extras")
    assert f"needs: [{', '.join(extras)}]" in check and "if: always()" in check
    for job in extras:
        assert f"${{{{ needs.{job}.result }}}}" in check, job
    # Never on a pull request, always on main, in the merge queue and for a release.
    assert runs.group(1).startswith("github.event_name != 'pull_request' && (")
    assert "github.ref == 'refs/heads/main'" in runs.group(1)
    assert "startsWith(github.ref, 'refs/tags/')" in runs.group(1)


def test_runs_on_main_tags_and_the_merge_queue_are_never_cancelled():
    for path in sorted(WORKFLOWS.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        cancel = re.search(r"(?m)^  cancel-in-progress: (.*)$", text)
        if cancel is None or cancel.group(1) == "false":
            continue
        assert cancel.group(1) == (
            "${{ github.event_name == 'pull_request' || (github.event_name == 'push' && "
            "github.ref != 'refs/heads/main' && !startsWith(github.ref, 'refs/tags/')) }}"
        ), path.name


def test_every_check_main_needs_runs_in_the_merge_queue():
    for workflow in ("ci.yml", "extras.yml"):
        text = (WORKFLOWS / workflow).read_text(encoding="utf-8")
        assert re.search(r"(?m)^  merge_group:$", text), workflow


def test_every_ci_job_has_a_time_budget():
    """A job's timeout is its budget: one that grows past it fails instead of slowing every
    run down."""
    for workflow in ("ci.yml", "extras.yml"):
        text = (WORKFLOWS / workflow).read_text(encoding="utf-8")
        jobs = re.findall(r"(?m)^  ([\w-]+):\n", text.split("\njobs:\n", 1)[1])
        for job in jobs:
            budget = re.search(r"(?m)^    timeout-minutes: (\d+)$", _job(workflow, job))
            assert budget, f"{workflow}'s {job} has no timeout-minutes"


def test_a_release_needs_ci_its_extras_and_the_docs():
    release = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    for job in ("ci", "extras", "docs"):
        assert f"uses: ./.github/workflows/{job}.yml" in _job("release.yml", job)
        assert "workflow_call:" in (WORKFLOWS / f"{job}.yml").read_text(encoding="utf-8")
    assert re.search(r"needs: \[ci, extras, docs\]", _job("release.yml", "build")), release


def test_the_check_runs_on_every_python_pyproject_lists():
    """CI once ran only the Python uv picked (3.14, from .python-version), so a 3.13-only
    failure could pass it."""
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    listed = re.findall(r'"Programming Language :: Python :: (3\.\d+)"', pyproject)
    minimum = re.search(r'requires-python = ">=(3\.\d+)"', pyproject)
    assert minimum and listed and listed[0] == minimum.group(1), "classifiers start at the minimum"
    for name in ("collect", "test", "check"):
        job = _job("ci.yml", name)
        matrix = re.search(r"(?m)^\s+python: \[(.*)\]$", job)
        assert matrix, f"ci.yml's {name} job has no python matrix"
        assert re.findall(r'"(3\.\d+)"', matrix.group(1)) == listed, name
    for name in ("collect", "test"):
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


def _image_keys_named_in(path: Path) -> list[str]:
    """The keys of the ``_container_images.image("key")`` calls in ``path``."""
    return [
        node.args[0].value
        for node in _source.walk(path)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "image"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "_container_images"
        and len(node.args) == 1
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    ]


def _literal_images_in(path: Path) -> list[str]:
    """Module-level ``..._IMAGE = "name:tag"`` assignments: an image not pinned in
    tests/container_images.json, which CI would not have cached."""
    return [
        f"{path.name}:{node.lineno}"
        for node in _source.tree(path).body
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
        and any(isinstance(t, ast.Name) and t.id.endswith("IMAGE") for t in node.targets)
    ]


def test_every_container_image_the_oracle_fixtures_name_is_cached():
    """A fixture's image comes from tests/container_images.json, and CI caches each one it
    names (only an ARM-only image, which CI's x86 runners never start, is left out)."""
    fixtures = _source.files(ROOT / "tests" / "oracle", recursive=False)
    assert [hit for path in fixtures for hit in _literal_images_in(path)] == []
    named = {key for path in fixtures for key in _image_keys_named_in(path)}
    assert named <= set(_container_images.IMAGES), named - set(_container_images.IMAGES)
    cached = {image.key for image in _container_images.cached()}
    arm_only = {key for key, image in _container_images.IMAGES.items() if image.arm_only}
    assert named - arm_only <= cached, (named - arm_only) - cached
    assert cached <= named, f"pinned but no fixture runs it: {sorted(cached - named)}"
    for image in _container_images.IMAGES.values():
        assert re.fullmatch(r"sha256:[0-9a-f]{64}", image.digest), image


def test_the_server_tests_load_the_cached_images_and_never_pull():
    """One job per workflow pulls each pinned image once and caches the archives; every job
    that runs server tests restores them under the same key, made from the pins, and fails on
    a miss (.github/actions/container-images)."""
    action = (ROOT / ".github" / "actions" / "container-images" / "action.yml").read_text(
        encoding="utf-8"
    )
    key = (
        "key: container-images-${{ hashFiles('tests/container_images.json', "
        "'tests/_container_images.py') }}"
    )
    assert action.count(key) == 2, "save and load must use one key, made from the pins"
    assert "lookup-only: true" in action and "fail-on-cache-miss: true" in action
    assert "run: python3 tests/_container_images.py save .images" in action
    assert 'echo "PYFECT_IMAGE_ARCHIVES=$GITHUB_WORKSPACE/.images"' in action
    save = "uses: ./.github/actions/container-images\n        with:\n          mode: save"
    load = "uses: ./.github/actions/container-images\n        with:\n          mode: load"
    for workflow, saver, runners in (
        ("ci.yml", "images", ["test"]),
        ("drivers.yml", "images", ["driver"]),
    ):
        assert save in _job(workflow, saver), f"{workflow}'s {saver} job saves no images"
        for runner in runners:
            job = _job(workflow, runner)
            assert f"needs: {saver}" in job and load in job, f"{workflow}'s {runner} job"
    for workflow in WORKFLOWS.glob("*.yml"):
        assert "docker pull" not in workflow.read_text(encoding="utf-8"), workflow.name
