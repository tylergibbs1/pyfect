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
import _effect_ref
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
        assert _effect_ref.ENV in job, "the oracle tests need Effect's checkout"


def test_the_lint_job_checks_a_source_change_adds_a_fragment():
    """scripts/changelog_fragment.py finds HEAD's merge-base with main, so the checkout needs
    every commit; a shallow one fails the check instead of passing it."""
    lint = _job("ci.yml", "lint")
    assert "run: python3 scripts/changelog_fragment.py\n" in lint
    assert "fetch-depth: 0\n" in lint and "filter: blob:none\n" in lint


def test_one_pyright_run_checks_every_python():
    """Pyright analyses for pyproject's pythonVersion whatever runs it; the types job syncs that
    Python."""
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    version = re.search(r'(?m)^pythonVersion = "(3\.\d+)"$', pyproject)
    assert version, "pyproject.toml pins pyright's pythonVersion"
    synced = re.search(r'(?m)^          python: "(3\.\d+)\.\d+"$', _job("ci.yml", "types"))
    assert synced and synced.group(1) == version.group(1), "the types job syncs pythonVersion"


def test_ci_runs_the_batch_file_tests_on_windows():
    """``_skips.ALLOWED`` lets the Windows-only tests skip elsewhere because this job runs them."""
    job = _job("ci.yml", "windows")
    assert "runs-on: windows-latest" in job
    assert "tests/test_process_batch_files.py" in job


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
    assert f"--shard=${{{{ matrix.shard }}}}/{count} " in run.group(1)
    for narrowing in (" -k ", " -m ", "--deselect", "--ignore", " -x", "--maxfail", "--lf"):
        assert narrowing not in run.group(1), f"the shards must run every test: {narrowing}"
    assert "--shard-manifest=.shards/shard-${{ matrix.shard }}.txt" in run.group(1)
    assert "name: manifest-${{ matrix.python }}-${{ matrix.shard }}" in test

    collect = _job("ci.yml", "collect")
    assert "--collect-only -p no:randomly --shard-manifest=.shards/full.txt" in collect
    assert "name: manifest-${{ matrix.python }}-full" in collect

    check = _job("ci.yml", "check")
    jobs = ["lint", "types", "collect", "images", "test", "windows"]
    assert f"needs: [{', '.join(jobs)}]" in check
    # A required check that is skipped counts as passed, so it must run when a job failed.
    assert "if: always()" in check
    for job in jobs:
        assert f"${{{{ needs.{job}.result }}}}" in check, job
        assert f'[ "${job.upper()}" = success ]' in check, job
    assert "--pattern 'manifest-${{ matrix.python }}-*' --dir .shards" in check
    assert "actions: read" in check, "gh run download lists the run's artifacts"
    assert "scripts/test_shards.py verify .shards/*/full.txt .shards/*/shard-*.txt" in check


def test_ci_downloads_artifacts_without_the_download_artifact_action():
    """actions/download-artifact (v8.0.2 and earlier) leaves a failed blob request's socket
    open when it retries, so node stays alive until the socket's 3-minute timeout
    (actions/toolkit#2575). That cancelled `check (3.13)`, whose budget is 2 minutes, twice on
    2026-11-18, so ci.yml downloads with `gh run download`, which exits when it is done. The
    release's publish job keeps the action: it has no short budget, so the hang costs it at
    most 3 minutes, which is cheaper than changing the publish path untested."""
    text = (WORKFLOWS / "ci.yml").read_text(encoding="utf-8")
    using = [
        number
        for number, line in enumerate(text.splitlines(), 1)
        if "actions/download-artifact@" in line
    ]
    assert using == [], "use gh run download"


