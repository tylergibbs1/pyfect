"""The guides' Python code runs, and only comes from checked files.

Every Python block in `website/content/docs` is an `<include>` of a file under
`website/snippets`, which pyright checks and these tests run (the site is built
from `website/` alone, so guides can't include files outside it):
a snippet asserts its own results, and `test_*.py` snippets are pytest files.

Snippets under `postgres/` and `mysql/` read `DATABASE_URL`: each runs on a fresh database
of the throwaway server the pg or MySQL tests use (`tests/oracle/_postgres.py`,
`tests/oracle/_mysql.py`), and skips without one. Those under `clickhouse/` read
`CLICKHOUSE_URL` and its credentials, of the ClickHouse tests' server
(`tests/oracle/_clickhouse.py`), and make their own tables.
The site build never runs snippets, so it needs no server.

A snippet that prints has its output next to it (`x.py` -> `x.out`), which guides show
in "Output" tabs. The file must equal what running the snippet prints; regenerate with

    UPDATE_SNIPPET_OUTPUT=1 uv run pytest tests/test_doc_snippets.py
"""

import os
import re
import subprocess
import sys
from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path

import _source
import pytest
from _count_sleeps import MARKER
from _inventory import parse
from _next_item import NEXT_ITEM

from pyfect.duration import from_input_unsafe

ROOT = Path(__file__).parent.parent
SNIPPETS = ROOT / "website" / "snippets"
GUIDES = ROOT / "website" / "content" / "docs"

INCLUDE = re.compile(r"<include[^>]*>\s*([^<]+?)\s*</include>")
PYTHON_FENCE = re.compile(r"^\s*(```|~~~)\s*(py|python|python3|pycon)\b", re.MULTILINE)


def snippet_files() -> list[Path]:
    return list(_source.files(SNIPPETS))


def output_files() -> list[Path]:
    return sorted(SNIPPETS.rglob("*.out"))


def guide_files() -> list[Path]:
    return sorted(GUIDES.rglob("*.mdx"))


def included_files(guide: Path) -> list[Path]:
    """The files a guide includes, resolved as Fumadocs does: relative to the
    guide, with any `#region` suffix removed."""
    targets = INCLUDE.findall(guide.read_text())
    return [(guide.parent / target.split("#")[0]).resolve() for target in targets]


def run(*args: str, env: dict[str, str] | None = None) -> subprocess.CompletedProcess[str]:
    """Runs on a worker thread (see `runs`), so the child gets a copy of the environment:
    inheriting it would have the child exec with the process's own environment array, which
    pytest rewrites on the main thread (PYTEST_CURRENT_TEST), and exec failed with EFAULT."""
    # -P: don't put the snippet's directory on sys.path, as `python file.py` would.
    return subprocess.run(
        [sys.executable, "-P", *args],
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
        cwd=ROOT,
        env=os.environ | (env or {}),
    )


POSTGRES = SNIPPETS / "postgres"
MYSQL = SNIPPETS / "mysql"
MSSQL = SNIPPETS / "mssql"
CLICKHOUSE = SNIPPETS / "clickhouse"


def mysql_env(path: Path) -> dict[str, str]:
    """`DATABASE_URL` of a new, empty database for a MySQL snippet."""
    from oracle._mysql import query_now, server

    mysql = server()  # skips without Docker
    database = "snippet_" + "_".join(path.relative_to(MYSQL).with_suffix("").parts)
    query_now(f"DROP DATABASE IF EXISTS `{database}`", root=True)
    query_now(f"CREATE DATABASE `{database}`", root=True)
    return {"DATABASE_URL": mysql.uri(root=True).rpartition("/")[0] + f"/{database}"}


def mssql_env(path: Path) -> dict[str, str]:
    """The server and a new, empty database for a SQL Server snippet."""
    from oracle._mssql import PASSWORD, query_now, server

    mssql = server()  # skips without Docker
    database = "snippet_" + "_".join(path.relative_to(MSSQL).with_suffix("").parts)
    query_now(
        f"IF DB_ID('{database}') IS NOT NULL BEGIN "
        f"ALTER DATABASE [{database}] SET SINGLE_USER WITH ROLLBACK IMMEDIATE; "
        f"DROP DATABASE [{database}] END"
    )
    query_now(f"CREATE DATABASE [{database}]")
    return {
        "MSSQL_SERVER": mssql.host,
        "MSSQL_PORT": str(mssql.port),
        "MSSQL_DATABASE": database,
        "MSSQL_PASSWORD": PASSWORD,
    }


