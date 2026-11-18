"""CI runs the project's full check, and a release publishes only after CI, its extras and the
docs pass.

The check line in CLAUDE.md is what "done" means locally; CI's `lint`, `types` and `test` jobs
must run the same four tools, or a commit green on one machine is red on the other.
"""

import ast
import json
import re
from datetime import UTC, date, datetime, timedelta
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


def test_one_commit_gets_one_run():
    """A pull request is checked by its pull_request run and a push runs only on main. A branch
    push would check the same commit again, and cancelling either copy leaves a failed required
    check on a commit main may move to (it once blocked a fast-forward)."""
    for path in sorted(WORKFLOWS.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        if not re.search(r"(?m)^  pull_request:", text):
            continue
        push = re.search(r"(?m)^  push:\n    branches: (.*)$", text)
        assert push and push.group(1) == "[main]", path.name
        assert "head.repo.fork" not in text, path.name
    for name in ("ci.yml", "extras.yml", "docs.yml", "audit.yml"):
        text = (WORKFLOWS / name).read_text(encoding="utf-8")
        triggers = text.split("\njobs:\n", 1)[0]
        for trigger in ("push:", "pull_request:", "merge_group:", "workflow_call:"):
            assert f"\n  {trigger}" in triggers, (name, trigger)
        assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in triggers, name


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
    # Always on main, in the merge queue and for a release; on a pull request until the merge
    # queue runs them.
    assert runs.group(1) == "github.event_name != 'pull_request' || vars.MERGE_QUEUE != 'on'"


def test_runs_on_main_tags_and_the_merge_queue_are_never_cancelled():
    for path in sorted(WORKFLOWS.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        cancel = re.search(r"(?m)^  cancel-in-progress: (.*)$", text)
        if cancel is None or cancel.group(1) == "false":
            continue
        # Only a pull request's superseded commit, which main can never move to.
        assert cancel.group(1) == "${{ github.event_name == 'pull_request' }}", path.name


def test_every_check_main_needs_runs_in_the_merge_queue():
    for workflow in ("ci.yml", "extras.yml"):
        text = (WORKFLOWS / workflow).read_text(encoding="utf-8")
        assert re.search(r"(?m)^  merge_group:$", text), workflow


_IGNORE_LONGEST = timedelta(days=30)


def _audit_ignore_problems(workflow: str, today: date) -> list[str]:
    """An audit may ignore an advisory only with a comment just above saying why and until
    when, at most 30 days out, so an ignore is rechecked instead of outliving its reason."""
    lines = workflow.splitlines()
    problems: list[str] = []
    for number, line in enumerate(lines):
        if "audit" not in line:
            continue
        above: list[str] = []
        for previous in reversed(lines[:number]):
            if not previous.strip().startswith("#"):
                break
            above.insert(0, previous.strip().lstrip("#").strip())
        comment = " ".join(above)
        for advisory in re.findall(r"--ignore[= ]+(\S+)", line):
            why = re.search(
                rf"{re.escape(advisory)}\b(.{{20,}}?)\buntil (\d{{4}}-\d{{2}}-\d{{2}})", comment
            )
            if why is None:
                problems.append(
                    f"{advisory}: no reason and `until YYYY-MM-DD` in the comment above"
                )
            elif (until := date.fromisoformat(why.group(2))) < today:
                problems.append(f"{advisory}: ignored until {until}, which has passed: recheck it")
            elif until - today > _IGNORE_LONGEST:
                problems.append(f"{advisory}: ignored until {until}, over 30 days out")
    return problems


def test_an_audit_ignores_an_advisory_only_with_a_reason_and_an_expiry():
    for path in sorted(WORKFLOWS.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        assert _audit_ignore_problems(text, datetime.now(UTC).date()) == [], path.name


def test_the_audit_ignore_guard_rejects_a_missing_reason_or_date_and_a_stale_one():
    today = date(2026, 11, 17)
    run = "run: bun audit --ignore=GHSA-aaaa-bbbb-cccc"
    reason = "# GHSA-aaaa-bbbb-cccc: build-time only, no untrusted input reaches it,"
    cases = {
        run: "no reason",
        f"# build-time only, no untrusted input reaches it\n{run}": "no reason",
        f"{reason}\n{run}": "no reason",
        f"{reason} until 2026-11-16\n{run}": "has passed",
        f"{reason} until 2026-12-18\n{run}": "over 30 days",
        f"{reason}\n# until 2026-12-08\n\n{run}": "no reason",
    }
    for text, problem in cases.items():
        found = _audit_ignore_problems(text, today)
        assert len(found) == 1 and problem in found[0], (text, found)
    for until in ("2026-11-17", "2026-12-17"):
        assert _audit_ignore_problems(f"{reason}\n# until {until}\n{run}", today) == []
    assert _audit_ignore_problems("run: bun audit", today) == []


def test_every_ci_job_has_a_time_budget():
    """A job's timeout is its budget: one that grows past it fails instead of slowing every
    run down."""
    for workflow in ("ci.yml", "extras.yml", "soak-nightly.yml"):
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
        ("soak-nightly.yml", "images", ["cluster"]),
    ):
        assert save in _job(workflow, saver), f"{workflow}'s {saver} job saves no images"
        for runner in runners:
            job = _job(workflow, runner)
            assert f"needs: {saver}" in job and load in job, f"{workflow}'s {runner} job"
    for workflow in WORKFLOWS.glob("*.yml"):
        assert "docker pull" not in workflow.read_text(encoding="utf-8"), workflow.name


_PYTEST_RUN = re.compile(r"(?:\buv run\b[^#\n]*?\s|\s-m\s+)pytest\b")
"""A line that runs pytest (``uv run [--no-sync] pytest``, ``python -m pytest``), not one that
installs it."""


def _serial_pytest_problems(workflow: str) -> list[str]:
    """Every pytest run uses ``-n auto``, one xdist worker per CPU the runner has, or says why
    it runs serially in a comment just above (``# Serial: ...``)."""
    lines = workflow.splitlines()
    problems: list[str] = []
    for number, line in enumerate(lines):
        if line.strip().startswith("#") or not _PYTEST_RUN.search(line):
            continue
        if re.search(r"\s-n auto\b", line):
            continue
        above: list[str] = []
        for previous in reversed(lines[:number]):
            if not previous.strip().startswith("#"):
                break
            above.insert(0, previous.strip().lstrip("#").strip())
        reason = re.match(r"Serial: (.{20,})", " ".join(above))
        if reason is None:
            problems.append(f"line {number + 1}: no -n auto and no `# Serial: why` above")
    return problems


def test_every_pytest_run_uses_every_core_or_says_why_not():
    """A runner's CPU count is printed by each workflow's first job; `-n auto` follows it, where
    a hardcoded `-n 4` would not. Without psutil, xdist's `auto` counts the CPUs the process may
    use (os.sched_getaffinity); with it, only physical cores."""
    runs = 0
    for path in sorted(WORKFLOWS.glob("*.yml")):
        text = path.read_text(encoding="utf-8")
        runs += sum(1 for line in text.splitlines() if _PYTEST_RUN.search(line))
        assert _serial_pytest_problems(text) == [], path.name
    assert runs >= 6, "the guard finds the workflows' pytest runs"
    lock = (ROOT / "uv.lock").read_text(encoding="utf-8")
    assert '\nname = "psutil"\n' not in lock, "psutil makes -n auto count physical cores only"


def test_the_serial_pytest_guard_rejects_a_fixed_count_and_a_missing_reason():
    cases = {
        "run: uv run --no-sync pytest -q -n 4 tests": 1,
        "run: uv run pytest -q tests/test_x.py": 1,
        '"$PY" -m pytest -q tests': 1,
        "# Serial\nrun: uv run pytest -q tests": 1,
        "# Serial: too short\nrun: uv run pytest -q tests": 1,
        "# Serial: one fixture feeds every test, so\n\nrun: uv run pytest tests": 1,
        "run: uv run --no-sync pytest -q -n auto tests": 0,
        '"$PY" -m pytest -q -n auto tests': 0,
        "# Serial: one fixture feeds every test, so workers\n# would repeat it\nuv run pytest": 0,
        "uv pip install -q --python python . pytest pytest-xdist": 0,
        "# uv run pytest -q": 0,
    }
    for text, count in cases.items():
        assert len(_serial_pytest_problems(text)) == count, text


def test_every_workflow_prints_the_runners_cpus():
    """The CPU count `-n auto`, `pyright --threads` and the fuzz runner follow, in the log."""
    step = "      - name: CPUs\n        run: |\n          nproc\n"
    for path in sorted(WORKFLOWS.glob("*.yml")):
        assert step in path.read_text(encoding="utf-8"), path.name


def test_the_nightly_soak_runs_the_kill_suites_daily_and_never_retries():
    """scripts/stability.py's bar needs the nightly soak green; a retried or tolerated failure
    would hide the bug it found. Its rounds rerun the suites that kill runners and restart
    clusters, on every server, and the first failed round fails the job and opens an issue."""
    text = (WORKFLOWS / "soak-nightly.yml").read_text(encoding="utf-8")
    assert re.search(r'(?m)^    - cron: "\d+ \d+ \* \* \*"$', text), "scheduled daily"
    for tolerated in ("continue-on-error", "--reruns", "retry", "|| true", "set +e"):
        assert tolerated not in text, tolerated
    rounds = _job("soak-nightly.yml", "cluster")
    files = [
        path
        for pattern in re.findall(r"tests/oracle/[\w*]+\.py", rounds)
        for path in ROOT.glob(pattern)
    ]
    assert any("cluster.kill(" in path.read_text(encoding="utf-8") for path in files)
    assert any("mysql_server" in path.read_text(encoding="utf-8") for path in files)
    assert any("cluster_db" in path.read_text(encoding="utf-8") for path in files), "PostgreSQL"
    assert "exit 1" in rounds and 'PYFECT_REQUIRE_ALL_TESTS: "1"' in rounds
    assert "-m soak run" in _job("soak-nightly.yml", "soak")
    report = _job("soak-nightly.yml", "report")
    assert "needs: [images, cluster, soak]" in report
    assert "if: failure() || cancelled()" in report and "gh issue create" in report