def _pushes_outside_main(text: str) -> bool:
    """Whether a workflow runs on a push to a branch other than main: a ``push`` trigger
    with no filter, a branch filter other than ``[main]``, or ``branches-ignore``. A push of
    tags only (release.yml) pushes no branch."""
    triggers = text.split("\njobs:\n", 1)[0]
    if re.search(r"(?m)^on:\s*(?:push|\[.*\bpush\b.*\])\s*$", triggers):
        return True
    found = re.search(r"(?m)^  push:[ \t]*\n((?:(?:    .*)?\n)*)", triggers + "\n")
    if found is None:
        return re.search(r"(?m)^  push:", triggers) is not None
    keys = re.findall(r"(?m)^    ([\w-]+):(.*)$", found.group(1))
    if not keys:
        return True
    return any(
        key == "branches-ignore" or (key == "branches" and value.strip() != "[main]")
        for key, value in keys
    ) or all(key not in ("branches", "tags") for key, _ in keys)


def test_no_workflow_runs_on_a_push_to_a_branch_other_than_main():
    """A branch push runs everything again on a commit its pull request (or main) checks."""
    for path in sorted(WORKFLOWS.glob("*.yml")):
        assert not _pushes_outside_main(path.read_text(encoding="utf-8")), path.name


def test_the_push_check_sees_each_way_a_branch_push_runs():
    def on(triggers: str) -> str:
        return f"on:\n{triggers}\njobs:\n  x:\n"

    assert _pushes_outside_main("on: push\njobs:\n")
    assert _pushes_outside_main("on: [push, pull_request]\njobs:\n")
    assert _pushes_outside_main(on("  push:\n  pull_request:\n"))
    assert _pushes_outside_main(on("  push:\n    branches: [main, 'stack-*']\n"))
    assert _pushes_outside_main(on("  push:\n    branches-ignore: [gh-pages]\n"))
    assert _pushes_outside_main(on("  push:\n    paths: [src/**]\n"))
    assert not _pushes_outside_main(on("  push:\n    branches: [main]\n  pull_request:\n"))
    assert not _pushes_outside_main(on('  push:\n    tags:\n      - "v*"\n'))
    assert not _pushes_outside_main(on("  pull_request:\n  schedule:\n"))


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


def _triggers(workflow: str) -> list[str]:
    """The lines of a workflow's `on:` block, without comments."""
    text = (WORKFLOWS / workflow).read_text(encoding="utf-8")
    block = re.search(r"(?ms)^on:\n(.*?)^\S", text)
    assert block, workflow
    return [ln for ln in block.group(1).splitlines() if ln.strip() and ln.split()[0] != "#"]


def test_pyright_checks_the_snippets_once_in_ci():
    """ci.yml's types job checks every file pyproject.toml includes, website/snippets too, on
    the same events docs.yml runs on; the snippets job ran pyright over them a second time."""
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    include = re.search(r"(?m)^include = (\[.*\])$", pyproject)
    assert include and "website/snippets" in json.loads(include.group(1))
    assert re.search(
        r'(?m)^        run: uv run --no-sync pyright --threads "\$\(nproc\)"$',
        _job("ci.yml", "types"),
    )
    assert _triggers("docs.yml") == _triggers("ci.yml")
    pyright_runs = re.compile(r"(?m)^[^#\n]*\bpyright\b")
    for path in sorted(WORKFLOWS.glob("*.yml")):
        runs = pyright_runs.findall(path.read_text(encoding="utf-8"))
        assert len(runs) == (1 if path.name == "ci.yml" else 0), (path.name, runs)


def _budget_problems(job: str) -> list[str]:
    """The job's last step fails it once it has taken over 80% of its timeout, from the
    `JOB_START` its first step records."""
    timeout = re.search(r"(?m)^    timeout-minutes: (\d+)$", job)
    steps = re.split(r"(?m)^      - ", job)
    problems: list[str] = []
    if 'echo "JOB_START=$(date +%s)" >> "$GITHUB_ENV"' not in steps[1]:
        problems.append("the first step does not record JOB_START")
    budget = re.search(r"(?m)^          TIMEOUT_MINUTES: (\d+)$", steps[-1])
    if not (timeout and budget and budget.group(1) == timeout.group(1)):
        problems.append("the last step's TIMEOUT_MINUTES is not the job's timeout-minutes")
    if "[ $(( took * 100 )) -le $(( budget * 80 )) ]" not in steps[-1]:
        problems.append("the last step does not fail above 80% of the budget")
    return problems