def clickhouse_env() -> dict[str, str]:
    """The URL and credentials of the ClickHouse server the driver's tests use."""
    from oracle._clickhouse import PASSWORD, USER, server

    clickhouse = server()  # skips without Docker
    return {
        "CLICKHOUSE_URL": clickhouse.url,
        "CLICKHOUSE_USER": USER,
        "CLICKHOUSE_PASSWORD": PASSWORD,
    }


def snippet_env(path: Path) -> dict[str, str] | None:
    """`DATABASE_URL` of a new, empty database for a PostgreSQL or MySQL
    snippet; the server and database of a SQL Server one."""
    if path.is_relative_to(MYSQL):
        return mysql_env(path)
    if path.is_relative_to(MSSQL):
        return mssql_env(path)
    if path.is_relative_to(CLICKHOUSE):
        return clickhouse_env()
    if not path.is_relative_to(POSTGRES):
        return None
    from oracle._postgres import query_now, server

    pg = server()  # skips without a local PostgreSQL
    database = "snippet_" + "_".join(path.relative_to(POSTGRES).with_suffix("").parts)
    query_now(f'DROP DATABASE IF EXISTS "{database}" WITH (FORCE)')
    query_now(f'CREATE DATABASE "{database}"')
    return {"DATABASE_URL": pg.uri.rpartition("/")[0] + f"/{database}"}


def name(path: Path) -> str:
    return str(path.relative_to(SNIPPETS))


SCRIPTS = [p for p in snippet_files() if not p.name.startswith("test_")]
TESTS = [p for p in snippet_files() if p.name.startswith("test_")]
SERVERS = (POSTGRES, MYSQL, MSSQL, CLICKHOUSE)


COUNT_SLEEPS = Path(__file__).parent / "_count_sleeps.py"


def snippet_args(path: Path) -> tuple[str, ...]:
    """A snippet runs as `python file.py`; a `test_*.py` snippet under pytest. Either way
    `_count_sleeps.py` runs it, to report the live-clock sleeps it completed."""
    if path.name.startswith("test_"):
        return (str(COUNT_SLEEPS), "-m", "pytest", "-q", "-p", "no:cacheprovider", str(path))
    return (str(COUNT_SLEEPS), str(path))


SLEEP_LIMIT = 5.0
FIXED_BELOW = SLEEP_LIMIT / 2
LONGER_SLEEPS = Path(__file__).parent / "_snippet_sleeps.txt"
"""``snippet limit  # reason`` per line (``tests/_inventory.py``): a snippet allowed more
than 5 s of completed live-clock sleep, with its measured totals and the waits behind them."""


def sleep_limits() -> dict[str, float]:
    return {
        snippet: from_input_unsafe(entry.value).to_seconds()
        for snippet, entry in parse(LONGER_SLEEPS.read_text()).items()
    }


def slept(done: subprocess.CompletedProcess[str]) -> float:
    """The live-clock sleep a run completed, from `_count_sleeps.py`'s line on stderr."""
    totals = [line[len(MARKER) :] for line in done.stderr.splitlines() if line.startswith(MARKER)]
    assert len(totals) == 1, f"no {MARKER!r} line: the run did not exit through atexit"
    return float(totals[0])


def assert_sleeps_in_limit(snippet: str, done: subprocess.CompletedProcess[str]) -> None:
    """A snippet may complete 5 s of live-clock sleep: timing beyond that belongs on the
    TestClock, or must get faster. A listed snippet gets its own limit, and once it is
    under half the default it is fixed and its line goes."""
    total = slept(done)
    listed = sleep_limits().get(snippet)
    if listed is None:
        assert total <= SLEEP_LIMIT, (
            f"{snippet} completed {total:.2f} s of live-clock sleep, over {SLEEP_LIMIT:g} s: "
            "move its timing to the TestClock or make it faster"
        )
    else:
        assert FIXED_BELOW <= total <= listed, (
            f"{snippet} completed {total:.2f} s of live-clock sleep; its limit in "
            f"{LONGER_SLEEPS.name} is {listed:g} s"
            + (": it is fixed, delete its line" if total < FIXED_BELOW else "")
        )


