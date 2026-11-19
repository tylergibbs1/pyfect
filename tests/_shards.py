"""Split the suite into shards CI runs on separate runners: ``--shard K/N`` collects only the
test files of shard K of N.

Files are packed by their recorded duration (``tests/shard_durations.json``, written by
``scripts/test_shards.py update``), longest first onto the lightest shard, so every runner
finishes at about the same time. A file longer than a shard's even share would leave its shard
behind the others, so its tests are spread instead: each test goes to the shard its id
hashes to. A file with no recorded duration goes to the shard its path hashes to. Either way
every test lands in exactly one shard. ``--shard-manifest=PATH`` writes
the collected test ids, which CI's ``check`` job compares with a full collection
(``scripts/test_shards.py verify``), so no test is skipped or run twice.

Every option takes its value after ``=``: pytest picks the rootdir and the initial conftests
before a conftest plugin's options exist, so a value given as its own word reads as a test
path. One that exists (a manifest the controller has written, which a replacement xdist worker
then sees) moves the rootdir or skips tests/conftest.py, and the option is unrecognized.
"""

import json
import os
import shlex
import zlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

DURATIONS = Path(__file__).parent / "shard_durations.json"


@dataclass(frozen=True)
class Shard:
    index: int
    """1-based."""
    count: int


def parse_shard(text: str) -> Shard:
    index, sep, count = text.partition("/")
    if not (sep and index.isdigit() and count.isdigit() and 1 <= int(index) <= int(count)):
        raise pytest.UsageError(f"--shard takes K/N with 1 <= K <= N, not {text!r}")
    return Shard(int(index), int(count))


@dataclass(frozen=True)
class Plan:
    shards: Mapping[str, int]
    """Each packed file's 1-based shard."""
    spread: frozenset[str]
    """Files whose tests are spread over every shard by test id."""
    loads: tuple[float, ...]
    """Each shard's recorded seconds, a spread file's split evenly."""


def assign(durations: Mapping[str, float], count: int) -> Plan:
    """Spread the files too long for one shard, then pack the rest longest first onto the shard
    with the least time."""
    share = sum(durations.values()) / count
    spread = frozenset(path for path, s in durations.items() if s > share)
    loads = [sum(durations[path] for path in spread) / count] * count
    shards: dict[str, int] = {}
    packed = (item for item in durations.items() if item[0] not in spread)
    for path, seconds in sorted(packed, key=lambda item: (-item[1], item[0])):
        lightest = min(range(count), key=lambda shard: (loads[shard], shard))
        loads[lightest] += seconds
        shards[path] = lightest + 1
    return Plan(shards, spread, tuple(loads))


def _hashed(text: str, count: int) -> int:
    return zlib.crc32(text.encode()) % count + 1


def shard_of(path: str, plan: Plan, count: int) -> int | None:
    """The shard that collects ``path``; None when its tests are spread over every shard."""
    if path in plan.spread:
        return None
    known = plan.shards.get(path)
    return known if known is not None else _hashed(path, count)


def shard_of_test(nodeid: str, count: int) -> int:
    """The shard that runs a test of a spread file."""
    return _hashed(nodeid, count)


def load_durations(path: Path) -> dict[str, float]:
    recorded: dict[str, float] = json.loads(path.read_text(encoding="utf-8"))
    return recorded


@dataclass(eq=False)  # a plugin: pluggy hashes it
class _Selection:
    shard: Shard
    plan: Plan
    patterns: list[str]
    root: Path

    @pytest.hookimpl
    def pytest_ignore_collect(self, collection_path: Path) -> bool | None:
        is_test_file = collection_path.suffix == ".py" and any(
            collection_path.match(pattern) for pattern in self.patterns
        )
        if not is_test_file:
            return None
        path = collection_path.relative_to(self.root).as_posix()
        owner = shard_of(path, self.plan, self.shard.count)
        return True if owner is not None and owner != self.shard.index else None

    @pytest.hookimpl
    def pytest_collection_modifyitems(
        self, config: pytest.Config, items: list[pytest.Item]
    ) -> None:
        if not self.plan.spread:
            return
        keep: list[pytest.Item] = []
        drop: list[pytest.Item] = []
        for item in items:
            spread = item.nodeid.partition("::")[0] in self.plan.spread
            mine = not spread or shard_of_test(item.nodeid, self.shard.count) == self.shard.index
            (keep if mine else drop).append(item)
        if drop:
            config.hook.pytest_deselected(items=drop)
            items[:] = keep