def test_the_snippets_job_fails_above_80_percent_of_its_budget():
    """Run 44735422935 took 195 s and was cancelled at the 180 s timeout, the snippets job's
    usual 102-161 s having crept up unnoticed. Now it fails, with its time, before that."""
    assert _budget_problems(_job("docs.yml", "snippets")) == []


def test_the_budget_guard_sees_a_stale_timeout_and_a_missing_start():
    job = _job("docs.yml", "snippets")
    assert _budget_problems(job.replace("timeout-minutes: 3", "timeout-minutes: 4")) == [
        "the last step's TIMEOUT_MINUTES is not the job's timeout-minutes"
    ]
    assert _budget_problems(job.replace('echo "JOB_START', 'echo "START')) == [
        "the first step does not record JOB_START"
    ]
    assert _budget_problems(job.replace("budget * 80", "budget * 95")) == [
        "the last step does not fail above 80% of the budget"
    ]


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
    assert re.search(r"--python 3\.14\.\d+t ", _job("extras.yml", "free-threaded"))


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
    for workflow in ("ci.yml", "extras.yml", "soak-nightly.yml", "flakes-nightly.yml"):
        text = (WORKFLOWS / workflow).read_text(encoding="utf-8")
        jobs = re.findall(r"(?m)^  ([\w-]+):\n", text.split("\njobs:\n", 1)[1])
        for job in jobs:
            budget = re.search(r"(?m)^    timeout-minutes: (\d+)$", _job(workflow, job))
            assert budget, f"{workflow}'s {job} has no timeout-minutes"


def test_no_budgeted_job_waits_on_a_package_mirror():
    """A job's tools come locked from PyPI (py-spy in uv.lock). Where one must come from apt (gdb,
    for free-threaded Python, which py-spy can't read), the step has its own short budget and
    can't fail the job: the mirrors once took 3 minutes of free-threaded's 4, and the job was
    cancelled as its tests finished."""
    for workflow in ("ci.yml", "extras.yml", "soak-nightly.yml", "flakes-nightly.yml"):
        text = (WORKFLOWS / workflow).read_text(encoding="utf-8")
        for step in re.split(r"(?m)^      - ", text)[1:]:
            if "apt-get" not in step and "apt install" not in step:
                continue
            name = step.splitlines()[0]
            assert re.search(r"(?m)^        timeout-minutes: 1$", step), f"{workflow}: {name}"
            assert re.search(r"(?m)^        continue-on-error: true$", step), f"{workflow}: {name}"


def test_a_release_needs_ci_its_extras_and_the_docs():
    release = (WORKFLOWS / "release.yml").read_text(encoding="utf-8")
    for job in ("ci", "extras", "docs"):
        assert f"uses: ./.github/workflows/{job}.yml" in _job("release.yml", job)
        assert "workflow_call:" in (WORKFLOWS / f"{job}.yml").read_text(encoding="utf-8")
    assert re.search(r"needs: \[ci, extras, docs\]", _job("release.yml", "build")), release


def test_the_local_python_request_names_the_gil_build():
    """Since uv 0.9 a request for "3.14" may resolve to a free-threaded 3.14t interpreter. Plain
    `uv run` in a worktree then rebuilt its venv on 3.14t, where psycopg-binary has no wheel, so the
    rebuild failed and left the venv without lefthook or pytest. CI passes --python explicitly."""
    request = (ROOT / ".python-version").read_text(encoding="utf-8").strip()
    assert request.endswith("+gil"), request