def assert_ran(done: subprocess.CompletedProcess[str]) -> None:
    """Fails unless a run exited 0. `run_main` reports a failure on stdout, so the message
    is both streams in full: pytest truncates the CompletedProcess repr."""
    assert done.returncode == 0, f"stdout:\n{done.stdout}\nstderr:\n{done.stderr}"


def run_with_server(path: Path) -> subprocess.CompletedProcess[str]:
    return run(*snippet_args(path), env=snippet_env(path))


def snippet_threads(cpus: int, workers: int) -> int:
    """Snippet runs at once: this process's share of the CPUs, one left free."""
    return max(1, cpus // workers - 1)


CLUSTER = SNIPPETS / "cluster"
CLUSTER_SCRIPTS = [p for p in SCRIPTS if p.is_relative_to(CLUSTER)]

# Printed to stderr by `SLOW_DRAIN` each time it delays a drain.
DELAYED_DRAIN = "slow-drain: delayed a drain"

# Runs a snippet with each entity's drain starting 600 ms late, as a loaded machine can make
# it: whether a job finishes before its runner stops must not decide a snippet's outcome.
SLOW_DRAIN = f"""
import runpy, sys
import pyfect as fx
from pyfect.cluster._entity_manager._activation import _Activation
drain = _Activation.drain
marked = fx.sync(lambda: print({DELAYED_DRAIN!r}, file=sys.stderr, flush=True))
_Activation.drain = lambda self: marked.and_then(fx.sleep("600 millis")).and_then(
    fx.suspend(lambda: drain(self))
)
runpy.run_path(sys.argv[1], run_name="__main__")
"""

# A runner unregisters when it starts to stop, so a `RunnerStorage sync` during its drain
# finds no healthy runners and warns, as Effect's Sharding does. A delayed drain makes that
# overlap likely, so a slow-drain run may print this record on top of the snippet's output.
STOPPING_RUNNER_LOG = re.compile(
    r"^\[[\d:.]+\] WARN \(#\d+\): No healthy runners available "
    r"\{'module': 'effect/cluster/Sharding', 'fiber': 'RunnerStorage sync', .*\}\n",
    re.MULTILINE,
)


def slow_drain_output(done: subprocess.CompletedProcess[str]) -> str:
    """A slow-drain run's stdout, without the stopping runner's warnings if a drain was
    delayed. Without a delayed drain the warning is not explained, so it stays."""
    if DELAYED_DRAIN not in done.stderr.splitlines():
        return done.stdout
    return STOPPING_RUNNER_LOG.sub("", done.stdout)


SNIPPET_TESTS = (
    "test_snippet_runs",
    "test_snippet_tests_pass",
    "test_cluster_snippet_with_a_slow_drain",
    "test_cluster_snippet_with_slow_storage",
)

# A run of a snippet: the name of the test that checks it, and the snippet.
type RunKey = tuple[str, Path]

RUN_LOG = "PYFECT_SNIPPET_RUN_LOG"
"""A file each started run appends a line to (its xdist worker, test and snippet), for
``test_each_worker_starts_only_its_own_runs``."""


def run_key(item: pytest.Item | None) -> RunKey | None:
    """The run ``item`` checks, if it is a snippet test."""
    if (
        isinstance(item, pytest.Function)
        and item.originalname in SNIPPET_TESTS
        and isinstance(path := item.callspec.params["path"], Path)
    ):
        return item.originalname, path
    return None


class Runs:
    """Snippet runs, each started once, the first time it is asked for. A run is mostly an
    interpreter importing pyfect, so one after another they took minutes: they run side by
    side on this process's share of the CPUs (the other xdist workers have the rest), one left
    free, as some snippets time their own wake-ups (threads/lag.py) and a CPU taken by another
    run would make them late, as it would other workers' tests. Snippets of a database server
    share it, so they run one at a time, alongside the others; one that finds no server skips
    its test."""

    def __init__(self, pool: ThreadPoolExecutor, servers: ThreadPoolExecutor) -> None:
        self._pool = pool
        self._servers = servers
        self._started: dict[RunKey, Future[subprocess.CompletedProcess[str]]] = {}

    def __getitem__(self, key: RunKey) -> Future[subprocess.CompletedProcess[str]]:
        return self.start(key)

    def start(self, key: RunKey) -> Future[subprocess.CompletedProcess[str]]:
        started = self._started.get(key)
        if started is None:
            started = self._started[key] = self._submit(*key)
            log = os.environ.get(RUN_LOG)
            if log:
                worker = os.environ.get("PYTEST_XDIST_WORKER", "main")
                with Path(log).open("a") as lines:
                    lines.write(f"{worker} {key[0]} {name(key[1])}\n")
        return started

    def _submit(self, test: str, path: Path) -> Future[subprocess.CompletedProcess[str]]:
        if test == "test_cluster_snippet_with_a_slow_drain":
            return self._pool.submit(run, "-c", SLOW_DRAIN, str(path))
        if test == "test_cluster_snippet_with_slow_storage":
            return self._pool.submit(run, str(SLOW_STORAGE), str(path))
        if any(path.is_relative_to(server) for server in SERVERS):
            return self._servers.submit(run_with_server, path)
        return self._pool.submit(run, *snippet_args(path))


@pytest.fixture(scope="module")
def runs(request: pytest.FixtureRequest) -> Iterator[Runs]:
    """This process's snippet runs. Without xdist it runs every collected test, in order, so
    their runs all start at once and a test waits only for the few ahead of it. An xdist
    worker's ``session.items`` lists every collected test, not only those it is sent, so it
    starts a run only when its test, or the test before it (``start_the_next_run``), asks:
    starting them all made each worker run every snippet, and a worker's database snippet
    queued behind all the others."""
    workers = int(os.environ.get("PYTEST_XDIST_WORKER_COUNT", "1"))
    pool = ThreadPoolExecutor(max_workers=snippet_threads(os.process_cpu_count() or 1, workers))
    servers = ThreadPoolExecutor(max_workers=1)
    started = Runs(pool, servers)
    if not hasattr(request.config, "workerinput"):
        for item in request.session.items:
            key = run_key(item)
            if key is not None:
                started.start(key)
    try:
        yield started
    finally:
        pool.shutdown(cancel_futures=True)
        servers.shutdown(cancel_futures=True)


@pytest.fixture(autouse=True)
def start_the_next_run(request: pytest.FixtureRequest) -> None:
    """A snippet test's run, then the next test's, start now: the next one is under way while
    this test waits on its own."""
    keys = [run_key(request.node), run_key(request.node.stash.get(NEXT_ITEM, None))]
    wanted = [key for key in keys if key is not None]
    if wanted:
        started: Runs = request.getfixturevalue("runs")
        for key in wanted:
            started.start(key)


@pytest.mark.parametrize("path", SCRIPTS, ids=name)
def test_snippet_runs(path: Path, runs: Runs):
    done = runs["test_snippet_runs", path].result()
    assert_ran(done)
    assert_sleeps_in_limit(name(path), done)
    expected = path.with_suffix(".out")
    if os.environ.get("UPDATE_SNIPPET_OUTPUT") and done.stdout:
        expected.write_text(done.stdout)
    if expected.exists():
        assert done.stdout == expected.read_text(), (
            f"{name(expected)} is stale: rerun with UPDATE_SNIPPET_OUTPUT=1"
        )
    else:
        assert not done.stdout, (
            f"{name(path)} prints; write {name(expected)} with UPDATE_SNIPPET_OUTPUT=1"
        )


@pytest.mark.parametrize("path", snippet_files(), ids=name)
def test_snippet_names_do_not_shadow_the_standard_library(path: Path):
    """Readers run `python file.py`, which puts the file's directory first on sys.path:
    a snippet named `queue.py` would hide the stdlib module and break `import pyfect`.
    `run` uses -P, so test_snippet_runs can't see this."""
    assert path.stem not in sys.stdlib_module_names, (
        f"{name(path)} shadows the standard-library module {path.stem!r}: rename it"
    )


@pytest.mark.parametrize("path", output_files(), ids=name)
def test_outputs_belong_to_snippets(path: Path):
    assert path.with_suffix(".py").is_file(), f"{name(path)} has no snippet"


@pytest.mark.parametrize("path", TESTS, ids=name)
def test_snippet_tests_pass(path: Path, runs: Runs):
    done = runs["test_snippet_tests_pass", path].result()
    assert_ran(done)
    assert_sleeps_in_limit(name(path), done)


@pytest.mark.parametrize("path", CLUSTER_SCRIPTS, ids=name)
def test_cluster_snippet_with_a_slow_drain(path: Path, runs: Runs):
    """CI's load once had cluster/drain.py's runner reach its entity's drain after the
    half-second job had finished, which is right (Effect does the same), and the snippet's
    handover assertion failed. A runner that is slow to stop must not change any output."""
    done = runs["test_cluster_snippet_with_a_slow_drain", path].result()
    assert_ran(done)
    expected = path.with_suffix(".out")
    assert slow_drain_output(done) == (expected.read_text() if expected.exists() else "")


SLOW_STORAGE = Path(__file__).parent / "_slow_storage.py"


@pytest.mark.parametrize("path", CLUSTER_SCRIPTS, ids=name)
def test_cluster_snippet_with_slow_storage(path: Path, runs: Runs):
    """CI's disk once made cluster/drain.py's runners take seconds to stop, and their poll
    loops slept on for 7.3 s in all. A snippet's sleep must not depend on how fast the
    disk is; a listed snippet is held to its own limit here too (cluster/runners.py, left
    out, later overran its 18 s by up to 878 s on CI's disks)."""
    done = runs["test_cluster_snippet_with_slow_storage", path].result()
    assert_ran(done)
    assert_sleeps_in_limit(name(path), done)
    expected = path.with_suffix(".out")
    assert done.stdout == (expected.read_text() if expected.exists() else "")


def test_slow_storage_slows_file_commits_only(tmp_path: Path):
    from _slow_storage import SlowCommits, slow_connect

    def delayed(database: str) -> int:
        db = slow_connect(database, isolation_level=None)
        db.execute("CREATE TABLE t (x)")
        for i in range(5):
            db.execute("INSERT INTO t VALUES (?)", (i,))
        db.execute("BEGIN")
        db.execute("INSERT INTO t VALUES (5)")
        db.execute("COMMIT")
        db.execute("SELECT * FROM t").fetchall()
        db.close()
        return db.delayed if isinstance(db, SlowCommits) else 0

    # Five INSERTs commit on their own; the one inside the transaction waits at its COMMIT.
    assert delayed(str(tmp_path / "file.db")) == 6
    assert delayed(":memory:") == 0


STOPPING_RUNNER = Path(__file__).parent / "_stopping_runner.py"


def test_a_delayed_drain_explains_a_stopping_runners_warning():
    """A slow-drain run of cluster/cron.py printed the stopping runner's warning in CI.
    It is real, so it is printed, but the delay made the overlap that caused it."""
    done = run("-c", SLOW_DRAIN, str(STOPPING_RUNNER))
    assert_ran(done)
    assert "No healthy runners available" in done.stdout
    assert slow_drain_output(done) == "stopping\n"


def test_without_a_delayed_drain_the_warning_stays():
    done = run("-c", SLOW_DRAIN, str(STOPPING_RUNNER))
    assert_ran(done)
    undelayed = subprocess.CompletedProcess(done.args, 0, done.stdout, stderr="")
    assert slow_drain_output(undelayed) == done.stdout != "stopping\n"


def test_a_failed_run_reports_all_its_output():
    """A snippet's error is on stdout (cluster/drain.py failed in CI with only a truncated
    repr to show for it), and a long one must not be cut."""
    error = "\n".join(f"line {i}" for i in range(500))
    done = run(
        "-c", f"import sys; print({error!r}); print('to stderr', file=sys.stderr); sys.exit(1)"
    )
    with pytest.raises(AssertionError) as failed:
        assert_ran(done)
    shown = [line.strip() for line in str(failed.value).splitlines()]
    assert all(line in shown for line in [*error.splitlines(), "to stderr"])


def test_a_snippet_sleeping_over_the_limit_fails():
    """60 sleeps of 100 ms at once complete 6 s of live-clock sleep in a tenth of a second."""
    done = run(*snippet_args(Path(__file__).parent / "_sleeps_six_seconds.py"))
    assert_ran(done)
    assert slept(done) == pytest.approx(6.0)
    with pytest.raises(AssertionError, match="over 5 s"):
        assert_sleeps_in_limit("_sleeps_six_seconds.py", done)


def test_listed_sleeps_are_snippets():
    assert set(sleep_limits()) <= {name(p) for p in snippet_files()}


def test_there_are_guides_and_snippets():
    assert guide_files() and SCRIPTS and TESTS


@pytest.mark.parametrize("guide", guide_files(), ids=lambda p: p.name)
def test_guides_have_no_inline_python(guide: Path):
    """Python in a guide must be an `<include>` of a checked file."""
    assert not PYTHON_FENCE.search(guide.read_text()), (
        f"{guide.name} has an inline Python block: move it to website/snippets and include it"
    )


@pytest.mark.parametrize("guide", guide_files(), ids=lambda p: p.name)
def test_guides_include_only_checked_files(guide: Path):
    for target in included_files(guide):
        assert target.is_file(), f"{guide.name} includes a missing file: {target}"
        assert target.is_relative_to(SNIPPETS.resolve()), (
            f"{guide.name} includes {target}, outside website/snippets"
        )


def test_every_snippet_is_used_by_a_guide():
    used = {path for guide in guide_files() for path in included_files(guide)}
    unused = [name(p) for p in [*snippet_files(), *output_files()] if p.resolve() not in used]
    assert not unused, f"snippets no guide includes: {unused}"


DIAGRAMS = ROOT / "website" / "diagrams"
DIAGRAM = re.compile(r'<Diagram\s+name="([^"]+)"')


def test_diagrams_exist_and_are_used():
    """Guides draw diagrams from `website/diagrams/<name>.mmd` (rendered by pele at build)."""
    used = {name for guide in guide_files() for name in DIAGRAM.findall(guide.read_text())}
    files = {path.stem for path in DIAGRAMS.glob("*.mmd")}
    assert used <= files, f"missing diagram files: {sorted(used - files)}"
    assert files <= used, f"diagrams no guide uses: {sorted(files - used)}"


def test_the_snippet_runs_leave_the_other_xdist_workers_their_cpus():
    # Four workers on a four-CPU runner: three more snippet threads would make seven busy
    # processes, and tests on the other workers that time themselves ran late.
    assert snippet_threads(cpus=4, workers=4) == 1
    assert snippet_threads(cpus=18, workers=4) == 3
    assert snippet_threads(cpus=4, workers=1) == 3
    assert snippet_threads(cpus=1, workers=1) == 1


CHEAP_SNIPPETS = (
    "atoms/atoms.py",
    "batching/sizes.py",
    "asyncio_apps/memo_map.py",
    "cli/deploy_help.py",
)


def test_each_worker_starts_only_its_own_runs(tmp_path: Path):
    """Two xdist workers, two snippet tests each: four runs in all, each started by the worker
    that runs its test. ``worksteal`` splits the tests between the workers (the suite's own
    scheduler keeps nearly all of this file's tests on one worker), and every worker's
    ``session.items`` still lists all four."""
    log = tmp_path / "runs.log"
    ids = [
        f"tests/test_doc_snippets.py::test_snippet_runs[{snippet}]" for snippet in CHEAP_SNIPPETS
    ]
    done = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "-n",
            "2",
            "--dist",
            "worksteal",
            "-p",
            "no:randomly",
            "-p",
            "no:cacheprovider",
            *ids,
        ],
        check=False,
        capture_output=True,
        text=True,
        timeout=120,
        cwd=ROOT,
        # Not the outer run's xdist worker variables (PYTEST_XDIST_WORKER, ...).
        env={k: v for k, v in os.environ.items() if not k.startswith("PYTEST_")}
        | {RUN_LOG: str(log)},
    )
    assert done.returncode == 0, f"stdout:\n{done.stdout}\nstderr:\n{done.stderr}"
    started = log.read_text().splitlines()
    snippets = sorted(line.split()[2] for line in started)
    assert snippets == sorted(CHEAP_SNIPPETS), "\n".join(started)
    assert {line.split()[0] for line in started} == {"gw0", "gw1"}, "\n".join(started)