@dataclass(eq=False)  # a plugin: pluggy hashes it
class _Manifest:
    path: Path

    def write(self, ids: list[str]) -> None:
        self.path.write_text("".join(f"{nodeid}\n" for nodeid in ids), encoding="utf-8")

    @pytest.hookimpl
    def pytest_collection_finish(self, session: pytest.Session) -> None:
        if session.items:  # under xdist the controller collects nothing; the workers report
            self.write([item.nodeid for item in session.items])

    @pytest.hookimpl(optionalhook=True)
    def pytest_xdist_node_collection_finished(self, node: object, ids: list[str]) -> None:
        # Every worker collects the same tests (xdist checks); the first one's ids are the run's.
        if not self.path.exists():
            self.write(ids)


@dataclass(eq=False)  # a plugin: pluggy hashes it
class _Timings:
    path: Path
    seconds: dict[str, float] = field(default_factory=dict[str, float])

    @pytest.hookimpl
    def pytest_runtest_logreport(self, report: pytest.TestReport) -> None:
        file = report.nodeid.partition("::")[0]
        self.seconds[file] = self.seconds.get(file, 0.0) + report.duration

    @pytest.hookimpl
    def pytest_sessionfinish(self) -> None:
        rounded = {file: round(seconds, 2) for file, seconds in sorted(self.seconds.items())}
        self.path.write_text(json.dumps(rounded, indent=1) + "\n", encoding="utf-8")


_OPTIONS: Mapping[str, tuple[Callable[[str], object], str]] = {
    "--shard": (parse_shard, "collect only shard K of N (--shard=K/N)"),
    "--shard-manifest": (Path, "write the collected test ids here"),
    "--shard-durations": (Path, "write each file's seconds here (JSON)"),
    "--shard-recorded": (Path, "pack by these durations (JSON)"),
}


def pytest_addoption(parser: pytest.Parser) -> None:
    group = parser.getgroup("shards")
    for name, (parse, text) in _OPTIONS.items():
        group.addoption(name, type=parse, help=f"{text}; the value goes after =")


def _check_values_joined(args: Sequence[str]) -> None:
    """Refuse ``--shard-manifest PATH``: see the module docstring."""
    for arg in args:
        if arg in _OPTIONS:
            raise pytest.UsageError(
                f"write {arg}=VALUE, not {arg} VALUE: pytest reads a separate VALUE as a test"
                " path before this plugin's options exist (tests/_shards.py)"
            )


def pytest_configure(config: pytest.Config) -> None:
    from_env = shlex.split(os.environ.get("PYTEST_ADDOPTS", ""))
    _check_values_joined([*config.getini("addopts"), *from_env, *config.invocation_params.args])
    shard: Shard | None = config.getoption("shard")
    manifest: Path | None = config.getoption("shard_manifest")
    timings: Path | None = config.getoption("shard_durations")
    if shard is not None:
        patterns: list[str] = config.getini("python_files")
        recorded: Path | None = config.getoption("shard_recorded")
        plan = assign(load_durations(recorded or DURATIONS), shard.count)
        config.pluginmanager.register(_Selection(shard, plan, patterns, config.rootpath))
    # Under xdist the controller sees every test's report, so only it writes; a worker would
    # overwrite the files with its own share.
    is_worker = hasattr(config, "workerinput")
    if manifest is not None and not is_worker:
        manifest.unlink(missing_ok=True)
        config.pluginmanager.register(_Manifest(manifest))
    if timings is not None and not is_worker:
        config.pluginmanager.register(_Timings(timings))