def test_the_check_runs_on_every_python_pyproject_lists():
    """CI once ran only the Python uv picked (3.14, from .python-version), so a 3.13-only
    failure could pass it. Branch protection requires `check (3.13)` and `check (3.14)`, so the
    check job is named by the minor version whatever patch its matrix runs."""
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    listed = re.findall(r'"Programming Language :: Python :: (3\.\d+)"', pyproject)
    minimum = re.search(r'requires-python = ">=(3\.\d+)"', pyproject)
    assert minimum and listed and listed[0] == minimum.group(1), "classifiers start at the minimum"
    pythons = _ci_pythons()
    assert [python.rpartition(".")[0] for python in pythons] == listed
    for name in ("collect", "test", "check"):
        job = _job("ci.yml", name)
        matrix = re.search(r"(?m)^        python: \[(.*)\]$", job)
        assert matrix, f"ci.yml's {name} job has no python matrix"
        assert re.findall(r'"([^"]+)"', matrix.group(1)) == pythons, name
    for name in ("collect", "test"):
        job = _job("ci.yml", name)
        assert "UV_PYTHON: ${{ matrix.python }}" in job
        assert "python: ${{ matrix.python }}" in job
    check = _job("ci.yml", "check")
    assert check.startswith("    # ") and "\n    name: check (${{ matrix.minor }})\n" in check
    minors = re.findall(r'(?m)^          - python: "([^"]+)"\n            minor: "([^"]+)"$', check)
    assert minors == [(python, python.rpartition(".")[0]) for python in pythons], minors
    setup = (ROOT / ".github" / "actions" / "check-setup" / "action.yml").read_text("utf-8")
    assert "PYTHON: ${{ inputs.python }}" in setup
    assert 'uv sync --locked --python "$PYTHON"' in setup
    assert "assert '$PYTHON' in (v, v.rpartition('.')[0]), v" in setup, "checks the patch it got"


def _ci_pythons() -> list[str]:
    """ci.yml's test matrix: one exact CPython patch per Python pyproject lists."""
    matrix = re.search(r"(?m)^        python: \[(.*)\]$", _job("ci.yml", "test"))
    assert matrix, "ci.yml's test job has no python matrix"
    return re.findall(r'"([^"]+)"', matrix.group(1))


# Every way a workflow or action names a Python: `--python X`, `uv python install X`, a
# `UV_PYTHON` or `python:` value, and a `python:` matrix list.
_PYTHON_REQUESTS = (
    r"--python (\S+)",
    r"uv python install (?:-q )?(\S+)",
    r"UV_PYTHON: (\S+)",
    r"(?m)^\s+(?:- )?python: (?!\[)(\S+)$",
)


def _python_requests(text: str) -> list[str]:
    found = [m.strip("\"';") for pattern in _PYTHON_REQUESTS for m in re.findall(pattern, text)]
    for matrix in re.findall(r"(?m)^\s+python: \[(.*)\]$", text):
        found += re.findall(r'"([^"]+)"', matrix)
    # An expression, a variable or an interpreter's path names no version itself.
    return [python for python in found if "$" not in python and "/" not in python]


def test_every_workflow_names_an_exact_cpython_patch():
    """A request for "3.14" takes whichever 3.14 the runner has: ci.yml's ran 3.14.4 while
    3.14.10 was out, and a failure only 3.14.0 has (an `inspect.signature` that 3.14.4 no longer
    reached) went unseen until the nightly ran 3.14.0. Every workflow names exact patches, and
    its newest of each minor version is ci.yml's, so a newer patch is one change everywhere; an
    older patch (the nightly's 3.14.0) is there on purpose."""
    ci = {python.rpartition(".")[0]: python for python in _ci_pythons()}
    files = [
        *sorted(WORKFLOWS.glob("*.yml")),
        ROOT / ".github" / "actions" / "check-setup" / "action.yml",
    ]
    for path in files:
        newest: dict[str, tuple[int, ...]] = {}
        for python in _python_requests(path.read_text(encoding="utf-8")):
            exact = re.fullmatch(r"(3\.\d+)\.(\d+)t?", python)
            assert exact, f"{path.name} asks for Python {python!r}, not an exact patch"
            assert exact.group(1) in ci, f"{path.name}: {python} is no Python ci.yml runs"
            patch = tuple(int(n) for n in python.removesuffix("t").split("."))
            newest[exact.group(1)] = max(newest.get(exact.group(1), patch), patch)
        for minor, patch in newest.items():
            assert ".".join(map(str, patch)) == ci[minor], f"{path.name}'s newest {minor}"
    # The nightly hunts flakes on the patches the pull requests run, and on 3.14.0.
    nightly = _python_requests(_job("flakes-nightly.yml", "suite"))
    assert set(ci.values()) <= set(nightly), (nightly, ci)


def test_the_python_request_finder_sees_every_form():
    found = _python_requests(
        "        run: uv sync --locked --python 3.13 --group fuzz\n"
        "          uv python install -q 3.14t; fi\n"
        '      UV_PYTHON: "3.14"\n'
        '          python: "3.13"\n'
        '            python: "3.14"\n'
        '        python: ["3.13", "3.14t"]\n'
        "      UV_PYTHON: ${{ matrix.python }}\n"
        '        uv sync --locked --python "$PYTHON"\n'
    )
    assert sorted(found) == ["3.13", "3.13", "3.13", "3.14", "3.14", "3.14t", "3.14t"]


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
    assert _effect_ref.ENV in job and "setup-node" in job


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
            # A PR changing only the tests runs them too (redis-py 8.2.0 broke a test harness).
            assert f'"{pattern}"' in triggers, f"{extra}: a PR changing {pattern} skips the job"


def _image_keys_named_in(path: Path) -> list[str]:
    """The keys of the ``_container_images.image("key")`` calls in ``path``."""
    if not _source.mentions(path, "_container_images"):  # parsing every fixture costs 3 s
        return []
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
    if not _source.mentions(path, "IMAGE"):
        return []
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


def test_the_image_scan_finds_a_named_key_and_a_literal_image(tmp_path: Path):
    fixture = tmp_path / "conftest_fixture.py"
    fixture.write_text(
        'POSTGRES_IMAGE = "postgres:17"\n\n\n'
        "def start():\n"
        '    return _container_images.image("uncached")\n'
    )
    assert _literal_images_in(fixture) == ["conftest_fixture.py:1"]
    assert _image_keys_named_in(fixture) == ["uncached"]
    assert "uncached" not in _container_images.IMAGES


def test_the_server_tests_load_the_cached_images_and_never_pull():
    """One job per workflow pulls each pinned image once and caches the archives; every job
    that runs server tests restores them under the same key, made from the pins, fails on a
    miss, and loads the images it names before its tests start (.github/actions/container-images).
    The tests loaded each image when one first needed it, writing GBs to the disk while other
    tests ran: a subprocess's imports waited on it until its test timed out (run 45937052191)."""
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
    assert 'python3 tests/_container_images.py load .images "$IMAGES"' in action
    assert 'echo "PYFECT_IMAGES_PRELOADED=$IMAGES" >> "$GITHUB_ENV"' in action
    save = "uses: ./.github/actions/container-images\n        with:\n          mode: save"
    load = re.compile(
        r"uses: \./\.github/actions/container-images\n        with:\n          mode: load\n"
        r"          images: (?P<images>.+)\n"
    )
    for workflow, saver, runner, images in (
        ("ci.yml", "images", "test", ["all"]),
        ("drivers.yml", "images", "driver", ["mysql busybox", "mssql busybox", "redis"]),
        ("soak-nightly.yml", "images", "cluster", ["all"]),
        ("flakes-nightly.yml", "images", "suite", ["all"]),
        ("docs.yml", "images", "snippets", ["mysql mssql clickhouse"]),
    ):
        assert save in _job(workflow, saver), f"{workflow}'s {saver} job saves no images"
        job = _job(workflow, runner)
        loaded = load.search(job)
        assert f"needs: {saver}" in job and loaded, f"{workflow}'s {runner} job loads no images"
        tests = _PYTEST_RUN.search(job)
        assert tests and loaded.end() < tests.start(), f"{workflow}'s {runner} job: load first"
        if loaded["images"] == "${{ matrix.driver.images }}":
            assert re.findall(r"(?m)^ {12}images: (.+)$", job) == images, workflow
        else:
            assert [loaded["images"]] == images, workflow
        for named in images:
            _container_images.named(named)  # each names cached images
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


def _runs_on_a_push_to_main(text: str) -> bool:
    triggers = text.split("\njobs:\n", 1)[0]
    return re.search(r"(?m)^  push:\n    branches: \[main\]$", triggers) is not None


def test_a_failed_run_on_main_opens_an_issue_for_every_push_workflow():
    """No workflow but ci is a required check, so a red run on main is silent unless
    main-alert.yml opens an issue for it (fuzz was red on main for 13 hours unseen). It must
    follow every workflow a push to main runs, by name, and only runs of pushes to main."""
    pushed = {
        re.search(r"(?m)^name: (.+)$", text).group(1)  # pyright: ignore[reportOptionalMemberAccess]
        for path in sorted(WORKFLOWS.glob("*.yml"))
        if _runs_on_a_push_to_main(text := path.read_text(encoding="utf-8"))
    }
    assert "fuzz" in pushed
    alert = (WORKFLOWS / "main-alert.yml").read_text(encoding="utf-8")
    triggers = alert.split("\njobs:\n", 1)[0]
    followed = re.search(r"(?m)^    workflows: \[(.*)\]$", triggers)
    assert followed, "main-alert.yml follows no workflows"
    assert {name.strip() for name in followed.group(1).split(",")} == pushed
    assert re.search(r"(?m)^    types: \[completed\]$", triggers)
    assert re.search(r"(?m)^    branches: \[main\]$", triggers)
    assert "github.event.workflow_run.event == 'push'" in alert
    for command in ("gh issue create", "gh issue comment", "gh issue close"):
        assert command in alert, command


def _steps(job: str) -> dict[str, str]:
    """A job's named steps by name."""
    found: dict[str, str] = {}
    for step in re.split(r"(?m)^      - ", job)[1:]:
        name = re.match(r"name: (.*)$", step.splitlines()[0])
        if name:
            found[name.group(1)] = step
    return found


def test_the_nightly_flake_hunt_reruns_the_suite_as_ci_runs_it_and_tolerates_nothing():
    """flakes-nightly.yml finds the one-in-a-hundred failures a release's rerun used to: ci.yml's
    shards and extras.yml's free-threaded suites, round after round in new random orders on
    exact CPython patches. A retried, skipped or slower-allowed test would hide the flake."""
    text = (WORKFLOWS / "flakes-nightly.yml").read_text(encoding="utf-8")
    for tolerated in (
        "--reruns", "retry", "|| true", "set +e", "--timeout", "-p no:randomly", " -x",
        "--maxfail", "--lf", " -k ", " -m \"", " -m '", "--deselect", "--ignore",
    ):  # fmt: skip
        assert tolerated not in text, tolerated
    tolerant = [step for step in re.split(r"(?m)^      - ", text) if "continue-on-error" in step]
    assert all("apt-get install -y -qq gdb" in step for step in tolerant), "only gdb may fail"

    suite = _job("flakes-nightly.yml", "suite")
    ci_test = _job("ci.yml", "test")
    shards = re.search(r"(?m)^\s+shard: \[(.*)\]$", ci_test)
    assert shards and f"        shard: [{shards.group(1)}]" in suite, "ci.yml's shards"
    count = len(shards.group(1).split(","))
    assert (
        f"uv run --no-sync pytest -q -rfEs -n auto --shard=${{{{ matrix.shard }}}}/{count}\n"
        in suite
    )
    for setup in ("uses: ./.github/actions/check-setup", "python: ${{ matrix.python }}"):
        assert setup in suite, setup
    for env in (
        "UV_PYTHON: ${{ matrix.python }}",
        'PYFECT_REQUIRE_ALL_TESTS: "1"',
        _effect_ref.ENV,
    ):
        assert env in suite and env in ci_test, env
    ci_steps, nightly_steps = _steps(ci_test), _steps(suite)
    for name in ("Fetch main", "Warm up pwsh"):
        run = re.search(r"(?m)^        run: (.*)$", ci_steps[name])
        assert run and run.group(0) in nightly_steps[name], f"{name} as in ci.yml's test job"

    # Exact patches of every Python pyproject lists, 3.14's oldest among them.
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    listed = re.findall(r'"Programming Language :: Python :: (3\.\d+)"', pyproject)
    matrix = re.search(r"(?m)^        python: \[(.*)\]$", suite)
    assert matrix, "the suite job has no python matrix"
    pythons = re.findall(r'"([^"]+)"', matrix.group(1))
    assert all(re.fullmatch(r"3\.\d+\.\d+", python) for python in pythons), pythons
    assert {python.rpartition(".")[0] for python in pythons} == set(listed)
    assert "3.14.0" in pythons
    newest = max(pythons, key=lambda v: tuple(int(n) for n in v.split(".")))
    threaded = _job("flakes-nightly.yml", "free-threaded")
    assert f'        python: ["{newest}t"]' in threaded, "3.14t at the suite's newest 3.14"
    for env in ('PYTHON_GIL: "0"', 'PYFECT_REQUIRE_FREE_THREADED: "1"'):
        assert env in threaded and env in _job("extras.yml", "free-threaded"), env

    # One list of free-threaded suites, read by both jobs that run it.
    suites = "$(sed 's/#.*//' tests/free_threaded_suites.txt)"
    assert suites in threaded and suites in _job("extras.yml", "free-threaded")
    listing = (ROOT / "tests" / "free_threaded_suites.txt").read_text(encoding="utf-8")
    paths = [line.split("#")[0].strip() for line in listing.splitlines()]
    assert [path for path in paths if path and not (ROOT / path).exists()] == []

    for job in (suite, threaded):
        assert "scripts/flakes.py rounds" in job and '--minutes "$MINUTES"' in job
        budget = re.search(r"(?m)^    timeout-minutes: (\d+)$", job)
        assert budget and int(budget.group(1)) >= 50 + 15, "the longest rounds, setup and one more"
    report = _job("flakes-nightly.yml", "report")
    assert "needs: [images, suite, free-threaded]" in report and "if: always()" in report
    assert "python3 scripts/flakes.py report --out flake-report flake-rounds" in report
    # upload-artifact leaves out hidden files: a `.flakes` directory uploaded nothing, and the
    # report found no rounds.
    uploads = re.findall(r"(?m)^          path: (.*)$", text)
    assert uploads and not [path for path in uploads if path.startswith(".")], uploads
    for job in (suite, threaded):
        assert "path: ${{ runner.temp }}/flake-rounds\n          if-no-files-found: error" in job
    assert (
        '[ "$IMAGES" = success ] && [ "$SUITE" = success ] && [ "$FREE_THREADED" = success ]'
        in report
    )


def test_the_nightly_flake_hunt_only_reads_and_gates_nothing():
    """It runs on a schedule (and by hand) and only reads: no release or pull request waits on
    it, it publishes nothing, and it opens no issue, since what to file in public is the
    maintainers' call."""
    text = (WORKFLOWS / "flakes-nightly.yml").read_text(encoding="utf-8")
    triggers = text.split("\njobs:\n", 1)[0]
    assert re.findall(r"(?m)^  (\w+):", triggers.split("\non:\n", 1)[1].split("\n\n", 1)[0]) == [
        "schedule",
        "workflow_dispatch",
    ]
    assert re.search(r'(?m)^    - cron: "\d+ \d+ \* \* \*"$', triggers), "daily"
    for path in sorted(WORKFLOWS.glob("*.yml")):
        if path.name != "flakes-nightly.yml":
            assert "workflows/flakes-nightly.yml" not in path.read_text(encoding="utf-8"), path.name
    levels = re.findall(r"(?m)^ +(?:contents|actions|[\w-]+): (read|write|none)$", text)
    assert levels and set(levels) == {"read"}, "every permission is read-only"
    assert re.findall(r"\$\{\{\s*(secrets\.\w+)", text) == [], "no secrets"
    assert "GH_TOKEN: ${{ github.token }}" in text
    for publishing in ("gh issue", "gh release", "gh pr ", "git push", "pypi", "upload-release"):
        assert publishing not in text, publishing
